# Recon
Intel on new tech roles, the minute they drop.

## v1 step 1

## Setup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

## 1. Verify company slugs
python -m recon.detect stripe databricks palantir openai ramp notion

## 2. Run the bot
python -m recon.main

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

## Referral contacts (private)
Optional, gitignored: create config/referrals.csv with columns company,contact
