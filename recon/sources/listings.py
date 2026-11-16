"""New-grad job lists on GitHub: jobs from companies we can't scan directly (Google, Microsoft, ...).

Lists (credited in the README), one companies.csv row each, e.g.
"New-Grad-2027 list,listings,vanshb03/New-Grad-2027,2":
  vanshb03/New-Grad-2027              MIT license
  SimplifyJobs/New-Grad-Positions     no license: personal use only
  speedyapply/2027-SWE-College-Jobs   no license: personal use only
Rows from the personal-use lists live only in the database (the repo is public): recon.discover
and recon.sponsors, which write committed files, read only the lists marked reusable.

Each active row that passes the title/location filter is resolved once (vanshb03's go.vansh.nyc
links redirect to the real posting; a link already on a job board isn't requested). Greenhouse, Lever, Ashby and Workday postings get our usual job
IDs and descriptions from those sites' APIs, so a job our adapters already track is the same job.
Amazon is skipped (our Amazon adapter has every Amazon job). Anything else gets the page's text
if it reads like the job, else a one-line description from the list, and is judged on that.
The list's own sponsorship column ("U.S. Citizenship is Required", "Does Not Offer Sponsorship")
goes into the description, so the eligibility gates still apply.
"""
import asyncio
import hashlib
import html
import re
import time
from datetime import datetime, timezone

import httpx

from recon.filters import classify
from recon.models import Job
from recon.sources import ashby
from recon.text import strip_html

LISTS = {   # repo -> (format, URL, license allows reuse)
    "vanshb03/New-Grad-2027": (
        "json", "https://raw.githubusercontent.com/vanshb03/New-Grad-2027/dev/.github/scripts/listings.json", True),
    "SimplifyJobs/New-Grad-Positions": (
        "json", "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
        False),
    "speedyapply/2027-SWE-College-Jobs": (
        "markdown", "https://raw.githubusercontent.com/speedyapply/2027-SWE-College-Jobs/main/NEW_GRAD_USA.md", False),
}
REUSABLE = [repo for repo, (_, _, ok) in LISTS.items() if ok]
SKIP_LINK = re.compile(r"^https?://(www\.)?simplify\.jobs/", re.I)   # Simplify's own pages, not the posting
SHORT_LINK = re.compile(r"^https?://go\.vansh\.nyc/", re.I)
BUDGET = 4.5 * 60   # seconds of resolving per list per run; what's left waits for the next run
TIER = 2           # the companies these lists add are mostly ones we'd track at Tier 1-2 if we could
PARALLEL = 4
DELAY = 0.3
MIN_PAGE_TEXT = 800   # less than this is a JavaScript shell, not the job
GATES = {"U.S. Citizenship is Required", "Does Not Offer Sponsorship"}
GREENHOUSE = re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/([\w-]+)/jobs/(\d+)")
LEVER = re.compile(r"^https?://jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})")
ASHBY = re.compile(r"^https?://jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})")
WORKDAY = re.compile(r"^https?://(?:([\w-]+)\.wd\d+\.myworkdayjobs\.com|wd\d+\.myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?"
                     r"recruiting/([\w-]+))/")
AMAZON = re.compile(r"^https?://(www\.)?amazon\.jobs/")


async def rows(client: httpx.AsyncClient, repo: str) -> list[dict]:
    """The list's active, visible rows, as {id, company_name, title, locations, url, sponsorship,
    date_posted}."""
    kind, url, _ = LISTS[repo]
    r = await client.get(url)
    r.raise_for_status()
    found = markdown_rows(r.text) if kind == "markdown" else r.json()
    return [x for x in found if x.get("active", True) and x.get("is_visible", True) and not SKIP_LINK.match(x["url"])]


CELL_LINK = re.compile(r'href="([^"]+)"')
AGE = re.compile(r"^(\d+)d$")


def markdown_rows(md: str, now: float | None = None) -> list[dict]:
    """speedyapply's tables: | Company | Position | Location | [Salary |] Posting | Age |.
    No row IDs: the posting URL is the ID."""
    now = now or datetime.now(timezone.utc).timestamp()
    out = []
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 5 or "<strong>" not in cells[0]:
            continue
        posting = next((m.group(1) for c in reversed(cells) if (m := CELL_LINK.search(c)) and "Apply" in c), None)
        if not posting:
            continue
        age = AGE.match(cells[-1])
        out.append({"id": "sa-" + hashlib.sha1(posting.encode()).hexdigest()[:16],
                    "company_name": html.unescape(re.sub(r"<[^>]+>", "", cells[0])).strip(),
                    "title": html.unescape(cells[1]), "locations": [html.unescape(cells[2])], "url": posting,
                    "sponsorship": "Other", "date_posted": now - int(age.group(1)) * 86400 if age else None})
    return out


