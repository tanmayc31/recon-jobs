"""Is a saved job still open, and does its Apply link open a real job page?

Open or gone is decided by the site's own API (is_open). HTTP status can't tell: Workday answers
200 for a taken-down job and only then shows "The page you are looking for doesn't exist" in the
browser. Ashby's API kept listing jobs for boards whose job pages are switched off.

Whether a link opens a real job page is decided from the page a browser renders (render): it
must show the job's title and none of the "not found" / "no longer available" messages.

    python -m recon.linkcheck                 # 20 random open Workday matches + 5 from each other source
    python -m recon.linkcheck --recheck-open  # daily: every job in New/Backlog/Later through its API;
                                              # the gone ones are closed (Applied jobs aren't checked)
"""
import argparse
import asyncio
import os
import re

import httpx

from recon.env import load_env
from recon.main import HEADERS, quiet
from recon.sources import ashby, listings
from recon.store import Store

DELAY = 0.3
PARALLEL = {"workday": 6, "greenhouse": 4, "lever": 3, "ashby": 3, "amazon": 2, "list": 3}   # per site, polite
SAMPLE = {"workday": 20, "greenhouse": 5, "lever": 5, "ashby": 5, "amazon": 5}
COLS = ["job_id", "source", "url", "source_ids", "company", "title"]
WORKDAY = [  # public job URL -> parts of the detail API URL
    re.compile(r"https://(?P<tenant>[^./]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?"
               r"(?P<site>[^/]+)(?P<path>/job/.+)$"),
    re.compile(r"https://(?P<wd>wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/"
               r"(?P<tenant>[^/]+)/(?P<site>[^/]+)(?P<path>/job/.+)$"),
]
GONE = {403, 404, 410}   # Workday answers 403 "permission denied" for a job taken down
# rendered text of a dead job page (Workday, Ashby, Greenhouse, company sites)
DEAD = re.compile(r"page you are looking for doesn.t exist|page (you requested )?(was )?not found|"
                  r"no longer (available|accepting|open|active)|job (has been|is) (closed|filled|removed)|"
                  r"position (has been|is) (closed|filled)|this job (posting )?(has )?expired|"
                  r"couldn.t find (that|this|the) (job|page)", re.I)
# bot protection in front of a company site (Tesla, Citadel Securities): the page can't be judged
BLOCKED = re.compile(r"access denied|security verification|verify you are (a )?human|are you a robot|captcha|"
                     r"checking your browser|unusual traffic", re.I)
RENDER_PARALLEL = 3
BATCH = 300   # jobs checked, then saved, at a time (recheck_open)
PAGE_LIMIT = 70   # seconds for one rendered page, all in


def workday_api(url: str) -> str | None:
    for rx in WORKDAY:
        if m := rx.match(url):
            return (f"https://{m['tenant']}.{m['wd']}.myworkdayjobs.com/wday/cxs/{m['tenant']}/{m['site']}"
                    f"{m['path']}")
    return None


def ids(job: dict) -> list[str]:
    """The site's own ID(s) for the job."""
    if job["source"] == "amazon":
        return (job.get("source_ids") or "").split(",")
    return [job["job_id"].split(":", 2)[2]]


async def ashby_board(client: httpx.AsyncClient, slug: str) -> set[str] | None:
    """Listed job IDs, or an empty set if the board's job pages are switched off (and the
    company's own pages aren't known, see ashby.CAREERS). None if Ashby didn't answer."""
    r = await client.get(ashby.URL.format(slug=slug))
    if r.status_code != 200:
        return None
    listed = {j["id"] for j in r.json().get("jobs", []) if j.get("isListed") is not False}
    if slug not in ashby.CAREERS:
        page = await client.get(ashby.BOARD.format(slug=slug))
        if page.status_code == 404:   # jobs.ashbyhq.com/<slug> itself is gone: no job page opens
            return set()
    return listed


