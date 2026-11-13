"""Jobs you add by URL (the dashboard's "Add job" box): the real posting is read, checked by the
filters and judged by the AI right away, and saved to New as "added by you".

The dashboard saves the URL in the `added` table and starts this through GitHub Actions; the
Tier 1-2 lane runs it too, in case that didn't happen.

Greenhouse, Lever, Ashby, Workday and Amazon postings are read through their APIs (same job IDs
as our adapters'). Other company sites: the page's JobPosting data when it has it, else its title
and text. Job aggregators (LinkedIn, Jobright, Indeed, ...) are never read: a short or tracking
link is followed only by its redirects, and an aggregator's own job page gets "paste the company's
link instead".

    python -m recon.add                 # process what the dashboard queued
    python -m recon.add URL [URL ...]   # add these now
"""
import asyncio
import json
import os
import re
import sys
import uuid
from urllib.parse import urljoin, urlparse

import httpx

from recon import eligibility, judge, linkcheck
from recon.env import load_env
from recon.filters import classify
from recon.main import HEADERS, load_companies, quiet
from recon.models import Job
from recon.sources import amazon, ashby
from recon.sources.listings import ASHBY, GREENHOUSE, LEVER
from recon.store import Store
from recon.text import strip_html

TIER = 2          # a company you add yourself counts like the ones we track closely
MAX_HOPS = 8
AGGREGATORS = re.compile(r"(^|\.)(linkedin\.com|jobright\.ai|indeed\.com|glassdoor\.com|ziprecruiter\.com|"
                         r"simplify\.jobs|joinhandshake\.com|wellfound\.com|builtin\.com)$", re.I)
WORKDAY_URL = re.compile(r"myworkdayjobs\.com|myworkdaysite\.com", re.I)
AMAZON_URL = re.compile(r"^https?://(www\.)?amazon\.jobs/(?:[a-z]{2}/)?jobs/(\d+)", re.I)
JSON_LD = re.compile(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)


class NeedsCompanyLink(Exception):
    """The URL is (or redirects to) an aggregator's own page, which Recon doesn't read."""


async def resolve(client: httpx.AsyncClient, url: str) -> str:
    """Follow redirects one hop at a time, without ever requesting an aggregator's page."""
    for _ in range(MAX_HOPS):
        if AGGREGATORS.search(urlparse(url).hostname or ""):
            raise NeedsCompanyLink(urlparse(url).hostname)
        r = await client.get(url, follow_redirects=False)
        if not r.is_redirect:
            return url
        url = urljoin(url, r.headers["location"])
    return url


def tracked(ats: str, key: str) -> dict | None:
    """The companies.csv row for this board (Workday: tenant|site), if we track it."""
    for c in load_companies():
        slug = c["slug"].lower()
        if c["ats"] == ats and (slug == key.lower() or (ats == "workday" and
                                                         "|".join(slug.split("|")[::2]) == key.lower())):
            return c
    return None


def named(c: dict | None, fallback: str) -> tuple[str, int]:
    return (c["company"], int(c["tier"])) if c else (fallback, TIER)


