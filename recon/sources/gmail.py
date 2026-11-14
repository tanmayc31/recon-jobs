"""Jobright job-alert emails in your Gmail: their job links, resolved to the real postings.

Read-only Gmail API (scope gmail.readonly), and only messages from Jobright's sender address
(JOBRIGHT_SENDER). Each link is followed by its redirects alone, exactly like the dashboard's
"Add job" (recon/add.py): a jobright.ai page is never requested, Recon never logs into Jobright
or reads its website. Links that end on jobright.ai itself are counted and dropped.
companies.csv row: "Jobright alerts,gmail,jobright,2". Without the GMAIL_* settings it does nothing.

One-time sign-in (opens your browser, prints the refresh token to save as GMAIL_REFRESH_TOKEN):
    python -m recon.sources.gmail --auth
"""
import asyncio
import base64
import html
import os
import re
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from recon.filters import classify
from recon.models import Job

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
WINDOW = "newer_than:3d"     # alerts this recent; older ones were read by earlier runs
MAX_MESSAGES = 30
PARALLEL = 4
HREF = re.compile(r'href="([^"]+)"', re.I)
NOT_JOBS = re.compile(r"unsubscribe|preferences|settings|privacy|terms|help|support|facebook\.com|twitter\.com|"
                      r"x\.com/|instagram\.com|youtube\.com|apps\.apple\.com|play\.google\.com|mailto:", re.I)


def configured() -> bool:
    return all(os.environ.get(k) for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN",
                                           "JOBRIGHT_SENDER"))


async def access_token(client: httpx.AsyncClient) -> str:
    r = await client.post(TOKEN, data={"client_id": os.environ["GMAIL_CLIENT_ID"],
                                       "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
                                       "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
                                       "grant_type": "refresh_token"})
    r.raise_for_status()
    return r.json()["access_token"]


def bodies(part: dict) -> list[str]:
    """Every text/html (else text/plain) body in a Gmail message payload."""
    out = []
    for p in [part] + part.get("parts", []):
        if p is not part and p.get("parts"):
            out += bodies(p)
        elif p.get("mimeType") in ("text/html", "text/plain") and (data := p.get("body", {}).get("data")):
            out.append(base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace"))
    return out


def job_links(message: dict) -> list[str]:
    """Links in an alert email that could be jobs (not unsubscribe, social, app-store links)."""
    links = []
    for body in bodies(message.get("payload", {})):
        links += [html.unescape(u) for u in HREF.findall(body)] or re.findall(r"https?://\S+", body)
    return list(dict.fromkeys(u for u in links if u.startswith("http") and not NOT_JOBS.search(u)))


async def messages(client: httpx.AsyncClient, token: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {token}"}
    q = f"from:{os.environ['JOBRIGHT_SENDER']} {WINDOW}"
    r = await client.get(f"{API}/messages", params={"q": q, "maxResults": MAX_MESSAGES}, headers=headers)
    r.raise_for_status()
    return [(await client.get(f"{API}/messages/{m['id']}", params={"format": "full"}, headers=headers))
            .raise_for_status().json() for m in r.json().get("messages", [])]


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    """company: its companies.csv row plus, from main, known (job IDs already saved)."""
    company["partial"] = True   # alerts aren't a board: never used to auto-close
    if not configured():
        return []
    from recon import add   # imports main, which imports this
    msgs = await messages(client, await access_token(client))
    links = list(dict.fromkeys(u for m in msgs for u in job_links(m)))
    sem, counts = asyncio.Semaphore(PARALLEL), {"links": len(links), "jobright pages": 0, "unreadable": 0}

    async def one(url):
        async with sem:
            try:
                job = await add.read(client, await add.resolve(client, url))
            except add.NeedsCompanyLink:
                counts["jobright pages"] += 1
                return None
            except (LookupError, httpx.HTTPError):
                counts["unreadable"] += 1
                return None
        if job.job_id in company.get("known", ()) or not classify(job)[0]:
            return None
        job.via, job.tier = "email", int(company["tier"])
        return job
    jobs = [j for j in await asyncio.gather(*(one(u) for u in links)) if j]
    print(f"Jobright alerts: {len(msgs)} emails, " + ", ".join(f"{k}: {v}" for k, v in counts.items())
          + f", {len(jobs)} new postings")
    return jobs


def authorize():
    """One-time: sign in with Google in your browser (loopback flow), print the refresh token."""
    client_id, secret = os.environ["GMAIL_CLIENT_ID"], os.environ["GMAIL_CLIENT_SECRET"]
    state, got = secrets.token_urlsafe(16), {}

    class Back(BaseHTTPRequestHandler):
        def do_GET(self):
            q = parse_qs(urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                got["code"] = q.get("code", [""])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Recon: done, you can close this tab.")

        def log_message(self, *args):
            pass
    server = HTTPServer(("127.0.0.1", 0), Back)
    redirect = f"http://127.0.0.1:{server.server_port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})
    print(f"Opening Google sign-in (read-only Gmail). If it doesn't open, visit:\n{url}")
    webbrowser.open(url)
    while "code" not in got:
        server.handle_request()
    r = httpx.post(TOKEN, data={"code": got["code"], "client_id": client_id, "client_secret": secret,
                                "redirect_uri": redirect, "grant_type": "authorization_code"})
    r.raise_for_status()
    print("\nSave this as GMAIL_REFRESH_TOKEN (local env file and GitHub secret). Don't share it:\n")
    print(r.json()["refresh_token"])


if __name__ == "__main__":
    from recon.env import load_env
    load_env()
    if "--auth" in sys.argv:
        authorize()
