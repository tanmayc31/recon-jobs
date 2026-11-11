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
# Tier 3 (hundreds of discovered tenants) and big boards: search instead of paging through every
# posting. The title filter needs "engineer"/"developer" (or SWE/SDE/SRE) anyway.
SEARCHES = ["engineer", "developer"]
# Big boards (RTX 4,600 postings, Nvidia 2,000+) ran past the 2-minute company timeout. Above
# BIG_BOARD, filter with the board's own facets: US, regular full-time, software/engineering family.
# Still above it after filtering: fetch PARALLEL_PAGES pages at a time.
BIG_BOARD = 1000
PARALLEL_PAGES = 3
RETRIES = 3        # 429s: wait 1s, 2s, 4s, then give up on the company this run
MAX_FACET_VALUES = 100   # RTX's 386 US sites in one request -> HTTP 500; 100 at a time works
US_COUNTRY = re.compile(r"^(united states( of america)?|usa|us)$", re.I)
US_SITE = re.compile(r"^US[-\s,]|\bUnited States\b|\bUSA\b")   # RTX: "US-IA-CEDAR RAPIDS-112 ~ ..."
NOT_REGULAR = re.compile(r"intern|co-?op|contract|temp|apprentice|fixed term|trainee|academic|part[- ]time", re.I)
FULL_TIME = re.compile(r"full", re.I)
SOFTWARE_FAMILY = re.compile(r"engineer|software|technolog|\bIT\b|digital|univ|graduate|campus|early career",
                             re.I)   # Nvidia's new-grad roles sit under "Univ Employment"
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
    for search in SEARCHES if int(company["tier"]) >= 3 else [""]:
        first = await search_page(client, api, search, 0)
        filters, firsts = [{}], [first]
        if (first.get("total") or 0) > BIG_BOARD:   # "total" is only right on page 1
            filters = big_board_facets(first.get("facets") or []) or [{}]
            if filters != [{}]:
                firsts = [await search_page(client, api, search, 0, f) for f in filters]
        parallel = sum(f.get("total") or 0 for f in firsts) > BIG_BOARD   # still big after filtering
        for facets, page1 in zip(filters, firsts):
            await page_through(client, api, search, postings, seen, page1, facets, parallel)

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


def flat_facets(facets: list[dict]) -> dict[str, list[dict]]:
    """facetParameter -> values. Location facets nest inside a group (Nvidia's locationMainGroup)."""
    out = {}
    for f in facets:
        values = f.get("values") or []
        nested = [v for v in values if "facetParameter" in v]
        if nested:
            out |= flat_facets(nested)
        else:
            out[f["facetParameter"]] = values
    return out


def big_board_facets(facets: list[dict]) -> list[dict[str, list[str]]]:
    """appliedFacets for a big board: US, regular full-time, software/engineering family (where offered).
    One dict per request: a long list of US sites is split into chunks of MAX_FACET_VALUES."""
    applied, sites = {}, {}
    for param, values in flat_facets(facets).items():
        name = param.lower()
        pick = lambda rx, keep=True: [v["id"] for v in values if bool(rx.search(v.get("descriptor", ""))) == keep]
        if "location" in name or "country" in name:
            if ids := pick(US_COUNTRY):
                applied[param] = ids
            elif ids := pick(US_SITE):
                sites[param] = ids
        elif name.startswith("workersubtype") or name.startswith("workertype"):
            ids = pick(NOT_REGULAR, keep=False)
            if 0 < len(ids) < len(values):
                applied[param] = ids
        elif name.startswith("timetype"):
            if ids := pick(FULL_TIME):
                applied[param] = ids
        elif name.startswith("jobfamily"):
            if ids := pick(SOFTWARE_FAMILY):
                applied[param] = ids
    if not any("location" in k.lower() or "country" in k.lower() for k in applied) and sites:
        best = max(sites, key=lambda k: len(sites[k]))   # no country facet: every US site
        applied[best] = sites[best]
    if "jobFamilyGroup" in applied:
        applied.pop("jobFamily", None)   # the group is enough; both would AND together
    long = next((k for k, ids in applied.items() if len(ids) > MAX_FACET_VALUES), None)
    if not long:
        return [applied] if applied else []
    ids = applied[long]
    return [applied | {long: ids[i:i + MAX_FACET_VALUES]} for i in range(0, len(ids), MAX_FACET_VALUES)]


async def search_page(client, api, search, offset, facets=None) -> dict:
    for attempt in range(RETRIES + 1):
        r = await client.post(f"{api}/jobs", json={"appliedFacets": facets or {}, "limit": PAGE,
                                                   "offset": offset, "searchText": search})
        if r.status_code != 429 or attempt == RETRIES:
            break
        await asyncio.sleep(2 ** attempt)   # back off: 1s, 2s, 4s
    r.raise_for_status()
    return r.json()


def add_fresh(page: list[dict], postings: list, seen: set) -> bool:
    fresh = [p for p in page if p.get("externalPath") and p["externalPath"] not in seen]
    for p in fresh:
        seen.add(p["externalPath"])
        postings.append(p)
    return bool(fresh)


async def page_through(client, api, search, postings, seen, first, facets=None, parallel=False):
    """Add every posting for this search to postings. first: page 1, already fetched.
    parallel: the board is still big after filtering, so fetch PARALLEL_PAGES pages at a time."""
    total = first.get("total") or 0
    if not add_fresh(first.get("jobPostings") or [], postings, seen):
        return
    if parallel:
        sem = asyncio.Semaphore(PARALLEL_PAGES)

        async def one(offset):
            async with sem:
                data = await search_page(client, api, search, offset, facets)
                await asyncio.sleep(DELAY)
                return data.get("jobPostings") or []
        pages = await asyncio.gather(*(one(o) for o in range(PAGE, min(total, MAX_OFFSET), PAGE)))
        for page in pages:
            add_fresh(page, postings, seen)
        return
    offset = PAGE
    while offset < MAX_OFFSET:
        await asyncio.sleep(DELAY)
        data = await search_page(client, api, search, offset, facets)
        if not add_fresh(data.get("jobPostings") or [], postings, seen):
            break   # out of results, or past Workday's 2000 cap (it wraps back to page 1)
        offset += PAGE


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
