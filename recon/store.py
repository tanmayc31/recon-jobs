"""Memory: remembers every job so we only alert on NEW ones.

SQLite locally by default; Postgres (e.g. Supabase) when given a DATABASE_URL.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from recon.models import Job

DB = Path(__file__).parent.parent / "data" / "recon.db"

SCHEMA = ["""
CREATE TABLE IF NOT EXISTS jobs (
    job_id        TEXT PRIMARY KEY,
    company       TEXT,
    title         TEXT,
    location      TEXT,
    url           TEXT,
    source        TEXT,
    tier          INTEGER,
    posted_at     TEXT,   -- what the site says: ISO date, or Workday text "Posted 30+ Days Ago"
    first_seen_at TEXT,   -- when Recon first saw it (our own clock)
    last_seen_at  TEXT,
    decision      TEXT,   -- 'match' or 'skip'
    reason        TEXT,   -- why skipped, or flags for matches
    min_years     INTEGER,
    site_updated_at TEXT, -- the site's last-edit time, when it has one (Greenhouse)
    status        TEXT DEFAULT 'new'   -- new / backlog / applied / later / skipped / closed
);
""", """
CREATE TABLE IF NOT EXISTS companies (
    company       TEXT PRIMARY KEY,   -- fetched successfully at least once
    first_run_at  TEXT                -- jobs found in this first run are backlog, not new
);
"""]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path = DB, url: str | None = None):
        if url:
            import psycopg   # only needed for Postgres
            # prepare_threshold=None: Supabase's pooler can't handle prepared statements
            self.db = psycopg.connect(url, prepare_threshold=None)
            self.placeholder = "%s"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(path)
            self.placeholder = "?"
        for statement in SCHEMA:
            self.db.execute(statement)
        self.db.commit()
        self.add_column("site_updated_at", "TEXT")   # tables made before this column existed

    def add_column(self, name: str, kind: str):
        try:
            self.db.execute(f"SELECT {name} FROM jobs LIMIT 0")
        except Exception:
            self.db.rollback()   # Postgres aborts the transaction on error
            self.db.execute(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
            self.db.commit()

    def execute(self, sql: str, params: tuple = ()):
        """Run SQL written with ? placeholders on either backend."""
        return self.db.execute(sql.replace("?", self.placeholder), params)

    def is_empty(self) -> bool:
        return self.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    def seen_companies(self) -> set[str]:
        return {r[0] for r in self.execute("SELECT company FROM companies").fetchall()}

    def mark_seen(self, companies: list[str]):
        t = now()
        for c in companies:
            self.execute("INSERT INTO companies (company, first_run_at) VALUES (?, ?)"
                         " ON CONFLICT (company) DO NOTHING", (c, t))

    def upsert(self, job: Job, decision: str, reason: str | None, min_years: int | None,
               status: str = "new") -> bool:
        """Save the job. Returns True if this is the first time we've seen it.
        status only applies to new rows; it never overwrites what the user chose."""
        t = now()
        cur = self.execute(
            "UPDATE jobs SET last_seen_at=?, decision=?, reason=?, min_years=?,"
            " posted_at=COALESCE(?, posted_at), site_updated_at=COALESCE(?, site_updated_at) WHERE job_id=?",
            (t, decision, reason, min_years, job.posted_at, job.updated_at, job.job_id),
        )
        if cur.rowcount:
            return False
        self.execute(
            "INSERT INTO jobs (job_id, company, title, location, url, source, tier, posted_at,"
            " first_seen_at, last_seen_at, decision, reason, min_years, site_updated_at, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job.job_id, job.company, job.title, job.location, job.url, job.source, job.tier,
             job.posted_at, t, t, decision, reason, min_years, job.updated_at, status),
        )
        return True

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.close()
