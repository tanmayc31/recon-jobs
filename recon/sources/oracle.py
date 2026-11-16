"""Oracle HCM (Oracle Recruiting Cloud) career sites: JPMorgan Chase, Goldman Sachs, American Express,
Oracle, Ford, ... Config slug = host|site, e.g. jpmc.fa.oraclecloud.com|CX_1001.

Public Candidate Experience API (/hcmRestApi/resources/latest/recruitingCEJobRequisitions), the one
the career site itself calls. Every US posting is read, PAGE at a time (its keyword search also
matches descriptions, so it narrows little): the listing is complete and can close jobs. The US
filter is the site's own "United States" location facet. Descriptions come from
recruitingCEJobRequisitionDetails, only for new jobs that pass the title + location filter.
"""
import asyncio

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

PAGE = 200          # the API's largest page
DELAY = 0.3         # seconds between requests, be polite
MAX_PAGES = 100     # safety stop (Safeway: ~8,600 US postings = 43 pages)
US = {"United States", "United States of America", "USA"}
# expand is required: without it, every page past the first comes back empty
EXPAND = "requisitionList.secondaryLocations"


def parse_slug(slug: str) -> tuple[str, str]:
    host, site = slug.split("|")
    return host, site


def job_url(host: str, site: str, rid) -> str:
    return f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}"


async def search(client: httpx.AsyncClient, host: str, site: str, offset: int, extra: str = "") -> dict:
    finder = f"findReqs;siteNumber={site},limit={PAGE},offset={offset},sortBy=POSTING_DATES_DESC" + extra
    r = await client.get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions",
                         params={"onlyData": "true", "expand": EXPAND, "finder": finder})
    r.raise_for_status()
    return (r.json().get("items") or [{}])[0]


async def details(client: httpx.AsyncClient, host: str, site: str, rid) -> dict | None:
    """The posting, or None if the site no longer has it (the API answers an empty list)."""
    r = await client.get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
                         params={"expand": "all", "onlyData": "true", "finder": f'ById;Id="{rid}",siteNumber={site}'})
    r.raise_for_status()
    items = r.json().get("items") or []
    return items[0] if items else None


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    host, site = parse_slug(company["slug"])
    first = await search(client, host, site, 0, ",facetsList=LOCATIONS")
    us = next((f["Id"] for f in first.get("locationsFacet") or [] if f.get("Name") in US), None)
    if us is None:
        return []   # no US postings on this site
    found, extra = {}, f",selectedLocationsFacet={us}"
    for page in range(MAX_PAGES):
        reqs = (await search(client, host, site, page * PAGE, extra)).get("requisitionList") or []
        found |= {r["Id"]: r for r in reqs}
        await asyncio.sleep(DELAY)
        if len(reqs) < PAGE:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    jobs = []
    for r in found.values():
        locs = [r.get("PrimaryLocation")] + [s.get("Name") for s in r.get("secondaryLocations") or []]
        job = Job(job_id=f"oracle:{host}:{r['Id']}", company=company["company"], title=r.get("Title", ""),
                  location="; ".join(dict.fromkeys(x for x in locs if x)), url=job_url(host, site, r["Id"]),
                  posted_at=r.get("PostedDate"), source="oracle", tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the detail request
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            info = await details(client, host, site, r["Id"])
            await asyncio.sleep(DELAY)
            if info:
                job.description = strip_html(" ".join(info.get(k) or "" for k in (
                    "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")))
        jobs.append(job)
    return jobs
