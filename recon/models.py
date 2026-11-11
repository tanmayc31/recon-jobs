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
    description: str = ""  # plain text
    updated_at: str | None = None  # site's last-edit time (Greenhouse only; others don't publish one)
    openings: int = 1      # Amazon: identical title + location postings collapsed into one job
    source_ids: str | None = None  # Amazon: every job ID behind this job, comma-separated
