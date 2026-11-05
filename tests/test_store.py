import sqlite3
import sys
import types

from recon.models import Job
from recon.store import Store

JOB = Job("greenhouse:co:1", "Co", "SWE", "NYC", "u", None, "greenhouse", 1)


def test_new_then_seen(tmp_path):
    s = Store(tmp_path / "t.db")
    j = JOB
    assert s.is_empty()
    assert s.upsert(j, "match", None, None) is True     # first time
    assert s.upsert(j, "match", None, None) is False    # already seen
    assert not s.is_empty()


def fake_psycopg(tmp_path, seen):
    """Stand-in for psycopg: checks the SQL uses %s, then runs it on SQLite."""
    class Conn:
        def __init__(self):
            self.db = sqlite3.connect(tmp_path / "pg.db")

        def execute(self, sql, params=()):
            assert "?" not in sql, sql
            seen.append(sql)
            return self.db.execute(sql.replace("%s", "?"), params)

        def commit(self):
            self.db.commit()

        def close(self):
            self.db.close()

    def connect(url, prepare_threshold=0):
        assert url == "postgresql://u:p@host:5432/postgres"
        assert prepare_threshold is None    # needed for Supabase's pooler
        return Conn()

    return types.SimpleNamespace(connect=connect)


def test_postgres_path_same_behavior(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg(tmp_path, seen))
    s = Store(url="postgresql://u:p@host:5432/postgres")
    assert s.is_empty()
    assert s.upsert(JOB, "match", None, None) is True
    assert s.upsert(JOB, "skip", "requires U.S. citizenship", 0) is False
    s.commit()
    assert not s.is_empty()
    assert any("%s" in q for q in seen)


def test_blank_url_means_sqlite(tmp_path):
    s = Store(tmp_path / "t.db", url="")    # DATABASE_URL= left blank in .env
    assert isinstance(s.db, sqlite3.Connection)


def test_rerun_refreshes_posted_keeps_status(tmp_path):
    s = Store(tmp_path / "t.db")
    j = Job("workday:nvidia:JR1", "Nvidia", "SWE", "Santa Clara, CA", "u", "Posted Today", "workday", 1)
    s.upsert(j, "match", None, None, "backlog")
    s.execute("UPDATE jobs SET status='applied' WHERE job_id=?", (j.job_id,))   # user clicked Applied
    j.posted_at = "Posted 2 Days Ago"
    s.upsert(j, "match", None, None, "new")
    assert s.execute("SELECT posted_at, status FROM jobs").fetchone() == ("Posted 2 Days Ago", "applied")


def test_adds_updated_column_to_old_table(tmp_path):
    old = sqlite3.connect(tmp_path / "t.db")
    old.execute("CREATE TABLE jobs (job_id TEXT PRIMARY KEY, company TEXT, title TEXT, location TEXT,"
                " url TEXT, source TEXT, tier INTEGER, posted_at TEXT, first_seen_at TEXT, last_seen_at TEXT,"
                " decision TEXT, reason TEXT, min_years INTEGER, status TEXT DEFAULT 'new')")
    old.commit()
    old.close()
    s = Store(tmp_path / "t.db")
    j = Job("greenhouse:robinhood:8220757", "Robinhood", "Software Engineer, AI Security", "Bellevue, WA",
            "u", "2026-10-09T17:58:39-04:00", "greenhouse", 2, updated_at="2026-11-05T11:50:21-05:00")
    s.upsert(j, "match", None, None)
    assert s.execute("SELECT site_updated_at FROM jobs").fetchone() == ("2026-11-05T11:50:21-05:00",)
