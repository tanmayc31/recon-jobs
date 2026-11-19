"""Apple careers (jobs.apple.com). companies.csv row: "Apple,apple,apple,2" (the slug is unused).

Only the public requests the careers site itself makes, signed out:
1. /api/v1/refData/teamsByInput: its Teams filter's suggestions (every team and subteam, with codes).
2. /api/v1/CSRFToken, then /api/v1/search: its search, US only, filtered to the software subteams
   (TEAMS, SUBTEAMS), PAGE jobs at a time. The listing is complete for those teams and can close jobs.
3. /api/v1/jobDetails/<id>: a job's description, for new jobs that pass the title + location
   filter; 404 for a job Apple took down. These take 3-60 s each, so a run fetches what it can in
   DETAIL_BUDGET, DETAIL_PARALLEL at a time; the rest are saved without a description (unverified,
   hidden) and fetched by the next runs. A first run has ~300.
If Apple answers with a block or a challenge, the run fails with Blocked: Recon stops there and
doesn't try to get around it.
"""
import asyncio
import re

import httpx

from recon.filters import classify
from recon.models import Job
from recon.text import strip_html

API = "https://jobs.apple.com/api/v1"
PAGE = 20           # the site's page size
DELAY = 0.3         # seconds between requests, be polite
MAX_PAGES = 200     # safety stop (Nov 2026: ~1,600 US software jobs = 81 pages)
TEAMS = {"SFTWR", "MLAI"}   # Software and Services, Machine Learning and AI: every subteam
SUBTEAMS = {        # software subteams of other teams
    ("HRDWR", "Machine Learning and AI"), ("HRDWR", "Spatial Computing"), ("HRDWR", "Platform Security"),
    ("CORSV", "Information Systems and Technology"), ("OPMFG", "Software Engineering"),
    ("OPMFG", "Applied AI and Machine Learning"),
}
LETTERS = "aeios"   # the suggestions need some input: these letters together cover every subteam
RETRIES = 3         # Apple's API sometimes stalls past the 30 s timeout: wait 2 s, 4 s, 8 s and ask again
DETAIL_BUDGET = 240  # seconds of detail requests per run (the company's limit is 6 minutes)
DETAIL_PARALLEL = 3
DETAIL_TIMEOUT = 30  # one try each during a scan: a stalled one waits for the next run
# labeled like the site shows them, so the years rule and the judge know minimums from preferred
SECTIONS = {"jobSummary": "", "description": "Description:", "responsibilities": "Responsibilities:",
            "minimumQualifications": "Minimum qualifications:", "preferredQualifications": "Preferred qualifications:"}


class Blocked(Exception):
    """Apple answered with a block or a challenge: stop, don't work around it."""


def check(r: httpx.Response, what: str, json: bool = True) -> httpx.Response:
    """A block (403, 429) or a page instead of the JSON the site's own code gets: Blocked."""
    if r.status_code in (403, 429) or (json and r.status_code == 200 and "json" not in r.headers.get("content-type", "")):
        raise Blocked(f"{what}: HTTP {r.status_code}")
    return r


async def request(client: httpx.AsyncClient, method: str, url: str, retries: int = RETRIES, timeout: float = 45,
                  **kw) -> httpx.Response:
    """The request, asked again after a timeout or a server error (5xx). A block isn't retried."""
    for attempt in range(retries + 1):
        try:
            r = await client.request(method, url, timeout=timeout, **kw)
            if r.status_code < 500 or attempt == retries:
                return r
        except httpx.TimeoutException:
            if attempt == retries:
                raise
        await asyncio.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def job_url(position_id: str, slug: str) -> str:
    return f"https://jobs.apple.com/en-us/details/{position_id}/{slug}"


async def software_teams(client: httpx.AsyncClient) -> list[dict]:
    found = {}
    for letter in LETTERS:
        r = check(await request(client, "GET", f"{API}/refData/teamsByInput", params={"input": letter}), "teams")
        r.raise_for_status()
        for t in r.json().get("res") or []:
            if t["teamCode"] in TEAMS or (t["teamCode"], t["name"]) in SUBTEAMS:
                found[t["uniqueKey"]] = {"team": t["teamID"], "subTeam": t["id"]}
        await asyncio.sleep(DELAY)
    if not found:
        raise ValueError("no software teams in Apple's team list (it changed?)")
    return list(found.values())


