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
from recon.sources import ashby, greenhouse, lever, workday
from recon.store import Store

SOURCES = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}
COMPANIES = Path(__file__).parent.parent / "config" / "companies.csv"
REFERRALS = Path(__file__).parent.parent / "config" / "referrals.csv"   # private, gitignored
HEADERS = {"User-Agent": "recon-jobs/0.2"}
MAX_PARALLEL = 20     # different boards; Workday adds its own per-request delay
# GitHub kills the job at 15 min (incl. setup). Stop starting companies after DEADLINE,
# and give any one company at most COMPANY_TIMEOUT, so fetching ends by ~10 min.
DEADLINE = 8 * 60
COMPANY_TIMEOUT = 2 * 60


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


async def fetch_company(client, sem, company, deadline, outcome):
    """Jobs, or None if the company failed or wasn't reached in time (not its first run then)."""
    async with sem:
        if time.monotonic() > deadline:
            outcome["not reached"] += 1
            return None
        try:
            jobs = await asyncio.wait_for(SOURCES[company["ats"]].fetch(client, company), COMPANY_TIMEOUT)
            outcome["ok"] += 1
            return jobs
        except Exception as e:
            outcome["failed"] += 1
            detail = "" if quiet() else f" {e}"   # error text can contain URLs
            print(f"⚠️  {company['company']}: {type(e).__name__}{detail}")
            return None


async def run(tiers: set[int] | None = None):
    started = time.monotonic()
    companies = [c for c in load_companies() if not tiers or int(c["tier"]) in tiers]
    random.shuffle(companies)   # if the time budget runs out, a different set waits each run
    sem = asyncio.Semaphore(MAX_PARALLEL)
    outcome = Counter()
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        results = await asyncio.gather(*(
            fetch_company(client, sem, c, started + DEADLINE, outcome) for c in companies))
    all_jobs = [j for jobs in results if jobs for j in jobs]

    store = Store(url=os.environ.get("DATABASE_URL"))   # blank/unset -> local SQLite
    seen = store.seen_companies()
    new_matches, backlog, skipped, rows, kept = [], 0, Counter(), [], {}

    for j in all_jobs:
        keep, flags = classify(j)                 # stage 1: title + location
        if not keep:
            continue
        # a company's first run is its existing backlog, not news
        status = "new" if j.company in seen else "backlog"
        ok, reason, yrs, desc_flags = eligibility.check(j.description)   # stage 2: description
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
    store.mark_seen([c["company"] for c, jobs in zip(companies, results) if jobs is not None])
    store.commit()
    store.close()

    total = sum(1 for _ in all_jobs)
    label = f"tiers {','.join(map(str, sorted(tiers)))}" if tiers else "all tiers"
    print(f"\nChecked {len(companies)} companies ({label}), {total} jobs in {time.monotonic() - started:.0f}s")
    print("Companies: " + ", ".join(f"{k}: {v}" for k, v in outcome.most_common()))
    print("Skipped by description: " + (", ".join(f"{k}: {v}" for k, v in skipped.most_common()) or "none"))

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
    args = parser.parse_args()
    load_env()
    asyncio.run(run({int(t) for t in args.tiers.split(",")} if args.tiers else None))
