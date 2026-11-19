import asyncio
import json

import httpx
import pytest

from recon.sources import bytedance

CO = {"company": "TikTok", "ats": "bytedance", "slug": "tiktok", "tier": "2"}


def city(code, name, state, country, country_code):
    return {"code": code, "location_type": 3, "en_name": name, "parent": {
        "code": "ST_1", "location_type": 2, "en_name": state, "parent": {"code": country_code, "location_type": 1, "en_name": country}}}


# shapes of real answers (Nov 2026)
CITIES = [city("CT_1103355", "Seattle", "Washington", "United States of America", "CN_6"),
          city("CT_242", "Toronto", "Ontario", "Canada", "CN_12")]


def post(pid, title, c=CITIES[0]):
    return {"id": pid, "title": title, "description": "Build the For You feed.", "requirement": "BS in CS. 1+ years.",
            "city_info": c, "recruit_type": {"en_name": "Regular"}}


def handler(asked, pages, blocked=False):
    def h(req):
        asked.append(req)
        if blocked:
            return httpx.Response(403, text="Access denied")
        if "/api/" in req.url.path:   # the site's own headers on its API calls
            assert req.headers["website-path"] == "tiktok" and req.headers["origin"] == "https://lifeattiktok.com"
        if req.url.path.endswith("/config/job/filters"):
            return httpx.Response(200, json={"code": 0, "data": {"city_list": CITIES}})
        if req.url.path.endswith("/search/job/posts"):
            body = json.loads(req.content)
            assert body["location_code_list"] == ["CT_1103355"]   # US cities only
            n = body["offset"] // bytedance.PAGE
            return httpx.Response(200, json={"code": 0, "data": {"job_post_list": pages[n] if n < len(pages) else [], "count": 3}})
        jid = req.url.path.rsplit("/", 1)[-1]
        title = "" if jid == "1000000000000000001" else "Software Engineer - Ads Interface and Platform"
        return httpx.Response(200, text=f"<html><head><title>{title}</title></head></html>")
    return h


def test_reads_every_us_page_with_descriptions(monkeypatch):
    monkeypatch.setattr(bytedance, "DELAY", 0)
    monkeypatch.setattr(bytedance, "PAGE", 2)
    pages = [[post("7594626946647492917", "Software Engineer - Ads Interface and Platform"), post("2", "Recruiter")],
             [post("3", "Software Engineer, New Grad")]]
    asked = []
    co = dict(CO)
    jobs = {j.title: j for j in asyncio.run(bytedance.fetch(httpx.AsyncClient(transport=httpx.MockTransport(handler(asked, pages))), co))}
    assert len(jobs) == 3 and "partial" not in co
    j = jobs["Software Engineer - Ads Interface and Platform"]
    assert j.job_id == "bytedance:jobs:7594626946647492917"   # the same id on both sites: one job
    assert j.location == "Seattle, Washington, United States"
    assert j.url == "https://lifeattiktok.com/search/7594626946647492917"
    assert "For You feed" in j.description and "1+ years" in j.description
    assert len(asked) == 3   # filters + 2 pages, no per-job requests


def test_open_and_gone():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [])))
    assert asyncio.run(bytedance.is_open(client, "tiktok", "7594626946647492917")) is True
    assert asyncio.run(bytedance.is_open(client, "tiktok", "1000000000000000001")) is False


def test_a_block_stops_the_run():
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler([], [], blocked=True)))
    with pytest.raises(bytedance.Blocked):
        asyncio.run(bytedance.fetch(client, dict(CO)))
