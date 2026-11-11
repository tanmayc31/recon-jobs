"""Memory: remembers every job so we only alert on NEW ones.

SQLite locally by default; Postgres (e.g. Supabase) when given a DATABASE_URL.
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from recon.models import Job

DB = Path(__file__).parent.parent / "data" / "recon.db"
DESC_CHARS = 8000   # stored description length (matches only)
AI_COLUMNS = [("description", "TEXT"), ("fit_score", "INTEGER"), ("ai_why", "TEXT"),
              ("ai_missing", "TEXT"), ("ai_resume", "TEXT"), ("ai_seniority", "TEXT"),
              ("ai_sponsorship", "TEXT"), ("ai_years", "INTEGER"), ("ai_max_years", "INTEGER"), ("ai_skip", "TEXT"),
              ("ai_scored_at", "TEXT")]

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
    decision      TEXT,   -- 'match', 'skip', or 'unverified' (no description yet)
    reason        TEXT,   -- why skipped, or flags for matches
    min_years     INTEGER,
    site_updated_at TEXT, -- the site's last-edit time, when it has one (Greenhouse)
    status        TEXT DEFAULT 'new',  -- new / backlog / applied / later / skipped / closed
    description   TEXT,   -- matches only (trimmed), for the AI judge
    openings      INTEGER DEFAULT 1,  -- Amazon: identical title + location postings in this job
    source_ids    TEXT,   -- Amazon: the site's job IDs behind it, comma-separated
    -- AI judge (recon/judge.py); ai_scored_at is NULL until judged
    fit_score     INTEGER,
    ai_why        TEXT,
    ai_missing    TEXT,   -- comma-separated skills
    ai_resume     TEXT,   -- 'ai' or 'general'
    ai_seniority  TEXT,
    ai_sponsorship TEXT,  -- ok / no / unclear
    ai_years      INTEGER,
    ai_max_years  INTEGER, -- most experience the posting allows (null: no cap)
    ai_skip       TEXT,   -- 'ai: <reason>' if the AI vetoed it; survives --recheck
    ai_scored_at  TEXT
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
        for name, kind in [("site_updated_at", "TEXT"), ("openings", "INTEGER DEFAULT 1"),
                           ("source_ids", "TEXT")] + AI_COLUMNS:   # tables made before these existed
            self.add_column(name, kind)

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

    def known_jobs(self) -> dict[str, tuple[str, str | None, int | None]]:
        """job_id -> (decision, reason, min_years) for every judged job. Unverified rows
        (description fetch failed) are left out, so the next run fetches and judges them."""
        return {r[0]: (r[1], r[2], r[3]) for r in self.execute(
            "SELECT job_id, decision, reason, min_years FROM jobs WHERE decision <> 'unverified'").fetchall()}

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

    def touch_many(self, jobs: list[Job]):
        """Known jobs still listed: refresh last_seen, the site's dates and openings, nothing else."""
        t = now()
        self.executemany(
            "UPDATE jobs SET last_seen_at=?, posted_at=COALESCE(?, posted_at),"
            " site_updated_at=COALESCE(?, site_updated_at), openings=?, source_ids=COALESCE(?, source_ids)"
            " WHERE job_id=?",
            [(t, j.posted_at, j.updated_at, j.openings, j.source_ids, j.job_id) for j in jobs])

    def upsert_many(self, rows: list[tuple[Job, str, str | None, int | None, str]]) -> set[str]:
        """Save (job, decision, reason, min_years, status) rows in two batches.
        Returns the job_ids seen for the first time. status only applies to new rows;
        it never overwrites what the user chose. An AI veto (ai_skip) beats a rule match."""
        latest = {r[0].job_id: r for r in rows}   # a board can list the same job twice
        ids = list(latest)
        vetoed = {}   # known job_id -> ai_skip (or None)
        for i in range(0, len(ids), 1000):
            chunk = ids[i:i + 1000]
            vetoed |= {r[0]: r[1] for r in self.execute(
                f"SELECT job_id, ai_skip FROM jobs WHERE job_id IN ({','.join('?' * len(chunk))})", tuple(chunk))}
        t = now()

        def desc(j, d):
            return j.description[:DESC_CHARS] if d == "match" and j.description else None

        updates = []
        for j, d, r, y, _ in latest.values():
            if j.job_id not in vetoed:
                continue
            if d == "match" and vetoed[j.job_id]:
                d, r = "skip", vetoed[j.job_id]
            updates.append((t, d, r, y, j.posted_at, j.updated_at, desc(j, d), j.openings, j.source_ids, j.job_id))
        self.executemany(
            "UPDATE jobs SET last_seen_at=?, decision=?, reason=?, min_years=?,"
            " posted_at=COALESCE(?, posted_at), site_updated_at=COALESCE(?, site_updated_at),"
            " description=COALESCE(?, description), openings=?, source_ids=COALESCE(?, source_ids)"
            " WHERE job_id=?", updates)
        self.executemany(
            "INSERT INTO jobs (job_id, company, title, location, url, source, tier, posted_at, first_seen_at,"
            " last_seen_at, decision, reason, min_years, site_updated_at, status, description, openings, source_ids)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(j.job_id, j.company, j.title, j.location, j.url, j.source, j.tier,
              j.posted_at, t, t, d, r, y, j.updated_at, s, desc(j, d), j.openings, j.source_ids)
             for j, d, r, y, s in latest.values() if j.job_id not in vetoed])
        return set(ids) - set(vetoed)

    def unscored(self, limit: int) -> list[dict]:
        """Rule-filter matches with a description and no AI verdict yet: New first, then
        Backlog by tier (Tier 1 first), then anything else; newest first within each."""
        cols = ["job_id", "company", "title", "location", "description"]
        return [dict(zip(cols, r)) for r in self.execute(
            f"SELECT {', '.join(cols)} FROM jobs WHERE decision = 'match' AND ai_scored_at IS NULL"
            " AND description IS NOT NULL AND description <> ''"
            " ORDER BY CASE status WHEN 'new' THEN 0 WHEN 'backlog' THEN 1 ELSE 2 END,"
            " CASE WHEN status = 'backlog' THEN tier ELSE 0 END, first_seen_at DESC, job_id"
            " LIMIT ?", (limit,)).fetchall()]

    def save_scores(self, results: list[tuple[str, dict, str | None]]):
        """(job_id, AI result, skip reason or None). A veto turns the match into a skip."""
        t = now()
        self.executemany(
            "UPDATE jobs SET fit_score=?, ai_why=?, ai_missing=?, ai_resume=?, ai_seniority=?,"
            " ai_sponsorship=?, ai_years=?, ai_max_years=?, ai_skip=?, ai_scored_at=?,"
            " decision=?, reason=COALESCE(?, reason) WHERE job_id=? AND decision='match'",
            [(a["fit_score"], a["why"], ", ".join(a["missing_skills"]), a["resume"], a["seniority"],
              a["sponsorship"], a["required_years"], a["max_years_allowed"], skip, t, "skip" if skip else "match", skip, job_id)
             for job_id, a, skip in results])

    def commit(self):
        self.db.commit()

    def close(self):
        self.db.close()
