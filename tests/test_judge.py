import asyncio
import json
import re

import httpx

from recon import judge
from recon.models import Job
from recon.store import Store

PROFILE = """Jane Doe | jane.doe@northeastern.edu | (617) 555-0142 | linkedin.com/in/janedoe
https://github.com/janedoe
MS CS, Northeastern (2024 - 2026). Python, TypeScript, AWS, Postgres. Built a RAG chatbot."""

# overall = 0.5 * 80 + 0.3 * 90 + 0.2 * 75 = 82
GOOD = {"sponsorship": "unclear", "citizenship_or_clearance": False, "required_years": 2, "max_years_allowed": None,
        "is_software": True, "seniority": "junior", "skills_match": 80, "level_fit": 90, "domain_fit": 75,
        "why": "Strong Python and AWS overlap. RAG project matches.", "missing_skills": ["Go"],
        "resume": "ai"}


def job(n, description="Build APIs in Python on AWS."):
    return Job(f"greenhouse:co:{n}", "Co", f"Software Engineer {n}", "NYC", "u", None, "greenhouse", 1,
               description)


def gemini(answers: list):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answers)}]}}]})


def asked(request) -> list[str]:
    """job_ids in a request's prompt, in order."""
    return re.findall(r"^job_id: (\S+)$", json.loads(request.content)["contents"][0]["parts"][0]["text"], re.M)


def answering(answer=lambda job_id: GOOD, sent=None):
    """Mock Gemini: answers every job in the batch with answer(job_id) (None: leave it out)."""
    def handler(request):
        if sent is not None:
            sent.append(request)
        return gemini([dict(a, job_id=i) for i in asked(request) if (a := answer(i)) is not None])
    return httpx.MockTransport(handler)


def setup(tmp_path, monkeypatch, jobs):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("CANDIDATE_PROFILE", PROFILE)
    monkeypatch.setattr(judge, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    s = Store(tmp_path / "t.db")
    for j in jobs:                    # one at a time so first_seen_at differs: newest last
        s.upsert_many([(j, "match", None, None, "new")])
        s.execute("UPDATE jobs SET first_seen_at=? WHERE job_id=?", (f"2026-11-{int(j.job_id.split(':')[-1]):02}", j.job_id))
    s.commit()
    return s


def row(s, job_id):
    return s.execute("SELECT decision, reason, fit_score, ai_why, ai_missing, ai_resume, ai_scored_at,"
                     " ai_skills, ai_level, ai_domain FROM jobs WHERE job_id=?", (job_id,)).fetchone()


def test_profile_contact_info_is_removed():
    out = judge.scrub(PROFILE)
    for secret in ["jane.doe@", "555-0142", "linkedin.com", "github.com"]:
        assert secret not in out
    assert "2024 - 2026" in out and "RAG chatbot" in out


def test_vetoes():
    assert judge.veto(GOOD) is None
    assert judge.veto(dict(GOOD, sponsorship="no")) == "ai: no sponsorship"
    assert judge.veto(dict(GOOD, citizenship_or_clearance=True)) == "ai: citizenship/clearance"
    assert judge.veto(dict(GOOD, is_software=False)) == "ai: not software"
    assert judge.veto(dict(GOOD, required_years=5)) == "ai: 5+ years"
    assert judge.veto(dict(GOOD, required_years=4)) is None
    assert judge.veto(dict(GOOD, required_years=None)) is None

    # experience caps are flagged, never vetoed: "less than 18 months" -> 1, "0-2 years" -> 2
    for cap, flag in [(0, "exp cap: max 0 yrs"), (1, "exp cap: max 1 yr"), (2, "exp cap: max 2 yrs"),
                      (3, None), (None, None)]:
        assert judge.veto(dict(GOOD, max_years_allowed=cap)) is None
        assert judge.cap_flag(dict(GOOD, max_years_allowed=cap)) == flag


def test_rubric_overall_is_the_weighted_sum_of_the_parts():
    assert judge.clean(dict(GOOD, job_id="x"))["fit_score"] == 82
    a = judge.clean(dict(GOOD, job_id="x", skills_match=140, level_fit=-5, domain_fit=100))
    assert (a["skills_match"], a["level_fit"], a["fit_score"]) == (100, 0, 70)    # clamped to 0-100 first


def test_malformed_answers_are_rejected():
    ok = dict(GOOD, job_id="x")
    assert judge.clean(ok)
    for bad in [dict(ok, skills_match="high"), dict(ok, level_fit=True), dict(ok, seniority="principal"),
                dict(ok, why="  "), {k: v for k, v in ok.items() if k != "domain_fit"}, "not an object"]:
        assert judge.clean(bad) is None


def test_scores_newest_first_in_one_batch_and_vetoes_become_skips(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1), job(2), job(3, description="")])
    sent = []
    # job 2 is newer, so it goes first; job 3 has no description, so it isn't sent
    asyncio.run(judge.run(limit=10, pace=0, transport=answering(
        lambda i: GOOD if i.endswith(":2") else dict(GOOD, sponsorship="no", skills_match=60, level_fit=60,
                                                    domain_fit=60), sent)))
    assert len(sent) == 1 and asked(sent[0]) == ["greenhouse:co:2", "greenhouse:co:1"]
    r = sent[0]
    assert r.headers["x-goog-api-key"] == "test-key" and "test-key" not in str(r.url)
    assert "jane.doe" not in r.content.decode() and "555-0142" not in r.content.decode()
    config = json.loads(r.content)["generationConfig"]
    assert config["responseMimeType"] == "application/json" and config["responseSchema"]["type"] == "ARRAY"
    assert row(s, "greenhouse:co:2")[:6] == ("match", None, 82, GOOD["why"], "Go", "ai")
    assert row(s, "greenhouse:co:2")[7:] == (80, 90, 75)                # the rubric parts
    assert row(s, "greenhouse:co:1")[:3] == ("skip", "ai: no sponsorship", 60)
    assert row(s, "greenhouse:co:3")[6] is None                       # unjudged


