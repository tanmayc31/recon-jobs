"""SQLite memory: remembers every job so we only alert on NEW ones."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from recon.models import Job

DB = Path(__file__).parent.parent / "data" / "recon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    company       TEXT,
    title         TEXT,
    location      TEXT,
    url           TEXT,
    source        TEXT,
    tier          INTEGER,
    posted_at     TEXT,
    first_seen_at TEXT,   -- when Recon first saw it (our own clock)
    last_seen_at  TEXT,
    decision      TEXT,   -- 'match' or 'skip'
    reason        TEXT,   -- why skipped, or flags for matches
    min_years     INTEGER,
    status        TEXT DEFAULT 'new'   -- new / applied / later / skipped / closed
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path = DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(SCHEMA)

    def is_empty(self) -> bool:
        return self.db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    def upsert(self, job: Job, decision: str, reason: str | None, min_years: int | None) -> bool:
        """Save the job. Returns True if this is the first time we've seen it."""
        t = now()
        cur = self.db.execute(
            "UPDATE jobs SET last_seen_at=?, decision=?, reason=?, min_years=? WHERE job_id=?",
            (t, decision, reason, min_years, job.job_id),
        )
        if cur.rowcount:
            return False
        self.db.execute(
            "INSERT INTO jobs (job_id, company, title, location, url, source, tier, posted_at,"
            " first_seen_at, last_seen_at, decision, reason, min_years) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job.job_id, job.company, job.title, job.location, job.url, job.source, job.tier,
             job.posted_at, t, t, decision, reason, min_years),
        )
        return True

    def commit(self):
        self.db.commit()
