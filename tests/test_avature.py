import asyncio
import json

import httpx
import pytest

from recon.sources import avature

CO = {"company": "Deloitte", "ats": "avature", "slug": "apply.deloitte.com/en_US/careers", "tier": "2"}
BASE = "https://apply.deloitte.com/en_US/careers"


def card(jid, title, place):
    # shape of a real Deloitte search card (Nov 2026): the location is the subtitle's last part
    return (f'<article class="article--result " data-total="999+"><h3><a href="{BASE}/JobDetail/{title.replace(" ", "-")}/{jid}" class="link"> {title} </a></h3>'
            f'<div class="article__header__text__subtitle"> <span> Deloitte US </span> | <span> Deloitte Consulting LLP </span> | <span>{place}</span> </div></article>')


PAGE_LINKS = f'<a class="paginationNextLink" href="{BASE}/SearchJobs/?jobRecordsPerPage=10&amp;jobOffset=10">Next</a>'
POSTING = {"@type": "JobPosting", "title": "x", "datePosted": "2026-10-14T00:00:00Z", "description": "&lt;p&gt;Build .NET services. 2+ years.&lt;/p&gt;",
           "jobLocation": {"@type": "Place", "address": {"addressLocality": "", "addressRegion": None, "addressCountry": None}}}
PLACES = ('<div class="article__header--locations article__header--locations-none" > <div class="fluid-cols fluid-cols--cols2">'
          '<p class="paragraph">Atlanta, Georgia, United States</p> <p class="paragraph">Austin, Texas, United States</p> </div> </div>')


def handler(asked, pages, gone=(), waf=False):
    def h(req):
        asked.append(req)
        if waf:
            return httpx.Response(202, headers={"x-amzn-waf-action": "challenge"})
        if req.url.path.endswith("/SearchJobs/"):
            n = int(req.url.params.get("jobOffset", "0")) // 2
            items = pages.get(req.url.params["search"], [])
            return httpx.Response(200, text=PAGE_LINKS + "".join(items[n] if n < len(items) else []))
        jid = req.url.path.rsplit("/", 1)[-1]
        if jid in gone:
            return httpx.Response(302, headers={"location": f"{BASE}/Error"})
        if req.url.path.endswith("/Error"):
            return httpx.Response(403, text="Error")
        return httpx.Response(200, text=f'{PLACES}<script type="application/ld+json">{json.dumps(POSTING)}</script>')
    return h


def test_searches_pages_and_fills_multiple_locations_from_the_job_page(monkeypatch):
    monkeypatch.setattr(avature, "DELAY", 0)
    pages = {"software engineer": [[card("375988", "Business Analyst", "Philadelphia, Pennsylvania, United States"),
                                    card("371100", ".NET Software Engineer", "Multiple Locations")],
                                   [card("370001", "Full Stack Software Engineer II", "Des Moines, Iowa, United States")]],
             "developer": [[card("371100", ".NET Software Engineer", "Multiple Locations")]]}   # same job: once
    asked = []
    co = dict(CO, known=set())
    jobs = {j.title: j for j in asyncio.run(avature.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 3 and "partial" not in co
    net = jobs[".NET Software Engineer"]
    assert net.job_id == "avature:apply.deloitte.com:371100"
    assert net.location == "Atlanta, Georgia, United States; Austin, Texas, United States"   # "Same job available in 2 locations"
    assert "Build .NET services." in net.description and net.posted_at == "2026-10-14"
    assert jobs["Full Stack Software Engineer II"].location == "Des Moines, Iowa, United States"
    pages_read = [r.url.path for r in asked if "/JobDetail/" in r.url.path]
    assert len(pages_read) == 2   # the two engineers; never the analyst


def test_gone_goes_to_the_error_page():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], {}, gone={"1"})))
    assert asyncio.run(avature.details(client, f"{BASE}/JobDetail/x/1")) is None
    assert asyncio.run(avature.details(client, f"{BASE}/JobDetail/x/371100"))["location"].startswith("Atlanta")


def test_a_waf_challenge_stops_the_run():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], {}, waf=True)))
    with pytest.raises(avature.Blocked):
        asyncio.run(avature.fetch(client, dict(CO)))


def test_bloomberg_cards():
    # real Bloomberg card: the subtitle is just the location
    page = ('<article class="article article--result" id="article--1"> <h3 class="article__header__text__title title title--04">'
            '<a class="link" href="https://bloomberg.avature.net/careers/JobDetail/Software-Engineering-Team-Lead/21342"> Software Engineering Team Lead </a>'
            '</h3> <div class="article__header__text__subtitle"> <span class="list-item-location">Frankfurt, Germany</span> </div></article>')
    assert avature.cards(page) == [{"url": "https://bloomberg.avature.net/careers/JobDetail/Software-Engineering-Team-Lead/21342",
                                    "id": "21342", "title": "Software Engineering Team Lead", "location": "Frankfurt, Germany"}]
