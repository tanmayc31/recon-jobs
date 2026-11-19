"""ByteDance and TikTok careers (joinbytedance.com, lifeattiktok.com). companies.csv rows:
"ByteDance,bytedance,bytedance,2" and "TikTok,bytedance,tiktok,2" (slug = which site).

Only the public requests the sites themselves make, signed out: their filters (the US cities) and
their job search, with the same "website-path" header the sites send. Every US job comes with its
description and requirements, PAGE at a time, so there are no per-job requests and the listing is
complete. A job's page has its title in <title>; a job that's gone has an empty one (the open check).
A job on both sites is one job (same id).
"""
import asyncio
import re

import httpx

from recon.models import Job
from recon.text import strip_html

SITES = {   # slug -> (API, site, website-path header the site sends)
    "tiktok": ("https://api.lifeattiktok.com", "https://lifeattiktok.com", "tiktok"),
    "bytedance": ("https://jobs.bytedance.com", "https://joinbytedance.com", "en"),
}
PAGE = 100
DELAY = 0.3
MAX_PAGES = 60
US = {"United States of America", "United States", "USA"}
TITLE = re.compile(r"<title>(.*?)</title>", re.S)


class Blocked(Exception):
    """The site answered with a block or a challenge: stop, don't work around it."""


def headers(slug: str) -> dict:
    _, site, path = SITES[slug]
    return {"website-path": path, "origin": site, "referer": site + "/", "accept-language": "en-US"}


async def post(client: httpx.AsyncClient, slug: str, path: str, body: dict) -> dict:
    api = SITES[slug][0]
    r = await client.post(f"{api}/api/v1/public/supplier/{path}", json=body, headers=headers(slug))
    if r.status_code in (403, 429) or (r.status_code == 200 and "json" not in r.headers.get("content-type", "")):
        raise Blocked(f"{slug} {path}: HTTP {r.status_code}")
    r.raise_for_status()
    d = r.json()
    if d.get("code") != 0:
        raise ValueError(f"{slug} {path}: {d.get('message')}")
    return d["data"]


def root(loc: dict) -> dict:
    while loc.get("parent"):
        loc = loc["parent"]
    return loc


def place(city: dict) -> str:
    """city_info (city -> state -> country) -> "Seattle, Washington, United States"."""
    names, loc = [], city
    while loc:
        names.append(loc.get("en_name") or loc.get("i18n_name") or "")
        loc = loc.get("parent")
    if names and names[-1] in US:
        names[-1] = "United States"
    return ", ".join(dict.fromkeys(n for n in names if n))


def job_url(slug: str, jid: str) -> str:
    return f"{SITES[slug][1]}/search/{jid}"


async def is_open(client: httpx.AsyncClient, slug: str, jid: str) -> bool:
    r = await client.get(job_url(slug, jid), follow_redirects=True)
    if r.status_code in (403, 429):
        raise Blocked(f"{slug} job page: HTTP {r.status_code}")
    r.raise_for_status()
    m = TITLE.search(r.text)
    return bool(m and m[1].strip())


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    slug = company["slug"]
    cities = (await post(client, slug, "config/job/filters", {})).get("city_list") or []
    us = [c["code"] for c in cities if root(c).get("en_name") in US]
    if not us:
        raise ValueError(f"{slug}: no US cities in the site's filters (changed?)")
    found = {}
    for page in range(MAX_PAGES):
        data = await post(client, slug, "search/job/posts", {
            "recruitment_id_list": [], "job_category_id_list": [], "subject_id_list": [],
            "location_code_list": us, "keyword": "", "limit": PAGE, "offset": page * PAGE})
        posts = data.get("job_post_list") or []
        found |= {p["id"]: p for p in posts}
        await asyncio.sleep(DELAY)
        if len(posts) < PAGE:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    return [Job(job_id=f"bytedance:jobs:{p['id']}", company=company["company"], title=(p.get("title") or "").strip(),
                location=place(p.get("city_info") or {}), url=job_url(slug, p["id"]), posted_at=None,
                source="bytedance", tier=int(company["tier"]),
                description=strip_html(f"{p.get('description') or ''}\n{p.get('requirement') or ''}"))
            for p in found.values()]
