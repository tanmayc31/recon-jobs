import asyncio
import httpx
from recon.sources import ashby, greenhouse, lever

CO = {"company": "Acme", "slug": "acme", "tier": "1"}


def client(payload):
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload)))


def run(coro):
    return asyncio.run(coro)


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
