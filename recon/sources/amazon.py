"""amazon.jobs: the public search JSON its own search page loads (www.amazon.jobs/en/search.json).

Filtered server-side to US, full-time, and software / cloud / systems categories. The results
already carry the description and qualifications, so there are no per-job detail requests.
Amazon posts one requisition per opening, so identical title + location postings collapse into one
job ("N openings"). Its ID comes from title + location, not one requisition, so a closed
requisition doesn't make the same role look new; every Amazon job ID is kept in source_ids.
If amazon.jobs ever blocks or challenges us, we stop (Blocked) instead of working around it.
"""
import asyncio
import hashlib
import json
from datetime import datetime

import httpx
from recon.models import Job
from recon.text import strip_html

SEARCH = "https://www.amazon.jobs/en/search.json"
SITE = "https://www.amazon.jobs"
PAGE = 100          # largest page amazon.jobs serves
DELAY = 0.5         # seconds between pages, be polite
MAX_OFFSET = 10000  # amazon.jobs stops at 10,000 results per query
CATEGORIES = [
    "software-development",                   # SDE
    "operations-it-support-engineering",      # cloud support, DevOps, systems development engineers
    "systems-quality-security-engineering",   # SysDE, QAE, security engineers
    "solutions-architect",                    # AWS cloud
]
FILTERS = [("normalized_country_code[]", "USA"), ("schedule_type_id[]", "Full-Time"), ("sort", "recent")] + \
          [("category[]", c) for c in CATEGORIES]


class Blocked(Exception):
    """amazon.jobs refused or challenged the request (not JSON, or not 200): stop, don't work around it."""


async def search_page(client: httpx.AsyncClient, offset: int) -> dict:
    r = await client.get(SEARCH, params=FILTERS + [("offset", offset), ("result_limit", PAGE)])
    if r.status_code != 200 or "json" not in r.headers.get("content-type", ""):
        raise Blocked(f"amazon.jobs answered {r.status_code} ({r.headers.get('content-type', '?')})")
    return r.json()


def location(j: dict) -> str:
    """'Jessup, MD; Seattle, WA' for multi-location jobs, else 'US, WA, Seattle'."""
    places = []
    for loc in j.get("locations") or []:
        loc = json.loads(loc) if isinstance(loc, str) else loc
        place = ", ".join(p for p in (loc.get("city"), loc.get("region")) if p) or loc.get("location")
        if place and place.lower() not in (p.lower() for p in places):   # "SANTA CLARA, CA" twice
            places.append(place)
    return "; ".join(places) if len(places) > 1 else j.get("location") or (places[0] if places else "")


def posted(text: str | None) -> str | None:
    """'November 10, 2026' -> '2026-11-10'."""
    try:
        return datetime.strptime(text.strip(), "%B %d, %Y").date().isoformat()
    except (AttributeError, ValueError):
        return None


def to_job(j: dict, company: dict) -> Job:
    parts = [strip_html(j.get("description")),
             "Basic qualifications: " + strip_html(j.get("basic_qualifications")),
             "Preferred qualifications: " + strip_html(j.get("preferred_qualifications"))]
    return Job(
        job_id=f"amazon:{j['id_icims']}",   # Amazon's job ID, the number in the job URL
        company=company["company"],
        title=j.get("title", ""),
        location=location(j),
        url=SITE + j.get("job_path", ""),
        posted_at=posted(j.get("posted_date")),
        source="amazon",
        tier=int(company["tier"]),
        description=" ".join(parts),
    )


def collapse(jobs: list[Job]) -> list[Job]:
    """One job per title + location. Jobs come newest first, so the newest posting gives the URL and date."""
    groups = {}
    for j in jobs:
        groups.setdefault((j.title.strip().lower(), j.location.strip().lower()), []).append(j)
    out = []
    for (title, loc), group in groups.items():
        job = group[0]
        ids = sorted({g.job_id.split(":", 1)[1] for g in group}, key=lambda i: (len(i), i))
        job.job_id = "amazon:" + hashlib.sha1(f"{title}|{loc}".encode()).hexdigest()[:12]
        job.openings, job.source_ids = len(ids), ",".join(ids)
        out.append(job)
    return out


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    jobs, seen, offset = [], set(), 0
    while offset < MAX_OFFSET:
        data = await search_page(client, offset)
        page = data.get("jobs") or []   # null past the last page
        for j in page:
            if j.get("id_icims") and j["id_icims"] not in seen:
                seen.add(j["id_icims"])
                jobs.append(to_job(j, company))
        offset += PAGE
        if not page or offset >= (data.get("hits") or 0):
            break
        await asyncio.sleep(DELAY)
    else:
        company["partial"] = True   # stopped at MAX_OFFSET: missing jobs may still be open
    return collapse(jobs)
