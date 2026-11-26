import asyncio
import time
from collections import Counter

from recon import main
from recon.models import Job
from recon.store import Store, now


def job(n, description="Build backend services in Python and SQL. 1+ years of experience."):
    return Job(f"greenhouse:co:{n}", "Co", "Software Engineer II", "New York, NY",
               f"https://example.com/jobs/{n}", None, "greenhouse", 1, description)


def run_once(tmp_path, monkeypatch, jobs, tiers=None, recheck=False, ats=None):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": "Jane Doe"}])

    async def fetch(client, sems, company, deadline, outcome):
        return jobs
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    return asyncio.run(main.run(tiers, recheck, ats))


def statuses(tmp_path):
    return dict(Store(tmp_path / "t.db").execute("SELECT job_id, status FROM jobs").fetchall())


def test_first_run_is_backlog_then_new(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    assert run_once(tmp_path, monkeypatch, [job(1)]) == []        # company's first run
    assert "1 backlog matches" in capsys.readouterr().out
    assert len(run_once(tmp_path, monkeypatch, [job(1), job(2)])) == 1
    assert statuses(tmp_path) == {"greenhouse:co:1": "backlog", "greenhouse:co:2": "new"}


def test_failed_fetch_is_not_a_first_run(tmp_path, monkeypatch):
    run_once(tmp_path, monkeypatch, None)                         # source errored
    run_once(tmp_path, monkeypatch, [job(1)])                     # first real run: backlog
    assert statuses(tmp_path) == {"greenhouse:co:1": "backlog"}


def test_ci_logs_counts_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CI", "true")
    run_once(tmp_path, monkeypatch, [])
    assert len(run_once(tmp_path, monkeypatch, [job(1)])) == 1
    out = capsys.readouterr().out
    assert "Checked 1 companies (all tiers), 1 jobs in" in out
    assert "Software Engineer II" not in out and "example.com" not in out and "Jane Doe" not in out


def test_local_shows_jobs(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [])
    run_once(tmp_path, monkeypatch, [job(1)])
    out = capsys.readouterr().out
    assert "Software Engineer II" in out and "Jane Doe" in out


def test_tiers_filter_companies(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1)], tiers={3})          # Co is Tier 1
    assert "Checked 0 companies (tiers 3), 0 jobs" in capsys.readouterr().out


def verdicts(tmp_path):
    return dict(Store(tmp_path / "t.db").execute("SELECT job_id, decision FROM jobs").fetchall())


def test_known_jobs_reuse_verdict_unless_recheck(tmp_path, monkeypatch):
    run_once(tmp_path, monkeypatch, [])
    run_once(tmp_path, monkeypatch, [job(1)])
    assert verdicts(tmp_path) == {"greenhouse:co:1": "match"}

    # a new rule would now block it...
    monkeypatch.setattr(main.eligibility, "check", lambda text, title="": (False, "citizenship/clearance", None, []))
    run_once(tmp_path, monkeypatch, [job(1)])
    assert verdicts(tmp_path) == {"greenhouse:co:1": "match"}       # ...but known jobs aren't re-judged
    run_once(tmp_path, monkeypatch, [job(1)], recheck=True)
    assert verdicts(tmp_path) == {"greenhouse:co:1": "skip"}        # --recheck applies the new rule
    assert statuses(tmp_path) == {"greenhouse:co:1": "new"}         # status untouched


def test_recheck_tells_adapters_nothing_is_known(tmp_path, monkeypatch):
    seen_known = []

    async def fetch(client, sems, company, deadline, outcome):
        seen_known.append(len(company["known"]))
        return [job(1)]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": ""}])
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    for recheck in (False, False, True):
        asyncio.run(main.run(None, recheck))
    assert seen_known == [0, 1, 0]


def test_ats_filter(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1)], ats={"workday"})    # Co is Greenhouse
    assert "Checked 0 companies (all tiers, workday), 0 jobs" in capsys.readouterr().out


