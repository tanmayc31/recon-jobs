import asyncio
import json

import httpx
import pytest

from recon.sources import google

CO = {"company": "Google", "ats": "google", "slug": "google", "tier": "2"}


def row(jid, title, locs=("Mountain View, CA, USA",)):
    # shape of a real r06xKb job (Nov 2026): 3 responsibilities, 4 qualifications, 9 locations,
    # 10 about the job, 12 created
    return [jid, title, "https://www.google.com/about/careers/applications/signin?jobId=x", [None, "<ul><li>Build Search infra.</li></ul>"],
            [None, "<h3>Minimum qualifications:</h3><ul><li>Bachelor's degree and 1 year of experience.</li></ul>"],
            "projects/x", None, "Google", "en-US", [[l, [], "", "", "", "US"] for l in locs],
            [None, "<p>The US base salary range is $141,000.</p>"], [2], [1791821340, 0]]


def rpc_answer(rows, total):
    payload = json.dumps([rows, None, total, 20])
    line = json.dumps([["wrb.fr", "r06xKb", payload, None, None, None, "generic"]])
    return f")]}}'\n\n{len(line)}\n{line}\n25\n[[\"e\",4,null,null,123]]\n"


def handler(asked, pages, blocked=False):
    def h(req):
        asked.append(req)
        if blocked and not req.url.path.startswith("/sorry"):
            return httpx.Response(302, headers={"location": "https://www.google.com/sorry/index?continue=x"})
        if req.url.path.endswith("/batchexecute"):
            freq = json.loads(dict(httpx.QueryParams(req.content.decode()))["f.req"])
            q, *_, where, page = json.loads(freq[0][0][1])[0]
            assert q == "" and where == [["United States"]] and req.headers["x-same-domain"] == "1"
            return httpx.Response(200, text=rpc_answer(pages[page - 1] if page <= len(pages) else [], 25))
        if req.url.path.startswith("/sorry"):
            return httpx.Response(429, text="Our systems have detected unusual traffic")
        jid = req.url.path.rstrip("/").split("/")[-1]
        data = json.dumps([[jid, "Software Engineer"]]) if jid != "100000000000000001" else "[]"
        return httpx.Response(200, text=f"<script>AF_initDataCallback({{key: 'ds:0', hash: '1', data:{data}, sideChannel: {{}}}});</script>")
    return h


def test_reads_every_page_with_descriptions(monkeypatch):
    monkeypatch.setattr(google, "DELAY", 0)
    pages = [[row(str(100 + i), f"Software Engineer {i}") for i in range(20)],
             [row("200", "Software Engineer, Early Career", ("New York, NY, USA", "Seattle, WA, USA")), row("201", "Product Manager")]]
    asked = []
    co = dict(CO)
    jobs = {j.title: j for j in asyncio.run(google.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 22 and "partial" not in co and len(asked) == 2   # no per-job requests
    j = jobs["Software Engineer, Early Career"]
    assert j.job_id == "google:google:200" and j.location == "New York, NY, USA; Seattle, WA, USA"
    assert j.url == "https://www.google.com/about/careers/applications/jobs/results/200-software-engineer-early-career"
    assert "Build Search infra." in j.description and "1 year of experience" in j.description and "$141,000" in j.description
    assert j.posted_at == "2026-10-12"


def test_open_and_gone():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [])))
    assert asyncio.run(google.details(client, "137359440260014790")) is True
    assert asyncio.run(google.details(client, "100000000000000001")) is None


def test_unusual_traffic_page_stops_the_run():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], blocked=True)))
    with pytest.raises(google.Blocked):
        asyncio.run(google.fetch(client, dict(CO)))
