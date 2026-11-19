import asyncio

import httpx
import pytest

from recon.sources import apple

CO = {"company": "Apple", "ats": "apple", "slug": "apple", "tier": "2"}
# shapes of real answers (Nov 2026)
TEAMS = [{"id": "subTeam-COS", "name": "Operating Systems", "teamID": "teamsAndSubTeams-SFTWR", "teamCode": "SFTWR",
          "uniqueKey": "teamsAndSubTeams-SFTWR:subTeam-COS"},
         {"id": "subTeam-ISTECH", "name": "Information Systems and Technology", "teamID": "teamsAndSubTeams-CORSV",
          "teamCode": "CORSV", "uniqueKey": "teamsAndSubTeams-CORSV:subTeam-ISTECH"},
         {"id": "subTeam-SALES", "name": "Sales", "teamID": "teamsAndSubTeams-APPST", "teamCode": "APPST",
          "uniqueKey": "teamsAndSubTeams-APPST:subTeam-SALES"}]


def result(pid, title, city="Cupertino"):
    return {"id": f"{pid}-0836", "positionId": pid, "postingTitle": title, "transformedPostingTitle": title.lower().replace(" ", "-"),
            "postDateInGMT": "2026-11-17T22:16:42.400Z", "type": "REQ",
            "locations": [{"name": city, "city": "", "stateProvince": "", "countryName": "United States of America"}]}


def handler(asked, pages, gone=(), blocked=False):
    def h(req):
        asked.append(req)
        path = req.url.path
        if blocked:
            return httpx.Response(403, text="Access denied")
        if path == "/api/v1/refData/teamsByInput":
            return httpx.Response(200, json={"res": TEAMS})
        if path == "/api/v1/CSRFToken":
            return httpx.Response(200, headers={"x-apple-csrf-token": "tok"})
        if path == "/api/v1/search":
            assert req.headers["x-apple-csrf-token"] == "tok"
            body = __import__("json").loads(req.content)
            assert body["filters"]["locations"] == ["postLocation-USA"]
            assert {t["subTeam"] for t in body["filters"]["teams"]} == {"subTeam-COS", "subTeam-ISTECH"}   # no retail
            n = body["page"]
            return httpx.Response(200, json={"res": {"searchResults": pages[n - 1] if n <= len(pages) else [], "totalRecords": 99}})
        pid = path.rsplit("/", 1)[-1]
        if pid in gone:
            return httpx.Response(404, json={"error": "jobsite.general.serviceError"})
        return httpx.Response(200, json={"res": {"jobSummary": "Build iOS frameworks.", "minimumQualifications": "BS in CS",
                                                 "description": "<p>Ship Swift code.</p>"}})
    return h


def test_reads_every_page_merges_cities_and_describes_new_matches(monkeypatch):
    monkeypatch.setattr(apple, "DELAY", 0)
    monkeypatch.setattr(apple, "PAGE", 3)
    pages = [[result("200695375", "Software Engineer, iOS"), result("200695375", "Software Engineer, iOS", "Austin"),
              result("200694596", "Engineering Project Manager")],
             [result("200111111", "Senior Software Engineer")]]
    asked = []
    co = dict(CO, known=set())
    jobs = {j.title: j for j in asyncio.run(apple.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 3 and "partial" not in co
    j = jobs["Software Engineer, iOS"]
    assert j.job_id == "apple:apple:200695375" and j.posted_at == "2026-11-17"
    assert j.location == "Cupertino, United States of America; Austin, United States of America"
    assert j.url == "https://jobs.apple.com/en-us/details/200695375/software-engineer,-ios"
    assert "Build iOS frameworks." in j.description and "Description: Ship Swift code." in j.description
    assert "Minimum qualifications: BS in CS" in j.description   # labeled: minimums are gates
    details = [r.url.path for r in asked if r.url.path.startswith("/api/v1/jobDetails/")]
    assert details == ["/api/v1/jobDetails/200695375"]   # not the manager or the senior role


def test_gone_is_404():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], gone={"100000001"})))
    assert asyncio.run(apple.details(client, "100000001")) is None
    assert asyncio.run(apple.details(client, "200695375"))["jobSummary"] == "Build iOS frameworks."


def test_a_block_stops_the_run():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], blocked=True)))
    with pytest.raises(apple.Blocked):
        asyncio.run(apple.fetch(client, dict(CO)))


def test_descriptions_that_dont_fit_the_budget_wait_for_the_next_run(monkeypatch):
    monkeypatch.setattr(apple, "DELAY", 0)
    monkeypatch.setattr(apple, "DETAIL_BUDGET", 0)   # no time left: none fetched, all saved without one
    asked = []
    pages = [[result("200695375", "Software Engineer, iOS")]]
    jobs = asyncio.run(apple.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), dict(CO)))
    assert [j.description for j in jobs] == [""]
    assert not [r for r in asked if r.url.path.startswith("/api/v1/jobDetails/")]
