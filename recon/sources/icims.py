"""iCIMS career sites (Charles Schwab, ICE, Liberty Mutual, UWM, Cotiviti). Config slug = the site's
host, e.g. career-schwab.icims.com.

Public pages only, the ones the site's own job search serves: /jobs/search lists every open job,
50 a page (read until a page adds none), so the listing is complete and can close jobs. A job's
page (/jobs/<id>/job) has its JobPosting JSON-LD (description, posted date, locations), read only
for new jobs that pass the title + location filter; it answers 410 for a job that's gone. Some
sites (Liberty Mutual, UWM) list no locations: their jobs are checked on the title, and the
location comes from the job's page.
"""
import asyncio
import dataclasses
import html
import json
import re

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

DELAY = 0.4         # seconds between requests, be polite
MAX_PAGES = 80      # safety stop (50 jobs a page)
CARD = re.compile(r'<li class="iCIMS_JobCardItem">(.*?)</li>', re.S)
LINK = re.compile(r'href="https://[^"/]+/jobs/(\d+)/([^"/]+)/job[^"]*"')
TITLE = re.compile(r"<h3[^>]*>(.*?)</h3>", re.S)
PLACES = re.compile(r'field-label">(?:Job )?Locations?</span>\s*<span[^>]*>(.*?)</span>', re.S)   # "Location" at ICE
# "US-AZ-Phoenix" -> "Phoenix, AZ, US"; "US-Remote" -> "Remote, US"
ICIMS_PLACE = re.compile(r"^([A-Z]{2})-(?:([A-Z]{2})-)?(.+)$")
JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)


class Blocked(Exception):
    """The site answered with a block: stop, don't work around it."""


def place(text: str) -> str:
    text = text.strip()
    m = ICIMS_PLACE.match(text)
    if not m:
        return text
    country, state, city = m.groups()
    return ", ".join(p for p in (city.strip(), state, country) if p)


def ld_places(posting: dict) -> str:
    """JobPosting jobLocation -> "Boston, MA, US; ..."."""
    locs = posting.get("jobLocation") or []
    out = []
    for loc in locs if isinstance(locs, list) else [locs]:
        a = (loc or {}).get("address") or {}
        out.append(", ".join(p for p in (a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")) if p))
    return "; ".join(dict.fromkeys(p for p in out if p))


def cards(page: str) -> list[dict]:
    out = []
    for card in CARD.findall(page):
        link, title = LINK.search(card), TITLE.search(card)
        if not link or not title:
            continue
        places = PLACES.search(card)
        out.append({"id": link[1], "slug": link[2], "title": html.unescape(strip_html(title[1])).strip(),
                    "location": "; ".join(place(p) for p in html.unescape(strip_html(places[1])).split("|") if p.strip())
                    if places else ""})
    return out


async def get(client: httpx.AsyncClient, url: str, **params) -> httpx.Response:
    r = await client.get(url, params=params, follow_redirects=True)
    if r.status_code in (403, 429):
        raise Blocked(f"{url}: HTTP {r.status_code}")
    return r


async def details(client: httpx.AsyncClient, host: str, jid: str) -> dict | None:
    """The job's JobPosting, or None if it's gone (410, or 404)."""
    r = await get(client, f"https://{host}/jobs/{jid}/job", in_iframe="1")
    if r.status_code in (404, 410):
        return None
    r.raise_for_status()
    for block in JSON_LD.findall(r.text):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            return d
    raise ValueError(f"job page {jid} has no JobPosting")


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    host = company["slug"]
    found = {}
    for page in range(MAX_PAGES):
        r = await get(client, f"https://{host}/jobs/search", ss="1", in_iframe="1", pr=str(page))
        r.raise_for_status()
        new = {c["id"]: c for c in cards(r.text) if c["id"] not in found}
        found |= new
        await asyncio.sleep(DELAY)
        if not new:   # past the last page (iCIMS repeats it or shows none)
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    jobs = []
    for c in found.values():
        job = Job(job_id=f"icims:{host}:{c['id']}", company=company["company"], title=c["title"], location=c["location"],
                  url=f"https://{host}/jobs/{c['id']}/{c['slug']}/job", posted_at=None, source="icims",
                  tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the job page. No location listed: the title
        # decides, the job's page gives the location (main filters on it)
        check = job if job.location else dataclasses.replace(job, location="United States")
        if job.job_id not in company.get("known", ()) and classify(check)[0]:
            info = await details(client, host, c["id"])
            await asyncio.sleep(DELAY)
            if info:
                job.description = strip_html(html.unescape(info.get("description") or ""))
                job.posted_at = (info.get("datePosted") or "")[:10] or None
                job.location = job.location or ld_places(info)
        jobs.append(job)
    return jobs