def base_job(row: dict, repo: str) -> Job:
    posted = row.get("date_posted")
    return Job(job_id=f"list:{row['id']}", company=row["company_name"].strip(), title=row["title"],
               location="; ".join(row.get("locations") or []), url=row["url"],
               posted_at=datetime.fromtimestamp(posted, tz=timezone.utc).date().isoformat() if posted else None,
               source="list", tier=TIER, source_ids=row["id"], via="list")


def from_list(job: Job, row: dict) -> str:
    """What the list says, when the posting itself can't be read."""
    text = f"{job.title} at {job.company}, {job.location}. (From a job list; the posting couldn't be read.)"
    return text + (f" {row['sponsorship']}." if row.get("sponsorship") in GATES else "")


async def resolve(client: httpx.AsyncClient, url: str) -> str:
    """A short link's target: one request, the redirect isn't followed. Other links as they are."""
    if not SHORT_LINK.match(url):
        return url
    r = await client.get(url, follow_redirects=False)
    return r.headers.get("location", url) if r.is_redirect else url


async def describe(client: httpx.AsyncClient, job: Job, url: str, boards: dict) -> Job | None:
    """Fill job from the real posting. None: skip it (Amazon, which our adapter covers)."""
    job.url = url
    if AMAZON.match(url):
        return None
    if m := GREENHOUSE.match(url):
        slug, gid = m.groups()
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{gid}")
        if r.status_code == 200:
            job.job_id, job.source = f"greenhouse:{slug}:{gid}", "greenhouse"
            job.description = strip_html(r.json().get("content"))
        return job
    if m := LEVER.match(url):
        slug, lid = m.groups()
        r = await client.get(f"https://api.lever.co/v0/postings/{slug}/{lid}")
        if r.status_code == 200:
            d = r.json()
            parts = [d.get("descriptionPlain") or ""] + [strip_html(x.get("content")) for x in d.get("lists") or []]
            job.job_id, job.source = f"lever:{slug}:{lid}", "lever"
            job.description = " ".join(p for p in parts if p) + " " + (d.get("additionalPlain") or "")
        return job
    if m := ASHBY.match(url):
        slug, aid = m.groups()
        if slug not in boards:
            r = await client.get(ashby.URL.format(slug=slug))
            boards[slug] = {j["id"]: j for j in r.json().get("jobs", [])} if r.status_code == 200 else {}
        if j := boards[slug].get(aid):
            job.job_id, job.source, job.url = f"ashby:{slug}:{aid}", "ashby", ashby.job_url(slug, j)
            job.description = j.get("descriptionPlain") or strip_html(j.get("descriptionHtml"))
        return job
    if WORKDAY.match(url):
        from recon.linkcheck import workday_api   # linkcheck imports main, which imports this
        api = workday_api(url)
        r = await client.get(api) if api else None
        if r is not None and r.status_code == 200:
            info = r.json().get("jobPostingInfo") or {}
            tenant = api.split("/wday/cxs/")[1].split("/")[0]
            job.job_id = f"workday:{tenant}:{info.get('jobReqId') or job.source_ids}"
            job.source, job.url = "workday", info.get("externalUrl") or url
            job.description = strip_html(info.get("jobDescription"))
        return job
    r = await client.get(url, follow_redirects=True)   # a company's own site: use the page if it reads like the job
    text = strip_html(r.text) if r.status_code == 200 and "html" in r.headers.get("content-type", "") else ""
    if len(text) >= MIN_PAGE_TEXT and job.title.split()[0].lower() in text.lower():
        job.description = text
    return job


async def fetch(client: httpx.AsyncClient, company: dict) -> list[Job]:
    """company: the list's companies.csv row, plus from main: known (job IDs), list_ids (rows
    already saved, not resolved again), covered ((company, title) of every saved job) and
    urls (every saved job's link): a job Recon has from any source isn't added again."""
    company["partial"] = True   # a list isn't a company's whole board: never used to auto-close
    repo, done = company["slug"], set(company.get("list_ids", ()))
    covered, urls = company.get("covered", set()), company.get("urls", set())
    todo = []
    for row in await rows(client, repo):
        job = base_job(row, repo)
        if row["id"] in done or row["url"] in urls or \
                (job.company.lower(), job.title.lower()) in covered:
            continue
        if classify(job)[0]:   # title + location before any request
            todo.append((job, row))
    sem, boards, started = asyncio.Semaphore(PARALLEL), {}, time.monotonic()

    async def one(job, row):
        async with sem:
            if time.monotonic() - started > BUDGET:
                return None   # not saved, so the next run resolves it
            try:
                out = await describe(client, job, await resolve(client, job.url), boards)
            except httpx.HTTPError:
                out = job   # keep the list's go link; it still opens the posting
            await asyncio.sleep(DELAY)
        if out is None or out.job_id in company.get("known", ()) or out.url in urls:
            return None
        if not out.description.strip():
            out.description = from_list(out, row)
        elif row.get("sponsorship") in GATES:
            out.description += f" {row['sponsorship']}."
        return out
    return [j for j in await asyncio.gather(*(one(j, r) for j, r in todo)) if j]
