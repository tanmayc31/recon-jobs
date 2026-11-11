import asyncio
import json

import httpx
from recon.sources import workday

CO = {"company": "Capital One", "slug": "capitalone|wd12|Capital_One", "tier": "2"}
API = "/wday/cxs/capitalone/Capital_One"


def posting(title, loc, path, req):
    return {"title": title, "externalPath": path, "locationsText": loc, "bulletFields": [req],
            "postedOn": "Posted 30+ Days Ago"}


# Real titles from the Capital One / Salesforce feeds
SEARCH = [
    posting("Full-stack Engineer 4", "Plano, TX", "/job/Plano-TX/Full-stack-Engineer-4_R1003192-1", "R1003192"),
    posting("Software Engineer II", "4 Locations", "/job/McLean-VA/Software-Engineer-II_R1000001-1", "R1000001"),
    posting("Account Executive, Identity (West)", "Remote", "/job/USA-CA/Account-Executive_JR-0111166", "JR-0111166"),
]
DETAIL = {"jobPostingInfo": {
    "jobReqId": "R1000001", "location": "McLean, VA", "additionalLocations": ["Richmond, VA", "Toronto, ON"],
    "startDate": "2026-11-04", "postedOn": "Posted Today", "externalUrl": "https://capitalone.wd12.myworkdayjobs.com/Capital_One/job/x",
    "jobDescription": "<p>2+ years of experience building backend software.</p>"}}


