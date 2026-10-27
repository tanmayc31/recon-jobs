from dataclasses import dataclass


@dataclass
class Job:
    job_id: str          # unique key, e.g. "greenhouse:stripe:12345"
    company: str
    title: str
    location: str
    url: str
    posted_at: str | None  # what the site claims (may be unreliable)
    source: str
    tier: int
