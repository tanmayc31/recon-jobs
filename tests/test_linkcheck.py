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