def test_busy_workday_lane_does_not_block_others(monkeypatch):
    # Every Workday slot is stuck until the Greenhouse company runs: with one shared
    # pool this would deadlock; with separate lanes Greenhouse still gets a slot.
    unblock = asyncio.Event()

    async def slow_workday(client, company):
        await unblock.wait()
        return []

    async def greenhouse(client, company):
        unblock.set()
        return []
    monkeypatch.setattr(main, "SOURCES", {"workday": type("W", (), {"fetch": staticmethod(slow_workday)}),
                                          "greenhouse": type("G", (), {"fetch": staticmethod(greenhouse)})})
    monkeypatch.setattr(main, "PARALLEL", {"workday": 1, "other": 1})

    async def go():
        sems = {lane: asyncio.Semaphore(n) for lane, n in main.PARALLEL.items()}
        outcome = Counter()
        cos = [{"company": "W1", "ats": "workday"}, {"company": "W2", "ats": "workday"},
               {"company": "G", "ats": "greenhouse"}]
        far = time.monotonic() + 60
        await asyncio.wait_for(asyncio.gather(*(main.fetch_company(None, sems, c, far, outcome) for c in cos)), 2)
        return outcome
    assert asyncio.run(go())["ok"] == 3


def test_empty_description_is_unverified_and_retried(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [])
    # Real case: Genworth "Software Engineer - Java Development" was judged while its
    # Workday detail request failed (429), so it matched on an empty description
    assert run_once(tmp_path, monkeypatch, [job(1, description="")]) == []
    assert "Unverified (no description, retried next run): 1" in capsys.readouterr().out
    assert verdicts(tmp_path) == {"greenhouse:co:1": "unverified"}

    known = []

    async def fetch(client, sems, company, deadline, outcome):
        known.append(dict(company["known"]))
        return [job(1, description="This role is not eligible for employment visa sponsorship.")]
    monkeypatch.setattr(main, "fetch_company", fetch)
    asyncio.run(main.run())
    assert known == [{}]                                           # not "known": fetched again
    assert verdicts(tmp_path) == {"greenhouse:co:1": "skip"}       # judged once it has a description


def test_connection_not_held_during_fetch(tmp_path, monkeypatch):
    # Supabase drops idle connections: the one used for reading must be closed before fetching
    opened = []

    class Tracked(Store):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.closed = False
            opened.append(self)

        def close(self):
            self.closed = True
            super().close()

    async def fetch(client, sems, company, deadline, outcome):
        assert all(s.closed for s in opened)          # nothing open while fetching
        return [job(1)]
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": ""}])
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Tracked(tmp_path / "t.db", url))
    asyncio.run(main.run())
    assert len(opened) == 2 and all(s.closed for s in opened)