async def search(client: httpx.AsyncClient, token: str, teams: list[dict], page: int) -> list[dict]:
    r = check(await request(client, "POST", f"{API}/search", headers={"x-apple-csrf-token": token}, json={
        "query": "", "filters": {"locations": ["postLocation-USA"], "teams": teams}, "page": page,
        "locale": "en-us", "sort": "", "format": {"longDate": "MMMM D, YYYY", "mediumDate": "MMM D, YYYY"}}), "search")
    r.raise_for_status()
    return (r.json().get("res") or {}).get("searchResults") or []


async def details(client: httpx.AsyncClient, position_id: str, retries: int = RETRIES,
                  timeout: float = 45) -> dict | None:
    """The job's details, or None if Apple took it down (404)."""
    r = await request(client, "GET", f"{API}/jobDetails/{position_id}", retries=retries, timeout=timeout)
    if r.status_code == 404:
        return None
    check(r, "job details").raise_for_status()
    return r.json().get("res") or None


def place(loc: dict) -> str:
    # "Cupertino" + country; the state, when Apple gives one
    parts = [loc.get("name") or loc.get("city"), loc.get("stateProvince"), loc.get("countryName")]
    return ", ".join(dict.fromkeys(p for p in parts if p))


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    teams = await software_teams(client)
    r = check(await request(client, "GET", f"{API}/CSRFToken"), "token", json=False)   # the token is a header
    token = r.headers.get("x-apple-csrf-token")
    if not token:
        raise Blocked("no request token")
    found: dict[str, dict] = {}
    for page in range(1, MAX_PAGES + 1):
        rows = await search(client, token, teams, page)
        for row in rows:   # a job in several cities comes once per city: one job, every location
            job = found.setdefault(row["positionId"], dict(row, places=[]))
            job["places"] += [place(loc) for loc in row.get("locations") or []]
        await asyncio.sleep(DELAY)
        if len(rows) < PAGE:
            break
    else:
        company["partial"] = True   # stopped at MAX_PAGES: missing jobs may still be open
    jobs, wanted = [], []
    for pid, row in found.items():
        job = Job(job_id=f"apple:apple:{pid}", company=company["company"], title=(row.get("postingTitle") or "").strip(),
                  location="; ".join(dict.fromkeys(p for p in row["places"] if p)),
                  url=job_url(pid, row.get("transformedPostingTitle") or re.sub(r"[^a-z0-9]+", "-", row.get("postingTitle", "").lower())),
                  posted_at=(row.get("postDateInGMT") or "")[:10] or None, source="apple",
                  tier=int(company["tier"]), description="")
        # known jobs keep their stored verdict, so skip the detail request
        if job.job_id not in company.get("known", ()) and classify(job)[0]:
            wanted.append((pid, job))
        jobs.append(job)
    await describe(client, wanted)
    return jobs


async def describe(client: httpx.AsyncClient, wanted: list[tuple[str, Job]]):
    """Descriptions for as many as fit in DETAIL_BUDGET; the rest stay empty (retried next run)."""
    sem = asyncio.Semaphore(DETAIL_PARALLEL)
    deadline = asyncio.get_running_loop().time() + DETAIL_BUDGET

    async def one(pid: str, job: Job):
        async with sem:
            left = deadline - asyncio.get_running_loop().time()
            if left <= 1:
                return
            try:
                info = await details(client, pid, retries=0, timeout=min(DETAIL_TIMEOUT, left))
            except httpx.HTTPError:
                return   # stalled or failed: the next run asks again
            await asyncio.sleep(DELAY)
            if info:
                job.description = " ".join(f"{label} {strip_html(str(info[k]))}".strip()
                                           for k, label in SECTIONS.items() if info.get(k))
    await asyncio.gather(*(one(pid, job) for pid, job in wanted))
