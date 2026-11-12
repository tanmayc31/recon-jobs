import asyncio
import time
from collections import Counter

from recon import main
from recon.models import Job
from recon.store import Store


def job(n, description="Build backend services in Python and SQL. 1+ years of experience."):
    return Job(f"greenhouse:co:{n}", "Co", "Software Engineer II", "New York, NY",
               f"https://example.com/jobs/{n}", None, "greenhouse", 1, description)


def run_once(tmp_path, monkeypatch, jobs, tiers=None, recheck=False, ats=None):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": "Jane Doe"}])

    async def fetch(client, sems, company, deadline, outcome):
        return jobs
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    return asyncio.run(main.run(tiers, recheck, ats))


def statuses(tmp_path):
    return dict(Store(tmp_path / "t.db").execute("SELECT job_id, status FROM jobs").fetchall())


def test_first_run_is_backlog_then_new(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    assert run_once(tmp_path, monkeypatch, [job(1)]) == []        # company's first run
    assert "1 backlog matches" in capsys.readouterr().out
    assert len(run_once(tmp_path, monkeypatch, [job(1), job(2)])) == 1
    assert statuses(tmp_path) == {"greenhouse:co:1": "backlog", "greenhouse:co:2": "new"}


def test_failed_fetch_is_not_a_first_run(tmp_path, monkeypatch):
    run_once(tmp_path, monkeypatch, None)                         # source errored
    run_once(tmp_path, monkeypatch, [job(1)])                     # first real run: backlog
    assert statuses(tmp_path) == {"greenhouse:co:1": "backlog"}


def test_ci_logs_counts_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    run_once(tmp_path, monkeypatch, [])
    assert len(run_once(tmp_path, monkeypatch, [job(1)])) == 1
    out = capsys.readouterr().out
    assert "Checked 1 companies (all tiers), 1 jobs in" in out
    assert "Software Engineer II" not in out and "example.com" not in out and "Jane Doe" not in out


def test_local_shows_jobs(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [])
    run_once(tmp_path, monkeypatch, [job(1)])
    out = capsys.readouterr().out
    assert "Software Engineer II" in out and "Jane Doe" in out


def test_tiers_filter_companies(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1)], tiers={3})          # Co is Tier 1
    assert "Checked 0 companies (tiers 3), 0 jobs" in capsys.readouterr().out


def verdicts(tmp_path):
    return dict(Store(tmp_path / "t.db").execute("SELECT job_id, decision FROM jobs").fetchall())


def test_known_jobs_reuse_verdict_unless_recheck(tmp_path, monkeypatch):
    run_once(tmp_path, monkeypatch, [])
    run_once(tmp_path, monkeypatch, [job(1)])
    assert verdicts(tmp_path) == {"greenhouse:co:1": "match"}

    # a new rule would now block it...
    monkeypatch.setattr(main.eligibility, "check", lambda text, title="": (False, "citizenship/clearance", None, []))
    run_once(tmp_path, monkeypatch, [job(1)])
    assert verdicts(tmp_path) == {"greenhouse:co:1": "match"}       # ...but known jobs aren't re-judged
    run_once(tmp_path, monkeypatch, [job(1)], recheck=True)
    assert verdicts(tmp_path) == {"greenhouse:co:1": "skip"}        # --recheck applies the new rule
    assert statuses(tmp_path) == {"greenhouse:co:1": "new"}         # status untouched


def test_recheck_tells_adapters_nothing_is_known(tmp_path, monkeypatch):
    seen_known = []

    async def fetch(client, sems, company, deadline, outcome):
        seen_known.append(len(company["known"]))
        return [job(1)]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": ""}])
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    for recheck in (False, False, True):
        asyncio.run(main.run(None, recheck))
    assert seen_known == [0, 1, 0]


def test_ats_filter(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1)], ats={"workday"})    # Co is Greenhouse
    assert "Checked 0 companies (all tiers, workday), 0 jobs" in capsys.readouterr().out


