"""One-time: fetch descriptions for matches saved before descriptions were stored, then run
the description rules on them (some become skips). The AI judge only reads matches with a
description, so these were never judged.

Same adapters as a normal run, but politely: a few companies at a time and a pause between
companies. Greenhouse and Workday request details only for the jobs missing a description
(every other job is passed as known); Lever and Ashby include descriptions in the board list.
Jobs a board no longer lists are left as they are.

    python -m recon.backfill
"""
import asyncio
import os
from collections import Counter

import httpx

from recon import eligibility
from recon.env import load_env
from recon.filters import classify
from recon.main import HEADERS, SOURCES, load_companies, quiet
from recon.store import Store

PARALLEL = {"workday": 2, "other": 3}
GAP = 2                # seconds between companies, per lane slot
TIMEOUT = 15 * 60      # big Workday boards page slowly


async def run(gap: float = GAP, transport=None) -> Counter:
    store = Store(url=os.environ.get("DATABASE_URL"))
    missing = store.undescribed()          # job_id -> company
    known = set(store.known_jobs())
    store.close()
    names = set(missing.values())
    companies = [c for c in load_companies() if c["company"] in names]
    for c in companies:
        c["known"] = known - set(missing)  # adapters skip detail requests for these
    tracked = {c["company"] for c in companies}
    counts = Counter(queued=len(missing), companies=len(companies),
                     company_gone=sum(1 for n in missing.values() if n not in tracked))   # not in companies.csv
    sems = {lane: asyncio.Semaphore(n) for lane, n in PARALLEL.items()}
    failed = set()

    async def one(client, company):
        async with sems["workday" if company["ats"] == "workday" else "other"]:
            try:
                return await asyncio.wait_for(SOURCES[company["ats"]].fetch(client, company), TIMEOUT)
            except Exception as e:
                failed.add(company["company"])
                print(f"⚠️  {'company' if quiet() else company['company']}: {type(e).__name__}")
                return []
            finally:
                await asyncio.sleep(gap)

    async with httpx.AsyncClient(timeout=30, headers=HEADERS, transport=transport) as client:
        results = await asyncio.gather(*(one(client, c) for c in companies))

    rows, found = [], set()
    for j in (j for jobs in results for j in jobs):
        if j.job_id not in missing or j.job_id in found:
            continue
        found.add(j.job_id)
        keep, flags = classify(j)
        if not keep:              # filter rules changed since: left as is, like a normal run
            counts["title_filter_now_fails"] += 1
            continue
        if not j.description.strip():
            counts["still_no_description"] += 1
            continue
        ok, reason, yrs, desc_flags = eligibility.check(j.description, j.title)
        if ok:
            counts["filled_match"] += 1
            rows.append((j, "match", ", ".join(flags + desc_flags) or None, yrs, "backlog"))
        else:
            counts["filled_skip"] += 1
            counts[f"skip: {'too many years' if 'years' in reason else reason}"] += 1
            rows.append((j, "skip", reason, yrs, "backlog"))   # status only applies to new rows
    left = [n for i, n in missing.items() if i not in found and n in tracked]
    counts["companies_failed"] = len(failed)
    counts["fetch_failed"] = sum(1 for n in left if n in failed)        # retry: run it again
    counts["not_listed_anymore"] = sum(1 for n in left if n not in failed)

    store = Store(url=os.environ.get("DATABASE_URL"))
    store.upsert_many(rows)
    store.commit()
    store.close()
    print("Backfill: " + ", ".join(f"{k}: {v}" for k, v in counts.items() if v))
    return counts


if __name__ == "__main__":
    load_env()
    asyncio.run(run())
