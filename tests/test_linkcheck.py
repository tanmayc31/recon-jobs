import asyncio

import httpx

from recon import linkcheck
from recon.linkcheck import check_open as real_check_open   # conftest replaces the module's copy
from recon.models import Job
from recon.store import Store

AUTODESK = "https://autodesk.wd1.myworkdayjobs.com/Ext/job/Novi-MI-USA/Software-Engineer_26WD102129-1"
FIDELITY = ("https://wd1.myworkdaysite.com/recruiting/fmr/FidelityCareers/job/Durham-NC/"
            "Senior-Front-End-Developer--Angular--TypeScript--NodeJS--REST-APIs-_2132735")


def job(job_id, source, url, source_ids=None, title="Software Engineer"):
    return {"job_id": job_id, "source": source, "url": url, "source_ids": source_ids, "company": "Co", "title": title}


def test_workday_api_from_public_urls():
    assert linkcheck.workday_api(AUTODESK) == \
        "https://autodesk.wd1.myworkdayjobs.com/wday/cxs/autodesk/Ext/job/Novi-MI-USA/Software-Engineer_26WD102129-1"
    assert linkcheck.workday_api(FIDELITY).startswith(
        "https://fmr.wd1.myworkdayjobs.com/wday/cxs/fmr/FidelityCareers/job/Durham-NC/")
    assert linkcheck.workday_api("https://cox.wd1.myworkdayjobs.com/en-US/Cox_External_Career_Site_1/job/"
                                 "Burlington-VT/Software-Engineer-II_R202684945").endswith(
        "/wday/cxs/cox/Cox_External_Career_Site_1/job/Burlington-VT/Software-Engineer-II_R202684945")


def handler(req):
    url = str(req.url)
    if "/wday/cxs/autodesk/" in url:       # real: taken down -> 403 "permission denied"
        return httpx.Response(403, json={"errorCode": "S22", "message": "permission denied"})
    if "/wday/cxs/" in url:
        return httpx.Response(200, json={"jobPostingInfo": {"title": "Software Engineer"}})
    if "boards-api.greenhouse.io" in url:
        return httpx.Response(200 if url.endswith("/8304038") else 404, json={})
    if "api.lever.co" in url:
        return httpx.Response(404 if "gone" in url else 200, json={})
    if "api.ashbyhq.com" in url:             # listed on both boards
        return httpx.Response(200, json={"jobs": [{"id": "a1"}, {"id": "a2", "isListed": False}]})
    if url == "https://jobs.ashbyhq.com/maple":
        return httpx.Response(404)           # real: Maple's Ashby job pages are switched off
    if "jobs.ashbyhq.com" in url:
        return httpx.Response(200)
    if "amazon.jobs/en/jobs/10601870" in url:
        return httpx.Response(404)
    return httpx.Response(200)


def run(jobs, monkeypatch):
    monkeypatch.setattr(linkcheck, "DELAY", 0)
    return {j["job_id"]: ok for j, ok in asyncio.run(real_check_open(jobs, httpx.MockTransport(handler)))}


def test_open_and_gone_per_source(monkeypatch):
    assert run([
        job("workday:autodesk:26WD102129", "workday", AUTODESK),
        job("workday:fmr:2132735", "workday", FIDELITY),
        job("greenhouse:coinbase:8304038", "greenhouse", "https://www.coinbase.com/careers/positions/8304038"),
        job("greenhouse:coinbase:1", "greenhouse", "https://www.coinbase.com/careers/positions/1"),
        job("lever:co:gone", "lever", "https://jobs.lever.co/co/gone"),
        job("ashby:co:a1", "ashby", "https://jobs.ashbyhq.com/co/a1"),
        job("ashby:co:a2", "ashby", "https://jobs.ashbyhq.com/co/a2"),
        job("ashby:maple:a1", "ashby", "https://jobs.ashbyhq.com/maple/a1"),
        job("ashby:cursor:a1", "ashby", "https://cursor.com/careers/software-engineer"),
        job("amazon:abc", "amazon", "https://www.amazon.jobs/en/jobs/10601990/sde", "10601870,10601990"),
    ], monkeypatch) == {
        "workday:autodesk:26WD102129": False, "workday:fmr:2132735": True,
        "greenhouse:coinbase:8304038": True, "greenhouse:coinbase:1": False,
        "lever:co:gone": False,
        "ashby:co:a1": True, "ashby:co:a2": False,          # a2: unlisted
        "ashby:maple:a1": False,                            # listed, but no job page opens
        "ashby:cursor:a1": True,                            # switched off too, but cursor.com has the page
        "amazon:abc": True,                                 # one of its requisitions is still up
    }


