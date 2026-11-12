import asyncio

import httpx

from recon import linkcheck

AUTODESK = "https://autodesk.wd1.myworkdayjobs.com/Ext/job/Novi-MI-USA/Software-Engineer_26WD102129-1"
FIDELITY = ("https://wd1.myworkdaysite.com/recruiting/fmr/FidelityCareers/job/Durham-NC/"
            "Senior-Front-End-Developer--Angular--TypeScript--NodeJS--REST-APIs-_2132735")


def job(job_id, source, url, source_ids=None):
    return {"job_id": job_id, "source": source, "url": url, "source_ids": source_ids, "company": "Co", "title": "SWE"}


def test_workday_api_from_public_urls():
    assert linkcheck.workday_api(AUTODESK) == \
        "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/job/Novi-MI-USA/Software-Engineer_26WD102129-1"
    assert linkcheck.workday_api(FIDELITY).startswith(
        "https://fmr.wd1.myworkdayjobs.com/wday/cxs/fmr/FidelityCareers/job/Durham-NC/")
    assert linkcheck.workday_api("https://cox.wd1.myworkdayjobs.com/en-US/Cox_External_Career_Site_1/job/"
                                 "Burlington-VT/Software-Engineer-II_R202684945").endswith(
        "/wday/cxs/cox/Cox_External_Career_Site_1/job/Burlington-VT/Software-Engineer-II_R202684945")


def run(jobs, handler, monkeypatch):
    monkeypatch.setattr(linkcheck, "DELAY", 0)
    return {r["job_id"]: (r["open"], r["page"]) for r in asyncio.run(linkcheck.check(jobs, httpx.MockTransport(handler)))}


def test_open_and_gone_per_source(monkeypatch):
    def handler(req):
        url = str(req.url)
        if "/wday/cxs/autodesk/" in url:   # real: taken down -> 403 "permission denied"
            return httpx.Response(403, json={"errorCode": "S22", "message": "permission denied"})
        if "/wday/cxs/fmr/" in url:
            return httpx.Response(200, json={"jobPostingInfo": {"title": "Senior Front End Developer"}})
        if "boards-api.greenhouse.io" in url:
            return httpx.Response(200 if url.endswith("/8304038") else 404, json={})
        if "coinbase.com" in url:          # company site blocks scripts
            return httpx.Response(403)
        if "api.lever.co" in url or "jobs.lever.co" in url:
            return httpx.Response(404 if "gone" in url else 200, json={})
        if "api.ashbyhq.com" in url:
            return httpx.Response(200, json={"jobs": [{"id": "a1"}, {"id": "a2", "isListed": False}]})
        if "amazon.jobs/en/jobs/10601870" in url:
            return httpx.Response(404)
        return httpx.Response(200)         # Workday and Ashby pages: always a 200 shell

    got = run([
        job("workday:autodesk:26WD102129", "workday", AUTODESK),
        job("workday:fmr:2132735", "workday", FIDELITY),
        job("greenhouse:coinbase:8304038", "greenhouse", "https://www.coinbase.com/careers/positions/8304038?gh_jid=8304038"),
        job("greenhouse:coinbase:1", "greenhouse", "https://www.coinbase.com/careers/positions/1?gh_jid=1"),
        job("lever:co:gone", "lever", "https://jobs.lever.co/co/gone"),
        job("ashby:co:a1", "ashby", "https://jobs.ashbyhq.com/co/a1"),
        job("ashby:co:a2", "ashby", "https://jobs.ashbyhq.com/co/a2"),
        job("amazon:abc", "amazon", "https://www.amazon.jobs/en/jobs/10601990/sde", "10601870,10601990"),
    ], handler, monkeypatch)
    assert got == {
        "workday:autodesk:26WD102129": (False, "ok"),    # page "works" (200 shell) but the job is gone
        "workday:fmr:2132735": (True, "ok"),
        "greenhouse:coinbase:8304038": (True, "blocked"),
        "greenhouse:coinbase:1": (False, "blocked"),
        "lever:co:gone": (False, "broken"),
        "ashby:co:a1": (True, "ok"),
        "ashby:co:a2": (False, "ok"),                    # unlisted
        "amazon:abc": (True, "ok"),                      # one of its requisitions is still up
    }


def test_redirect_to_a_generic_careers_page_is_broken(monkeypatch):
    def handler(req):
        if str(req.url).startswith("https://example.com/jobs/77"):
            return httpx.Response(302, headers={"location": "https://example.com/careers"})
        return httpx.Response(200, json={})
    got = run([job("lever:co:77", "lever", "https://example.com/jobs/77")], handler, monkeypatch)
    assert got["lever:co:77"] == (True, "broken")


def test_close_unseen_checks_old_workday_jobs_and_closes_the_gone_ones(tmp_path, monkeypatch, capsys):
    from recon.models import Job
    from recon.store import Store
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(linkcheck, "DELAY", 0)
    monkeypatch.setattr(linkcheck, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    s = Store(tmp_path / "t.db")
    jobs = {  # (url, last seen, status)
        "workday:autodesk:26WD102129": (AUTODESK, "2026-11-01T00:00:00+00:00", "new"),        # gone
        "workday:autodesk:R2": (AUTODESK.replace("26WD102129-1", "R2"), "2026-11-01T00:00:00+00:00", "applied"),
        "workday:cisco:2025041": ("https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/Seattle-Washington-US/"
                                  "Software-Engineer--Backend---Webex-Signaling_2025041", "2026-11-01T00:00:00+00:00", "new"),
        "workday:cisco:1": ("https://cisco.wd5.myworkdayjobs.com/Cisco_Careers/job/x_1", "2999-01-01T00:00:00+00:00", "new"),
    }
    for job_id, (url, seen, status) in jobs.items():
        s.upsert_many([(Job(job_id, "Co", "Software Engineer", "Austin, TX", url, None, "workday", 3, "x"),
                        "match", None, None, status)])
        s.execute("UPDATE jobs SET last_seen_at=? WHERE job_id=?", (seen, job_id))
    s.commit()
    asked = []

    def handler(req):
        asked.append(str(req.url))
        if "/wday/cxs/autodesk/" in str(req.url):
            return httpx.Response(403, json={"errorCode": "S22"})                 # taken down
        return httpx.Response(200, json={"jobPostingInfo": {"title": "Software Engineer"}})
    assert asyncio.run(linkcheck.close_unseen(httpx.MockTransport(handler))) == (3, 2)
    assert not any("x_1" in u for u in asked)                                       # seen recently: not checked
    rows = dict(Store(tmp_path / "t.db").execute("SELECT job_id, closed_at IS NOT NULL FROM jobs").fetchall())
    assert rows == {"workday:autodesk:26WD102129": 1, "workday:autodesk:R2": 1,     # Applied: badge only
                    "workday:cisco:2025041": 0, "workday:cisco:1": 0}
    assert dict(Store(tmp_path / "t.db").execute("SELECT job_id, status FROM jobs").fetchall())[
        "workday:autodesk:R2"] == "applied"
    assert "3 Workday jobs unseen for 3+ days, 2 confirmed gone and closed" in capsys.readouterr().out
