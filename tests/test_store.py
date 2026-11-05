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
