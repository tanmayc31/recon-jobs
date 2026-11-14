# Recon
Intel on new tech roles, the minute they drop.

## v1 step 1

## Setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

## 1. Verify company slugs
python -m recon.detect stripe databricks palantir openai ramp notion

## 2. Run the bot
python -m recon.main              # all tiers
python -m recon.main --tiers 1,2                          # GitHub Actions: every 30 min
python -m recon.main --tiers 3 --ats greenhouse,lever,ashby  # every 3 h
python -m recon.main --tiers 3 --ats workday                 # every 6 h (slow: ~20s per tenant)
python -m recon.main --recheck     # re-judge known jobs too (after changing filter rules)

Known jobs keep their stored verdict, so Recon only fetches descriptions for job IDs it has
never seen. Use --recheck after editing filters.py or eligibility.py to apply the new rules.

## H-1B sponsors
python -m recon.sponsors data/LCA_Disclosure_Data_FY2025_Q*.xlsx   # rebuilds config/sponsors.csv

Ranks employers by certified H-1B LCA filings for software roles (DOL OFLC disclosure data,
public), marks the ones companies.csv already covers, and finds the ATS of the top 500 missing
ones. Download a fiscal year's four quarterly xlsx files in a browser (dol.gov blocks scripts)
from https://www.dol.gov/agencies/eta/foreign-labor/performance into data/ (gitignored).
Needs `pip install python-calamine` to read them.

## AI judge
python -m recon.judge --limit 10   # score 10 unjudged matches (default 40)

Gemini (free tier) scores each match 0-100 against your profile and double-checks the
hard gates; a veto (no sponsorship, citizenship/clearance, not software, >4 years) moves it
to Skipped as "ai: <reason>". Needs GEMINI_API_KEY plus your profile in config/profile.md
(gitignored) or the CANDIDATE_PROFILE secret. Emails, phone numbers and links are stripped
before sending. Leave your name and address out of the profile.

## 3. Run tests
python -m pytest -q

## Add a company
Add a row to config/companies.csv: company,ats,slug,tier

ats is greenhouse, lever, ashby or workday. For Workday, slug is `tenant|wdN|site`,
read from the career site URL:

    https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite
            tenant  wdN                  site
    -> Nvidia,workday,nvidia|wd5|NVIDIAExternalCareerSite,2

Workday search results have no descriptions, so Recon fetches the job detail only
for jobs that pass the title + location filter.

## Discover more companies
python -m recon.discover            # verify boards, append working ones as Tier 3
python -m recon.discover --dry-run  # report only

Sources: job links in vanshb03/New-Grad-2027 and Job Seek's board list (Greenhouse, Lever, Ashby
and Workday boards only).
python -m recon.discover --jobright  # which job system each company on Jobright's new-grad list uses

## Job lists
The Tier 1-2 lane also reads [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027)
(recon/sources/listings.py): jobs from companies we can't scan directly. Each row's link is
resolved to the real posting; Greenhouse/Lever/Ashby/Workday postings are read through their APIs,
anything else is judged on its page or on the list's title, company and location ("from list").
Only lists whose license allows reuse are read: SimplifyJobs/New-Grad-Positions and
speedyapply/2027-SWE-College-Jobs have no license, so Recon doesn't use them.
A company's first run is saved as backlog, not shown as new.

## Jobright alert emails (optional)
The Tier 1-2 lane reads Jobright's job-alert emails from your Gmail (recon/sources/gmail.py):
read-only Gmail API, only messages from JOBRIGHT_SENDER. Each link is followed by its redirects
alone; Recon never requests jobright.ai pages, logs into Jobright or reads its website.
Settings (local env file and GitHub secrets): GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET,
GMAIL_REFRESH_TOKEN (from `python -m recon.sources.gmail --auth`), JOBRIGHT_SENDER.

## Add a job by URL
The dashboard's "Add job" box queues a link; `python -m recon.add` (GitHub Actions lane "add",
started by the dashboard when GITHUB_DISPATCH_TOKEN is set in Vercel) reads, filters and judges it.

## Credits
Company board data from [Job Seek](https://github.com/colophon-group/jobseek)
(`apps/crawler/data/boards.csv`, MIT License, Copyright (c) 2025 Viktor Shcherbakov).
New-grad job listings from [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027)
(`.github/scripts/listings.json`, MIT License, Copyright (c) 2025 Vansh Bataviya) and contributors.
Company names (only) from [jobright-ai/2026-Software-Engineer-New-Grad](https://github.com/jobright-ai/2026-Software-Engineer-New-Grad),
to find which companies Recon should watch; Recon doesn't use its job links.

## Referral contacts (private)
Optional, gitignored: create config/referrals.csv with columns company,contact
