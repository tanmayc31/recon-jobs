import argparse
import asyncio
import csv
import os
import random
import time
from collections import Counter
from pathlib import Path

import httpx

from recon import eligibility
from recon.env import load_env
from recon.filters import classify
from recon.sources import amazon, ashby, gmail, greenhouse, lever, listings, workday
from recon.store import MISSES_TO_CLOSE, Store, fresh, now

SOURCES = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday, "amazon": amazon,
           "listings": listings, "gmail": gmail}
COMPANIES = Path(__file__).parent.parent / "config" / "companies.csv"
REFERRALS = Path(__file__).parent.parent / "config" / "referrals.csv"   # private, gitignored
HEADERS = {"User-Agent": "recon-jobs/0.2"}
# Separate lanes: slow Workday tenants (~20s each) can't starve the fast ATSes (~0.1s each)
PARALLEL = {"workday": 10, "other": 20}
# GitHub kills the job at 15 min (incl. setup). Stop starting companies after DEADLINE,
# and give any one company at most COMPANY_TIMEOUT, so fetching ends by ~10 min.
DEADLINE = 8 * 60
COMPANY_TIMEOUT = 2 * 60
LIST_TIMEOUT = 6 * 60   # a job list resolves every new row's link; the first run has hundreds


def quiet() -> bool:
    """In CI (GitHub sets CI=true) logs are public: print counts only, never jobs or contacts."""
    return bool(os.environ.get("CI"))


def load_referrals(path: Path = REFERRALS) -> dict[str, str]:
    """company (lowercase) -> contact. Missing file means no referrals."""
    if not path.exists():
        return {}
    with open(path) as f:
        return {r["company"].strip().lower(): r["contact"].strip()
                for r in csv.DictReader(f) if (r.get("contact") or "").strip()}


def load_companies(path: Path = COMPANIES, referrals: Path = REFERRALS) -> list[dict]:
    with open(path) as f:
        companies = list(csv.DictReader(f))
    contacts = load_referrals(referrals)
    for c in companies:
        c["referral"] = contacts.get(c["company"].lower(), "")
    return companies


async def fetch_company(client, sems, company, deadline, outcome):
    """Jobs, or None if the company failed or wasn't reached in time (not its first run then)."""
    async with sems["workday" if company["ats"] == "workday" else "other"]:
        if time.monotonic() > deadline:
            outcome["not reached"] += 1
            return None
        try:
            limit = LIST_TIMEOUT if company["ats"] in ("listings", "gmail") else COMPANY_TIMEOUT
            jobs = await asyncio.wait_for(SOURCES[company["ats"]].fetch(client, company), limit)
            outcome["ok"] += 1
            return jobs
        except Exception as e:
            outcome["failed"] += 1
            detail = "" if quiet() else f" {e}"   # error text can contain URLs
            print(f"⚠️  {company['company']}: {type(e).__name__}{detail}")
            return None


