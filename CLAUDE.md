# Recon (recon-jobs)
Real-time job intelligence: polls company ATS boards (Greenhouse, Lever, Ashby),
filters for US early-career SWE / Full-Stack / Cloud / FDE roles, alerts on NEW jobs only.
Recon finds and ranks. It never applies to jobs.

## Rules
- Python 3.11, httpx (async), pytest. Keep it simple; no frameworks.
- Every filter change gets a test using a real example title/location.
- Run `python -m pytest -q` after every change.
- Eligibility blockers (citizenship, clearance, ITAR, explicit "no sponsorship") are hard gates.
  "Authorized to work in the US" alone is NOT a blocker.
- Never commit secrets, data/, .venv/, or config/referrals.csv (private contacts).
- One step at a time. Explain changes briefly in plain English.
- Act as the product designer and QA, not just the coder. For every feature, walk through the real
  user flow end to end, pick sensible defaults (sorting, dates, empty states), check every tab it
  touches, and fix small UX gaps without being asked. List what you noticed and fixed in each summary.

## Layout
recon/sources/  one adapter per ATS
recon/filters.py  title + location rules
recon/eligibility.py  description: years + blockers
recon/store.py  SQLite memory (first_seen_at)
recon/main.py  runs everything

## Roadmap
Step 2: descriptions + memory (in progress) -> Step 3: Telegram alerts
-> Step 4: AWS Lambda + DynamoDB + Terraform -> Step 5: more sources
