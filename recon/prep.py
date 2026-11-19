"""AI prep for an assessment or interview: a short checklist from the job description and your
profile, written by Gemini (the judge's model, key and profile, recon/judge.py).

The dashboard's "AI prep" button queues it (applications.prep_state = 'queued') and starts the
GitHub Actions "add" lane; every Tier 1-2 run also handles any still queued. The checklist is saved
on the application, where you can edit it. CI logs show counts only.

    python -m recon.prep
"""
import asyncio
import os

import httpx

from recon import judge
from recon.env import load_env
from recon.store import Store, now

INSTRUCTIONS = """You help a candidate prepare for one stage of a job application.
Write a short, practical prep checklist in plain text, at most about 250 words, using these three
headings exactly, each followed by "- " bullets:
Likely topics
What to review from your experience
Questions to ask
Likely topics: what this stage will probably test, from the job description (languages,
frameworks, system design areas, domain), most likely first. For an online assessment, the kinds of
problems to practice. What to review from your experience: specific projects, roles or skills from
the candidate's profile that match this job, and how to tell them. Questions to ask: 2-3 good
questions for this team. Be concrete; no generic advice, no greetings, no markdown other than the
headings and bullets."""


def prompt(job: dict, profile: str) -> str:
    return (f"CANDIDATE PROFILE:\n{profile}\n\nSTAGE: {job['stage']}\n\nJOB\nTitle: {job['title']}\n"
            f"Company: {job['company']}\nLocation: {job['location']}\n"
            f"Description:\n{(job['description'] or '')[:judge.DESC_CHARS]}")


async def write(client: httpx.AsyncClient, key: str, job: dict, profile: str) -> str:
    body = {"systemInstruction": {"parts": [{"text": INSTRUCTIONS}]},
            "contents": [{"role": "user", "parts": [{"text": prompt(job, profile)}]}],
            "generationConfig": {"temperature": 0.3}}
    url = judge.API.format(model=os.environ.get("GEMINI_MODEL") or judge.MODEL)
    for attempt in range(2):
        # key in a header, never the URL: error messages include the URL
        r = await client.post(url, headers={"x-goog-api-key": key}, json=body)
        if r.status_code not in (429, 503):
            break
        delay = judge.wait_for(r) if r.status_code == 429 else judge.MAX_WAIT
        if attempt or delay is None:
            raise judge.RateLimited(r.status_code)
        await asyncio.sleep(delay)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    if not text:
        raise ValueError("empty answer")
    return text


async def run(transport=None) -> dict[str, int]:
    counts = {"written": 0, "failed": 0}
    key, profile = os.environ.get("GEMINI_API_KEY"), judge.load_profile()
    store = Store(url=os.environ.get("DATABASE_URL"))
    cols = ["job_id", "stage", "title", "company", "location", "description"]
    jobs = [dict(zip(cols, r)) for r in store.execute(
        "SELECT a.job_id, a.stage, j.title, j.company, j.location, j.description FROM applications a"
        " JOIN jobs j ON j.job_id = a.job_id WHERE a.prep_state = 'queued'").fetchall()]
    store.close()
    if not jobs:
        return counts
    if not key or not profile:
        print("AI prep skipped: " + ("GEMINI_API_KEY" if not key else "profile") + " not set")
        return counts
    done = []
    async with httpx.AsyncClient(timeout=120, transport=transport) as client:
        for job in jobs:
            try:
                done.append((await write(client, key, job, profile), "done", job["job_id"]))
                counts["written"] += 1
            except (httpx.HTTPError, judge.RateLimited, KeyError, IndexError, ValueError):
                done.append((None, "failed", job["job_id"]))
                counts["failed"] += 1
    store = Store(url=os.environ.get("DATABASE_URL"))
    store.executemany("UPDATE applications SET prep = COALESCE(?, prep), prep_state = ?, prep_at = ?"
                      " WHERE job_id = ?", [(text, state, now(), jid) for text, state, jid in done])
    store.commit()
    store.close()
    print(f"AI prep: {counts['written']} written, {counts['failed']} failed")   # counts only: logs are public
    return counts


if __name__ == "__main__":
    load_env()
    asyncio.run(run())
