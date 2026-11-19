"""SmartRecruiters (ServiceNow, AbbVie, Nagarro, ASML, ...). Config slug = the company identifier in
its careers URL (careers.smartrecruiters.com/<slug>), e.g. ServiceNow, Nagarro1.

Public Posting API (api.smartrecruiters.com/v1/companies/<slug>/postings): every US posting, PAGE at
a time, so the listing is complete and can close jobs. Descriptions come from the posting's own
endpoint, only for new jobs that pass the title + location filter; it answers 404 (or active:
false) for a posting that's gone.
"""
import asyncio

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE = 100          # the API's largest page
DELAY = 0.2         # seconds between requests, be polite
MAX_PAGES = 50      # safety stop (Mindlance: ~1,400 US postings = 14 pages)
SECTIONS = ["jobDescription", "qualifications", "additionalInformation"]


def job_url(slug: str, pid: str) -> str:
    return f"https://jobs.smartrecruiters.com/{slug}/{pid}"


async def details(client: httpx.AsyncClient, slug: str, pid: str) -> dict | None:
    """The posting, or None if it's gone (404, or no longer active)."""
    r = await client.get(f"{API.format(slug=slug)}/{pid}")
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()
    return d if d.get("active", True) else None


def location(p: dict) -> str:
    loc = p.get("location") or {}
    full = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)
    return f"{full} (Remote)" if loc.get("remote") else full


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    slug = company["slug"]
    found = {}
    for page in range(MAX_PAGES):
        r = await client.get(API.format(slug=slug), params={"country": "us", "limit": PAGE, "offset": page * PAGE})
        r.raise_for_status()
        postings = r.json().get("content") or []
        found |= {p["id"]: p for p in postings}
        await asyncio.sleep(DELAY)
        if len(postings) < PAGE:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    jobs = []
    for p in found.values():
        job = Job(job_id=f"smartrecruiters:{slug}:{p['id']}", company=company["company"], title=p.get("name", ""),
                  location=location(p), url=job_url(slug, p["id"]), posted_at=(p.get("releasedDate") or "")[:10] or None,
                  source="smartrecruiters", tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the detail request
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            info = await details(client, slug, p["id"])
            await asyncio.sleep(DELAY)
            if info:
                sections = (info.get("jobAd") or {}).get("sections") or {}
                job.description = strip_html(" ".join((sections.get(s) or {}).get("text") or "" for s in SECTIONS))
                job.url = info.get("postingUrl") or job.url
        jobs.append(job)
    return jobs
