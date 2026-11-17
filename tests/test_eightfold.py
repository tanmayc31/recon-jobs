import asyncio

import httpx

from recon.sources import eightfold

CO = {"company": "Microsoft", "ats": "eightfold", "slug": "apply.careers.microsoft.com|microsoft.com", "tier": "2"}


def position(n, name, locs=("Redmond, WA, US",)):
    # shape of a real /api/pcsx/search position (Nov 2026)
    return {"id": 1970393556952500 + n, "displayJobId": f"2000462{n}", "name": name, "locations": ["United States, Washington, Redmond"],
            "standardizedLocations": list(locs), "postedTs": 1791931454, "department": "Software Engineering",
            "positionUrl": f"/careers/job/{1970393556952500 + n}"}


SOFTWARE = [[position(i, f"Software Engineer {i}") for i in range(10)],
            [position(10, "Software Engineer II - Backend"), position(11, "Senior Software Engineer")]]
DEVELOPER = [[position(10, "Software Engineer II - Backend"), position(20, "Developer Advocate", ("Seattle, WA, US",))]]


def run(monkeypatch, known=(), pages=None):
    monkeypatch.setattr(eightfold, "DELAY", 0)
    asked = []

    def handler(req):
        asked.append(req.url)
        if req.url.path == "/api/pcsx/search":
            src = pages or (SOFTWARE if req.url.params["query"] == "software" else DEVELOPER)
            n = int(req.url.params["start"]) // eightfold.PAGE
            assert req.url.params["location"] == "United States" and req.url.params["domain"] == "microsoft.com"
            return httpx.Response(200, json={"status": 200, "data": {"positions": src[n] if n < len(src) else [],
                                                                     "count": 12}})
        if req.url.path == "/api/pcsx/position_details":
            return httpx.Response(200, json={"status": 200, "data": {
                "jobDescription": "<p>Build Azure services. 2+ years.</p>",
                "publicUrl": f"https://apply.careers.microsoft.com/careers/job/{req.url.params['position_id']}"}})
        return httpx.Response(404)
    co = dict(CO, known=set(known))
    jobs = asyncio.run(eightfold.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), co))
    return {j.title: j for j in jobs}, asked, co


def test_pages_both_searches_and_reads_descriptions_for_new_matches(monkeypatch):
    jobs, asked, co = run(monkeypatch, known={"eightfold:microsoft.com:1970393556952500"})
    assert len(jobs) == 13                                           # 12 + 1 from "developer", no repeats
    j = jobs["Software Engineer II - Backend"]
    assert j.job_id == "eightfold:microsoft.com:1970393556952510" and j.location == "Redmond, WA, US"
    assert j.url == "https://apply.careers.microsoft.com/careers/job/1970393556952510" and j.posted_at == "2026-10-13"
    assert "Build Azure services" in j.description
    details = [u for u in asked if u.path == "/api/pcsx/position_details"]
    # 1, 2 and II pass the title filter (Engineer 3-9: levels too senior): 3 fetched. Known job 0,
    # Senior and Developer Advocate: never fetched
    assert len(details) == 3
    assert jobs["Software Engineer 0"].description == "" and "partial" not in co


def test_hitting_the_page_limit_is_partial(monkeypatch):
    monkeypatch.setattr(eightfold, "MAX_PAGES", 2)
    endless = [[position(100 * p + i, f"Software Engineer {p}-{i}") for i in range(10)] for p in range(5)]
    _, _, co = run(monkeypatch, pages=endless)
    assert co["partial"] is True


def test_stops_when_results_stop_being_engineering(monkeypatch):
    # real Starbucks "software" search: engineering first, then thousands of barista jobs
    pages = [[position(i, f"engineer II (Web) {i}") for i in range(10)],
             [position(10 + i, f"barista - Store# 0834{i}") for i in range(10)],
             [position(20 + i, f"barista - Store# 2619{i}") for i in range(10)],
             [position(30 + i, f"Service Engineer II {i}") for i in range(10)],   # Microsoft: real ones resume
             [position(40 + i, f"barista - Store# 2447{i}") for i in range(10)],
             [position(50 + i, f"barista - Store# 6710{i}") for i in range(10)],
             [position(60 + i, f"barista - Store# 0296{i}") for i in range(10)],
             [position(70 + i, f"barista - Store# 1111{i}") for i in range(10)]]
    jobs, asked, co = run(monkeypatch, pages=pages)
    searches = [u for u in asked if u.path == "/api/pcsx/search"]
    # "software": 3 barista pages in a row end it (pages 1-7, never 8); "developer" (same mock pages):
    # page 1 is all known, stop
    assert len(searches) == 8 and len(jobs) == 70 and "Service Engineer II 3" in jobs
    assert co["partial"] is True


def test_older_api_sites(monkeypatch):
    # real Netflix: /api/pcsx answers 403 "PCSX is not enabled"; /api/apply/v2 is what its site loads
    monkeypatch.setattr(eightfold, "DELAY", 0)

    def handler(req):
        if req.url.path.startswith("/api/pcsx/"):
            return httpx.Response(403, json={"message": "PCSX is not enabled for this user."})
        if req.url.path == "/api/apply/v2/jobs":
            first = req.url.params["start"] == "0" and req.url.params["query"] == "software"
            return httpx.Response(200, json={"count": 1, "positions": [{
                "id": 790319372667, "name": "Software Engineer (L4), Payments", "locations": ["Los Gatos,California,United States of America"],
                "t_create": 1793836800, "canonicalPositionUrl": "https://explore.jobs.netflix.net/careers/job/790319372667",
            }] if first else []})
        if req.url.path == "/api/apply/v2/jobs/790319372667":
            return httpx.Response(200, json={"job_description": "<p>Build the payments platform.</p>",
                                             "canonicalPositionUrl": "https://explore.jobs.netflix.net/careers/job/790319372667"})
        return httpx.Response(404, json={"message": "Job with ID 1 not found"})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    co = {"company": "Netflix", "ats": "eightfold", "slug": "explore.jobs.netflix.net|netflix.com", "tier": "2", "known": set()}
    [j] = asyncio.run(eightfold.fetch(client, co))
    assert j.job_id == "eightfold:netflix.com:790319372667" and j.location == "Los Gatos,California,United States of America"
    assert j.url == "https://explore.jobs.netflix.net/careers/job/790319372667"
    assert "payments platform" in j.description
    assert asyncio.run(eightfold.details(client, "explore.jobs.netflix.net", "netflix.com", 1)) is None   # gone
