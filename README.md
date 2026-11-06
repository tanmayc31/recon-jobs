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

Sources: application links in the SimplifyJobs New-Grad-Positions and Summer2026-Internships
READMEs, and Job Seek's board list (Greenhouse, Lever, Ashby and Workday boards only).
A company's first run is saved as backlog, not shown as new.

## Credits
Company board data from [Job Seek](https://github.com/colophon-group/jobseek)
(`apps/crawler/data/boards.csv`, MIT License, Copyright (c) 2025 Viktor Shcherbakov).

## Referral contacts (private)
Optional, gitignored: create config/referrals.csv with columns company,contact
