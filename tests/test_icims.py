import asyncio
import json

import httpx

from recon.sources import icims

CO = {"company": "Charles Schwab", "ats": "icims", "slug": "career-schwab.icims.com", "tier": "2"}


def card(jid, title, places="US-AZ-Phoenix | US-TX-Austin", label="Job Locations"):
    # shape of a real iCIMS search card (Nov 2026); Liberty Mutual's have no location span
    loc = f'<span class="sr-only field-label">{label}</span> <span > {places}</span>' if places else ""
    return (f'<li class="iCIMS_JobCardItem"> <div class="row"> <div class="col-xs-6 header left"> {loc} </div>'
            f'<div class="col-xs-12 title"> <a href="https://career-schwab.icims.com/jobs/{jid}/{title.lower().replace(" ", "-")}/job?in_iframe=1"'
            f' class="iCIMS_Anchor"> <span class="sr-only field-label">Job Posting Title</span> <h3 > {title}</h3> </a> </div></div> </li>')


POSTING = {"@type": "JobPosting", "title": "x", "datePosted": "2026-11-18T05:00:00.000Z",
           "description": "&lt;p&gt;Build trading APIs. 1+ years.&lt;/p&gt;",
           "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Boston", "addressRegion": "MA", "addressCountry": "US"}}]}


def handler(asked, pages, gone=()):
    def h(req):
        asked.append(req)
        if req.url.path == "/jobs/search":
            n = int(req.url.params["pr"])
            items = pages[min(n, len(pages) - 1)]   # past the end iCIMS shows the last page again
            return httpx.Response(200, text=f'<ul class="container-fluid iCIMS_JobsTable">{"".join(items)}</ul>')
        jid = req.url.path.split("/")[2]
        if jid in gone:
            return httpx.Response(410, text="This job is no longer open")
        return httpx.Response(200, text=f'<script type="application/ld+json">{json.dumps(POSTING)}</script>')
    return h


def test_reads_every_page_and_describes_new_matches(monkeypatch):
    monkeypatch.setattr(icims, "DELAY", 0)
    pages = [[card("130760", "Sr. Disaster Recovery Systems Engineer"), card("130761", "Associate Software Engineer")],
             [card("14256", "Software Engineer", "US-IL-Chicago", label="Location")]]   # ICE's label
    asked = []
    co = dict(CO, known=set())
    jobs = {j.title: j for j in asyncio.run(icims.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 3 and "partial" not in co
    j = jobs["Associate Software Engineer"]
    assert j.job_id == "icims:career-schwab.icims.com:130761" and j.location == "Phoenix, AZ, US; Austin, TX, US"
    assert j.url == "https://career-schwab.icims.com/jobs/130761/associate-software-engineer/job"
    assert "Build trading APIs." in j.description and j.posted_at == "2026-11-18"
    assert jobs["Software Engineer"].location == "Chicago, IL, US"
    searches = [r for r in asked if r.url.path == "/jobs/search"]
    assert len(searches) == 3   # page 3 repeats page 2: the end


def test_no_location_listed_comes_from_the_job_page(monkeypatch):
    monkeypatch.setattr(icims, "DELAY", 0)
    pages = [[card("264332", "Software Engineer I", places=""), card("264333", "Claims Adjuster", places="")]]
    asked = []
    jobs = {j.title: j for j in asyncio.run(icims.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), dict(CO, known=set())))}
    assert jobs["Software Engineer I"].location == "Boston, MA, US"
    assert jobs["Claims Adjuster"].location == "" and len([r for r in asked if r.url.path.startswith("/jobs/2")]) == 1


def test_gone_is_410():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [[]], gone={"999999"})))
    assert asyncio.run(icims.details(client, "career-schwab.icims.com", "999999")) is None
    assert asyncio.run(icims.details(client, "career-schwab.icims.com", "130760"))["@type"] == "JobPosting"
