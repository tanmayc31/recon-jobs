"""Find more company boards and append the working ones to companies.csv as Tier 3.

Sources:
  simplify  application links in the SimplifyJobs New-Grad + Summer 2026 internship READMEs
  jobseek   apps/crawler/data/boards.csv from Job Seek (github.com/colophon-group/jobseek, MIT)
Only Greenhouse, Lever, Ashby and Workday boards are kept.

  python -m recon.discover            # verify + append
  python -m recon.discover --dry-run  # verify + report, don't write
"""
import asyncio
import csv
import json
import re
import sys
from collections import Counter
from urllib.parse import unquote

import httpx

from recon.main import COMPANIES, HEADERS

READMES = {
    "New-Grad-Positions": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
    "Summer2026-Internships": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/README.md",
}
JOBSEEK = "https://raw.githubusercontent.com/colophon-group/jobseek/main/apps/crawler/data/boards.csv"
TIER = 3
PARALLEL = 20

# US boards only: job-boards.eu.greenhouse.io / jobs.eu.lever.co are skipped
BOARD_URL = [
    ("greenhouse", re.compile(r"^https?://(?:job-)?boards\.greenhouse\.io/(?!embed/)([\w-]+)", re.I)),
    ("lever", re.compile(r"^https?://jobs\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"^https?://jobs\.ashbyhq\.com/([^/?#]+)", re.I)),
    ("workday", re.compile(
        r"^https?://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I)),
    # same boards on Workday's other domain: wd1.myworkdaysite.com/recruiting/<tenant>/<site>
    ("workday-site", re.compile(
        r"^https?://(wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/([\w-]+)/([\w-]+)", re.I)),
]


def parse_board(url: str) -> tuple[str, str] | None:
    """Board URL or job URL -> (ats, slug) in companies.csv format, or None."""
    for ats, rx in BOARD_URL:
        m = rx.match(url)
        if not m:
            continue
        if ats == "workday-site":
            wd, tenant, site = m.groups()
            return "workday", f"{tenant}|{wd}|{site}"
        if ats == "workday":
            tenant, wd, site = m.groups()
            if site.lower() in ("wday", "job"):
                return None
            return ats, f"{tenant}|{wd}|{site}"
        return ats, unquote(m.group(1))
    return None


def key(ats: str, slug: str) -> tuple[str, str]:
    """Dedupe key. Workday's wdN number doesn't identify the board, tenant + site do."""
    if ats == "workday":
        tenant, _, site = slug.split("|")
        slug = f"{tenant}|{site}"
    return ats, slug.lower()


TD = re.compile(r"<td>(.*?)</td>", re.S)
TAG = re.compile(r"<[^>]+>")


def from_readme(md: str) -> list[dict]:
    """Rows look like <td><strong><a ...>Twitch</a></strong></td> ... <a href="apply link">.
    A "↳" company cell means "same company as the row above"."""
    found, company = [], ""
    for row in re.findall(r"<tr>(.*?)</tr>", md, re.S):
        cells = TD.findall(row)
        if not cells:
            continue
        name = TAG.sub("", cells[0]).strip()
        company = company if name == "↳" else name
        for url in re.findall(r'href="([^"]+)"', row):
            board = parse_board(url)
            if board and company:
                found.append({"company": company, "ats": board[0], "slug": board[1]})
    return found


def name_from_slug(slug: str) -> str:
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", slug) if w)


def from_jobseek(text: str) -> list[dict]:
    found = []
    for r in csv.DictReader(text.splitlines()):
        if r["monitor_type"] not in ("greenhouse", "lever", "ashby", "workday"):
            continue
        board = parse_board(r["board_url"])
        if not board and r["monitor_type"] != "workday":
            token = json.loads(r["monitor_config"] or "{}").get("token")
            board = (r["monitor_type"], token) if token else None
        if board:
            found.append({"company": name_from_slug(r["company_slug"]), "ats": board[0], "slug": board[1]})
    return found


def dedupe(candidates: list[dict], existing: list[dict]) -> list[dict]:
    """Drop boards (or company names) already in companies.csv, and repeats.
    Names must be unique: main.py keys referrals and first-run backlog by company name."""
    boards = {key(c["ats"], c["slug"]) for c in existing}
    names = {c["company"].lower() for c in existing}
    out = []
    for c in candidates:
        k, n = key(c["ats"], c["slug"]), c["company"].lower()
        if k in boards or n in names:
            continue
        boards.add(k)
        names.add(n)
        out.append(c)
    return out


async def responds(client: httpx.AsyncClient, ats: str, slug: str) -> bool:
    """True if the board's public API answers with at least one job."""
    if ats == "greenhouse":
        r = await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
        return r.status_code == 200 and bool(r.json().get("jobs"))
    if ats == "lever":
        r = await client.get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=1")
        return r.status_code == 200 and isinstance(r.json(), list) and bool(r.json())
    if ats == "ashby":
        r = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        return r.status_code == 200 and bool(r.json().get("jobs"))
    tenant, wd, site = slug.split("|")
    r = await client.post(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs",
                          json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""})
    return r.status_code == 200 and bool(r.json().get("jobPostings"))


async def verify(client, sem, c) -> bool:
    async with sem:
        try:
            return await responds(client, c["ats"], c["slug"])
        except (httpx.HTTPError, ValueError):
            return False


async def run(dry_run: bool = False):
    with open(COMPANIES) as f:
        existing = list(csv.DictReader(f))
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
        simplify = []
        for url in READMES.values():
            r = await client.get(url)
            r.raise_for_status()
            simplify += from_readme(r.text)
        r = await client.get(JOBSEEK)
        r.raise_for_status()
        jobseek = from_jobseek(r.text)

        # Simplify first: its names are real company names, Job Seek's come from slugs
        tagged = [dict(c, source="simplify") for c in simplify] + [dict(c, source="jobseek") for c in jobseek]
        fresh = dedupe(tagged, existing)
        sem = asyncio.Semaphore(PARALLEL)
        ok = await asyncio.gather(*(verify(client, sem, c) for c in fresh))
    working = [c for c, good in zip(fresh, ok) if good]

    print(f"{'source':<10}{'links':>8}{'boards':>8}{'new':>8}{'working':>9}")
    for src, found in (("simplify", simplify), ("jobseek", jobseek)):
        boards = {key(c["ats"], c["slug"]) for c in found}
        new = [c for c in fresh if c["source"] == src]
        print(f"{src:<10}{len(found):>8}{len(boards):>8}{len(new):>8}"
              f"{sum(1 for c in working if c['source'] == src):>9}")
    print("working by ATS: " + ", ".join(f"{a}: {n}" for a, n in Counter(c["ats"] for c in working).most_common()))
    print(f"failed verification: {len(fresh) - len(working)}")

    if dry_run:
        print("dry run: companies.csv unchanged")
        return working
    with open(COMPANIES, "a", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        for c in working:
            w.writerow([c["company"], c["ats"], c["slug"], TIER])
    print(f"appended {len(working)} companies as Tier {TIER} -> {len(existing) + len(working)} total")
    return working


if __name__ == "__main__":
    asyncio.run(run(dry_run="--dry-run" in sys.argv))