def test_first_run_jobs_posted_in_the_last_3_days_are_new(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    today = datetime.now(timezone.utc).date()   # fresh() compares in UTC
    fresh, old, workday, undated = job(1), job(2), job(3), job(4)
    fresh.posted_at = (today - timedelta(days=3)).isoformat() + "T15:04:11Z"   # Lever/Ashby ISO date
    old.posted_at = (today - timedelta(days=4)).isoformat()
    workday.posted_at = "Posted 2 Days Ago"                                    # real Workday text
    # job 4: no posted date from the site -> stays backlog
    run_once(tmp_path, monkeypatch, [fresh, old, workday, undated])            # company's first run
    assert statuses(tmp_path) == {"greenhouse:co:1": "new", "greenhouse:co:2": "backlog",
                                  "greenhouse:co:3": "new", "greenhouse:co:4": "backlog"}


def test_existing_fresh_backlog_moves_to_new(tmp_path):
    s = Store(tmp_path / "t.db")
    seen = "2026-11-10T08:00:00+00:00"
    rows = [  # (n, posted_at from the site, posted_on as stored)
        (1, "2026-11-07", "2026-11-07"),                 # 3 days before first seen: new
        (2, "2026-11-06", "2026-11-06"),                 # 4 days: stays backlog
        (3, "Posted 30+ Days Ago", "2026-10-11"),        # Workday bound: stays
        (4, None, None)]                                 # no date: stays
    for n, posted_at, posted_on in rows:
        j = job(n)
        j.posted_at = posted_at
        s.upsert_many([(j, "match", None, None, "backlog")])
        s.execute("UPDATE jobs SET first_seen_at=?, posted_on=? WHERE job_id=?", (seen, posted_on, j.job_id))
    assert s.fresh_backlog_to_new() == ["greenhouse:co:1"]
    s.commit()
    assert statuses(tmp_path) == {"greenhouse:co:1": "new", "greenhouse:co:2": "backlog",
                                  "greenhouse:co:3": "backlog", "greenhouse:co:4": "backlog"}


def closed(tmp_path):
    return dict(Store(tmp_path / "t.db").execute("SELECT job_id, closed_at IS NOT NULL FROM jobs").fetchall())


def test_gone_two_runs_in_a_row_closes_and_reappearing_reopens(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1), job(2), job(3)])
    s = Store(tmp_path / "t.db")
    s.execute("UPDATE jobs SET status='applied' WHERE job_id='greenhouse:co:3'")
    s.commit()
    run_once(tmp_path, monkeypatch, [job(1)])                        # 2 and 3 missing once: still open
    assert closed(tmp_path) == {"greenhouse:co:1": 0, "greenhouse:co:2": 0, "greenhouse:co:3": 0}
    run_once(tmp_path, monkeypatch, [job(1)])                        # missing twice: closed
    assert closed(tmp_path) == {"greenhouse:co:1": 0, "greenhouse:co:2": 1, "greenhouse:co:3": 1}
    assert statuses(tmp_path)["greenhouse:co:3"] == "applied"        # Applied stays Applied (badge only)
    assert "Closed (gone from the board 2 runs in a row): 2, reopened: 0" in capsys.readouterr().out
    run_once(tmp_path, monkeypatch, [job(1), job(2)])                # 2 is back
    assert closed(tmp_path)["greenhouse:co:2"] == 0


def test_seen_again_resets_the_miss_count(tmp_path, monkeypatch):
    for listing in ([job(1), job(2)], [job(1)], [job(1), job(2)], [job(1)]):   # gone, back, gone: never 2 in a row
        run_once(tmp_path, monkeypatch, listing)
    assert closed(tmp_path)["greenhouse:co:2"] == 0


def test_partial_failed_or_empty_fetch_closes_nothing(tmp_path, monkeypatch):
    run_once(tmp_path, monkeypatch, [job(1), job(2)])
    for _ in range(2):
        run_once(tmp_path, monkeypatch, None)                        # fetch failed
        run_once(tmp_path, monkeypatch, [])                          # empty board: more often a glitch
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1", "referral": "", "partial": True}])   # cut off (Workday cap)

    async def fetch(client, sems, company, deadline, outcome):
        return [job(1)]
    monkeypatch.setattr(main, "fetch_company", fetch)
    for _ in range(2):
        asyncio.run(main.run())
    assert closed(tmp_path) == {"greenhouse:co:1": 0, "greenhouse:co:2": 0}


