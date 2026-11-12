import sqlite3
import sys
import types

from recon.models import Job
from recon.store import Store, posted_on

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

        def cursor(self):
            conn = self

            class Cursor:
                def executemany(self, sql, rows):
                    assert "?" not in sql, sql
                    seen.append(sql)
                    conn.db.executemany(sql.replace("%s", "?"), rows)
            return Cursor()

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


def test_touch_keeps_verdict(tmp_path):
    s = Store(tmp_path / "t.db")
    s.upsert(JOB, "skip", "citizenship/clearance", None)   # set by a --recheck run
    JOB.posted_at = "2026-11-01T00:00:00Z"
    s.touch_many([JOB])                                    # an overlapping normal run
    assert s.execute("SELECT decision, reason, posted_at FROM jobs").fetchone() == \
        ("skip", "citizenship/clearance", "2026-11-01T00:00:00Z")
    JOB.posted_at = None


def test_openings_saved_and_refreshed(tmp_path):
    s = Store(tmp_path / "t.db")
    j = Job("amazon:abc", "Amazon", "SDE", "US, WA, Seattle", "u", None, "amazon", 1, openings=3,
            source_ids="1,2,3")
    s.upsert(j, "match", None, None)
    j.openings, j.source_ids = 2, "2,3"          # one requisition closed
    s.touch_many([j])
    assert s.execute("SELECT openings, source_ids FROM jobs").fetchone() == (2, "2,3")
    other = Job("greenhouse:co:9", "Co", "SWE", "NYC", "u", None, "greenhouse", 1)
    s.upsert(other, "match", None, None)
    assert s.execute("SELECT openings, source_ids FROM jobs WHERE job_id=?", (other.job_id,)).fetchone() == (1, None)


def test_posted_on_resolves_dates_and_workday_text():
    seen = "2026-11-10T12:00:00+00:00"
    assert posted_on("2026-11-02T18:04:11-05:00", seen) == "2026-11-02"          # Greenhouse / Lever
    assert posted_on("2026-11-10", seen) == "2026-11-10"                         # Amazon
    assert posted_on("Posted Today", seen) == "2026-11-10"
    assert posted_on("Posted Yesterday", seen) == "2026-11-09"
    assert posted_on("Posted 3 Days Ago", seen) == "2026-11-07"
    assert posted_on("Posted 30+ Days Ago", seen) == "2026-10-11"
    assert posted_on(None, seen) is None and posted_on("Recently", seen) is None


def test_posted_on_keeps_the_earliest_date(tmp_path):
    # "Posted 30+ Days Ago" read again tomorrow must not move the date forward
    s = Store(tmp_path / "t.db")
    j = Job("workday:co:R1", "Co", "Software Engineer", "NYC", "u", "Posted 30+ Days Ago", "workday", 1)
    s.upsert(j, "match", None, None)
    first = s.execute("SELECT posted_on FROM jobs").fetchone()[0]
    s.execute("UPDATE jobs SET posted_on='2026-01-01'")      # as if first seen long ago
    s.touch_many([j])
    assert first and s.execute("SELECT posted_on FROM jobs").fetchone()[0] == "2026-01-01"


def test_new_rows_get_role_type_and_titles_are_trimmed(tmp_path):
    s = Store(tmp_path / "t.db")
    s.upsert(Job("amazon:x", "Amazon", " Software Development Engineer, AWS OpenSearch", "US, TX, Austin", "u",
                 "2026-11-10", "amazon", 1), "match", None, None)
    assert s.execute("SELECT title, role_type, posted_on FROM jobs").fetchone() == \
        ("Software Development Engineer, AWS OpenSearch", "swe", "2026-11-10")


def test_backfill_fills_old_rows(tmp_path):
    s = Store(tmp_path / "t.db")
    s.upsert(Job("workday:co:R2", "Co", "Site Reliability Engineer 2", "NYC", "u", "Posted 3 Days Ago",
                 "workday", 1), "match", None, None)
    s.execute("UPDATE jobs SET role_type=NULL, posted_on=NULL, last_seen_at='2026-11-10T08:00:00+00:00'")
    s.commit()
    s2 = Store(tmp_path / "t.db")                                # opening the store backfills
    assert s2.execute("SELECT role_type, posted_on FROM jobs").fetchone() == ("cloud", "2026-11-07")
