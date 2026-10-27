from datetime import datetime, timezone
import httpx
from recon.models import Job
from recon.text import strip_html

URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    r = await client.get(URL.format(slug=company["slug"]))
    r.raise_for_status()
    jobs = []
    for j in r.json():
        created = j.get("createdAt")  # milliseconds
        posted = (datetime.fromtimestamp(created / 1000, tz=timezone.utc).isoformat()
                  if created else None)
        parts = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            parts.append(lst.get("text", ""))
            parts.append(strip_html(lst.get("content")))
        parts.append(j.get("additionalPlain") or "")
        jobs.append(Job(
            job_id=f"lever:{company['slug']}:{j['id']}",
            company=company["company"],
            title=j.get("text", ""),
            location=(j.get("categories") or {}).get("location", ""),
            url=j.get("hostedUrl", ""),
            posted_at=posted,
            source="lever",
            tier=int(company["tier"]),
            description=" ".join(p for p in parts if p),
        ))
    return jobs
