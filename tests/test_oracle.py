import asyncio

import httpx

from recon.sources import oracle

CO = {"company": "JPMorgan Chase", "ats": "oracle", "slug": "jpmc.fa.oraclecloud.com|CX_1001", "tier": "2"}
US_ID = 300000000289738


def req(n, title, loc="Jersey City, NJ, United States", more=()):
    # shape of a real recruitingCEJobRequisitions requisition (Nov 2026)
    return {"Id": str(210800000 + n), "Title": title, "PostedDate": "2026-11-16", "PrimaryLocation": loc,
            "PrimaryLocationCountry": "US", "JobFamily": "Software Engineering",
            "secondaryLocations": [{"Name": m} for m in more]}


def run(monkeypatch, pages, known=(), us=True):
    monkeypatch.setattr(oracle, "DELAY", 0)
    monkeypatch.setattr(oracle, "PAGE", 3)
    asked = []

    def handler(req_):
        asked.append(req_.url)
        finder = req_.url.params["finder"]
        if req_.url.path.endswith("/recruitingCEJobRequisitions"):
            assert req_.url.params["expand"] == "requisitionList.secondaryLocations"   # else page 2+ is empty
            offset = int(finder.split("offset=")[1].split(",")[0])
            item = {"TotalJobsCount": 99, "requisitionList": pages[offset // 3] if offset // 3 < len(pages) else []}
            if "facetsList=LOCATIONS" in finder:
                item["locationsFacet"] = ([{"Name": "United States", "Id": US_ID}] if us else []) + [
                    {"Name": "United Kingdom", "Id": 300000000289276}]
            else:
                assert f"selectedLocationsFacet={US_ID}" in finder
            return httpx.Response(200, json={"items": [item]})
        if req_.url.path.endswith("/recruitingCEJobRequisitionDetails"):
            assert finder.startswith('ById;Id="') and finder.endswith(",siteNumber=CX_1001")
            return httpx.Response(200, json={"items": [{"ExternalDescriptionStr": "<p>Build payment rails.</p>",
                                                        "ExternalQualificationsStr": "<ul><li>BS in CS</li></ul>"}]})
        return httpx.Response(404)
    co = dict(CO, known=set(known))
    jobs = asyncio.run(oracle.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler)), co))
    return {j.title: j for j in jobs}, asked, co


def test_reads_every_us_page_and_describes_new_matches(monkeypatch):
    pages = [[req(1, "Software Engineer I"), req(2, "Associate Banker"), req(3, "Senior Software Engineer")],
             [req(4, "Software Engineer II - Java", more=("Plano, TX, United States",)), req(5, "Software Engineer I - Payments")]]
    jobs, asked, co = run(monkeypatch, pages, known={"oracle:jpmc.fa.oraclecloud.com:210800005"})
    assert len(jobs) == 5 and "partial" not in co
    j = jobs["Software Engineer II - Java"]
    assert j.job_id == "oracle:jpmc.fa.oraclecloud.com:210800004" and j.posted_at == "2026-11-16"
    assert j.location == "Jersey City, NJ, United States; Plano, TX, United States"
    assert j.url == "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210800004"
    assert "Build payment rails." in j.description and "BS in CS" in j.description
    details = [u for u in asked if u.path.endswith("Details")]
    assert len(details) == 2   # Engineer I and II; not the banker, the senior or the known job


def test_no_us_postings(monkeypatch):
    jobs, asked, _ = run(monkeypatch, [[req(1, "Software Engineer", "Pune, Maharashtra, India")]], us=False)
    assert jobs == {} and len(asked) == 1


def test_hitting_the_page_limit_is_partial(monkeypatch):
    monkeypatch.setattr(oracle, "MAX_PAGES", 2)
    endless = [[req(10 * p + i, f"Analyst {p}-{i}") for i in range(3)] for p in range(5)]
    _, _, co = run(monkeypatch, endless)
    assert co["partial"] is True
