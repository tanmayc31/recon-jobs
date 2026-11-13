import asyncio
import httpx
from recon.sources import ashby, greenhouse, lever

CO = {"company": "Acme", "slug": "acme", "tier": "1"}


def client(payload):
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def run(coro):
    return asyncio.run(coro)


def test_greenhouse_details_only_for_filter_passes():
    # Real Robinhood titles: the Senior one fails the title filter, so no detail request for it
    listing = {"jobs": [
        {"id": 8220757, "title": "Software Engineer, AI Security", "location": {"name": "Bellevue, WA; Menlo Park, CA"},
         "absolute_url": "u1", "first_published": "2026-10-09T17:58:39-04:00", "updated_at": "2026-11-05T11:50:21-05:00"},
        {"id": 8334429, "title": "Senior Software Engineer, AI Security", "location": {"name": "Bellevue, WA"},
         "absolute_url": "u2"}]}
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("/jobs"):
            assert "content" not in str(req.url)
            return httpx.Response(200, json=listing)
        return httpx.Response(200, json={"content": "&lt;p&gt;2+ years of experience&lt;/p&gt;"})
    jobs = run(greenhouse.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), CO))
    assert calls == ["/v1/boards/acme/jobs", "/v1/boards/acme/jobs/8220757"]
    assert "2+ years of experience" in jobs[0].description and jobs[1].description == ""


def test_greenhouse():
    payload = {"jobs": [{"id": 1, "title": "SWE", "location": {"name": "NYC"},
                         "absolute_url": "u", "first_published": "2026-10-09T17:58:39-04:00",
                         "updated_at": "2026-11-05T11:50:21-05:00"}]}   # real Robinhood 8220757 dates
    jobs = run(greenhouse.fetch(client(payload), CO))
    assert jobs[0].job_id == "greenhouse:acme:1" and jobs[0].location == "NYC"
    assert jobs[0].posted_at == "2026-10-09T17:58:39-04:00"
    assert jobs[0].updated_at == "2026-11-05T11:50:21-05:00"


def test_lever():
    payload = [{"id": "a", "text": "SWE", "categories": {"location": "Remote"},
                "hostedUrl": "u", "createdAt": 1761127200000}]
    jobs = run(lever.fetch(client(payload), CO))
    assert jobs[0].job_id == "lever:acme:a" and jobs[0].posted_at.startswith("2025")


def test_ashby_skips_unlisted():
    payload = {"jobs": [{"id": "1", "title": "SWE", "location": "SF", "jobUrl": "u", "isListed": True},
                        {"id": "2", "title": "Hidden", "isListed": False}]}
    jobs = run(ashby.fetch(client(payload), CO))
    assert len(jobs) == 1


def test_greenhouse_skips_details_for_known_jobs():
    listing = {"jobs": [{"id": 8220757, "title": "Software Engineer, AI Security",
                         "location": {"name": "Bellevue, WA; Menlo Park, CA"}, "absolute_url": "u1"}]}
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json=listing)
    known = {"greenhouse:acme:8220757": ("match", None, None)}
    jobs = run(greenhouse.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), dict(CO, known=known)))
    assert calls == ["/v1/boards/acme/jobs"] and len(jobs) == 1   # listed, but no detail request


def test_ashby_switched_off_board_links_to_the_company_page():
    # real: jobs.ashbyhq.com/cursor is a 404; the job lives at cursor.com/careers/<title>
    from recon.sources import ashby
    j = {"id": "164e27cd-289e-4bcd-8aaf-5280e75c5ed6", "title": "Software Engineer, New Grad 2027",
         "jobUrl": "https://jobs.ashbyhq.com/cursor/164e27cd-289e-4bcd-8aaf-5280e75c5ed6"}
    assert ashby.job_url("cursor", j) == "https://cursor.com/careers/software-engineer-new-grad-2027"
    assert ashby.job_url("notion", dict(j, jobUrl="https://jobs.ashbyhq.com/notion/x")) == "https://jobs.ashbyhq.com/notion/x"
