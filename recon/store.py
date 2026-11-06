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

    def executemany(self, sql: str, rows: list[tuple]):
        if not rows:
            return
        cur = self.db.cursor()   # psycopg pipelines executemany: one round trip, not one per row
        cur.executemany(sql.replace("?", self.placeholder), rows)

    def is_empty(self) -> bool:
        return self.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0

    def seen_companies(self) -> set[str]:
        return {r[0] for r in self.execute("SELECT company FROM companies").fetchall()}

    def mark_seen(self, companies: list[str]):
        t = now()
        self.executemany("INSERT INTO companies (company, first_run_at) VALUES (?, ?)"
                         " ON CONFLICT (company) DO NOTHING", [(c, t) for c in companies])

    def upsert(self, job: Job, decision: str, reason: str | None, min_years: int | None,
               status: str = "new") -> bool:
        """Save the job. Returns True if this is the first time we've seen it."""
        return bool(self.upsert_many([(job, decision, reason, min_years, status)]))

    def upsert_many(self, rows: list[tuple[Job, str, str | None, int | None, str]]) -> set[str]:
        """Save (job, decision, reason, min_years, status) rows in two batches.
        Returns the job_ids seen for the first time. status only applies to new rows;
        it never overwrites what the user chose."""
        latest = {r[0].job_id: r for r in rows}   # a board can list the same job twice
        ids = list(latest)
        known = set()
        for i in range(0, len(ids), 1000):
            chunk = ids[i:i + 1000]
            known |= {r[0] for r in self.execute(
                f"SELECT job_id FROM jobs WHERE job_id IN ({','.join('?' * len(chunk))})", tuple(chunk))}
        t = now()
        self.executemany(
            "UPDATE jobs SET last_seen_at=?, decision=?, reason=?, min_years=?,"
            " posted_at=COALESCE(?, posted_at), site_updated_at=COALESCE(?, site_updated_at) WHERE job_id=?",
            [(t, d, r, y, j.posted_at, j.updated_at, j.job_id)
             for j, d, r, y, _ in latest.values() if j.job_id in known])
        self.executemany(
            "INSERT INTO jobs (job_id, company, title, location, url, source, tier, posted_at,"
            " first_seen_at, last_seen_at, decision, reason, min_years, site_updated_at, status)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(j.job_id, j.company, j.title, j.location, j.url, j.source, j.tier,
              j.posted_at, t, t, d, r, y, j.updated_at, s)
             for j, d, r, y, s in latest.values() if j.job_id not in known])
        return set(ids) - known

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.close()