async def list_rows(client: httpx.AsyncClient) -> set[str] | None:
    """Row IDs still active on the job lists, or None if a list didn't load."""
    try:
        return {r["id"] for repo in listings.LISTS for r in await listings.rows(client, repo)}
    except (httpx.HTTPError, ValueError):
        return None


async def is_open(client: httpx.AsyncClient, job: dict, boards: dict) -> bool | None:
    """True open, False gone, None couldn't tell. boards: per-run cache of Ashby boards."""
    source, slug = job["source"], job["job_id"].split(":")[1]
    if source == "workday":
        api = workday_api(job["url"])
        if not api:
            return None
        r = await client.get(api)
        return True if r.status_code == 200 and "jobPostingInfo" in r.json() else False if r.status_code in GONE else None
    if source in ("greenhouse", "lever"):
        api = (f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{ids(job)[0]}" if source == "greenhouse"
               else f"https://api.lever.co/v0/postings/{slug}/{ids(job)[0]}")
        r = await client.get(api)
        return True if r.status_code == 200 else False if r.status_code == 404 else None
    if source == "ashby":   # no per-job endpoint: is it on the board?
        if slug not in boards:
            boards[slug] = asyncio.ensure_future(ashby_board(client, slug))   # one fetch per board
        listed = await boards[slug]
        return None if listed is None else ids(job)[0] in listed
    if source in ("list", "you"):   # a company site we can't ask (from a job list, or added by you): the page loads
        if source == "list":            # ... and the list still has it
            if "list" not in boards:
                boards["list"] = asyncio.ensure_future(list_rows(client))
            active = await boards["list"]
            if active is not None and job.get("source_ids") not in active:
                return False
        r = await client.get(job["url"])
        return False if r.status_code in (404, 410) else True if r.status_code < 400 else None
    if source == "amazon":  # collapsed: open while any of its requisitions is
        for i in ids(job):
            r = await client.get(f"https://www.amazon.jobs/en/jobs/{i}")
            if r.status_code == 200:
                return True
            await asyncio.sleep(DELAY)
        return False
    return None


async def check_open(jobs: list[dict], transport=None) -> list[tuple[dict, bool | None]]:
    """is_open for many jobs: a few at a time per site. Job-list jobs on company sites (no API)
    are also opened in a browser when Playwright is installed (render_open): Microsoft's page says
    "No longer accepting applications" only once rendered, while the list still calls it active."""
    results = await api_open(jobs, transport)
    on_site = lambda j, ok: j["source"] in ("list", "you") and ok is not False
    pages = [j for j, ok in results if on_site(j, ok)]
    if pages and transport is None:
        rendered = await render_open(pages)
        results = [(j, rendered.get(j["job_id"], ok) if on_site(j, ok) else ok) for j, ok in results]
    return results


async def render_open(jobs: list[dict]) -> dict[str, bool | None]:
    """job_id -> open, from the rendered page; {} without Playwright."""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return {}
    out = {}
    for r in await render(jobs):
        if r["page"] == "ok":
            out[r["job_id"]] = True
        elif r["page"] in ("dead", "no title"):
            out[r["job_id"]] = None if BLOCKED.search(r["text"]) else False
    return out


async def api_open(jobs: list[dict], transport=None) -> list[tuple[dict, bool | None]]:
    """is_open for many jobs: a few at a time per site."""
    sems, boards = {s: asyncio.Semaphore(n) for s, n in PARALLEL.items()}, {}
    async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True, transport=transport) as client:
        async def one(job):
            async with sems.get(job["source"], sems["lever"]):
                try:
                    return job, await is_open(client, job, boards)
                except (httpx.HTTPError, ValueError):
                    return job, None
                finally:
                    await asyncio.sleep(DELAY)
        return await asyncio.gather(*(one(j) for j in jobs))


