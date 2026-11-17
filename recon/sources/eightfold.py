"""Eightfold career sites (Microsoft, Qualcomm, Ericsson, ...). Config slug = host|domain, e.g.
apply.careers.microsoft.com|microsoft.com.

Public search API (/api/pcsx/search): 10 positions a page, filtered to the United States and
searched for SEARCHES (the title filter needs a software role anyway). Descriptions come from
/api/pcsx/position_details, only for new jobs that pass the title + location filter.
Sites still on Eightfold's older API (Netflix: "PCSX is not enabled") are read through
/api/apply/v2/jobs instead, the one their career site loads.
Results are ranked by relevance: a search stops after IRRELEVANT_PAGES full pages in a row with no
engineering title (Starbucks' "software" search runs on into thousands of barista jobs; Microsoft's
has single such pages between real ones).
"""
import asyncio
import re
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
IRRELEVANT_PAGES = 3
RELEVANT = re.compile(r"engineer|developer|software|\bsw?de\b|\bswe\b|programmer", re.I)


class OlderApi(Exception):
    """The site answers 403 "PCSX is not enabled": it uses /api/apply/v2."""


def parse_slug(slug: str) -> tuple[str, str]:
    host, domain = slug.split("|")
    return host, domain


async def get_json(client: httpx.AsyncClient, url: str, params: dict) -> dict | None:
    """The response's JSON, None on 404. Retries when the site answers with something else."""
    for attempt in range(RETRIES + 1):
        r = await client.get(url, params=params)
        if r.status_code == 404:
            return None
        if r.status_code == 403 and "PCSX is not enabled" in r.text:
            raise OlderApi(url)
        if r.status_code == 200 and "json" in r.headers.get("content-type", ""):
            return r.json()
        if attempt == RETRIES:
            r.raise_for_status()
            raise httpx.HTTPError(f"not JSON from {url}")
        await asyncio.sleep(2 ** attempt)


def from_v2(p: dict) -> dict:
    """An /api/apply/v2 position in the /api/pcsx shape."""
    return {"id": p["id"], "name": p.get("name", ""), "standardizedLocations": p.get("locations") or [],
            "postedTs": p.get("t_create"), "positionUrl": httpx.URL(p["canonicalPositionUrl"]).path
            if p.get("canonicalPositionUrl") else None}


async def details(client: httpx.AsyncClient, host: str, domain: str, pid) -> dict | None:
    """jobDescription and publicUrl, or None if the site no longer has the job (404)."""
    try:
        d = await get_json(client, f"https://{host}/api/pcsx/position_details",
                           {"position_id": pid, "domain": domain, "hl": "en"})
        return (d or {}).get("data") or None
    except OlderApi:
        d = await get_json(client, f"https://{host}/api/apply/v2/jobs/{pid}", {"domain": domain})
        return {"jobDescription": d.get("job_description"), "publicUrl": d.get("canonicalPositionUrl")} if d else None


async def search(client: httpx.AsyncClient, host: str, domain: str, query: str, start: int, v2: bool) -> list[dict]:
    params = {"domain": domain, "query": query, "location": "United States", "start": start}
    if v2:
        d = await get_json(client, f"https://{host}/api/apply/v2/jobs", params | {"num": PAGE})
        return [from_v2(p) for p in (d or {}).get("positions") or []]
    d = await get_json(client, f"https://{host}/api/pcsx/search", params)
    return ((d or {}).get("data") or {}).get("positions") or []


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    host, domain = parse_slug(company["slug"])
    found, v2 = {}, False
    for query in SEARCHES:
        irrelevant = 0
        for page in range(MAX_PAGES):
            try:
                positions = await search(client, host, domain, query, page * PAGE, v2)
            except OlderApi:
                v2 = True
                positions = await search(client, host, domain, query, page * PAGE, v2)
            new = [p for p in positions if p["id"] not in found]
            found |= {p["id"]: p for p in new}
            await asyncio.sleep(DELAY)
            if len(positions) < PAGE or not new:
                break
            irrelevant = 0 if any(RELEVANT.search(p.get("name", "")) for p in positions) else irrelevant + 1
            if irrelevant == IRRELEVANT_PAGES:
                company["partial"] = True   # relevance ran out; what's past it wasn't seen
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
