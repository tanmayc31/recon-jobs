import asyncio
import json

import httpx

from recon import add
from recon.store import Store

TANDEM = "https://tandemdiabetes.wd12.myworkdayjobs.com/tandemdiabetes/job/Remote-US/Sr-Software-Engineer-I_JR101511-1"
QUALCOMM_LD = {"@context": "https://schema.org", "@type": "JobPosting", "title": "#Backend Software Engineer",
               "hiringOrganization": {"@type": "Organization", "name": "Qualcomm"},
               "jobLocation": {"@type": "Place", "address": {"addressLocality": "San Diego", "addressRegion": "CA",
                                                             "addressCountry": "US"}},
               "description": "<p>Build backend services in Python and Go. 1+ years of experience.</p>"}


def handler(asked):
    def h(req):
        url = str(req.url)
        asked.append(url)
        if url == "https://lnkd.in/abc":                       # a short link that lands on LinkedIn
            return httpx.Response(301, headers={"location": "https://www.linkedin.com/jobs/view/4310573351"})
        if url == "https://click.example.com/t/1":             # an email tracking link to the company
            return httpx.Response(302, headers={"location": "https://job-boards.greenhouse.io/stripe/jobs/7012345"})
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/7012345":
            return httpx.Response(200, json={"title": "Software Engineer, New Grad", "location": {"name": "Seattle, WA"},
                                             "absolute_url": "https://stripe.com/jobs/listing/x/7012345",
                                             "content": "&lt;p&gt;Build payments APIs in Ruby. 1+ years.&lt;/p&gt;"})
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe":
            return httpx.Response(200, json={"name": "Stripe"})
        if "/wday/cxs/tandemdiabetes/tandemdiabetes/job/" in url:
            return httpx.Response(200, json={"jobPostingInfo": {
                "title": "Sr Backend Software Engineer I", "location": "Remote US", "jobReqId": "JR101511",
                "externalUrl": TANDEM, "jobDescription": "<p>Backend services.</p>"}})
        if url == "https://careers.qualcomm.com/careers/job/446721162271":
            return httpx.Response(200, text=f'<html><script type="application/ld+json">{json.dumps(QUALCOMM_LD)}</script></html>',
                                  headers={"content-type": "text/html"})
        if url == "https://lifeattiktok.com/search/7670276769459456309":
            return httpx.Response(200, text='<html><meta property="og:title" content="Software Engineer Graduate '
                                            '(Foundation Platform) - 2027 Start"><body>Build things.</body></html>',
                                  headers={"content-type": "text/html"})
        return httpx.Response(404)
    return h


def run(tmp_path, monkeypatch, url):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(add, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    monkeypatch.setattr(add, "load_companies", lambda: [])
    asked = []
    out = asyncio.run(add.add(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked))), url))
    return out, asked


def test_aggregator_pages_are_never_requested(tmp_path, monkeypatch):
    for url in ["https://www.linkedin.com/jobs/view/4310573351", "https://jobright.ai/jobs/info/6af5fe30323c531f31e2ea78"]:
        (state, message, job), asked = run(tmp_path, monkeypatch, url)
        assert state == "needs link" and "paste the company's own link" in message and job is None
        assert asked == []                                      # not one request to LinkedIn or Jobright
    (state, _, _), asked = run(tmp_path, monkeypatch, "https://lnkd.in/abc")
    assert state == "needs link" and asked == ["https://lnkd.in/abc"]   # followed to LinkedIn, stopped there


def test_tracking_link_to_greenhouse_is_added_to_new(tmp_path, monkeypatch):
    (state, message, job), _ = run(tmp_path, monkeypatch, "https://click.example.com/t/1")
    assert (state, job.job_id, job.company, job.via) == ("added", "greenhouse:stripe:7012345", "Stripe", "you")
    row = Store(tmp_path / "t.db").execute("SELECT decision, status, via, url FROM jobs").fetchone()
    assert row == ("match", "new", "you", "https://stripe.com/jobs/listing/x/7012345")


def test_filtered_job_says_why_and_is_saved_as_skipped(tmp_path, monkeypatch):
    (state, message, job), _ = run(tmp_path, monkeypatch, TANDEM)
    assert state == "skipped" and message == "The filters would skip it: title: Sr"
    assert job.job_id == "workday:tandemdiabetes:JR101511"
    assert Store(tmp_path / "t.db").execute("SELECT decision, reason FROM jobs").fetchone() == ("skip", "title: Sr")


def test_company_page_uses_jobposting_data_or_its_title(tmp_path, monkeypatch):
    (state, _, job), _ = run(tmp_path, monkeypatch, "https://careers.qualcomm.com/careers/job/446721162271")
    assert (state, job.company, job.title, job.location) == ("added", "Qualcomm", "Backend Software Engineer",
                                                             "San Diego, CA, US")
    assert "Python and Go" in job.description and job.source == "you"
    (_, _, job), _ = run(tmp_path, monkeypatch, "https://lifeattiktok.com/search/7670276769459456309")
    assert (job.company, job.title) == ("Tiktok", "Software Engineer Graduate (Foundation Platform)")


def test_a_job_you_kept_stays_a_match_on_recheck(tmp_path):
    from recon.models import Job
    s = Store(tmp_path / "t.db")
    j = Job("workday:tandemdiabetes:JR101511", "Tandem Diabetes Care", "Sr Backend Software Engineer I", "Remote US",
            TANDEM, None, "workday", 2, "Backend services.", via="you")
    s.upsert_many([(j, "skip", "title: Sr", None, "new")])
    s.execute("UPDATE jobs SET decision='match', reason=NULL")       # "Keep anyway" on the dashboard
    s.upsert_many([(j, "skip", "title: Sr", None, "new")])          # a recheck: the rules still say skip
    assert s.execute("SELECT decision FROM jobs").fetchone()[0] == "match"


def test_a_skipped_job_you_added_keeps_its_description_for_the_judge(tmp_path, monkeypatch):
    run(tmp_path, monkeypatch, TANDEM)
    assert Store(tmp_path / "t.db").execute("SELECT description FROM jobs").fetchone()[0] == "Backend services."
