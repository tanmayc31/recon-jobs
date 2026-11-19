import asyncio

import httpx
import pytest

from recon.sources import successfactors as sf

CO = {"company": "EY", "ats": "successfactors", "slug": "careers.ey.com/ey", "tier": "2"}


def row(jid, title, place):
    # shape of a real EY search row (Nov 2026)
    return (f'<tr class="data-row"> <td class="colTitle"> <span class="jobTitle hidden-phone"> <a href="/ey/job/x/{jid}/" '
            f'class="jobTitle-link">{title}</a> </span> </td> <td class="colLocation hidden-phone"> <span class="jobLocation"> {place} </span> </td> </tr>')


JOB_PAGE = ('<span itemprop="datePosted" content="Thu Nov 19 02:01:00 UTC 2026"></span><div><span class="jobdescription">'
            '<p>Build cloud data platforms. 1+ years.</p></span> </div>')


def handler(asked, pages, gone=(), challenge=False):
    def h(req):
        asked.append(req)
        if challenge:
            return httpx.Response(403, text="<title>Just a moment...</title>")
        if req.url.path == "/ey/search/":
            assert req.url.params["locationsearch"] == "United States" and req.url.params["q"] == ""
            n = int(req.url.params["startrow"]) // sf.PAGE
            return httpx.Response(200, text="".join(pages[n] if n < len(pages) else []))
        if req.url.path.startswith("/errorpage"):
            return httpx.Response(200, text="Error")
        jid = req.url.path.rstrip("/").rsplit("/", 1)[-1]
        if jid in gone:
            return httpx.Response(302, headers={"location": "https://careers.ey.com/errorpage/?errortype=Exception"})
        return httpx.Response(200, text=JOB_PAGE)
    return h


def test_reads_every_us_page_and_describes_new_matches(monkeypatch):
    monkeypatch.setattr(sf, "DELAY", 0)
    monkeypatch.setattr(sf, "PAGE", 2)
    pages = [[row("1450048533", "Tech Consulting - Software Engineer", "New York, NY, US, 10001-8604 +3 more…"),
              row("1416469333", "Assurance - Audit Manager", "Tampa, FL, US, 33602")],
             [row("1450000001", "Cloud Engineer", "McLean, VA, US, 22102")]]
    asked = []
    co = dict(CO, known=set())
    jobs = {j.title: j for j in asyncio.run(sf.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 3 and "partial" not in co
    j = jobs["Tech Consulting - Software Engineer"]
    assert j.job_id == "successfactors:careers.ey.com:1450048533" and j.location == "New York, NY, US"
    assert j.url == "https://careers.ey.com/ey/job/x/1450048533/"
    assert "Build cloud data platforms." in j.description and j.posted_at == "2026-11-19"
    assert len([r for r in asked if "/job/" in r.url.path]) == 2   # the two engineers, not the audit manager


def test_gone_goes_to_the_error_page():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], gone={"1000000001"})))
    assert asyncio.run(sf.details(client, "https://careers.ey.com/ey/job/x/1000000001/")) is None
    assert asyncio.run(sf.details(client, "https://careers.ey.com/ey/job/x/1450048533/"))["posted"] == "2026-11-19"


def test_a_cloudflare_challenge_stops_the_run():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], challenge=True)))
    with pytest.raises(sf.Blocked):
        asyncio.run(sf.fetch(client, dict(CO)))
