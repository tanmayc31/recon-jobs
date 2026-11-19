"""SuccessFactors Career Site Builder sites (EY). Config slug = the site's base path, e.g.
careers.ey.com/ey.

Public pages only, the ones the site's own search serves: /search/?locationsearch=United States,
every US job 25 rows a page (startrow; EY: ~1,150 in 48 pages), so the listing is complete and can
close jobs (its keyword search matches loosely: "software engineer" found 1,100). A row gives the
title and location;
the job's page has the description (span.jobdescription) and the posted date, read only for new
jobs that pass the title + location filter. A job that's gone sends you to /errorpage/. Sites that
answer with a challenge or a block (SAP: Cloudflare; American Airlines: Akamai) aren't scanned:
the run fails with Blocked and Recon doesn't work around it.
"""
import asyncio
import html
import re
from datetime import datetime

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

PAGE = 25           # the site's page size
DELAY = 0.4
MAX_PAGES = 100     # safety stop
ROW = re.compile(r'<tr class="data-row.*?</tr>', re.S)
LINK = re.compile(r'<a href="(/[^"]*/job/[^"]+/(\d+)/)" class="jobTitle-link">(.*?)</a>', re.S)
PLACE = re.compile(r'<span class="jobLocation">(.*?)</span>', re.S)
# "New York, NY, US, 10001-8604 +3 more…" -> "New York, NY, US" (the job's page lists every location)
NOISE = re.compile(r",\s*\d{5}(?:-\d{4})?|\s*\+\d+ more…?")
DESCRIPTION = re.compile(r'<span class="jobdescription">(.*?)</span>\s*</div>', re.S)
POSTED = re.compile(r'itemprop="datePosted"[^>]*content="([^"]+)"')


RETRIES = 2         # EY sometimes stalls past the timeout: ask again after 2 s, 4 s


class Blocked(Exception):
    """The site answered with a challenge or a block: stop, don't work around it."""


def check(r: httpx.Response, what: str) -> httpx.Response:
    if r.status_code in (403, 429) or "Just a moment" in r.text[:2000] or "Access Denied" in r.text[:2000]:
        raise Blocked(f"{what}: HTTP {r.status_code}")
    return r


async def get(client: httpx.AsyncClient, url: str, what: str, **params) -> httpx.Response:
    """A page, asked again after a timeout or a server error; a challenge or block stops the run."""
    for attempt in range(RETRIES + 1):
        try:
            r = await client.get(url, params=params or None, follow_redirects=True)
            if r.status_code < 500 or attempt == RETRIES:
                return check(r, what)
        except httpx.TimeoutException:
            if attempt == RETRIES:
                raise
        await asyncio.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def text(fragment: str) -> str:
    return " ".join(html.unescape(strip_html(fragment)).split())


def rows(page: str, host: str) -> list[dict]:
    out = []
    for row in ROW.findall(page):
        link, place = LINK.search(row), PLACE.search(row)
        if link:
            out.append({"url": f"https://{host}{link[1]}", "id": link[2], "title": text(link[3]),
                        "location": NOISE.sub("", text(place[1])).rstrip(", ") if place else ""})
    return out


def posted(value: str | None) -> str | None:
    """"Thu Nov 19 02:01:00 UTC 2026" -> "2026-11-19"."""
    try:
        return datetime.strptime(value or "", "%a %b %d %H:%M:%S %Z %Y").date().isoformat()
    except ValueError:
        return None


async def details(client: httpx.AsyncClient, url: str) -> dict | None:
    """The job's description and posted date, or None if it's gone (/errorpage/)."""
    r = await get(client, url, "job page")
    if r.status_code in (404, 410) or "errorpage" in r.url.path:
        return None
    r.raise_for_status()
    d = DESCRIPTION.search(r.text)
    p = POSTED.search(r.text)
    return {"description": text(d[1]) if d else "", "posted": posted(p[1] if p else None)}


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    base = company["slug"].rstrip("/")
    host = base.split("/")[0]
    found = {}
    for page in range(MAX_PAGES):
        r = await get(client, f"https://{base}/search/", "search", q="", locationsearch="United States", startrow=page * PAGE)
        r.raise_for_status()
        new = {x["id"]: x for x in rows(r.text, host) if x["id"] not in found}
        found |= new
        await asyncio.sleep(DELAY)
        if not new:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    jobs = []
    for x in found.values():
        job = Job(job_id=f"successfactors:{host}:{x['id']}", company=company["company"], title=x["title"],
                  location=x["location"], url=x["url"], posted_at=None, source="successfactors",
                  tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the job page
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            info = await details(client, x["url"])
            await asyncio.sleep(DELAY)
            if info:
                job.description, job.posted_at = info["description"], info["posted"]
        jobs.append(job)
    return jobs
