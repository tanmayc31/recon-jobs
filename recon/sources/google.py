"""Google careers (google.com/about/careers). companies.csv row: "Google,google,google,2" (the slug
is unused).

Only the public requests the careers site itself makes, signed out:
1. Its job search RPC (batchexecute, r06xKb), the one its "next page" button calls: every US job,
   PAGE at a time. Each job comes with its responsibilities, qualifications and locations, so no
   per-job requests; the listing is complete and can close jobs.
2. A job's page, for the open check: a job Google took down shows the search page instead (its
   embedded job data, ds:0, is empty).
If Google answers with its "unusual traffic" page or a block, the run fails with Blocked: Recon
stops there and doesn't try to get around it.
"""
import asyncio
import json
import re
from datetime import datetime, timezone

import httpx

from recon.models import Job
from recon.text import strip_html

SITE = "https://www.google.com/about/careers/applications"
RPC = f"{SITE}/_/HiringCportalFrontendUi/data/batchexecute"
RPC_ID = "r06xKb"
PAGE = 20           # the site's page size
DELAY = 0.3         # seconds between pages, be polite
MAX_PAGES = 150     # safety stop (Nov 2026: ~1,800 US jobs = 90 pages)
DS0 = re.compile(r"AF_initDataCallback\(\{key: 'ds:0'.*?data:(.*?), sideChannel: \{\}\}\);</script>", re.S)


class Blocked(Exception):
    """Google answered with a block or "unusual traffic" page: stop, don't work around it."""


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def job_url(jid: str, title: str) -> str:
    return f"{SITE}/jobs/results/{jid}-{slugify(title)}"


def blocked(r: httpx.Response) -> bool:
    return r.status_code in (403, 429) or "/sorry/" in str(r.url)


async def search_page(client: httpx.AsyncClient, page: int) -> tuple[list, int | None]:
    """(jobs on this page, total)."""
    inner = json.dumps([["", None, None, None, "en-US", None, [["United States"]], page]])
    r = await client.post(RPC, params={"rpcids": RPC_ID, "source-path": "/about/careers/applications/jobs/results/",
                                       "hl": "en-US", "rt": "c"},
                          data={"f.req": json.dumps([[[RPC_ID, inner, None, "generic"]]])},
                          headers={"X-Same-Domain": "1"}, follow_redirects=True)
    if blocked(r):
        raise Blocked(f"job search: HTTP {r.status_code}")
    r.raise_for_status()
    for line in r.text.split("\n"):   # rt=c: length-prefixed chunks, one per line
        if line.startswith('[["wrb.fr"'):
            payload = json.loads(line)[0][2]
            data = json.loads(payload) if payload else None
            return (data[0] or [], data[1] if len(data) > 1 else None) if data else ([], None)
    raise ValueError("job search answered without jobs (RPC changed?)")


def html_of(field) -> str:
    return field[1] if isinstance(field, list) and len(field) > 1 and field[1] else ""


def to_job(row: list, company: dict) -> Job:
    jid, title = row[0], row[1]
    locations = [loc[0] for loc in row[9] or [] if loc and loc[0]]
    created = row[12][0] if len(row) > 12 and isinstance(row[12], list) and row[12] else None
    return Job(job_id=f"google:google:{jid}", company=company["company"], title=title,
               location="; ".join(locations), url=job_url(jid, title),
               posted_at=datetime.fromtimestamp(created, tz=timezone.utc).date().isoformat() if created else None,
               source="google", tier=int(company["tier"]),
               # responsibilities, qualifications, about the job (salary): the description
               description=strip_html(" ".join(html_of(row[i]) for i in (3, 4, 10) if len(row) > i)))


async def details(client: httpx.AsyncClient, jid: str) -> bool | None:
    """True open, None if Google took the job down (its page shows the search instead)."""
    r = await client.get(f"{SITE}/jobs/results/{jid}", follow_redirects=True)
    if blocked(r):
        raise Blocked(f"job page: HTTP {r.status_code}")
    r.raise_for_status()
    m = DS0.search(r.text)
    if not m:
        raise ValueError(f"job page {jid} has no job data")
    data = json.loads(m[1])
    return True if data and jid in json.dumps(data) else None


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    found = {}
    for page in range(1, MAX_PAGES + 1):
        rows, _ = await search_page(client, page)
        new = [r for r in rows if r and r[0] not in found]
        found |= {r[0]: r for r in new}
        await asyncio.sleep(DELAY)
        if len(rows) < PAGE or not new:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    return [to_job(r, company) for r in found.values()]
