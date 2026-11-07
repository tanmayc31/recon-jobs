"""Workday career sites. Config slug = tenant|wdN|site, e.g. nvidia|wd5|NVIDIAExternalCareerSite.

The search list has no descriptions, so we fetch the detail page only for new jobs
that pass the title + location filter (far fewer requests).
"""
import asyncio
import re

import httpx
from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

BASE = "https://{tenant}.{wd}.myworkdayjobs.com"
PAGE = 20          # Workday's max page size
DELAY = 0.2        # seconds between requests, be polite
MAX_OFFSET = 5000  # safety stop; "total" is 0 after page 1, so we don't trust it
# Tier 3 (hundreds of discovered tenants): search instead of paging through every posting.
# The title filter needs "engineer"/"developer" (or SWE/SDE/SRE) anyway.
TIER3_SEARCHES = ["engineer", "developer"]
# "4 Locations" in search results -> real list only in the detail
MULTI = re.compile(r"^\d+\s+locations?$", re.I)


def search_id(posting: dict) -> str:
    """Requisition ID from a search result: the bullet the path ends with ("..._R1003192-1").
    Not simply bullets[0]: F5 lists ['0', 'RP1038981'], which gave every F5 job the ID "0"."""
    path = posting["externalPath"]
    for b in posting.get("bulletFields") or []:
        if b and re.search(rf"_{re.escape(b)}(-\d+)?$", path):
            return b
    return path


def parse_slug(slug: str) -> tuple[str, str, str]:
    tenant, wd, site = slug.split("|")
    return tenant, wd, site


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    tenant, wd, site = parse_slug(company["slug"])
    base = BASE.format(tenant=tenant, wd=wd)
    api = f"{base}/wday/cxs/{tenant}/{site}"

    postings, seen = [], set()
    for search in TIER3_SEARCHES if int(company["tier"]) >= 3 else [""]:
        offset = 0
        while offset < MAX_OFFSET:
            r = await client.post(f"{api}/jobs", json={"appliedFacets": {}, "limit": PAGE,
                                                       "offset": offset, "searchText": search})
            r.raise_for_status()
            page = r.json().get("jobPostings") or []
            fresh = [p for p in page if p.get("externalPath") and p["externalPath"] not in seen]
            if not fresh:
                break   # out of results, or past Workday's 2000 cap (it wraps back to page 1)
            for p in fresh:
                seen.add(p["externalPath"])
                postings.append(p)
            offset += PAGE
            await asyncio.sleep(DELAY)

    jobs = []
    for p in postings:
        loc = p.get("locationsText", "") or ""
        job = Job(
            job_id=f"workday:{tenant}:{search_id(p)}",
            company=company["company"],
            title=p.get("title", ""),
            location="Multiple Locations" if MULTI.match(loc) else loc,
            url=f"{base}/{site}{p['externalPath']}",
            posted_at=p.get("postedOn"),   # relative text: "Posted 30+ Days Ago"
            source="workday",
            tier=int(company["tier"]),
            description="",
        )
        # known jobs keep their stored verdict, so skip the detail request
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            await add_detail(client, api, p["externalPath"], job, tenant)
        jobs.append(job)
    return jobs


async def add_detail(client, api, path, job, tenant):
    r = await client.get(f"{api}{path}")
    await asyncio.sleep(DELAY)
    if r.status_code != 200:
        return   # keep the search-level job; main will judge it without a description
    info = r.json().get("jobPostingInfo") or {}
    if info.get("jobReqId"):
        job.job_id = f"workday:{tenant}:{info['jobReqId']}"   # same req across reposts
    places = [info.get("location")] + (info.get("additionalLocations") or [])
    job.location = "; ".join(p for p in places if p) or job.location
    job.url = info.get("externalUrl") or job.url
    job.posted_at = info.get("postedOn") or job.posted_at
    job.description = strip_html(info.get("jobDescription"))
