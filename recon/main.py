import asyncio
import csv
import os
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
MAX_PARALLEL = 5  # be polite


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


async def fetch_company(client, sem, company):
    async with sem:
        try:
            return await SOURCES[company["ats"]].fetch(client, company)
        except Exception as e:
            detail = "" if quiet() else f" {e}"   # error text can contain URLs
            print(f"⚠️  {company['company']}: {type(e).__name__}{detail}")
            return None   # failed, unlike an empty board: don't count it as the company's first run


async def run():
    companies = load_companies()
    sem = asyncio.Semaphore(MAX_PARALLEL)
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        results = await asyncio.gather(*(fetch_company(client, sem, c) for c in companies))
    all_jobs = [j for jobs in results if jobs for j in jobs]

    store = Store(url=os.environ.get("DATABASE_URL"))   # blank/unset -> local SQLite
    seen = store.seen_companies()
    new_matches, backlog, skipped = [], 0, Counter()

    for j in all_jobs:
        keep, flags = classify(j)                 # stage 1: title + location
        if not keep:
            continue
        # a company's first run is its existing backlog, not news
        status = "new" if j.company in seen else "backlog"
        ok, reason, yrs, desc_flags = eligibility.check(j.description)   # stage 2: description
        if not ok:
            skipped["too many years" if "years" in reason else reason] += 1
            store.upsert(j, "skip", reason, yrs, status)
            continue
        flags = flags + desc_flags
        is_new = store.upsert(j, "match", ", ".join(flags) or None, yrs, status)
        if is_new and status == "backlog":
            backlog += 1
        elif is_new:
            new_matches.append((j, flags, yrs))
    store.mark_seen([c["company"] for c, jobs in zip(companies, results) if jobs is not None])
    store.commit()
    store.close()

    total = sum(1 for _ in all_jobs)
    print(f"\nChecked {len(companies)} companies, {total} jobs")
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
    load_env()
    asyncio.run(run())