def mock(pages, calls):
    def handler(req):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            offset = json.loads(req.content)["offset"]
            return httpx.Response(200, json={"jobPostings": pages[offset // workday.PAGE]
                                             if offset // workday.PAGE < len(pages) else []})
        return httpx.Response(200, json=DETAIL)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(pages, monkeypatch):
    monkeypatch.setattr(workday, "DELAY", 0)
    calls = []
    jobs = asyncio.run(workday.fetch(mock(pages, calls), CO))
    return jobs, calls


def test_pagination_stops_when_results_run_out(monkeypatch):
    monkeypatch.setattr(workday, "PAGE", 2)
    jobs, calls = run([SEARCH[:2], SEARCH[2:]], monkeypatch)
    posts = [c for c in calls if c[0] == "POST"]
    assert len(posts) == 3 and all(p[1] == f"{API}/jobs" for p in posts)   # 2 full pages + 1 empty
    assert len(jobs) == 3


def test_pagination_stops_when_pages_repeat(monkeypatch):
    # Real Nvidia behavior: past offset 2000 Workday serves page 1 again, forever
    monkeypatch.setattr(workday, "PAGE", 2)
    jobs, calls = run([SEARCH[:2], SEARCH[2:], SEARCH[:2], SEARCH[:2]], monkeypatch)
    assert len([c for c in calls if c[0] == "POST"]) == 3 and len(jobs) == 3


def test_detail_only_for_jobs_passing_filter(monkeypatch):
    jobs, calls = run([SEARCH], monkeypatch)
    gets = [c[1] for c in calls if c[0] == "GET"]
    assert gets == [f"{API}/job/McLean-VA/Software-Engineer-II_R1000001-1"]   # not "Engineer 4", not sales
    by_title = {j.title: j for j in jobs}
    assert by_title["Full-stack Engineer 4"].description == ""
    assert by_title["Full-stack Engineer 4"].posted_at == "Posted 30+ Days Ago"   # no detail call: search text
    # No detail: ID still comes from the requisition (bulletFields), so the "-1" repost suffix is ignored
    assert by_title["Full-stack Engineer 4"].job_id == "workday:capitalone:R1003192"


def test_detail_fills_job(monkeypatch):
    jobs, _ = run([SEARCH], monkeypatch)
    j = next(j for j in jobs if j.title == "Software Engineer II")
    assert j.job_id == "workday:capitalone:R1000001"        # requisition ID, not the posting path
    assert j.location == "McLean, VA; Richmond, VA; Toronto, ON"
    assert j.posted_at == "Posted Today" and j.url.endswith("/job/x")
    assert "2+ years of experience" in j.description


def test_parse_slug():
    assert workday.parse_slug("nvidia|wd5|NVIDIAExternalCareerSite") == ("nvidia", "wd5", "NVIDIAExternalCareerSite")


def test_tier3_searches_engineer_and_developer(monkeypatch):
    monkeypatch.setattr(workday, "DELAY", 0)
    searches = []

    def handler(req):
        if req.method == "POST":
            body = json.loads(req.content)
            searches.append(body["searchText"])
            # both searches return the same posting: kept once
            return httpx.Response(200, json={"jobPostings": SEARCH[1:2] if body["offset"] == 0 else []})
        return httpx.Response(200, json=DETAIL)
    tier3 = dict(CO, tier="3")
    jobs = asyncio.run(workday.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), tier3))
    assert searches == ["engineer", "engineer", "developer"]   # 2nd search: page 1 is all repeats, stop
    assert len(jobs) == 1


def test_tier1_scans_everything(monkeypatch):
    jobs, calls = run([SEARCH], monkeypatch)
    assert len(jobs) == 3   # CO is Tier 1/2: full board, no search text


def test_known_jobs_skip_detail(monkeypatch):
    monkeypatch.setattr(workday, "DELAY", 0)
    calls = []
    known = {"workday:capitalone:R1000001": ("match", None, 2)}   # the Software Engineer II posting
    jobs = asyncio.run(workday.fetch(mock([SEARCH], calls), dict(CO, known=known)))
    assert not [c for c in calls if c[0] == "GET"] and len(jobs) == 3


def test_search_id_uses_bullet_matching_path():
    # Real F5 search result: bullets[0] is "0", the requisition is the second bullet
    f5 = {"externalPath": "/job/Field-MA/Forward-Deployed-Engineer---AI-Cybersecurity_RP1038981",
          "bulletFields": ["0", "RP1038981"]}
    assert workday.search_id(f5) == "RP1038981"
    cap1 = {"externalPath": "/job/Plano-TX/Full-stack-Engineer-4_R1003192-1", "bulletFields": ["R1003192"]}
    assert workday.search_id(cap1) == "R1003192"
    assert workday.search_id({"externalPath": "/job/x/No-Req", "bulletFields": ["0"]}) == "/job/x/No-Req"


def facet(param, *values):
    return {"facetParameter": param, "values": [{"descriptor": d, "id": f"{param}:{d}", "count": 1} for d in values]}


# Real facet values from Nvidia's and RTX's boards
NVIDIA_FACETS = [
    facet("jobFamilyGroup", "Engineering", "Sales", "Univ Employment", "IT - Information Technology",
          "Business Development", "Research"),
    facet("workerSubType", "Regular Employee", "Intern (Fixed Term)", "Management", "New College Graduate",
          "Regular Employee (Fixed Term)", "Academic (Fixed Term)"),
    facet("timeType", "Full time", "Part time"),
    {"facetParameter": "locationMainGroup", "values": [
        facet("locationHierarchy1", "India", "Israel", "United States"),
        facet("locations", "India, Bengaluru", "US, CA, Santa Clara")]},
]
RTX_FACETS = [
    facet("timeType", "Full time", "Part time"),
    facet("workerSubType", "Apprentice (Fixed Term) (Trainee)", "Intern/Co-op (Fixed Term)", "Regular", "Temporary"),
    facet("jobFamilyGroup", "Digital Technology", "Engineering", "Operations", "Quality"),
    {"facetParameter": "locationMainGroup", "values": [facet("locations",
        "CA-ON-MISSISSAUGA-P22M01 ~ 1801 Courtney Park Dr ~ P22M01 BLDG",
        "US-IA-CEDAR RAPIDS-112 ~ 400 Collins Rd NE ~ BLDG 112",
        "US-AZ-TUCSON-801 ~ 1151 E Hermans Rd ~ BLDG 801",
        "US-TX-RICHARDSON-111 ~ 3601 E Plano Pkwy ~ BLDG 111")]},
]


def names(applied):
    return {k: [v.split(":", 1)[1] for v in ids] for k, ids in applied.items()}


def test_big_board_facets_nvidia():
    [applied] = workday.big_board_facets(NVIDIA_FACETS)
    assert names(applied) == {
        "jobFamilyGroup": ["Engineering", "Univ Employment", "IT - Information Technology"],
        "workerSubType": ["Regular Employee", "Management", "New College Graduate"],   # no interns / fixed term
        "timeType": ["Full time"],
        "locationHierarchy1": ["United States"],   # the country, not every site
    }


def test_big_board_facets_rtx_us_sites_in_chunks(monkeypatch):
    # RTX has no country facet: pick the US sites; 386 of them in one request gave HTTP 500
    monkeypatch.setattr(workday, "MAX_FACET_VALUES", 2)
    chunks = [names(a) for a in workday.big_board_facets(RTX_FACETS)]
    assert [c["locations"] for c in chunks] == [
        ["US-IA-CEDAR RAPIDS-112 ~ 400 Collins Rd NE ~ BLDG 112", "US-AZ-TUCSON-801 ~ 1151 E Hermans Rd ~ BLDG 801"],
        ["US-TX-RICHARDSON-111 ~ 3601 E Plano Pkwy ~ BLDG 111"]]
    assert all(c["workerSubType"] == ["Regular"] and c["timeType"] == ["Full time"]
               and c["jobFamilyGroup"] == ["Digital Technology", "Engineering"] for c in chunks)


def big_board(totals, calls, fail_once=()):
    """Mock board: 4,633 postings unfiltered; filtered page 1 reports totals[i] for the i-th facet set."""
    failed = set()

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=DETAIL)
        body = json.loads(req.content)
        facets, offset = body["appliedFacets"], body["offset"]
        calls.append((bool(facets), offset))
        if not facets:
            return httpx.Response(200, json={"total": 4633, "facets": NVIDIA_FACETS, "jobPostings": SEARCH[2:]})
        if offset in fail_once and offset not in failed:
            failed.add(offset)
            return httpx.Response(429)
        n = offset // workday.PAGE
        page = [posting(f"Software Engineer {n}", "Santa Clara, CA", f"/job/x_R{n}", f"R{n}")]
        return httpx.Response(200, json={"total": totals[0], "jobPostings": page if offset < totals[0] else []})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_big_board_is_filtered_then_paged(monkeypatch):
    monkeypatch.setattr(workday, "DELAY", 0)
    calls = []
    jobs = asyncio.run(workday.fetch(big_board([45], calls), CO))
    assert calls[0] == (False, 0) and all(f for f, _ in calls[1:])   # every request after page 1 is filtered
    assert [o for _, o in calls[1:]] == [0, 20, 40, 60]                # 45 filtered postings: one by one
    assert len(jobs) == 3 and "Account Executive, Identity (West)" not in [j.title for j in jobs]


def test_still_big_after_filtering_pages_in_parallel_and_backs_off(monkeypatch):
    monkeypatch.setattr(workday, "DELAY", 0)
    waits = []

    async def no_wait(seconds):
        waits.append(seconds)
    monkeypatch.setattr(workday.asyncio, "sleep", no_wait)
    calls = []
    jobs = asyncio.run(workday.fetch(big_board([1500], calls, fail_once={40}), CO))
    offsets = sorted(o for f, o in calls[1:])
    assert offsets.count(40) == 2 and set(offsets) == set(range(0, 1500, 20))   # every page, 40 retried
    assert 1 in waits                                                           # backed off after the 429
    assert len(jobs) == 75


def test_small_boards_still_page_through_everything(monkeypatch):
    monkeypatch.setattr(workday, "DELAY", 0)
    bodies = []

    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=DETAIL)
        body = json.loads(req.content)
        bodies.append((body["searchText"], body["offset"]))
        return httpx.Response(200, json={"total": 3, "jobPostings": SEARCH if body["offset"] == 0 else []})

    jobs = asyncio.run(workday.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), CO))
    assert bodies == [("", 0), ("", 20)]          # page 1 reused, not fetched twice
    assert len(jobs) == 3
