import asyncio
import csv
from collections import Counter
from pathlib import Path

import httpx

from recon import eligibility
from recon.filters import classify
from recon.sources import ashby, greenhouse, lever
from recon.store import Store

SOURCES = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}
COMPANIES = Path(__file__).parent.parent / "config" / "companies.csv"
HEADERS = {"User-Agent": "recon-jobs/0.2"}
MAX_PARALLEL = 5  # be polite


def load_companies(path: Path = COMPANIES) -> list[dict]:
    with open(path) as f:
        return list(csv.DictReader(f))


async def fetch_company(client, sem, company):
    async with sem:
        try:
            return await SOURCES[company["ats"]].fetch(client, company)
        except Exception as e:
            print(f"⚠️  {company['company']}: {type(e).__name__} {e}")
            return []


async def run():
    companies = load_companies()
    sem = asyncio.Semaphore(MAX_PARALLEL)
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        results = await asyncio.gather(*(fetch_company(client, sem, c) for c in companies))
    all_jobs = [j for jobs in results for j in jobs]

    store = Store()
    baseline = store.is_empty()
    new_matches, skipped = [], Counter()

    for j in all_jobs:
        keep, flags = classify(j)                 # stage 1: title + location
        if not keep:
            continue
        ok, reason, yrs, desc_flags = eligibility.check(j.description)   # stage 2: description
        if not ok:
            skipped["too many years" if "years" in reason else reason] += 1
            store.upsert(j, "skip", reason, yrs)
            continue
        flags = flags + desc_flags
        is_new = store.upsert(j, "match", ", ".join(flags) or None, yrs)
        if is_new:
            new_matches.append((j, flags, yrs))
    store.commit()

    total = sum(1 for _ in all_jobs)
    print(f"\nChecked {len(companies)} companies, {total} jobs")
    print("Skipped by description: " + (", ".join(f"{k}: {v}" for k, v in skipped.most_common()) or "none"))

    if baseline:
        print(f"\n📦 First run: saved {len(new_matches)} matches as a baseline.")
        print("   From now on, Recon shows only NEW jobs.\n")
        show = new_matches
    else:
        print(f"\n🆕 {len(new_matches)} new matches since last run\n")
        show = new_matches

    show.sort(key=lambda m: (m[0].tier, m[0].company))
    for j, flags, yrs in show:
        tags = flags + ([f"{yrs}+ yrs"] if yrs else [])
        tag = f"  [{', '.join(tags)}]" if tags else ""
        print(f"[T{j.tier}] {j.company} | {j.title} | {j.location}{tag}\n      {j.url}")
    return new_matches


if __name__ == "__main__":
    asyncio.run(run())
