"""Greenhouse boards. The job list is fetched without content=true (much smaller); the
description is fetched only for new jobs that pass the title + location filter."""
import httpx
from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    api = API.format(slug=company["slug"])
    r = await client.get(api)
    r.raise_for_status()
    jobs = []
    for j in r.json().get("jobs", []):
        job = Job(
            job_id=f"greenhouse:{company['slug']}:{j['id']}",
            company=company["company"],
            title=j.get("title", ""),
            location=(j.get("location") or {}).get("name", ""),
            url=j.get("absolute_url", ""),
            posted_at=j.get("first_published"),   # updated_at is not a posted date
            updated_at=j.get("updated_at"),
            source="greenhouse",
            tier=int(company["tier"]),
        )
        # known jobs keep their stored verdict, so skip the detail request
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            d = await client.get(f"{api}/{j['id']}")
            if d.status_code == 200:   # else main judges it without a description
                job.description = strip_html(d.json().get("content"))
        jobs.append(job)
    return jobs