def test_recheck_moves_matches_that_fail_new_title_or_location_rules_to_skipped(tmp_path, monkeypatch):
    intern = Job("greenhouse:co:7", "Co", "NVIDIA 2027 Internships: Software Engineering", "Santa Clara, CA",
                 "https://example.com/jobs/7", None, "greenhouse", 1, "Build software in Python.")
    spain = Job("greenhouse:co:8", "Co", "Forward Deployed Engineer", "ESP - MD - LAS ROZAS",
                "https://example.com/jobs/8", None, "greenhouse", 1, "Build software in Python.")
    run_once(tmp_path, monkeypatch, [job(1)])
    s = Store(tmp_path / "t.db")   # saved as matches under the old rules
    s.upsert_many([(intern, "match", None, None, "new"), (spain, "match", None, None, "backlog")])
    s.commit()
    run_once(tmp_path, monkeypatch, [job(1), intern, spain])                 # normal run: verdicts kept
    assert dict(s.execute("SELECT job_id, decision FROM jobs").fetchall())["greenhouse:co:7"] == "match"
    run_once(tmp_path, monkeypatch, [job(1), intern, spain], recheck=True)
    rows = {r[0]: r[1:] for r in Store(tmp_path / "t.db").execute("SELECT job_id, decision, reason, status FROM jobs")}
    assert rows["greenhouse:co:7"] == ("skip", "intern/co-op", "new")
    assert rows["greenhouse:co:8"] == ("skip", "non-US location", "backlog")
    assert rows["greenhouse:co:1"][0] == "match"


def test_a_new_job_that_is_already_gone_never_shows_in_new(tmp_path, monkeypatch, capsys):
    from recon import linkcheck
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1)])                         # first run: backlog

    async def check_open(jobs, transport=None):
        return [(j, j["job_id"] != "greenhouse:co:3") for j in jobs]  # job 3: API says gone
    monkeypatch.setattr(linkcheck, "check_open", check_open)
    shown = run_once(tmp_path, monkeypatch, [job(1), job(2), job(3)])
    assert [j.job_id for j, _, _ in shown] == ["greenhouse:co:2"]
    assert closed(tmp_path)["greenhouse:co:3"] == 1
    assert "Not shown in New (gone when checked): 1" in capsys.readouterr().out


