import re

import httpx
from recon.models import Job
from recon.text import strip_html

URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"
BOARD = "https://jobs.ashbyhq.com/{slug}"
# Boards whose Ashby-hosted pages are switched off (jobs.ashbyhq.com/<slug> is a 404 while the
# API still lists jobs): the company's own job page, checked in a browser. Other switched-off
# boards have no reliable per-job page, so linkcheck.is_open treats their jobs as gone.
CAREERS = {
    "cursor": "https://cursor.com/careers/{title}",   # all 115 jobs listed this way (Nov 2026)
}


def title_slug(title: str) -> str:
    """'Software Engineer, New Grad 2027' -> 'software-engineer-new-grad-2027'"""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def job_url(slug: str, j: dict) -> str:
    if slug in CAREERS:
        return CAREERS[slug].format(title=title_slug(j.get("title", "")))
    return j.get("jobUrl", "")


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    r = await client.get(URL.format(slug=company["slug"]))
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        if j.get("isListed") is False:
            continue
        jobs.append(Job(
            job_id=f"ashby:{company['slug']}:{j['id']}",
            company=company["company"],
            title=j.get("title", ""),
            location=j.get("location", "") or "",
            url=job_url(company["slug"], j),
            posted_at=j.get("publishedAt"),
            source="ashby",
            tier=int(company["tier"]),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
        ))
    return jobs