def test_batches_of_six(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch, [job(n) for n in range(1, 15)])
    sent = []
    asyncio.run(judge.run(limit=20, pace=0, transport=answering(sent=sent)))
    assert [len(asked(r)) for r in sent] == [6, 6, 2]
    assert asked(sent[0])[0] == "greenhouse:co:14"                    # newest first
    assert "14 judged of 14 queued in 3 requests" in capsys.readouterr().out


def test_429_backs_off_once_then_stops(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(n) for n in range(1, 6)])
    monkeypatch.setattr(judge, "MAX_WAIT", 0)
    monkeypatch.setattr(judge, "BATCH", 2)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return gemini([dict(GOOD, job_id=i) for i in asked(request)])
        return httpx.Response(429, json={"error": {"code": 429, "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]}})

    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(handler)))
    assert len(calls) == 3                         # jobs 5+4 ok, jobs 3+2: 429, retry 429, stop
    assert row(s, "greenhouse:co:5")[2] == 82 and row(s, "greenhouse:co:4")[2] == 82
    assert all(row(s, f"greenhouse:co:{n}")[6] is None for n in (1, 2, 3))


def test_daily_quota_stops_without_retry(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, [job(1), job(2)])
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(429, json={"error": {"code": 429, "details": [
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
             "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}})

    assert asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(handler))) == []
    assert len(calls) == 1


def test_bad_response_leaves_the_whole_batch_for_next_run(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1), job(2)])
    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))))
    assert row(s, "greenhouse:co:1")[6] is None and row(s, "greenhouse:co:2")[6] is None


