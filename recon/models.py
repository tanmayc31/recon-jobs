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
    source_ids: str | None = None  # Amazon: every job ID behind this job, comma-separated; lists: the row's ID
    via: str | None = None  # how it reached Recon when not by scanning its board: "list" (a GitHub job list)

    def __post_init__(self):
        self.title = (self.title or "").strip()   # Amazon sends " Software Development Engineer, ..."