def test_job_list_rows_are_saved_once_and_marked_from_list(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    google = Job("list:id-3", "Google", "Software Engineer, Early Career", "Mountain View, CA",
                 "https://www.google.com/about/careers/x", now()[:10], "list", 2,
                 "Software Engineer, Early Career at Google, Mountain View, CA.", source_ids="id-3", via="list")
    seen = {}
    monkeypatch.setattr(main, "load_companies", lambda: [
        {"company": "New-Grad-2027 list", "ats": "listings", "slug": "vanshb03/New-Grad-2027", "tier": "2", "referral": ""}])

    async def fetch(client, sems, company, deadline, outcome):
        seen["list_ids"] = set(company["list_ids"])
        return [google]
    monkeypatch.setattr(main, "fetch_company", fetch)
    monkeypatch.setattr(main, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    asyncio.run(main.run())
    asyncio.run(main.run())
    assert seen["list_ids"] == {"id-3"}                                  # second run: not resolved again
    row = Store(tmp_path / "t.db").execute("SELECT via, status, decision FROM jobs").fetchone()
    assert row == ("list", "new", "match")                               # posted recently: New on the first run


def test_the_same_posting_from_two_lists_is_kept_once():
    def listed(n, url, company="Google", title="Software Engineer", location="Mountain View, CA"):
        return Job(f"list:{n}", company, title, location, url, None, "list", 2, "x", source_ids=n, via="list")
    pairs = [("vansh", listed("v1", "https://careers.google.com/jobs/1")),
             ("simplify", listed("s1", "https://careers.google.com/jobs/1")),              # same link
             ("speedy", listed("sa-1", "https://www.google.com/about/careers/1")),       # same company/title/place
             ("speedy", listed("sa-2", "https://www.google.com/about/careers/2", title="Software Engineer II")),
             ("Stripe", job(1))]                                                         # boards: untouched
    assert [j.job_id for _, j in main.one_copy(pairs)] == ["list:v1", "list:sa-2", "greenhouse:co:1"]


def test_missed_once_and_its_site_says_gone_closes_at_once(tmp_path, monkeypatch, capsys):
    # Northwestern Mutual (Workday Tier 3, every 6 h): gone from the board at 14:09, closed only at
    # 20:09 after a second miss. Now the first miss asks the site's API.
    from recon import linkcheck
    monkeypatch.delenv("CI", raising=False)
    run_once(tmp_path, monkeypatch, [job(1), job(2)])
    asked = []

    async def gone_now(jobs, transport=None):
        asked.extend(j["job_id"] for j in jobs)
        return ["greenhouse:co:2"]
    monkeypatch.setattr(linkcheck, "gone_now", gone_now)
    run_once(tmp_path, monkeypatch, [job(1)])
    assert asked == ["greenhouse:co:2"] and closed(tmp_path)["greenhouse:co:2"] == 1
    assert "Closed (missing from the board, and its site says gone): 1" in capsys.readouterr().out


def test_rotation_starts_with_the_companies_waited_on_longest(tmp_path):
    # Tier 3 Workday reached ~350 of 635 companies a run in random order: some waited a day
    companies = [{"company": c} for c in ["A", "B", "C", "D"]]
    last = {"A": "2026-11-23T17:00:00+00:00", "B": "2026-11-23T11:00:00+00:00", "C": "2026-11-23T14:00:00+00:00"}
    assert [c["company"] for c in main.rotate(companies, last)] == ["D", "B", "C", "A"]   # never scanned first


def test_a_run_records_which_companies_it_started(tmp_path, monkeypatch):
    s = Store(tmp_path / "t.db")
    s.mark_runs(["A", "B"])
    s.commit()
    first = s.last_runs()
    assert set(first) == {"A", "B"}
    s.mark_runs(["A"])
    s.commit()
    assert s.last_runs()["A"] >= first["A"] and s.last_runs()["B"] == first["B"]


def test_a_job_list_surfacing_an_untracked_board_adds_it(tmp_path, monkeypatch, capsys):
    # Handshake's FDE came through Simplify on jobs.ashbyhq.com/handshake before Recon scanned Handshake
    from recon.models import Job
    lst = Job("list:sa-1", "Handshake", "Forward Deployed Engineer", "San Francisco, CA",
              "https://jobs.ashbyhq.com/handshake/52be2db3-794d-466e-b3be-cae5d1ab5232", "2026-11-20", "ashby", 2,
              "Build things.", source_ids="sa-1", via="list")
    old = Job("list:sa-2", "Mach9", "Software Engineer - 3D Graphics", "Pittsburgh, PA",
              "https://jobs.ashbyhq.com/mach9/abc", "2020-01-01", "ashby", 2, "Build things.", source_ids="sa-2", via="list")
    tracked = Job("list:sa-3", "Co", "Software Engineer", "New York, NY", "https://boards.greenhouse.io/co/jobs/1",
                  None, "greenhouse", 2, "Build things.", source_ids="sa-3", via="list")
    run_once(tmp_path, monkeypatch, [lst, old, tracked])
    found = Store(tmp_path / "t.db").found_boards()
    assert found == [{"company": "Handshake", "ats": "ashby", "slug": "handshake", "tier": "2"},
                     {"company": "Mach9", "ats": "ashby", "slug": "mach9", "tier": "3"}]   # no new-grad post in 30 days
    assert "New boards from job lists: 2 (Tier 2: 1)" in capsys.readouterr().out
    # the next run scans them like companies.csv rows
    assert {c["company"] for c in main.with_found(main.load_companies(), found)} == {"Co", "Handshake", "Mach9"}


def test_restricted_boards_and_aggregators_are_not_added():
    from recon import discover
    from recon.models import Job
    def lj(url, co="X"):
        return Job("list:1", co, "Software Engineer", "Austin, TX", url, None, "list", 2, via="list")
    jobs = [lj("https://thehartford.wd5.myworkdayjobs.com/Careers_Restricted/job/x", "The Hartford"),
            lj("https://jobs.lever.co/jobgether/123", "Jobgether"),
            lj("https://sands.wd1.myworkdayjobs.com/referral_sands_careers/job/y", "Las Vegas Sands")]
    assert discover.found_in(jobs, [], "2026-11-26") == []