def test_one_malformed_answer_is_retried_alone_next_run(tmp_path, monkeypatch, capsys):
    s = setup(tmp_path, monkeypatch, [job(1), job(2), job(3), job(4)])
    # job 3's score is text, job 2 is missing, plus an answer for a job that wasn't asked
    # and a repeat of job 4: only jobs 4 and 1 count
    def handler(request):
        return gemini([dict(GOOD, job_id="greenhouse:co:4"), dict(GOOD, job_id="greenhouse:co:3", skills_match="high"),
                       dict(GOOD, job_id="greenhouse:co:1"), dict(GOOD, job_id="greenhouse:co:9"),
                       dict(GOOD, job_id="greenhouse:co:4", skills_match=0)])
    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(handler)))
    out = capsys.readouterr().out
    assert "2 judged of 4 queued in 1 requests" in out and "2 failed" in out
    assert row(s, "greenhouse:co:4")[2] == 82 and row(s, "greenhouse:co:1")[2] == 82   # first answer for 4 kept
    assert row(s, "greenhouse:co:3")[6] is None and row(s, "greenhouse:co:2")[6] is None

    sent = []
    asyncio.run(judge.run(limit=10, pace=0, transport=answering(sent=sent)))
    assert [asked(r) for r in sent] == [["greenhouse:co:3", "greenhouse:co:2"]]   # only the two left over
    assert row(s, "greenhouse:co:3")[2] == 82


def test_ci_prints_counts_only(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch, [job(1)])
    monkeypatch.setenv("CI", "true")
    asyncio.run(judge.run(limit=10, pace=0, transport=answering()))
    out = capsys.readouterr().out
    assert "1 judged" in out and "Software Engineer" not in out and "Python" not in out


def test_ai_veto_survives_recheck(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1)])
    s.save_scores([("greenhouse:co:1", judge.clean(dict(GOOD, job_id="greenhouse:co:1", sponsorship="no")),
                    "ai: no sponsorship")])
    s.upsert_many([(job(1), "match", None, None, "new")])            # rules still say match
    assert row(s, "greenhouse:co:1")[:2] == ("skip", "ai: no sponsorship")


def test_skipped_jobs_store_no_description(tmp_path):
    s = Store(tmp_path / "t.db")
    s.upsert_many([(job(1), "match", None, None, "new"), (job(2), "skip", "no sponsorship", None, "new")])
    descs = dict(s.execute("SELECT job_id, description FROM jobs").fetchall())
    assert descs == {"greenhouse:co:1": "Build APIs in Python on AWS.", "greenhouse:co:2": None}


def test_queue_new_first_then_backlog_by_tier(tmp_path):
    s = Store(tmp_path / "t.db")
    rows = [  # (n, status, tier, first_seen_at)
        (1, "backlog", 3, "2026-11-09"), (2, "backlog", 1, "2026-11-01"), (3, "backlog", 1, "2026-11-05"),
        (4, "new", 3, "2026-11-02"), (5, "new", 1, "2026-11-08"), (6, "applied", 1, "2026-11-09")]
    for n, status, tier, seen in rows:
        j = job(n)
        j.tier = tier
        s.upsert_many([(j, "match", None, None, status)])
        s.execute("UPDATE jobs SET first_seen_at=? WHERE job_id=?", (seen, j.job_id))
    assert [r["job_id"][-1] for r in s.unscored(10)] == ["5", "4", "3", "2", "1", "6"]


def test_experience_cap_is_saved_and_stays_a_match(tmp_path, monkeypatch, capsys):
    s = setup(tmp_path, monkeypatch, [job(1)])
    asyncio.run(judge.run(limit=10, pace=0, transport=answering(
        lambda i: dict(GOOD, required_years=None, max_years_allowed=1))))
    assert row(s, "greenhouse:co:1")[:2] == ("match", None)
    assert "FLAG exp cap: max 1 yr" in capsys.readouterr().out
    assert s.execute("SELECT ai_max_years FROM jobs").fetchone()[0] == 1


def test_my_rating_survives_a_recheck(tmp_path):
    s = Store(tmp_path / "t.db")
    s.upsert_many([(job(1), "match", None, None, "new")])
    s.execute("UPDATE jobs SET my_rating=-1, rated_at='2026-11-11T12:00:00+00:00'")
    s.upsert_many([(job(1), "match", None, None, "new")])
    assert s.execute("SELECT my_rating, rated_at FROM jobs").fetchone() == (-1, "2026-11-11T12:00:00+00:00")