async def run(tiers: set[int] | None = None, recheck: bool = False, ats: set[str] | None = None):
    """recheck=True re-fetches descriptions and re-judges every job (after a filter change)."""
    started = time.monotonic()
    # Read what we need, then close: fetching takes up to ~10 min and Supabase's pooler drops
    # idle connections (a Workday lane crashed at save time). A fresh connection does the writes.
    store = Store(url=os.environ.get("DATABASE_URL"))   # blank/unset -> local SQLite
    stored = store.known_jobs()
    known = {} if recheck else stored
    seen = store.seen_companies()
    companies = [c for c in load_companies()
                 if (not tiers or int(c["tier"]) in tiers) and (not ats or c["ats"] in ats)]
    for c in companies:
        c["known"] = known   # adapters skip description requests for these job IDs
    if any(c["ats"] == "listings" for c in companies):
        list_ids, covered = store.list_ids(), store.covered_keys()
        for c in companies:
            if c["ats"] == "listings":
                c["list_ids"], c["covered"] = list_ids, covered
    store.close()
    random.shuffle(companies)   # if the time budget runs out, a different set waits each run
    sems = {lane: asyncio.Semaphore(n) for lane, n in PARALLEL.items()}
    outcome = Counter()
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        results = await asyncio.gather(*(
            fetch_company(client, sems, c, started + DEADLINE, outcome) for c in companies))
    # (board, job): a job list's jobs belong to many companies, but its first run is the list's
    all_jobs = [(c["company"], j) for c, jobs in zip(companies, results) if jobs for j in jobs]

    store = Store(url=os.environ.get("DATABASE_URL"))
    new_matches, backlog, unverified, skipped, rows, kept, still_listed = [], 0, 0, Counter(), [], {}, []

    for board, j in all_jobs:
        if j.job_id in known:   # judged before: keep the stored verdict, just note it's still listed
            decision, reason, _ = known[j.job_id]
            if decision == "skip":
                skipped["too many years" if "years" in (reason or "") else reason] += 1
            still_listed.append(j)
            continue
        keep, flags = classify(j)                 # stage 1: title + location
        if not keep:
            # a recheck moves old matches that fail a new title/location rule to Skipped
            if recheck and stored.get(j.job_id, ("",))[0] == "match":
                rows.append((j, "skip", flags[0], None, "new"))   # status only applies to new rows
                skipped[flags[0]] += 1
            continue
        # a company's first run is its existing backlog, not news, unless the site says it was
        # posted in the last few days
        status = "new" if board in seen or fresh(j.posted_at, now()) else "backlog"
        if not j.description.strip():
            # the description request failed: can't judge it, so not a match. Hidden from every
            # tab and retried next run (known_jobs skips unverified rows)
            rows.append((j, "unverified", "no description", None, status))
            unverified += 1
            continue
        ok, reason, yrs, desc_flags = eligibility.check(j.description, j.title)   # stage 2: description
        if not ok:
            skipped["too many years" if "years" in reason else reason] += 1
            rows.append((j, "skip", reason, yrs, status))
            continue
        flags = flags + desc_flags
        rows.append((j, "match", ", ".join(flags) or None, yrs, status))
        kept[j.job_id] = (j, flags, yrs, status)
    for job_id in store.upsert_many(rows):   # one batch: thousands of round trips to Supabase are slow
        if job_id not in kept:
            continue
        j, flags, yrs, status = kept[job_id]
        if status == "backlog":
            backlog += 1
        else:
            new_matches.append((j, flags, yrs))
    # only open jobs enter New: each is checked through its site's API (a listed job can still be
    # unopenable, e.g. an Ashby board whose job pages are switched off). Gone ones close at once.
    if new_matches:
        from recon import linkcheck   # imports main
        checked = await linkcheck.check_open([{"job_id": j.job_id, "source": j.source, "url": j.url,
                                               "source_ids": j.source_ids, "company": j.company, "title": j.title}
                                              for j, _, _ in new_matches])
        gone = {job["job_id"] for job, ok in checked if ok is False}
        store.close_jobs(sorted(gone))
        new_matches = [m for m in new_matches if m[0].job_id not in gone]
        if gone:
            print(f"Not shown in New (gone when checked): {len(gone)}")
    # dates only, never the verdict: an overlapping --recheck run may have just updated it
    store.touch_many(still_listed)
    # only complete listings: a failed or cut-off fetch (company["partial"]) or an empty board
    # (more often a glitch than a hiring freeze) says nothing about which jobs closed
    closed, reopened = store.track_listings({c["company"]: {j.job_id for j in jobs}
                                             for c, jobs in zip(companies, results) if jobs and not c.get("partial")})
    store.mark_seen([c["company"] for c, jobs in zip(companies, results) if jobs is not None])
    store.commit()
    store.close()

    total = sum(1 for _ in all_jobs)
    label = f"tiers {','.join(map(str, sorted(tiers)))}" if tiers else "all tiers"
    label += f", {','.join(sorted(ats))}" if ats else ""
    label += ", recheck" if recheck else ""
    print(f"\nChecked {len(companies)} companies ({label}), {total} jobs in {time.monotonic() - started:.0f}s")
    print("Companies: " + ", ".join(f"{k}: {v}" for k, v in outcome.most_common()))
    print("Skipped by description: " + (", ".join(f"{k}: {v}" for k, v in skipped.most_common()) or "none"))

    if unverified:
        print(f"Unverified (no description, retried next run): {unverified}")
    if closed or reopened:
        print(f"Closed (gone from the board {MISSES_TO_CLOSE} runs in a row): {closed}, reopened: {reopened}")
    if backlog:
        print(f"\n📦 {backlog} backlog matches saved from first-time companies (not shown as new)")
    print(f"\n🆕 {len(new_matches)} new matches since last run\n")
    show = new_matches

    if quiet():
        return new_matches

    referral = {c["company"]: c["referral"] for c in companies}
    show.sort(key=lambda m: (m[0].tier, m[0].company))
    for j, flags, yrs in show:
        tags = flags + ([f"{yrs}+ yrs"] if yrs else [])
        tag = f"  [{', '.join(tags)}]" if tags else ""
        print(f"[T{j.tier}] {j.company} | {j.title} | {j.location}{tag}\n      {j.url}")
        if referral.get(j.company):
            print(f"      referral: {referral[j.company]}")
    return new_matches


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tiers", help="comma-separated, e.g. 1,2 (default: all)")
    parser.add_argument("--ats", help="comma-separated, e.g. workday or greenhouse,lever,ashby (default: all)")
    parser.add_argument("--recheck", action="store_true",
                        help="re-fetch descriptions and re-judge known jobs (after changing filters)")
    args = parser.parse_args()
    load_env()
    asyncio.run(run({int(t) for t in args.tiers.split(",")} if args.tiers else None, args.recheck,
                    set(args.ats.split(",")) if args.ats else None))
