from datetime import datetime, timezone

from recon import chores
from recon.store import Store


def at(s):   # UTC
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_periods():
    assert chores.week_start(at("2026-11-23T03:59:00"), 4) == at("2026-11-16T04:00:00")   # Monday before 04:00
    assert chores.week_start(at("2026-11-23T04:00:00"), 4) == at("2026-11-23T04:00:00")
    assert chores.week_start(at("2026-11-26T21:00:00"), 4) == at("2026-11-23T04:00:00")   # Thursday
    assert chores.day_start(at("2026-11-26T09:30:00"), 10) == at("2026-11-25T10:00:00")
    assert chores.slot_start(at("2026-11-26T14:30:00")) == at("2026-11-26T12:00:00")


def test_each_chore_runs_once_per_period_whoever_comes_first(tmp_path):
    s = Store(tmp_path / "t.db")
    # Monday 04:30: the 1-2 lane (cron-job.org) gets the recheck and both open checks
    first = chores.due(s, "1-2", at("2026-11-23T04:30:00"))
    assert first == {"recheck_12": True, "recheck_other": False, "recheck_workday": False,
                     "open_check": True, "open_check_best": True}
    # 05:00: the next 1-2 run does none of them; GitHub's late backup schedule only the lanes not yet rechecked
    assert not any(chores.due(s, "1-2", at("2026-11-23T05:00:00")).values())
    backup = chores.due(s, "all", at("2026-11-23T05:10:00"))
    assert backup == {"recheck_12": False, "recheck_other": True, "recheck_workday": True,
                      "open_check": False, "open_check_best": False}
    # 06:00: a new 3-hour slot; 10:00: a new day for the daily open check
    assert chores.due(s, "1-2", at("2026-11-23T06:00:00"))["open_check_best"]
    assert chores.due(s, "1-2", at("2026-11-23T10:00:00"))["open_check"]
    # the next Monday, everything again
    assert chores.due(s, "1-2", at("2026-11-30T04:00:00"))["recheck_12"]


def test_workday_rechecks_twice(tmp_path):
    s = Store(tmp_path / "t.db")
    assert chores.due(s, "3-workday", at("2026-11-23T05:00:00"))["recheck_workday"]       # first pass
    assert not chores.due(s, "3-workday", at("2026-11-23T05:30:00"))["recheck_workday"]   # before 08:00
    assert chores.due(s, "3-workday", at("2026-11-23T08:00:00"))["recheck_workday"]       # second pass
    assert not chores.due(s, "3-workday", at("2026-11-23T11:00:00"))["recheck_workday"]
    assert not chores.due(s, "3-workday", at("2026-11-23T11:00:00"))["open_check"]        # the 1-2 lane's job


def test_a_broken_database_never_blocks_a_lane(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")
    monkeypatch.setattr("sys.argv", ["chores", "--lane", "1-2"])
    chores.main()
    assert capsys.readouterr().out.split() == [f"{k}=false" for k in chores.KEYS]
