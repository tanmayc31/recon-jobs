import httpx
from recon.models import Job
from recon.text import strip_html

URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


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
            url=j.get("jobUrl", ""),
            posted_at=j.get("publishedAt"),
            source="ashby",
            tier=int(company["tier"]),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
        ))
    return jobs
