import asyncio
import csv
from pathlib import Path

import httpx

from recon.filters import classify
from recon.sources import ashby, greenhouse, lever

SOURCES = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby}
COMPANIES = Path(__file__).parent.parent / "config" / "companies.csv"
HEADERS = {"User-Agent": "recon-jobs/0.1"}
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
    async with httpx.AsyncClient(timeout=20, headers=HEADERS) as client:
        results = await asyncio.gather(*(fetch_company(client, sem, c) for c in companies))

    all_jobs = [j for jobs in results for j in jobs]
    matches = []
    for j in all_jobs:
        keep, flags = classify(j)
        if keep:
            matches.append((j, flags))
    matches.sort(key=lambda m: (m[0].tier, m[0].company))

    flagged = sum(1 for _, f in matches if f)
    print(f"\nChecked {len(companies)} companies, {len(all_jobs)} jobs, "
          f"{len(matches)} matches ({flagged} flagged)\n")
    for j, flags in matches:
        tag = f"  ⚠️ {', '.join(flags)}" if flags else ""
        print(f"[T{j.tier}] {j.company} | {j.title} | {j.location}{tag}\n      {j.url}")
    return matches


if __name__ == "__main__":
    asyncio.run(run())
