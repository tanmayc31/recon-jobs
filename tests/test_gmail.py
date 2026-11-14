import asyncio
import base64

import httpx

from recon.sources import gmail

CO = {"company": "Jobright alerts", "ats": "gmail", "slug": "jobright", "tier": "2"}
EMAIL = """<html><body>
<a href="https://click.example.com/t/1">Software Engineer, New Grad at Stripe</a>
<a href="https://jobright.ai/jobs/info/6af5fe30323c531f31e2ea78?utm_source=email">See on Jobright</a>
<a href="https://click.example.com/t/2">Senior Staff Engineer at Stripe</a>
<a href="https://jobright.ai/settings/unsubscribe?u=1">Unsubscribe</a>
</body></html>"""


def b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def setup(monkeypatch):
    for k, v in {"GMAIL_CLIENT_ID": "id", "GMAIL_CLIENT_SECRET": "secret", "GMAIL_REFRESH_TOKEN": "refresh",
                 "JOBRIGHT_SENDER": "alerts@jobright.ai"}.items():
        monkeypatch.setenv(k, v)
    from recon import add
    monkeypatch.setattr(add, "load_companies", lambda: [])
    asked = []

    def handler(req):
        url = str(req.url)
        asked.append(url)
        if url == gmail.TOKEN:
            return httpx.Response(200, json={"access_token": "token"})
        if url.startswith(f"{gmail.API}/messages?"):
            assert req.url.params["q"] == "from:alerts@jobright.ai newer_than:3d"   # Jobright's sender only
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        if url.startswith(f"{gmail.API}/messages/m1"):
            return httpx.Response(200, json={"id": "m1", "payload": {"mimeType": "multipart/alternative", "parts": [
                {"mimeType": "text/plain", "body": {"data": b64("plain copy")}},
                {"mimeType": "text/html", "body": {"data": b64(EMAIL)}}]}})
        if url == "https://click.example.com/t/1":
            return httpx.Response(302, headers={"location": "https://job-boards.greenhouse.io/stripe/jobs/7012345"})
        if url == "https://click.example.com/t/2":
            return httpx.Response(302, headers={"location": "https://job-boards.greenhouse.io/stripe/jobs/7099999"})
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/7012345":
            return httpx.Response(200, json={"title": "Software Engineer, New Grad", "location": {"name": "Seattle, WA"},
                                             "content": "Build payments APIs.", "absolute_url": "https://stripe.com/jobs/1"})
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe/jobs/7099999":
            return httpx.Response(200, json={"title": "Senior Staff Engineer", "location": {"name": "Seattle, WA"},
                                             "content": "Lead.", "absolute_url": "https://stripe.com/jobs/2"})
        if url == "https://boards-api.greenhouse.io/v1/boards/stripe":
            return httpx.Response(200, json={"name": "Stripe"})
        return httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), asked


def test_alert_links_become_postings_without_touching_jobright(monkeypatch, capsys):
    client, asked = setup(monkeypatch)
    co = dict(CO, known=set())
    jobs = asyncio.run(gmail.fetch(client, co))
    assert [(j.job_id, j.via, j.tier) for j in jobs] == [("greenhouse:stripe:7012345", "email", 2)]   # Senior: filtered
    assert not any(httpx.URL(u).host.endswith("jobright.ai") for u in asked)   # never one request to Jobright
    assert "jobright pages: 1" in capsys.readouterr().out          # counted and dropped
    assert co["partial"] is True


def test_does_nothing_until_gmail_is_set_up(monkeypatch):
    for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN", "JOBRIGHT_SENDER"):
        monkeypatch.delenv(k, raising=False)
    calls = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)))
    assert asyncio.run(gmail.fetch(client, dict(CO))) == [] and calls == []


def test_unsubscribe_and_social_links_are_not_jobs():
    message = {"payload": {"mimeType": "text/html", "body": {"data": b64(EMAIL)}}}
    assert gmail.job_links(message) == ["https://click.example.com/t/1",
                                        "https://jobright.ai/jobs/info/6af5fe30323c531f31e2ea78?utm_source=email",
                                        "https://click.example.com/t/2"]
