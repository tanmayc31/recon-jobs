import asyncio
import json

import httpx

from recon import judge
from recon.models import Job
from recon.store import Store

PROFILE = """Jane Doe | jane.doe@northeastern.edu | (617) 555-0142 | linkedin.com/in/janedoe
https://github.com/janedoe
MS CS, Northeastern (2024 - 2026). Python, TypeScript, AWS, Postgres. Built a RAG chatbot."""

GOOD = {"sponsorship": "unclear", "citizenship_or_clearance": False, "required_years": 2, "max_years_allowed": None,
        "is_software": True, "seniority": "junior", "fit_score": 82,
        "why": "Strong Python and AWS overlap. RAG project matches.", "missing_skills": ["Go"],
        "resume": "ai"}


def job(n, description="Build APIs in Python on AWS."):
    return Job(f"greenhouse:co:{n}", "Co", f"Software Engineer {n}", "NYC", "u", None, "greenhouse", 1,
               description)


def gemini(answer: dict):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]})


def setup(tmp_path, monkeypatch, jobs):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("CANDIDATE_PROFILE", PROFILE)
    monkeypatch.setattr(judge, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    s = Store(tmp_path / "t.db")
    for j in jobs:                    # one at a time so first_seen_at differs: newest last
        s.upsert_many([(j, "match", None, None, "new")])
        s.execute("UPDATE jobs SET first_seen_at=? WHERE job_id=?", (f"2026-11-0{j.job_id[-1]}", j.job_id))
    s.commit()
    return s


def row(s, job_id):
    return s.execute("SELECT decision, reason, fit_score, ai_why, ai_missing, ai_resume, ai_scored_at"
                     " FROM jobs WHERE job_id=?", (job_id,)).fetchone()


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
    # Harvey New Grad: "less than 18 months of professional experience" -> 1
    assert judge.veto(dict(GOOD, required_years=None, max_years_allowed=1)) == "ai: experience cap"
    assert judge.veto(dict(GOOD, max_years_allowed=2)) == "ai: experience cap"   # "0-2 years"
    assert judge.veto(dict(GOOD, max_years_allowed=0)) == "ai: experience cap"
    assert judge.veto(dict(GOOD, max_years_allowed=3)) is None


def test_scores_newest_first_and_vetoes_become_skips(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1), job(2), job(3, description="")])
    sent = []

    def handler(request):
        sent.append(request)
        body = json.loads(request.content)
        text = body["contents"][0]["parts"][0]["text"]
        # job 2 is newer, so it goes first; job 3 has no description, so it isn't sent
        return gemini(GOOD if "Engineer 2" in text else dict(GOOD, sponsorship="no", fit_score=60))

    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(handler)))
    assert len(sent) == 2
    assert "Engineer 2" in json.loads(sent[0].content)["contents"][0]["parts"][0]["text"]
    for r in sent:
        assert r.headers["x-goog-api-key"] == "test-key" and "test-key" not in str(r.url)
        body = json.loads(r.content)
        assert "jane.doe" not in r.content.decode() and "555-0142" not in r.content.decode()
        assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert row(s, "greenhouse:co:2")[:6] == ("match", None, 82, GOOD["why"], "Go", "ai")
    assert row(s, "greenhouse:co:1")[:3] == ("skip", "ai: no sponsorship", 60)
    assert row(s, "greenhouse:co:3")[6] is None                       # unjudged


def test_429_backs_off_once_then_stops(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1), job(2), job(3)])
    monkeypatch.setattr(judge, "MAX_WAIT", 0)
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return gemini(GOOD)
        return httpx.Response(429, json={"error": {"code": 429, "details": [
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}]}})

    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(handler)))
    assert len(calls) == 3                         # job 3 ok, job 2: 429, retry 429, stop
    assert row(s, "greenhouse:co:3")[2] == 82
    assert row(s, "greenhouse:co:2")[6] is None and row(s, "greenhouse:co:1")[6] is None


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


def test_bad_answer_is_left_for_next_run(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1)])
    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}))))
    assert row(s, "greenhouse:co:1")[6] is None


def test_ci_prints_counts_only(tmp_path, monkeypatch, capsys):
    setup(tmp_path, monkeypatch, [job(1)])
    monkeypatch.setenv("CI", "true")
    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(lambda r: gemini(GOOD))))
    out = capsys.readouterr().out
    assert "1 judged" in out and "Software Engineer" not in out and "Python" not in out


def test_ai_veto_survives_recheck(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1)])
    s.save_scores([("greenhouse:co:1", dict(GOOD, sponsorship="no"), "ai: no sponsorship")])
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


def test_experience_cap_is_saved_and_vetoes(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch, [job(1)])
    asyncio.run(judge.run(limit=10, pace=0, transport=httpx.MockTransport(
        lambda r: gemini(dict(GOOD, required_years=None, max_years_allowed=1)))))
    assert row(s, "greenhouse:co:1")[:2] == ("skip", "ai: experience cap")
    assert s.execute("SELECT ai_max_years FROM jobs").fetchone()[0] == 1
