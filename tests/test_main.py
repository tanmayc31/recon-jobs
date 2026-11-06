import asyncio

from recon import main
from recon.models import Job
from recon.store import Store


def job(n):
    return Job(f"greenhouse:co:{n}", "Co", "Software Engineer II", "New York, NY",
               f"https://example.com/jobs/{n}", None, "greenhouse", 1)


def run_once(tmp_path, monkeypatch, jobs, tiers=None):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": "Jane Doe"}])

    async def fetch(client, sem, company, deadline, outcome):
        return jobs
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    return asyncio.run(main.run(tiers))


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
