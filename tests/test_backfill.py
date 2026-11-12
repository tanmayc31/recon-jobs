import asyncio

from recon import backfill
from recon.models import Job
from recon.store import Store

GOOD = "Build backend services in Python and SQL. 1+ years of experience."


def job(n, description="", title="Software Engineer II", company="Co"):
    return Job(f"greenhouse:co:{n}", company, title, "New York, NY", f"https://example.com/jobs/{n}", None,
               "greenhouse", 1, description)


def test_fills_descriptions_and_applies_the_description_rules(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = Store(tmp_path / "t.db")
    # saved before descriptions were stored: matches with no description
    s.upsert_many([(job(1), "match", None, None, "backlog"), (job(2), "match", None, None, "new"),
                   (job(3), "match", None, None, "backlog"), (job(4, GOOD), "match", None, None, "new"),
                   (job(5, company="Gone Inc"), "match", None, None, "backlog")])
    s.commit()
    monkeypatch.setattr(backfill, "Store", lambda url=None: Store(tmp_path / "t.db", url))
    monkeypatch.setattr(backfill, "load_companies", lambda: [
        {"company": "Co", "ats": "greenhouse", "slug": "co", "tier": "1"}])
    asked = {}

    async def fetch(client, company):
        asked["known"] = company["known"]
        return [job(1, GOOD),                                                    # now a described match
                job(2, "Python APIs. U.S. citizenship is required for this role."),   # real blocker -> skip
                job(4, GOOD)]                                                     # job 3: no longer listed
    monkeypatch.setitem(backfill.SOURCES, "greenhouse", type("Fake", (), {"fetch": staticmethod(fetch)}))

    counts = asyncio.run(backfill.run(gap=0))
    assert asked["known"] == {"greenhouse:co:4"}            # only the undescribed jobs get detail requests
    assert (counts["filled_match"], counts["filled_skip"], counts["not_listed_anymore"], counts["company_gone"]) \
        == (1, 1, 1, 1)
    rows = {r[0]: r[1:] for r in Store(tmp_path / "t.db").execute(
        "SELECT job_id, decision, reason, status, description FROM jobs").fetchall()}
    assert rows["greenhouse:co:1"] == ("match", None, "backlog", GOOD)
    assert rows["greenhouse:co:2"][:3] == ("skip", "citizenship/clearance", "new")   # status kept
    assert rows["greenhouse:co:3"] == ("match", None, "backlog", None)              # left as is
    assert "skip: citizenship/clearance: 1" in capsys.readouterr().out
