import asyncio

from recon import main
from recon.models import Job
from recon.store import Store

JOB = Job("greenhouse:co:1", "Co", "Software Engineer II", "New York, NY",
          "https://example.com/jobs/1", None, "greenhouse", 1)


def run_once(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": "Jane Doe"}])

    async def fetch(client, sem, company):
        return [JOB]
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    return asyncio.run(main.run())


def test_ci_logs_counts_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    assert len(run_once(tmp_path, monkeypatch)) == 1
    out = capsys.readouterr().out
    assert "Checked 1 companies, 1 jobs" in out
    assert "Software Engineer II" not in out and "example.com" not in out and "Jane Doe" not in out


def test_local_shows_jobs(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch)
    out = capsys.readouterr().out
    assert "Software Engineer II" in out and "Jane Doe" in out
