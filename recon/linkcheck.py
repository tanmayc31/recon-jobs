"""Is a saved job still open, and does its link open a real job page?

The site's own API decides whether the job is open: Workday's public page always answers 200
and only then shows "page doesn't exist" in the browser. The page check follows the link: a
404, or a redirect to a generic careers page (the job's ID gone from the URL), is a broken link.
Company career sites that block scripts (403) can't be page-checked; the API still decides.

    python -m recon.linkcheck                 # 20 random open Workday matches + 5 each from the others
    python -m recon.linkcheck --close-unseen  # weekly: close Workday jobs gone from the detail API

Auto-close (store.track_listings) skips filtered or capped Workday boards, since a job missing
from a partial listing may still be open. The weekly --close-unseen pass covers them: Workday
jobs not seen for UNSEEN_DAYS are checked one by one, and confirmed-gone ones (403/404) closed.
"""
import argparse
import asyncio
import os
import re
from datetime import datetime, timedelta, timezone

import httpx

from recon.env import load_env
from recon.main import HEADERS, quiet
from recon.store import Store

DELAY = 0.5
UNSEEN_DAYS = 3
SAMPLE = {"workday": 20, "greenhouse": 5, "lever": 5, "ashby": 5, "amazon": 5}
WORKDAY = [  # public job URL -> parts of the detail API URL
    re.compile(r"https://(?P<tenant>[^./]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?"
               r"(?P<site>[^/]+)(?P<path>/job/.+)$"),
    re.compile(r"https://(?P<wd>wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/"
               r"(?P<tenant>[^/]+)/(?P<site>[^/]+)(?P<path>/job/.+)$"),
]
GONE = {403, 404, 410}   # Workday answers 403 "permission denied" for a job taken down


def workday_api(url: str) -> str | None:
    for rx in WORKDAY:
        if m := rx.match(url):
            return (f"https://{m['tenant']}.{m['wd']}.myworkdayjobs.com/wday/cxs/{m['tenant']}/{m['site']}"
                    f"{m['path']}")
    return None


def ids(job: dict) -> list[str]:
    """The site's own ID(s) for the job, as they appear in its URL."""
    if job["source"] == "amazon":
        return (job.get("source_ids") or "").split(",")
    return [job["job_id"].split(":", 2)[2]]


async def is_open(client: httpx.AsyncClient, job: dict, boards: dict) -> bool | None:
    """True open, False gone, None couldn't tell."""
    source, slug = job["source"], job["job_id"].split(":")[1]
    if source == "workday":
        api = workday_api(job["url"])
        if not api:
            return None
        r = await client.get(api)
        return True if r.status_code == 200 and "jobPostingInfo" in r.json() else False if r.status_code in GONE else None
    if source in ("greenhouse", "lever"):
        api = (f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{ids(job)[0]}" if source == "greenhouse"
               else f"https://api.lever.co/v0/postings/{slug}/{ids(job)[0]}")
        r = await client.get(api)
        return True if r.status_code == 200 else False if r.status_code == 404 else None
    if source == "ashby":   # no per-job endpoint: is it on the board?
        if slug not in boards:
            r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
            boards[slug] = {j["id"] for j in r.json().get("jobs", []) if j.get("isListed") is not False} \
                if r.status_code == 200 else None
        return None if boards[slug] is None else ids(job)[0] in boards[slug]
    if source == "amazon":  # collapsed: open while any of its requisitions is
        for i in ids(job):
            r = await client.get(f"https://www.amazon.jobs/en/jobs/{i}")
            if r.status_code == 200:
                return True
            await asyncio.sleep(DELAY)
        return False
    return None


async def page(client: httpx.AsyncClient, job: dict) -> tuple[int, str]:
    """(status, verdict) for the saved link: 'ok', 'broken', or 'blocked' (403 from a company site)."""
    r = await client.get(job["url"])
    if r.status_code == 403 and job["source"] != "workday":
        return 403, "blocked"
    kept = any(i and i in str(r.url) for i in ids(job))
    return r.status_code, "ok" if r.status_code == 200 and kept else "broken"


async def check(jobs: list[dict], transport=None) -> list[dict]:
    boards, out = {}, []
    async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True, transport=transport) as client:
        for job in jobs:
            try:
                status, verdict = await page(client, job)
                out.append(dict(job, open=await is_open(client, job, boards), status=status, page=verdict))
            except httpx.HTTPError as e:
                out.append(dict(job, open=None, status=0, page=type(e).__name__))
            await asyncio.sleep(DELAY)
    return out


def sample(store: Store) -> list[dict]:
    cols = ["job_id", "source", "url", "source_ids", "company", "title"]
    jobs = []
    for source, n in SAMPLE.items():
        jobs += [dict(zip(cols, r)) for r in store.execute(
            f"SELECT {', '.join(cols)} FROM jobs WHERE source = ? AND decision = 'match' AND closed_at IS NULL"
            " ORDER BY RANDOM() LIMIT ?", (source, n)).fetchall()]
    return jobs


def unseen(store: Store, days: int = UNSEEN_DAYS) -> list[dict]:
    """Open Workday jobs you'd see (matches, Later, Applied) not on their board for `days`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    cols = ["job_id", "source", "url", "source_ids", "company", "title"]
    return [dict(zip(cols, r)) for r in store.execute(
        f"SELECT {', '.join(cols)} FROM jobs WHERE source = 'workday' AND closed_at IS NULL"
        " AND (decision = 'match' OR status IN ('later', 'applied')) AND last_seen_at < ?", (cutoff,)).fetchall()]


async def close_unseen(transport=None) -> tuple[int, int]:
    """(checked, closed). Applied jobs close too: the dashboard keeps them in Applied with a badge."""
    store = Store(url=os.environ.get("DATABASE_URL"))
    jobs = unseen(store)
    store.close()
    results = await check(jobs, transport)
    gone = [r["job_id"] for r in results if r["open"] is False]
    store = Store(url=os.environ.get("DATABASE_URL"))
    store.close_jobs(gone)
    store.commit()
    store.close()
    print(f"Close check: {len(jobs)} Workday jobs unseen for {UNSEEN_DAYS}+ days, {len(gone)} confirmed gone"
          f" and closed, {sum(1 for r in results if r['open'] is None)} couldn't be checked")
    return len(jobs), len(gone)


async def main():
    store = Store(url=os.environ.get("DATABASE_URL"))
    jobs = sample(store)
    store.close()
    results = await check(jobs)
    good = sum(1 for r in results if r["open"] and r["page"] in ("ok", "blocked"))
    print(f"Link check: {good} of {len(results)} open with a working link")
    if quiet():
        return
    for r in results:
        mark = "✅" if r["open"] and r["page"] in ("ok", "blocked") else "❌"
        print(f"{mark} {r['source']:<10} open={r['open']!s:<5} page={r['status']} {r['page']:<7}"
              f" {r['company']} | {r['title'][:50]}\n     {r['url']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--close-unseen", action="store_true",
                        help=f"close Workday jobs unseen for {UNSEEN_DAYS}+ days that the detail API says are gone")
    args = parser.parse_args()
    load_env()
    asyncio.run(close_unseen() if args.close_unseen else main())
