"""Find which ATS a company uses.  Usage: python -m recon.detect stripe ramp palantir"""
import asyncio
import sys

import httpx

CHECKS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "lever": "https://api.lever.co/v0/postings/{s}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{s}",
}


async def detect(client, slug):
    found = []
    for ats, url in CHECKS.items():
        try:
            r = await client.get(url.format(s=slug))
            if r.status_code == 200:
                data = r.json()
                n = len(data) if isinstance(data, list) else len(data.get("jobs", []))
                if n:
                    found.append(f"{ats} ({n} jobs)")
        except Exception:
            pass
    print(f"{slug:20} -> {', '.join(found) or 'not found (custom site or different slug)'}")


async def main(slugs):
    async with httpx.AsyncClient(timeout=15) as client:
        for s in slugs:
            await detect(client, s)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
