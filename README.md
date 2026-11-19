# Recon
Intel on new tech roles, the minute they drop.

## Run your own Recon
For someone who forks this repo. Recon polls company job boards, filters for the roles you want,
scores them against your profile with Gemini, and shows them on a private dashboard. It never
applies to jobs. Everything below fits in free tiers.

### Accounts you need
| Account | What for |
|---|---|
| GitHub | your fork, and GitHub Actions to run the scans |
| Supabase | the Postgres database (jobs, applications, sponsors) |
| Vercel | the dashboard (web/, Next.js) |
| Google AI Studio | a Gemini API key for the AI judge and AI prep |
| cron-job.org | triggers the scans on time (GitHub's own cron is unreliable) |

### Setup, in order
1. **Fork** the repo. Keep it private if you'll add private contacts or edit the company list
   with anything personal; secrets are never in the repo either way.
2. **Supabase**: create a project. Copy the connection string from Connect, "Transaction pooler"
   (port 6543), with your database password filled in. That's `DATABASE_URL`. Recon creates its
   tables on the first run.
3. **Local run** (optional, but the fastest way to see it work):
   `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`, then
   create a file named `.env` in the repo root (it's gitignored) with `DATABASE_URL=...` (and
   `GEMINI_API_KEY=...` for the judge). Load the H-1B sponsor table once:
   `python -m recon.sponsors --load`.
4. **Your profile**: copy `config/profile.example.md` to `config/profile.md` (gitignored) and
   rewrite it for yourself (see "Your profile" below).
5. **GitHub secrets** (Settings → Secrets and variables → Actions → Secrets):
   - `DATABASE_URL`: the Supabase string from step 2
   - `GEMINI_API_KEY`: from Google AI Studio (Get API key)
   - `CANDIDATE_PROFILE`: the whole text of your profile.md
   - optional, only for the Jobright email source: `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`,
     `GMAIL_REFRESH_TOKEN`, `JOBRIGHT_SENDER`
6. **GitHub variables** (same page, Variables tab): leave `RECON_PERSONAL_LISTS` unset. See
   "Job lists" below.
7. **Vercel**: Add New → Project → import your fork, Root Directory `web`. Environment variables:
   - `DATABASE_URL`: the same string
   - `DASHBOARD_PASSWORD`: the password you'll log in with (pick a long one)
   - optional `GITHUB_DISPATCH_TOKEN`: a fine-grained GitHub token for your fork with
     Actions: read and write, so "Add job" and "AI prep" start right away instead of at the next
     scan
   - optional `GITHUB_REPO`: `owner/name` of your fork (defaults to the repo Vercel deployed)
8. **cron-job.org**: create a fine-grained GitHub token for your fork (Actions: read and write),
   then one job per lane, each a POST to
   `https://api.github.com/repos/<you>/<repo>/actions/workflows/recon.yml/dispatches` with headers
   `Authorization: Bearer <token>`, `Accept: application/vnd.github+json` and body
   `{"ref":"main","inputs":{"lane":"1-2"}}`. Lanes: `1-2` every 30 minutes, `3-other` every 3
   hours, `3-workday` every 6 hours. The weekly recheck and the daily open check run on GitHub's
   own schedule.
9. **Companies**: `config/companies.csv` lists the boards (company, ats, slug, tier). Tier 1-2 run
   every 30 minutes; Tier 3 less often. Add or remove rows; `python -m recon.detect <slug>` tells
   you which board a company uses, and "Add a company" below has the formats.

### Your profile
Plain text the AI judge reads to score each job (fit 0-100, which resume, what's missing):
your status (degree, graduation date, start date), work authorization, years of experience,
target roles and locations, skills, experience and projects with numbers, and which resume to
use for what. `config/profile.example.md` is a template. Emails, phone numbers and links are
stripped before anything is sent to Gemini. Keep the GitHub secret and your local file in sync.

### Change the filters for your own search
| You want | Change |
|---|---|
| Other locations | `recon/filters.py`: `US`, `NON_US`, `US_STATE`. Several scanners also ask the site for US jobs only (Oracle, Google, Apple, ByteDance/TikTok, SmartRecruiters `country=us`, Eightfold `location`, SuccessFactors `locationsearch`, Workday's US facet); change those too. |
| Another level | `recon/filters.py`: `EXCLUDE` (senior, staff, lead, levels 3-9, ...) and `STUDENT` (interns); `recon/eligibility.py`: `MAX_YEARS`; `recon/judge.py`: `MY_YEARS`, `MAX_YEARS`; `recon/roles.py`: `level`. |
| No sponsorship needed | `recon/eligibility.py`: drop the "no sponsorship" entry in `BLOCKERS`; `recon/judge.py`: `veto` (the `sponsorship == "no"` line); `web/lib/db.ts`: Best bets requires an H-1B sponsor (`sp.filings > 0`). Citizenship/clearance stays a gate unless you're a citizen. |
| Other roles | `recon/filters.py`: `ROLE` (what the title must name) and `ENG` (must be an engineer/developer); `recon/roles.py`: `role_type` for the dashboard's role filter. |
| Your graduation dates | `recon/eligibility.py`: `YOU_GRADUATE`, `EARLIEST_START`, `MIN_CAP_YEARS`. |
| What counts as a Best bet | `web/lib/db.ts`: `MAX_BEST_YEARS`, `MIN_BEST_FIT`, `PER_COMPANY`. |

Every filter change gets a test with a real title or location in `tests/`; after changing rules,
run the workflow once with "recheck" on so old jobs are judged again.

### Job lists
The MIT-licensed vanshb03/New-Grad-2027 list runs in every fork. The Simplify and speedyapply
lists have no license and are for the original owner's personal use only: they're off unless
the `RECON_PERSONAL_LISTS` variable is `1`, and a fork should leave it off.

### Test that it works
1. `python -m pytest -q`: every test passes (no network, no database).
2. `python -m recon.main --tiers 1`: a local scan of Tier 1 prints the companies checked and the
   matches found, and fills your database.
3. GitHub → Actions → recon → Run workflow (lane `1-2`): the run finishes green; the judge job
   scores the new matches.
4. Open your Vercel URL, log in, and check that Best bets, New and Backlog have jobs.
5. `python -m recon.linkcheck`: opens a sample of Apply links in a browser (needs
   `pip install playwright && python -m playwright install chromium`) and reports any that don't
   open a real, open job.

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

### Imported from career-ops (Nov 2026)
40 Tier 3 boards from the owner's career-ops company research, each tested before adding.
VERIFIED (board confirmed by career-ops): U.S. Bank, Argonne National Laboratory, Guidewire, Rocket,
SEI, Remitly, FICO, Baker Tilly, Axos, Lennar, Etched, Mercor, Clark Construction, Fluidstack,
Assembled, Mountain America Credit Union, Tessera Labs, CreatorIQ, Smithfield Foods, Camunda,
Tutor Intelligence, Reducto, Ascensus, Sailor Health, BeautyHealth (Hydrafacial), Joyful Health,
SHI, Brown & Brown. LIKELY (board guessed, works when tested): Nike, Zoom, Fractal Analytics, GSK,
MedImpact, WGU, Omnissa, Unum, GE Appliances (Haier), Wayve, Temporal. Also Sun Life Campus
(Sun Life's campus board), and Home Depot moved from its Canada board to the US one.

## Job lists
The Tier 1-2 lane also reads [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027)
(recon/sources/listings.py): jobs from companies we can't scan directly. Each row's link is
resolved to the real posting; Greenhouse/Lever/Ashby/Workday postings are read through their APIs,
anything else is judged on its page or on the list's title, company and location ("from list").
With `RECON_PERSONAL_LISTS=1` (the owner's deployment only; off in a fork) it also reads
[SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions)
and [speedyapply/2027-SWE-College-Jobs](https://github.com/speedyapply/2027-SWE-College-Jobs) for
the owner's personal use only: they have no license, so nothing from them is committed here. Their
rows live only in Recon's private database, simplify.jobs links are skipped, and recon.discover
and recon.sponsors (which write committed files) read only the MIT list. A job any source
already has (same job ID, link, or company + title) isn't added again, nor any job at a company
whose whole board Recon reads itself.
A company's first run is saved as backlog, not shown as new.

## Eightfold
recon/sources/eightfold.py scans Eightfold career sites (Microsoft, Qualcomm, Ericsson, Boston
Scientific, Dexcom, Infineon, Eaton, MTSI, Netflix, Starbucks) through their public search API;
companies.csv slug is host|domain, e.g. apply.careers.microsoft.com|microsoft.com. Netflix is on
Eightfold's older API (/api/apply/v2), used automatically when a site answers "PCSX is not enabled".

## Oracle HCM
recon/sources/oracle.py scans Oracle Recruiting Cloud career sites (JPMorgan Chase, Oracle, Goldman
Sachs, Ford, American Express, Albertsons (Safeway), Fortinet, Perficient, Cummins, Nokia, Citizens,
Staples, DTCC, BNY, Honeywell, Marriott International, Sherwin-Williams) through the public API their
career sites call; companies.csv slug is host|site, e.g. jpmc.fa.oraclecloud.com|CX_1001. Every US
posting is read (200 a page), so a run's listing is complete and closes jobs that are gone.

## Meta
recon/sources/meta.py reads metacareers.com through the same public requests its careers site makes,
signed out: the job search page (for its anonymous request token), its job search query (every
open job in one answer), and each new matching job's page (JobPosting JSON-LD). If Meta answers
with a login or security check, the run fails with Blocked and Recon doesn't work around it.

## Google
recon/sources/google.py reads google.com/about/careers through the same public request its "next
page" button makes, signed out (a batchexecute RPC): every US job, 20 a page, with its
responsibilities and qualifications, so no per-job requests. The open check reads the job's page. If
Google answers with a block or its "unusual traffic" page, the run fails with Blocked and Recon
doesn't work around it.

## SmartRecruiters
recon/sources/smartrecruiters.py reads SmartRecruiters companies (ServiceNow, AbbVie, Nagarro, ASML,
Tech Mahindra) through the public Posting API: every US posting, then descriptions for
new matches; companies.csv slug is the identifier in careers.smartrecruiters.com/<slug>. A gone
posting answers 404 (or active: false).

## Apple
recon/sources/apple.py reads jobs.apple.com through the same public requests its careers site makes,
signed out: its Teams suggestions, its CSRF token and search (US, software subteams), and each new
match's details. Details take 3-60 s each, so a run fetches what fits in 4 minutes and the rest
follow in the next runs (saved as unverified meanwhile). A block or challenge stops the run.

## iCIMS
recon/sources/icims.py reads iCIMS career sites (Charles Schwab, ICE, Liberty Mutual, United
Wholesale Mortgage, Cotiviti) through their public job search pages and each new match's job page
(JobPosting JSON-LD); companies.csv slug is the site's host, e.g. career-schwab.icims.com. A closed
job's page answers 410.

## ByteDance and TikTok
recon/sources/bytedance.py reads joinbytedance.com and lifeattiktok.com through the same public
requests the sites make (their filters for the US cities, their job search, with the header the
sites send): every US job with its description, no per-job requests. A job on both sites is one
job. The open check reads the job's page (an empty title when it's gone). Job lists add nothing
for companies whose whole board Recon reads itself (main.COMPLETE): lists retitle jobs ("New Grad
2027: ..." for "... - 2027 Start (PhD)").

## Avature
recon/sources/avature.py reads Avature career sites (Deloitte, Bloomberg) through their public job
search (keywords "software engineer" and "developer", paged the way the site pages) and each new
match's job page; companies.csv slug is the careers path, e.g. apply.deloitte.com/en_US/careers.
"Multiple Locations" cards get their locations from the job's page. Sites behind an AWS WAF
challenge (Delta, and IBM's job pages) aren't scanned: Recon doesn't work around a challenge.

## SuccessFactors
recon/sources/successfactors.py reads SuccessFactors Career Site Builder sites (EY) through their
public search: every US job, 25 a page, then each new match's page; companies.csv slug is the
site's base path, e.g. careers.ey.com/ey. A gone job's page redirects to /errorpage/. Not scanned:
SAP (Cloudflare challenge), American Airlines (Akamai block; results need JavaScript), and the
older SuccessFactors pages (Moody's, Yash).

## Jobright alert emails (off)
Not set up, and it stays off: Jobright's alert links lead to jobright.ai pages, which Recon never
reads, so the emails add nothing. Without the settings below the source does nothing.
When set up, the Tier 1-2 lane would read Jobright's job-alert emails from your Gmail (recon/sources/gmail.py):
read-only Gmail API, only messages from JOBRIGHT_SENDER. Each link is followed by its redirects
alone; Recon never requests jobright.ai pages, logs into Jobright or reads its website.
Settings (local env file and GitHub secrets): GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET,
GMAIL_REFRESH_TOKEN (from `python -m recon.sources.gmail --auth`), JOBRIGHT_SENDER.

## Application tracking
Apply remembers the job; coming back to the Recon tab asks "Did you apply?" (Yes: Applied with
today's date; Not interested: Skipped). Applied cards have a stage (Applied, Assessment, Interview,
Offer, Rejected, Ghosted, Withdrawn) with a dated timeline, optional details (notes, referral,
resume version, contact, link, deadline, follow-up), and at Assessment or Interview an "AI prep"
checklist written by recon/prep.py (the judge's Gemini key and profile, in GitHub Actions lane
"add") that you can edit. Stored in the `applications` and `application_events` tables;
jobs.status still drives the tabs.

## Add a job by URL
The dashboard's "Add job" box queues a link; `python -m recon.add` (GitHub Actions lane "add",
started by the dashboard when GITHUB_DISPATCH_TOKEN is set in Vercel) reads, filters and judges it.

## Credits
Company board data from [Job Seek](https://github.com/colophon-group/jobseek)
(`apps/crawler/data/boards.csv`, MIT License, Copyright (c) 2025 Viktor Shcherbakov).
New-grad job listings from [vanshb03/New-Grad-2027](https://github.com/vanshb03/New-Grad-2027)
(`.github/scripts/listings.json`, MIT License, Copyright (c) 2025 Vansh Bataviya) and contributors.
Job listings, for personal use only (no license; not redistributed, no data committed), from
[SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) (Simplify and
Coder Quad) and [speedyapply/2027-SWE-College-Jobs](https://github.com/speedyapply/2027-SWE-College-Jobs).
Company names (only) from [jobright-ai/2026-Software-Engineer-New-Grad](https://github.com/jobright-ai/2026-Software-Engineer-New-Grad),
to find which companies Recon should watch; Recon doesn't use its job links.

## Referral contacts (private)
Optional, gitignored: create config/referrals.csv with columns company,contact