async def recheck_open(transport=None) -> tuple[int, int]:
    """Daily: every job in New, Backlog and Later through its site's API; close the gone ones.
    Returns (checked, closed)."""
    store = Store(url=os.environ.get("DATABASE_URL"))
    jobs = [dict(zip(COLS, r)) for r in store.execute(
        f"SELECT {', '.join(COLS)} FROM jobs WHERE closed_at IS NULL"
        " AND ((decision = 'match' AND status IN ('new', 'backlog')) OR status = 'later')").fetchall()]
    store.close()
    gone, unknown = 0, 0
    for i in range(0, len(jobs), BATCH):   # saved batch by batch: a dropped connection loses one batch
        results = await check_open(jobs[i:i + BATCH], transport)
        closing = [job["job_id"] for job, ok in results if ok is False]
        store = Store(url=os.environ.get("DATABASE_URL"))
        store.close_jobs(closing)
        store.commit()
        store.close()
        gone, unknown = gone + len(closing), unknown + sum(1 for _, ok in results if ok is None)
    print(f"Open check: {len(jobs)} jobs in New/Backlog/Later, {gone} gone and closed, {unknown} couldn't be checked")
    return len(jobs), gone


def title_seen(title: str, text: str) -> bool:
    """Most of the title's words appear on the page (sites trim or reformat titles)."""
    words = [w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) > 2]
    page = set(re.findall(r"[a-z0-9]+", text.lower()))
    return bool(words) and sum(w in page for w in words) / len(words) >= 0.6


def verdict(title: str, text: str) -> str:
    """'ok' (a real job page), 'dead' (not found / closed message) or 'no title' (some other page)."""
    if DEAD.search(text[:3000]):
        return "dead"
    return "ok" if title_seen(title, text) else "no title"


async def render(jobs: list[dict], wait: float = 6) -> list[dict]:
    """Open each job's link in a real browser and judge the rendered page, a few at a time.
    Needs Playwright (pip install playwright; python -m playwright install chromium)."""
    from playwright.async_api import async_playwright
    sem = asyncio.Semaphore(RENDER_PARALLEL)
    async with async_playwright() as p:
        browser = await p.chromium.launch()

        async def one(job):
            async with sem:
                page = await browser.new_page()

                async def read():
                    await page.goto(job["url"], wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_timeout(wait * 1000)
                    return " ".join((await page.inner_text("body", timeout=10000)).split())
                try:
                    text = await asyncio.wait_for(read(), PAGE_LIMIT)   # one slow site can't stall the run
                    return dict(job, page=verdict(job["title"], text), final=page.url, text=text[:300])
                except Exception as e:
                    return dict(job, page=type(e).__name__, final="", text="")
                finally:
                    await page.close()
        out = await asyncio.gather(*(one(j) for j in jobs))
        await browser.close()
    return out


def sample(store: Store) -> list[dict]:
    jobs = []
    for source, n in SAMPLE.items():
        jobs += [dict(zip(COLS, r)) for r in store.execute(
            f"SELECT {', '.join(COLS)} FROM jobs WHERE source = ? AND decision = 'match' AND closed_at IS NULL"
            " AND status IN ('new', 'backlog', 'later') ORDER BY RANDOM() LIMIT ?", (source, n)).fetchall()]
    return jobs


async def main():
    store = Store(url=os.environ.get("DATABASE_URL"))
    jobs = sample(store)
    store.close()
    opened = dict((j["job_id"], ok) for j, ok in await check_open(jobs))
    results = await render(jobs)
    good = sum(1 for r in results if r["page"] == "ok" and opened[r["job_id"]])
    print(f"Link check: {good} of {len(results)} open, with a real job page in the browser")
    if quiet():
        return
    for r in results:
        mark = "✅" if r["page"] == "ok" and opened[r["job_id"]] else "❌"
        print(f"{mark} {r['source']:<10} api_open={opened[r['job_id']]!s:<5} page={r['page']:<8}"
              f" {r['company']} | {r['title'][:50]}\n     {r['url']}"
              + ("" if r["page"] == "ok" else f"\n     rendered: {r['text'][:150]}"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--recheck-open", action="store_true",
                        help="check every job in New/Backlog/Later through its site's API, close the gone ones")
    args = parser.parse_args()
    load_env()
    asyncio.run(recheck_open() if args.recheck_open else main())
