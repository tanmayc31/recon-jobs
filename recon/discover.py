"""Find more company boards and append the working ones to companies.csv as Tier 3.

Sources (licenses allow reuse):
  list      job links in vanshb03/New-Grad-2027 (MIT; recon/sources/listings.py), go links resolved
  jobseek   apps/crawler/data/boards.csv from Job Seek (github.com/colophon-group/jobseek, MIT)
Only Greenhouse, Lever, Ashby and Workday boards are kept.

  python -m recon.discover              # verify + append
  python -m recon.discover --dry-run    # verify + report, don't write
  python -m recon.discover --jobright   # company names from Jobright's new-grad list (names only,
                                        # never its jobs or jobright.ai links): which job system each
                                        # untracked company uses; Greenhouse/Lever/Ashby/Workday added
"""
import asyncio
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from urllib.parse import unquote

import httpx

from recon.main import COMPANIES, HEADERS

JOBRIGHT = "https://raw.githubusercontent.com/jobright-ai/2026-Software-Engineer-New-Grad/master/README.md"
JOBSEEK = "https://raw.githubusercontent.com/colophon-group/jobseek/main/apps/crawler/data/boards.csv"
TIER = 3
PARALLEL = 20
LIST_PARALLEL = 8   # go-link lookups
# boards a source names wrongly (checked by hand): Job Seek calls these Capgemini and Kroger
NOT_BOARDS = {("greenhouse", "cambridgeconsultantslimited"), ("greenhouse", "homechef")}

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


async def list_links(client: httpx.AsyncClient) -> list[dict]:
    """Every active job-list row: {company, url}, with its go link resolved (one request each)."""
    from recon.sources import listings
    sem = asyncio.Semaphore(LIST_PARALLEL)

    async def one(row):
        async with sem:
            try:
                return {"company": row["company_name"].strip(), "url": await listings.resolve(client, row["url"])}
            except httpx.HTTPError:
                return None
    links = []
    for repo in listings.LISTS:
        links += [x for x in await asyncio.gather(*(one(r) for r in await listings.rows(client, repo))) if x]
    return links


def from_list(links: list[dict]) -> list[dict]:
    # "Cincinnati Children’s" -> straight quotes: names stay plain text (test_config)
    return [{"company": x["company"].replace("’", "'").replace("‘", "'"), "ats": b[0], "slug": b[1]}
            for x in links if (b := parse_board(x["url"]))]


JOBRIGHT_ROW = re.compile(r"^\|\s*\*\*\[([^\]]+)\]\((https?://[^)\s]+)\)\*\*\s*\|", re.M)


def jobright_companies(md: str) -> dict[str, str]:
    """Company name -> its homepage, from the company column only. The job links (jobright.ai)
    are never read; "↳" rows repeat the company above."""
    return {name.strip(): home for name, home in JOBRIGHT_ROW.findall(md) if "jobright.ai" not in home}


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
        if k in boards or n in names or k in NOT_BOARDS:
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
        listed = from_list(await list_links(client))
        r = await client.get(JOBSEEK)
        r.raise_for_status()
        jobseek = from_jobseek(r.text)

        # the list first: its names are real company names, Job Seek's come from slugs
        tagged = [dict(c, source="list") for c in listed] + [dict(c, source="jobseek") for c in jobseek]
        fresh = dedupe(tagged, existing)
        sem = asyncio.Semaphore(PARALLEL)
        ok = await asyncio.gather(*(verify(client, sem, c) for c in fresh))
    working = [c for c, good in zip(fresh, ok) if good]

    print(f"{'source':<10}{'links':>8}{'boards':>8}{'new':>8}{'working':>9}")
    for src, found in (("list", listed), ("jobseek", jobseek)):
        boards = {key(c["ats"], c["slug"]) for c in found}
        new = [c for c in fresh if c["source"] == src]
        print(f"{src:<10}{len(found):>8}{len(boards):>8}{len(new):>8}"
              f"{sum(1 for c in working if c['source'] == src):>9}")
    print("working by ATS: " + ", ".join(f"{a}: {n}" for a, n in Counter(c["ats"] for c in working).most_common()))
    print(f"failed verification: {len(fresh) - len(working)}")

    if dry_run:
        print("dry run: companies.csv unchanged")
        return working
    append(working)
    print(f"appended {len(working)} companies as Tier {TIER} -> {len(existing) + len(working)} total")
    return working


def append(boards: list[dict]):
    with open(COMPANIES, "a", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        for c in boards:
            w.writerow([c["company"], c["ats"], c["slug"], TIER])


async def jobright(dry_run: bool = False) -> list[dict]:
    """Untracked companies on Jobright's list: find each one's job system (recon.sponsors' lookup:
    Job Seek, the job lists, slug checks, its own careers page). Boards we can scan are added as
    Tier 3; the rest are tabled by system with their H-1B software filings."""
    from recon import sponsors   # imports this module
    with open(COMPANIES) as f:
        existing = list(csv.DictReader(f))
    tracked = {k for c in existing for k in sponsors.keys(c["company"])}
    async with httpx.AsyncClient(timeout=20, headers=HEADERS, follow_redirects=True) as client:
        r = await client.get(JOBRIGHT)
        r.raise_for_status()
        homes = jobright_companies(r.text)
    names = [n for n in homes if not sponsors.keys(n) & tracked]
    entries = [{"employer": n, "key": sponsors.canon(n), "home": homes[n]} for n in names]
    await sponsors.find_ats(entries)
    filings = sponsors.filings_by_key()
    for e in entries:
        e["filings"] = max((filings.get(k, 0) for k in sponsors.keys(e["employer"]) | {e["key"]}), default=0)
    boards = dedupe([{"company": e["employer"], "ats": e["ats"], "slug": e["slug"]}
                     for e in entries if e["ats"] in sponsors.SUPPORTED and e.get("verified")], existing)

    print(f"Jobright list: {len(homes)} companies, {len(homes) - len(names)} already tracked, {len(names)} checked")
    groups = defaultdict(list)
    for e in entries:
        groups["added (" + e["ats"] + ")" if any(b["company"] == e["employer"] for b in boards) else e["ats"]].append(e)
    print(f"\n{'system':<26}{'companies':>10}{'H-1B SWE filings':>18}  examples")
    for g, es in sorted(groups.items(), key=lambda kv: (-sum(e["filings"] for e in kv[1]), -len(kv[1]))):
        es.sort(key=lambda e: -e["filings"])
        print(f"{g:<26}{len(es):>10}{sum(e['filings'] for e in es):>18}  "
              + ", ".join(f"{e['employer']} ({e['filings']})" for e in es[:5]))
    if not dry_run and boards:
        append(boards)
    print(f"\n{'would add' if dry_run else 'added'} {len(boards)} boards as Tier {TIER}")
    return entries


if __name__ == "__main__":
    if "--jobright" in sys.argv:
        asyncio.run(jobright(dry_run="--dry-run" in sys.argv))
    else:
        asyncio.run(run(dry_run="--dry-run" in sys.argv))
