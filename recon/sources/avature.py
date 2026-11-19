"""Avature career sites (Deloitte, Bloomberg). Config slug = the site's careers path, e.g.
apply.deloitte.com/en_US/careers or bloomberg.avature.net/careers.

Public pages only, the ones the site's own job search serves: SearchJobs with the keyword box
(SEARCHES), paged the way the site pages (10 a page at Deloitte, 12 at Bloomberg; "jobOffset", or
"folderOffset" on some sites). A card gives the title and usually the location; one that says
"Multiple Locations" (or none) is checked on its title and gets its location from the job's page.
The job's page (JobDetail) has the description: JobPosting JSON-LD where the site has it (Deloitte),
else the page's text fields. A job that's gone sends you to the site's Error page. If the site
answers with a challenge (AWS WAF: Delta, IBM), the run fails with Blocked: Recon doesn't work
around it.
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

SEARCHES = ["software engineer", "developer"]
DELAY = 0.4
MAX_PAGES = 60      # per search (Deloitte "software engineer": ~38 pages of 10)
CARD = re.compile(r'<article class="[^"]*article--result.*?</article>', re.S)
LINK = re.compile(r'href="(https://[^"]*/JobDetail/[^"]*?(\d+))"[^>]*>\s*([^<]+?)\s*</a>', re.S)
SUBTITLE = re.compile(r'article__header__text__subtitle">(.*?)</div>', re.S)
OFFSET = re.compile(r"[?&;](\w+)Offset=\d+")
FIELDS = re.compile(r'class="article__content__view__field__value[^"]*">(.*?)</div>', re.S)
JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S)
UNKNOWN = re.compile(r"multiple locations|^$", re.I)
# "Same job available in 38 locations": the list on the job's page (Deloitte)
PLACE_LIST = re.compile(r'article__header--locations[^"]*"[^>]*>(.*?)</div>\s*</div>', re.S)


class Blocked(Exception):
    """The site answered with a challenge or a block: stop, don't work around it."""


def check(r: httpx.Response, what: str) -> httpx.Response:
    if r.headers.get("x-amzn-waf-action") or r.status_code == 429 or (r.status_code == 202 and not r.text):
        raise Blocked(f"{what}: HTTP {r.status_code} {r.headers.get('x-amzn-waf-action') or ''}".strip())
    return r


def text(fragment: str) -> str:
    return " ".join(html.unescape(strip_html(fragment)).split())


def cards(page: str) -> list[dict]:
    out = []
    for card in CARD.findall(page):
        link = LINK.search(card)
        if not link:
            continue
        sub = SUBTITLE.search(card)
        parts = [text(p) for p in re.findall(r"<span[^>]*>(.*?)</span>", sub[1], re.S)] if sub else []
        place = next((p for p in reversed(parts) if p), "")   # the location is the last part
        out.append({"url": link[1], "id": link[2], "title": text(link[3]),
                    "location": "" if UNKNOWN.search(place) else place})
    return out


def page_places(page: str) -> str:
    m = PLACE_LIST.search(page)
    return "; ".join(dict.fromkeys(p for p in (text(x) for x in re.findall(r"<p[^>]*>(.*?)</p>", m[1], re.S)) if p)) if m else ""


def posting(page: str) -> dict:
    """Description, location and posted date from a job's page."""
    listed = page_places(page)
    for block in JSON_LD.findall(page):
        try:
            d = json.loads(block)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "JobPosting":
            locs = d.get("jobLocation") or []
            places = []
            for loc in locs if isinstance(locs, list) else [locs]:
                a = (loc or {}).get("address") or {}
                places.append(", ".join(p for p in (a.get("addressLocality"), a.get("addressRegion"),
                                                    a.get("addressCountry")) if p))
            return {"description": text(d.get("description") or ""), "posted": (d.get("datePosted") or "")[:10] or None,
                    "location": "; ".join(dict.fromkeys(p for p in places if p)) or listed}
    return {"description": " ".join(text(f) for f in FIELDS.findall(page)), "posted": None, "location": listed}


async def details(client: httpx.AsyncClient, url: str) -> dict | None:
    """The job's posting, or None if it's gone (the site's Error page, 403 or 404)."""
    r = check(await client.get(url, follow_redirects=True), "job page")
    if r.status_code in (403, 404, 410) or "/Error" in r.url.path:
        return None
    r.raise_for_status()
    return posting(r.text)


async def search(client: httpx.AsyncClient, base: str, keyword: str, company: dict) -> dict[str, dict]:
    found, param, offset = {}, "job", 0
    for page in range(MAX_PAGES):
        r = check(await client.get(f"{base}/SearchJobs/", params={"search": keyword, f"{param}Offset": offset},
                                   follow_redirects=True), "search")
        r.raise_for_status()
        if page == 0 and (m := OFFSET.search(html.unescape(r.text))):
            param = m[1]   # "folderOffset" on some sites
        new = {c["id"]: c for c in cards(r.text) if c["id"] not in found}
        found |= new
        offset += len(new)
        await asyncio.sleep(DELAY)
        if not new:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    return found


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    base = "https://" + company["slug"].rstrip("/")
    found = {}
    for keyword in SEARCHES:
        found |= await search(client, base, keyword, company)
    host = company["slug"].split("/")[0]
    jobs = []
    for c in found.values():
        job = Job(job_id=f"avature:{host}:{c['id']}", company=company["company"], title=c["title"], location=c["location"],
                  url=c["url"], posted_at=None, source="avature", tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict. No location on the card: the title decides, the
        # job's page gives the location (main filters on it)
        check_job = job if job.location else dataclasses.replace(job, location="United States")
        if job.job_id not in company.get("known", ()) and classify(check_job)[0]:
            info = await details(client, c["url"])
            await asyncio.sleep(DELAY)
            if info:
                job.description, job.posted_at = info["description"], info["posted"]
                job.location = job.location or info["location"]
        jobs.append(job)
    return jobs
