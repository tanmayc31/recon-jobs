"""Eightfold career sites (Microsoft, Qualcomm, Ericsson, ...). Config slug = host|domain, e.g.
apply.careers.microsoft.com|microsoft.com.

Public search API (/api/pcsx/search): 10 positions a page, filtered to the United States and
searched for SEARCHES (the title filter needs a software role anyway). Descriptions come from
/api/pcsx/position_details, only for new jobs that pass the title + location filter.
"""
import asyncio
from datetime import datetime, timezone

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

SEARCHES = ["software", "developer"]
PAGE = 10           # the API's fixed page size
DELAY = 0.4         # seconds between requests, be polite
MAX_PAGES = 200     # safety stop per search (Microsoft "software", US: ~86 pages)
RETRIES = 3         # rate limited (non-JSON or 429): wait 1s, 2s, 4s


def parse_slug(slug: str) -> tuple[str, str]:
    host, domain = slug.split("|")
    return host, domain


async def get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict | None:
    """The response's JSON, None on 404. Retries when the site answers with something else."""
    for attempt in range(RETRIES + 1):
        r = await client.get(url, params=params)
        if r.status_code == 404:
            return None
        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
            return r.json()
        if attempt == RETRIES:
            r.raise_for_status()
            raise httpx.HTTPError(f"not JSON from {url}")
        await asyncio.sleep(2 ** attempt)


async def details(client: httpx.AsyncClient, host: str, domain: str, pid) -> dict | None:
    d = await get_json(client, f"https://{host}/api/pcsx/position_details",
                       {"position_id": pid, "domain": domain, "hl": "en"})
    return (d or {}).get("data") or None


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    host, domain = parse_slug(company["slug"])
    found = {}
    for query in SEARCHES:
        for page in range(MAX_PAGES):
            d = await get_json(client, f"https://{host}/api/pcsx/search",
                               {"domain": domain, "query": query, "location": "United States", "start": page * PAGE})
            positions = ((d or {}).get("data") or {}).get("positions") or []
            new = [p for p in positions if p["id"] not in found]
            found |= {p["id"]: p for p in new}
            await asyncio.sleep(DELAY)
            if len(positions) < PAGE or not new:
                break
        else:
            company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    jobs = []
    for p in found.values():
        posted = p.get("postedTs")
        job = Job(job_id=f"eightfold:{domain}:{p['id']}", company=company["company"], title=p.get("name", ""),
                  location="; ".join(p.get("standardizedLocations") or p.get("locations") or []),
                  url=f"https://{host}{p.get('positionUrl') or '/careers/job/' + str(p['id'])}",
                  posted_at=datetime.fromtimestamp(posted, tz=timezone.utc).date().isoformat() if posted else None,
                  source="eightfold", tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the detail request
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            info = await details(client, host, domain, p["id"])
            await asyncio.sleep(DELAY)
            if info:
                job.description = strip_html(info.get("jobDescription"))
                job.url = info.get("publicUrl") or job.url
        jobs.append(job)
    return jobs
