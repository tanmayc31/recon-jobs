import asyncio
import json

import httpx
import pytest

from recon.sources import meta

CO = {"company": "Meta", "ats": "meta", "slug": "meta", "tier": "2"}
PAGE = '<html><script>requireLazy(["LSD"],function(){});["LSD",[],{"token":"AdQ9pvjFpjem8XMZ"},323]</script></html>'
# shape of real answers (Nov 2026)
JOBS = [{"id": "1982695235662578", "title": "Software Engineer, Systems", "locations": ["Menlo Park, CA", "New York, NY"],
         "teams": ["Infrastructure", "Software Engineering"]},
        {"id": "1426787916328283", "title": "Software Engineer, Systems", "locations": ["London, UK"]},
        {"id": "893276690137821", "title": "Embedded Software Engineer, Firmware", "locations": ["Redmond, WA"]},
        {"id": "4456053234655827", "title": "Software Engineer, Product - Ads Products", "locations": ["Menlo Park, CA"]},
        {"id": "555", "title": "Product Designer", "locations": ["Menlo Park, CA"]}]
POSTING = {"@context": "https://schema.org/", "@type": "JobPosting", "title": "Software Engineer, Systems",
           "datePosted": "2026-09-28T19:45:25-07:00", "description": "Meta is seeking a Software Engineer&nbsp;to build systems.",
           "responsibilities": "Design infrastructure.", "qualifications": "Bachelor's degree in Computer Science"}


def handler(asked, gone=(), challenge=False):
    def h(req):
        asked.append(req)
        if req.url.path == "/jobsearch/":
            if challenge:
                return httpx.Response(302, headers={"location": "https://www.metacareers.com/checkpoint/block/"})
            return httpx.Response(200, text=PAGE)
        if req.url.path.startswith("/checkpoint"):
            return httpx.Response(200, text="Security check")
        if req.url.path == "/graphql":
            form = dict(httpx.QueryParams(req.content.decode()))
            assert req.headers["x-fb-lsd"] == form["lsd"] == "AdQ9pvjFpjem8XMZ"
            assert form["doc_id"] == meta.DOC_ID and json.loads(form["variables"])["isLoggedIn"] is False
            return httpx.Response(200, json={"data": {"job_search_with_featured_jobs_v2": {"all_jobs": JOBS}}})
        if req.url.path.startswith("/jobs/position-not-available"):
            return httpx.Response(404, text="Sorry, this job is no longer available")
        jid = req.url.path.strip("/").split("/")[-1]
        if req.url.path.startswith("/jobs/"):
            if jid in gone:
                return httpx.Response(302, headers={"location": "https://www.metacareers.com/jobs/position-not-available/"})
            return httpx.Response(302, headers={"location": f"https://www.metacareers.com/profile/job_details/{jid}/"})
        if req.url.path.startswith("/profile/job_details/"):
            return httpx.Response(200, text=f'<script type="application/ld+json">{json.dumps(POSTING)}</script>')
        return httpx.Response(404)
    return h


def test_reads_every_job_and_describes_new_us_matches(monkeypatch):
    monkeypatch.setattr(meta, "DELAY", 0)
    asked = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler(asked)))
    jobs = asyncio.run(meta.fetch(client, dict(CO, known={"meta:meta:4456053234655827"})))
    assert len(jobs) == 5
    j = jobs[0]
    assert j.job_id == "meta:meta:1982695235662578" and j.location == "Menlo Park, CA; New York, NY"
    assert j.url == "https://www.metacareers.com/jobs/1982695235662578/" and j.posted_at == "2026-09-28"
    assert "build systems" in j.description and "Computer Science" in j.description
    pages = [r.url.path for r in asked if r.url.path.startswith("/jobs/")]
    # London (not US), Firmware (embedded), the known job and the designer: never opened
    assert pages == ["/jobs/1982695235662578/"]


def test_gone_job(monkeypatch):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], gone={"1000000000000001"})))
    assert asyncio.run(meta.details(client, "1000000000000001")) is None
    assert asyncio.run(meta.details(client, "1982695235662578"))["title"] == "Software Engineer, Systems"


def test_a_security_check_stops_the_run():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], challenge=True)))
    with pytest.raises(meta.Blocked):
        asyncio.run(meta.fetch(client, dict(CO)))