def test_daily_recheck_closes_gone_jobs_in_new_backlog_and_later(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(linkcheck, "DELAY", 0)
    monkeypatch.setattr(linkcheck, "check_open", real_check_open)
    monkeypatch.setattr(linkcheck, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    s = Store(tmp_path / "t.db")
    rows = {  # job_id: (url, status)
        "workday:autodesk:26WD102129": (AUTODESK, "new"),
        "workday:autodesk:R2": (AUTODESK.replace("26WD102129-1", "R2"), "later"),
        "workday:autodesk:R3": (AUTODESK.replace("26WD102129-1", "R3"), "applied"),   # not checked
        "lever:co:gone": ("https://jobs.lever.co/co/gone", "backlog"),
        "lever:co:ok": ("https://jobs.lever.co/co/ok", "new"),
    }
    for job_id, (url, status) in rows.items():
        s.upsert_many([(Job(job_id, "Co", "Software Engineer", "Austin, TX", url, None, job_id.split(":")[0], 1, "x"),
                        "match", None, None, status)])
    s.commit()
    assert asyncio.run(linkcheck.recheck_open(httpx.MockTransport(handler))) == (4, 3)
    closed = dict(Store(tmp_path / "t.db").execute("SELECT job_id, closed_at IS NOT NULL FROM jobs").fetchall())
    assert closed == {"workday:autodesk:26WD102129": 1, "workday:autodesk:R2": 1, "workday:autodesk:R3": 0,
                      "lever:co:gone": 1, "lever:co:ok": 0}
    assert "4 jobs in New/Backlog/Later, 3 gone and closed" in capsys.readouterr().out


def test_rendered_page_verdicts():
    # real rendered text (Nov 2026) from the four links that looked fine by HTTP status
    for text in ["Skip to main content Sign In Search for Jobs The page you are looking for doesn't exist. "
                 "Search for Jobs Follow Us © 2026 Workday, Inc.",
                 "Page not found The page you requested was not found Powered by Privacy Policy"]:
        assert linkcheck.verdict("Cloud Platform Engineer I", text) == "dead"
    cursor = ("Skip to content Cursor Models Product Careers Software Engineer, New Grad 2027 Engineering · "
              "Full-time · San Francisco, CA; New York, NY; Palo Alto, CA Apply")
    assert linkcheck.verdict("Software Engineer, New Grad 2027", cursor) == "ok"
    # a redirect to the careers home page: no dead message, but not the job either
    assert linkcheck.verdict("Site Reliability Engineer (US - Pacific time)",
                             "Products Pricing Docs Community Company Careers at PostHog Open roles") == "no title"


def test_list_jobs_are_open_while_listed_and_the_page_loads(monkeypatch):
    from recon.sources import listings
    monkeypatch.setattr(linkcheck, "DELAY", 0)

    def lists(req):
        url = str(req.url)
        if url in listings.LISTS.values():
            return httpx.Response(200, json=[{"id": "id-3", "active": True}, {"id": "id-4", "active": False}])
        return httpx.Response(404 if "gone" in url else 200)
    got = {j["job_id"]: ok for j, ok in asyncio.run(real_check_open([
        job("list:id-3", "list", "https://www.google.com/about/careers/x", "id-3"),
        job("list:id-4", "list", "https://www.google.com/about/careers/y", "id-4"),         # off the list
        job("list:id-5", "list", "https://www.google.com/about/careers/gone", "id-5"),       # not listed
    ], httpx.MockTransport(lists)))}
    assert got == {"list:id-3": True, "list:id-4": False, "list:id-5": False}


def test_rendered_list_pages_open_gone_or_blocked(monkeypatch):
    # real rendered text (Nov 2026): Microsoft's page loads but the job is closed; Tesla and
    # Citadel Securities put bot protection in front of a headless browser: can't tell, keep it
    pages = {
        "list:ms": "Careers Single Position View All Jobs Software Engineering IC2 United States, Washington, Redmond "
                   "No longer accepting applications. Job number 200064642",
        "list:tesla": "Access Denied You don't have permission to access \"http://www.tesla.com/careers/search/job/240332\"",
        "list:citadel": "www.citadelsecurities.com Performing security verification This website uses a security service",
        "list:apple": "Graphics Software Content Engineer Orlando, Florida, United States Software and Services",
    }

    async def render(jobs, wait=6):
        return [dict(j, page=linkcheck.verdict(j["title"], pages[j["job_id"]]), text=pages[j["job_id"]]) for j in jobs]
    monkeypatch.setattr(linkcheck, "render", render)
    jobs = [job("list:ms", "list", "u", title="Software Engineering IC2"), job("list:tesla", "list", "u", title="Software Engineer, Traction Control"),
            job("list:citadel", "list", "u", title="Software Engineer"), job("list:apple", "list", "u", title="Graphics Software Content Engineer")]
    assert asyncio.run(linkcheck.render_open(jobs)) == {"list:ms": False, "list:tesla": None, "list:citadel": None,
                                                       "list:apple": True}
