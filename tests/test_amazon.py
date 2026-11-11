import asyncio
import json

import httpx
import pytest

from recon.sources import amazon

CO = {"company": "Amazon", "ats": "amazon", "slug": "amazon", "tier": "1"}


def loc(city, region):
    return json.dumps({"city": city, "region": region, "normalizedCountryCode": "USA",
                       "location": f"US, {region}, {city}"})


def job(icims, title="Software Development Engineer, Amazon Dedicated Cloud, Early Career - 2027",
        locations=(("Seattle", "WA"),)):
    # shape of a real amazon.jobs search.json result
    return {"id": f"uuid-{icims}", "id_icims": icims, "title": title, "location": "US, WA, Seattle",
            "locations": [loc(c, r) for c, r in locations], "posted_date": "November 10, 2026",
            "job_path": f"/en/jobs/{icims}/software-development-engineer",
            "description": "Application deadline: Applications will be accepted on an ongoing basis<br/><br/>"
                           "Our engineers work on scalable systems.",
            "basic_qualifications": "- Experience with at least one general-purpose programming language<br/>"
                                    "- 1+ years of non-internship professional software development experience",
            "preferred_qualifications": "- Previous technical internship(s)"}


def board(pages, hits, seen):
    def handler(req):
        seen.append(req.url)
        offset = int(req.url.params["offset"])
        page = pages[offset // amazon.PAGE] if offset // amazon.PAGE < len(pages) else None
        return httpx.Response(200, json={"error": None, "hits": hits, "jobs": page})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run(client, monkeypatch):
    monkeypatch.setattr(amazon, "DELAY", 0)
    return asyncio.run(amazon.fetch(client, CO))


def test_pages_until_hits_and_dedupes_by_amazon_job_id(monkeypatch):
    monkeypatch.setattr(amazon, "PAGE", 2)
    seen = []
    jobs = run(board([[job("10601956", "SDE A"), job("10601957", "SDE B")],
                      [job("10601957", "SDE B"), job("10601958", "SDE C")]], 4, seen), monkeypatch)
    assert [(j.title, j.source_ids) for j in jobs] == [("SDE A", "10601956"), ("SDE B", "10601957"),
                                                       ("SDE C", "10601958")]   # 10601957 listed twice
    assert len(seen) == 2                                     # stopped at hits, no extra request
    params = seen[0].params
    assert params.get_list("normalized_country_code[]") == ["USA"]
    assert params.get_list("schedule_type_id[]") == ["Full-Time"]
    assert params.get_list("category[]") == amazon.CATEGORIES


def test_stops_when_jobs_is_null(monkeypatch):
    # real amazon.jobs: past the last page "jobs" is null, not []
    seen = []
    jobs = run(board([[job("1")]], 500, seen), monkeypatch)
    assert len(jobs) == 1 and len(seen) == 2


def test_job_fields(monkeypatch):
    [j] = run(board([[job("10601956", locations=(("Jessup", "MD"), ("Seattle", "WA")))]], 1, []), monkeypatch)
    assert j.title.startswith("Software Development Engineer")
    assert j.location == "Jessup, MD; Seattle, WA"
    assert j.posted_at == "2026-11-10"
    assert j.url == "https://www.amazon.jobs/en/jobs/10601956/software-development-engineer"
    assert "1+ years of non-internship professional software development experience" in j.description
    assert "<br/>" not in j.description and j.source == "amazon"


def test_identical_title_and_location_collapse_into_openings(monkeypatch):
    # real: "Software Engineer, AWS Applied AI Solutions" in Seattle was posted 4 times
    title = "Software Engineer, AWS Applied AI Solutions"
    page = [job("10601990", title), job("10601870", title), job("10601955", title.upper()),
            job("10601960", title, locations=(("Boston", "MA"), ("Seattle", "WA"))), job("10601961", "SDE II")]
    jobs = run(board([page], 5, []), monkeypatch)
    by_title = {(j.title, j.location): j for j in jobs}
    seattle = by_title[(title, "US, WA, Seattle")]
    assert seattle.openings == 3 and seattle.source_ids == "10601870,10601955,10601990"
    assert seattle.url.endswith("/10601990/software-development-engineer")   # newest posting (results are newest first)
    assert by_title[(title, "Boston, MA; Seattle, WA")].openings == 1       # different location: its own job
    assert len(jobs) == 3


def test_collapsed_id_survives_a_closed_requisition():
    # the role's ID comes from title + location, so losing one requisition doesn't make it look new
    a = amazon.collapse([amazon.to_job(job("1", "SDE"), CO), amazon.to_job(job("2", "SDE"), CO)])
    b = amazon.collapse([amazon.to_job(job("2", "SDE"), CO)])
    assert a[0].job_id == b[0].job_id and (a[0].openings, b[0].openings) == (2, 1)


def test_single_location_keeps_amazon_text():
    assert amazon.location(job("1")) == "US, WA, Seattle"
    # real AWS Elastic Disaster Recovery posting lists the same city twice in different case
    assert amazon.location(job("2", locations=(("SANTA CLARA", "CA"), ("Santa Clara", "CA")))) == "US, WA, Seattle"


@pytest.mark.parametrize("response", [
    httpx.Response(403, text="Forbidden"),
    httpx.Response(200, text="<html>Please verify you are a human</html>", headers={"content-type": "text/html"}),
])
def test_blocked_or_challenged_stops(monkeypatch, response):
    calls = []

    def handler(req):
        calls.append(req)
        return response
    with pytest.raises(amazon.Blocked):
        run(httpx.AsyncClient(transport=httpx.MockTransport(handler)), monkeypatch)
    assert len(calls) == 1                                    # no retry, no workaround
