import asyncio

import httpx

from recon import prep
from recon.models import Job
from recon.store import Store

CHECKLIST = "Likely topics\n- Kafka consumer groups\nWhat to review from your experience\n- The event pipeline\nQuestions to ask\n- On-call?"


def setup(tmp_path, monkeypatch, state="queued"):
    monkeypatch.setattr(prep, "Store", lambda url=None: Store(tmp_path / "t.db"))   # never a real database
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("CANDIDATE_PROFILE", "Backend engineer, 3 years, Kafka, Go. me@example.com")
    s = Store(tmp_path / "t.db")
    s.upsert_many([(Job("greenhouse:stripe:1", "Stripe", "Software Engineer, Payments", "Seattle, WA", "u", None,
                        "greenhouse", 1, "Build payment APIs with Kafka."), "match", None, None, "new")])
    s.execute("UPDATE jobs SET status = 'applied' WHERE job_id = ?", ("greenhouse:stripe:1",))
    s.execute("INSERT INTO applications (job_id, stage, prep_state) VALUES (?, 'interview', ?)", ("greenhouse:stripe:1", state))
    s.commit()
    return s


def test_writes_the_checklist_for_queued_preps(tmp_path, monkeypatch, capsys):
    s = setup(tmp_path, monkeypatch)
    sent = []

    def h(req):
        sent.append(req)
        assert req.headers["x-goog-api-key"] == "k" and "k" not in str(req.url)   # key never in the URL
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": CHECKLIST}]}}]})
    assert asyncio.run(prep.run(httpx.MockTransport(h))) == {"written": 1, "failed": 0}
    body = sent[0].content.decode()
    assert "STAGE: interview" in body and "Build payment APIs" in body and "me@example.com" not in body
    prep_text, state = s.execute("SELECT prep, prep_state FROM applications").fetchone()
    assert prep_text == CHECKLIST and state == "done"
    assert capsys.readouterr().out.strip() == "AI prep: 1 written, 0 failed"   # counts only


def test_a_failure_keeps_your_edited_prep(tmp_path, monkeypatch):
    s = setup(tmp_path, monkeypatch)
    s.execute("UPDATE applications SET prep = 'my notes'")
    s.commit()
    assert asyncio.run(prep.run(httpx.MockTransport(lambda r: httpx.Response(500)))) == {"written": 0, "failed": 1}
    assert s.execute("SELECT prep, prep_state FROM applications").fetchone() == ("my notes", "failed")


def test_nothing_queued_sends_nothing(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch, state="done")
    calls = []
    asyncio.run(prep.run(httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500))))
    assert calls == []