async def read(client: httpx.AsyncClient, url: str) -> Job:
    """The posting at url (already resolved) as a Job."""
    if m := GREENHOUSE.match(url):
        slug, gid = m.groups()
        d = (await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{gid}")).raise_for_status().json()
        board = (await client.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")).json().get("name", slug)
        company, tier = named(tracked("greenhouse", slug), board)
        return Job(f"greenhouse:{slug}:{gid}", company, d["title"], (d.get("location") or {}).get("name", ""),
                   d.get("absolute_url") or url, d.get("first_published"), "greenhouse", tier, strip_html(d.get("content")))
    if m := LEVER.match(url):
        slug, lid = m.groups()
        d = (await client.get(f"https://api.lever.co/v0/postings/{slug}/{lid}")).raise_for_status().json()
        company, tier = named(tracked("lever", slug), slug.replace("-", " ").title())
        text = " ".join([d.get("descriptionPlain") or ""] + [strip_html(x.get("content")) for x in d.get("lists") or []])
        return Job(f"lever:{slug}:{lid}", company, d["text"], (d.get("categories") or {}).get("location", ""),
                   d.get("hostedUrl") or url, None, "lever", tier, text)
    if m := ASHBY.match(url):
        slug, aid = m.groups()
        board = (await client.get(ashby.URL.format(slug=slug))).raise_for_status().json()
        j = next((x for x in board.get("jobs", []) if x["id"] == aid), None)
        if not j:
            raise LookupError("not on the company's Ashby board (closed?)")
        company, tier = named(tracked("ashby", slug), slug.replace("-", " ").title())
        return Job(f"ashby:{slug}:{aid}", company, j["title"], j.get("location") or "", ashby.job_url(slug, j),
                   j.get("publishedAt"), "ashby", tier, j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")))
    if WORKDAY_URL.search(url) and (api := linkcheck.workday_api(url)):
        r = await client.get(api)
        if r.status_code in linkcheck.GONE:
            raise LookupError("Workday says this job is no longer posted")
        info = r.raise_for_status().json()["jobPostingInfo"]
        tenant, site = api.split("/wday/cxs/")[1].split("/")[:2]
        company, tier = named(tracked("workday", f"{tenant}|{site}"), tenant.title())
        places = [info.get("location")] + (info.get("additionalLocations") or [])
        return Job(f"workday:{tenant}:{info.get('jobReqId') or uuid.uuid4().hex[:12]}", company, info["title"],
                   "; ".join(p for p in places if p), info.get("externalUrl") or url, info.get("postedOn"),
                   "workday", tier, strip_html(info.get("jobDescription")))
    if m := AMAZON_URL.match(url):
        r = await client.get(amazon.SEARCH, params={"base_query": m.group(2), "result_limit": 5})
        hit = next((j for j in r.raise_for_status().json().get("jobs") or [] if j.get("id_icims") == m.group(2)), None)
        if not hit:
            raise LookupError("not on amazon.jobs (closed?)")
        return amazon.collapse([amazon.to_job(hit, {"company": "Amazon", "tier": "1"})])[0]
    return await read_page(client, url)


async def read_page(client: httpx.AsyncClient, url: str) -> Job:
    """A company's own job page: its JobPosting data if it has any, else its title and text."""
    r = await client.get(url, follow_redirects=True)
    r.raise_for_status()
    post = next((x for b in JSON_LD.findall(r.text) for x in ld_items(b) if x.get("@type") == "JobPosting"), {})
    host = (urlparse(str(r.url)).hostname or "").removeprefix("www.").removeprefix("careers.").removeprefix("jobs.")
    title = post.get("title") or meta(r.text, "og:title") or re.sub(r"\s+", " ", (re.search(
        r"<title>(.*?)</title>", r.text, re.S | re.I) or [None, ""])[1]).strip()
    # "lifeattiktok.com" -> "Tiktok": the domain is the last resort for the company's name
    label = re.sub(r"^(lifeat|careersat|joinus|join|careers|jobs|work(at)?)(?=\w{3})", "", host.split(".")[0])
    company = (post.get("hiringOrganization") or {}).get("name") or meta(r.text, "og:site_name") or label.title()
    return Job(f"you:{uuid.uuid5(uuid.NAMESPACE_URL, str(r.url)).hex[:16]}", company.strip(),
               re.split(r"\s+[|\-–]\s+(?=[^|\-–]*$)", title.strip().lstrip("#"))[0] if title else "Job",
               place(post.get("jobLocation")), str(r.url), post.get("datePosted"), "you", TIER,
               strip_html(post.get("description")) or strip_html(r.text))


def ld_items(block: str) -> list[dict]:
    try:
        d = json.loads(block)
    except ValueError:
        return []
    items = d if isinstance(d, list) else d.get("@graph", [d]) if isinstance(d, dict) else []
    return [x for x in items if isinstance(x, dict)]


def meta(html: str, prop: str) -> str | None:
    m = re.search(rf'<meta[^>]+(?:property|name)="{prop}"[^>]+content="([^"]+)"', html, re.I)
    return m.group(1) if m else None


def place(loc) -> str:
    """JobPosting jobLocation (one place or a list) -> 'City, ST; City, ST'."""
    out = []
    for x in loc if isinstance(loc, list) else [loc] if loc else []:
        a = (x or {}).get("address") or {}
        a = a if isinstance(a, dict) else {"addressLocality": str(a)}
        out.append(", ".join(p for p in (a.get("addressLocality"), a.get("addressRegion"),
                                         a.get("addressCountry") if isinstance(a.get("addressCountry"), str) else None) if p))
    return "; ".join(o for o in out if o)


async def add(client: httpx.AsyncClient, url: str) -> tuple[str, str, Job | None]:
    """(state, message, job): read, filter, save. states: added / skipped / gone / needs link / failed."""
    try:
        resolved = await resolve(client, url)
        job = await read(client, resolved)
    except NeedsCompanyLink as e:
        return "needs link", (f"Recon doesn't read {e} pages. Open the job there and paste the company's own "
                              "link (where Apply takes you)."), None
    except (LookupError, httpx.HTTPStatusError) as e:
        return "gone", f"Couldn't find an open job there: {e}", None
    except httpx.HTTPError as e:
        return "failed", f"Couldn't open the link ({type(e).__name__})", None
    job.via = "you"
    store = Store(url=os.environ.get("DATABASE_URL"))
    if job.source == "you":   # a company page Recon already has (from a job list): the same job, even on
        # another host of the company's site (qualcomm.eightfold.ai vs careers.qualcomm.com)
        if same := store.execute("SELECT job_id, source, source_ids FROM jobs WHERE url IN (?, ?, ?)"
                                 " OR (LOWER(company) = LOWER(?) AND LOWER(title) = LOWER(?))",
                                 (job.url, resolved, url, job.company, job.title)).fetchone():
            job.job_id, job.source, job.source_ids = same
    store.close()
    keep, flags = classify(job)
    ok, reason, yrs, desc_flags = eligibility.check(job.description, job.title) if keep else (False, flags[0], None, [])
    store = Store(url=os.environ.get("DATABASE_URL"))
    note = (", ".join(flags + desc_flags) or None) if ok else reason   # flags on a match, why on a skip
    store.upsert_many([(job, "match" if ok else "skip", note, yrs, "new")])
    # added before by a scan: show it in New now, and as yours
    store.execute("UPDATE jobs SET status = 'new', via = 'you' WHERE job_id = ? AND status IN ('backlog', 'skipped')",
                  (job.job_id,))
    store.commit()
    store.close()
    if not ok:
        return "skipped", f"The filters would skip it: {reason}", job
    return "added", "Added to New", job


async def judge_added(client: httpx.AsyncClient) -> int:
    """Judge your matches without an AI verdict now, instead of waiting for the next judge run."""
    key, profile = os.environ.get("GEMINI_API_KEY"), judge.load_profile()
    if not key or not profile:
        return 0
    store = Store(url=os.environ.get("DATABASE_URL"))
    jobs = [dict(zip(["job_id", "company", "title", "location", "description"], r)) for r in store.execute(
        "SELECT job_id, company, title, location, description FROM jobs WHERE via = 'you' AND decision = 'match'"
        " AND ai_scored_at IS NULL AND description <> ''").fetchall()]
    store.close()
    results = []
    for i in range(0, len(jobs), judge.BATCH):
        try:
            answers = await judge.judge(client, key, jobs[i:i + judge.BATCH], profile)
        except judge.RateLimited:
            break   # the regular judge runs pick them up
        results += [(job_id, a, judge.veto(a)) for job_id, a in answers.items()]
    if results:
        store = Store(url=os.environ.get("DATABASE_URL"))
        store.save_scores(results)
        store.commit()
        store.close()
    return len(results)


async def run(urls: list[str] | None = None) -> list[dict]:
    store = Store(url=os.environ.get("DATABASE_URL"))
    for url in urls or []:
        store.queue_added(url)
    store.commit()
    queued = store.queued_added()
    store.close()
    out = []
    async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
        for row_id, url in queued:
            state, message, job = await add(client, url)
            if state == "added":   # same open check as any job entering New
                [(_, still)] = await linkcheck.check_open([{"job_id": job.job_id, "source": job.source, "url": job.url,
                                                            "source_ids": job.source_ids, "company": job.company,
                                                            "title": job.title}])
                if still is False:
                    state, message = "gone", "The posting is no longer open"
            store = Store(url=os.environ.get("DATABASE_URL"))
            if state == "gone" and job:
                store.close_jobs([job.job_id])
            store.finish_added(row_id, state, message, job.job_id if job else None)
            store.commit()
            store.close()
            out.append({"url": url, "state": state, "message": message, "job": job})
        judged = await judge_added(client)
    print(f"Add job: {len(out)} processed, {sum(1 for o in out if o['state'] == 'added')} added, {judged} judged")
    if not quiet():
        for o in out:
            j = o["job"]
            print(f"  {o['state']:<11} {o['message']}\n             {o['url']}"
                  + (f"\n             -> {j.company} | {j.title} | {j.location} ({j.job_id})" if j else ""))
    return out


if __name__ == "__main__":
    load_env()
    asyncio.run(run(sys.argv[1:]))
