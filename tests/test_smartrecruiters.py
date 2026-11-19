import asyncio

import httpx

from recon.sources import smartrecruiters as sr

CO = {"company": "ServiceNow", "ats": "smartrecruiters", "slug": "ServiceNow", "tier": "2"}


def posting(pid, name, city="Santa Clara", region="California", remote=False):
    # shape of a real /v1/companies/ServiceNow/postings entry (Nov 2026)
    return {"id": pid, "name": name, "releasedDate": "2026-11-19T00:15:31.790Z",
            "company": {"identifier": "ServiceNow", "name": "ServiceNow"},
            "location": {"city": city, "region": region, "country": "us", "remote": remote,
                         "fullLocation": f"{city}, {region}, United States"}}


def handler(asked, pages, gone=(), inactive=()):
    def h(req):
        asked.append(req)
        path = req.url.path
        if path == "/v1/companies/ServiceNow/postings":
            assert req.url.params["country"] == "us"
            n = int(req.url.params["offset"]) // sr.PAGE
            return httpx.Response(200, json={"totalFound": 999, "content": pages[n] if n < len(pages) else []})
        pid = path.rsplit("/", 1)[-1]
        if pid in gone:
            return httpx.Response(404, json={"httpCode": 404, "code": "RESOURCE_NOT_FOUND"})
        return httpx.Response(200, json={
            "id": pid, "active": pid not in inactive,
            "postingUrl": f"https://jobs.smartrecruiters.com/ServiceNow/{pid}-software-engineer",
            "jobAd": {"sections": {"companyDescription": {"text": "<p>About ServiceNow</p>"},
                                   "jobDescription": {"text": "<p>Build the Now Platform.</p>"},
                                   "qualifications": {"text": "<ul><li>2+ years of Java</li></ul>"}}}})
    return h


def test_reads_every_us_page_and_describes_new_matches(monkeypatch):
    monkeypatch.setattr(sr, "DELAY", 0)
    monkeypatch.setattr(sr, "PAGE", 2)
    pages = [[posting("1", "Software Engineer"), posting("2", "Sr Staff Systems Design Engineer")],
             [posting("3", "Associate Software Engineer", "San Diego", remote=True)]]
    asked = []
    co = dict(CO, known={"smartrecruiters:ServiceNow:1"})
    jobs = {j.title: j for j in asyncio.run(sr.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 3 and "partial" not in co
    j = jobs["Associate Software Engineer"]
    assert j.job_id == "smartrecruiters:ServiceNow:3" and j.location == "San Diego, California, United States (Remote)"
    assert j.url == "https://jobs.smartrecruiters.com/ServiceNow/3-software-engineer" and j.posted_at == "2026-11-19"
    assert "Build the Now Platform." in j.description and "2+ years of Java" in j.description
    assert "About ServiceNow" not in j.description   # the company blurb isn't the job
    details = [r.url.path for r in asked if r.url.path.count("/") == 5]
    assert details == ["/v1/companies/ServiceNow/postings/3"]   # not the known job, not the senior one


def test_gone_is_404_or_inactive():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], gone={"8"}, inactive={"9"})))
    assert asyncio.run(sr.details(client, "ServiceNow", "8")) is None
    assert asyncio.run(sr.details(client, "ServiceNow", "9")) is None
    assert asyncio.run(sr.details(client, "ServiceNow", "7"))["id"] == "7"