def test_busy_workday_lane_does_not_block_others(monkeypatch):
    # Every Workday slot is stuck until the Greenhouse company runs: with one shared
    # pool this would deadlock; with separate lanes Greenhouse still gets a slot.
    unblock = asyncio.Event()

    async def slow_workday(client, company):
        await unblock.wait()
        return []

    async def greenhouse(client, company):
        unblock.set()
        return []
    monkeypatch.setattr(main, "SOURCES", {"workday": type("W", (), {"fetch": staticmethod(slow_workday)}),
                                          "greenhouse": type("G", (), {"fetch": staticmethod(greenhouse)})})
    monkeypatch.setattr(main, "PARALLEL", {"workday": 1, "other": 1})

    async def go():
        sems = {lane: asyncio.Semaphore(n) for lane, n in main.PARALLEL.items()}
        outcome = Counter()
        cos = [{"company": "W1", "ats": "workday"}, {"company": "W2", "ats": "workday"},
               {"company": "G", "ats": "greenhouse"}]
        far = time.monotonic() + 60
        await asyncio.wait_for(asyncio.gather(*(main.fetch_company(None, sems, c, far, outcome) for c in cos)), 2)
        return outcome
    assert asyncio.run(go())["ok"] == 3


def test_empty_description_is_unverified_and_retried(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [])
    # Real case: Genworth "Software Engineer - Java Development" was judged while its
    # Workday detail request failed (429), so it matched on an empty description
    assert run_once(tmp_path, monkeypatch, [job(1, description="")]) == []
    assert "Unverified (no description, retried next run): 1" in capsys.readouterr().out
    assert verdicts(tmp_path) == {"greenhouse:co:1": "unverified"}

    known = []

    async def fetch(client, sems, company, deadline, outcome):
        known.append(dict(company["known"]))
        return [job(1, description="This role is not eligible for employment visa sponsorship.")]
    monkeypatch.setattr(main, "fetch_company", fetch)
    asyncio.run(main.run())
    assert known == [{}]                                           # not "known": fetched again
    assert verdicts(tmp_path) == {"greenhouse:co:1": "skip"}       # judged once it has a description


def test_connection_not_held_during_fetch(tmp_path, monkeypatch):
    # Supabase drops idle connections: the one used for reading must be closed before fetching
    opened = []

    class Tracked(Store):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.closed = False
            opened.append(self)

        def close(self):
            self.closed = True
            super().close()

    async def fetch(client, sems, company, deadline, outcome):
        assert all(s.closed for s in opened)          # nothing open while fetching
        return [job(1)]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": ""}])
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Tracked(tmp_path / "t.db", url))
    asyncio.run(main.run())
    assert len(opened) == 2 and all(s.closed for s in opened)


def test_first_run_jobs_posted_in_the_last_3_days_are_new(tmp_path, monkeypatch):
    from datetime import date, timedelta
    today = date.today()
    fresh, old, workday, undated = job(1), job(2), job(3), job(4)
    fresh.posted_at = (today - timedelta(days=3)).isoformat() + "T15:04:11Z"   # Lever/Ashby ISO date
    old.posted_at = (today - timedelta(days=4)).isoformat()
    workday.posted_at = "Posted 2 Days Ago"                                    # real Workday text
    # job 4: no posted date from the site -> stays backlog
    run_once(tmp_path, monkeypatch, [fresh, old, workday, undated])            # company's first run
    assert statuses(tmp_path) == {"greenhouse:co:1": "new", "greenhouse:co:2": "backlog",
                                  "greenhouse:co:3": "new", "greenhouse:co:4": "backlog"}


def test_existing_fresh_backlog_moves_to_new(tmp_path):
    s = Store(tmp_path / "t.db")
    seen = "2026-11-10T08:00:00+00:00"
    rows = [  # (n, posted_at from the site, posted_on as stored)
        (1, "2026-11-07", "2026-11-07"),                 # 3 days before first seen: new
        (2, "2026-11-06", "2026-11-06"),                 # 4 days: stays backlog
        (3, "Posted 30+ Days Ago", "2026-10-11"),        # Workday bound: stays
        (4, None, None)]                                 # no date: stays
    for n, posted_at, posted_on in rows:
        j = job(n)
        j.posted_at = posted_at
        s.upsert_many([(j, "match", None, None, "backlog")])
        s.execute("UPDATE jobs SET first_seen_at=?, posted_on=? WHERE job_id=?", (seen, posted_on, j.job_id))
    assert s.fresh_backlog_to_new() == ["greenhouse:co:1"]
    s.commit()
    assert statuses(tmp_path) == {"greenhouse:co:1": "new", "greenhouse:co:2": "backlog",
                                  "greenhouse:co:3": "backlog", "greenhouse:co:4": "backlog"}
