"""Meta careers (metacareers.com). companies.csv row: "Meta,meta,meta,2" (the slug is unused).

Only the public requests the careers site itself makes, signed out:
1. The job search page, for the anonymous request token (LSD) it hands every visitor.
2. Its job search query (graphql, CareersJobSearchResultsV2DataQuery) with an empty search: every
   open job in one answer (id, title, locations), so the listing is complete and can close jobs.
3. A job's page, for new jobs that pass the title + location filter: its JobPosting JSON-LD has
   the description and posted date. A job Meta took down redirects to /jobs/position-not-available/
   with a 404.
If Meta answers with a login or security check instead, the run fails with Blocked: Recon stops
there and doesn't try to get around it.
"""
import asyncio
import json
import re

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

SITE = "https://www.metacareers.com"
SEARCH_PAGE = f"{SITE}/jobsearch/"
# the search query's id in the site's own code (Nov 2026); when Meta ships a new one this fails loudly
DOC_ID = "27129360303422352"
QUERY = "CareersJobSearchResultsV2DataQuery"
LSD = re.compile(r'"LSD",\[\],\{"token":"([^"]+)"')
JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
GONE_PAGE = "/jobs/position-not-available"
DELAY = 0.5         # seconds between job pages, be polite


class Blocked(Exception):
    """Meta answered with a login or security check instead of the page: stop, don't work around it."""


def job_url(jid: str) -> str:
    return f"{SITE}/jobs/{jid}/"


def blocked(r: httpx.Response) -> bool:
    return r.status_code in (403, 429) or any(p in r.url.path for p in ("/checkpoint", "/login"))


async def all_jobs(client: httpx.AsyncClient) -> list[dict]:
    page = await client.get(SEARCH_PAGE, follow_redirects=True)
    if blocked(page) or not (m := LSD.search(page.text)):
        raise Blocked(f"search page: HTTP {page.status_code}, no request token")
    lsd = m[1]
    search = {"q": "", "divisions": [], "offices": [], "roles": [], "leadership_levels": [], "saved_jobs": [],
              "saved_searches": [], "sub_teams": [], "teams": [], "is_leadership": False, "is_remote_only": False,
              "sort_by_new": False, "results_per_page": None}
    r = await client.post(f"{SITE}/graphql", headers={"X-FB-LSD": lsd}, data={
        "lsd": lsd, "doc_id": DOC_ID, "fb_api_req_friendly_name": QUERY, "__a": "1", "server_timestamps": "true",
        "variables": json.dumps({"search_input": search, "viewasUserID": None, "isLoggedIn": False})})
    if blocked(r):
        raise Blocked(f"job search: HTTP {r.status_code}")
    r.raise_for_status()
    data = (r.json().get("data") or {}).get("job_search_with_featured_jobs_v2")
    if data is None:
        raise ValueError("job search answered without jobs (query changed?)")
    return data.get("all_jobs") or []


def posting(html: str) -> dict | None:
    for block in JSON_LD.findall(html):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return d
    return None


async def details(client: httpx.AsyncClient, jid: str) -> dict | None:
    """The job's JobPosting, or None if Meta took the job down."""
    r = await client.get(job_url(jid), follow_redirects=True)
    if r.status_code == 404 or GONE_PAGE in r.url.path:
        return None
    if blocked(r):
        raise Blocked(f"job page: HTTP {r.status_code}")
    r.raise_for_status()
    if (d := posting(r.text)) is None:
        raise ValueError(f"job page {jid} has no JobPosting")
    return d


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    jobs = []
    for p in await all_jobs(client):
        job = Job(job_id=f"meta:meta:{p['id']}", company=company["company"], title=p.get("title", ""),
                  location="; ".join(p.get("locations") or []), url=job_url(p["id"]), posted_at=None,
                  source="meta", tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the job page
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            info = await details(client, p["id"])
            await asyncio.sleep(DELAY)
            if info:
                job.description = strip_html(" ".join(str(info.get(k) or "") for k in (
                    "description", "responsibilities", "qualifications")))
                job.posted_at = (info.get("datePosted") or "")[:10] or None
        jobs.append(job)
    return jobs
