import httpx
from recon.models import Job
from recon.text import strip_html

URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    r = await client.get(URL.format(slug=company["slug"]))
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        jobs.append(Job(
            job_id=f"greenhouse:{company['slug']}:{j['id']}",
            company=company["company"],
            title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
            posted_at=j.get("first_published") or j.get("updated_at"),
            source="greenhouse",
            tier=int(company["tier"]),
            description=strip_html(j.get("content")),
        ))
    return jobs
