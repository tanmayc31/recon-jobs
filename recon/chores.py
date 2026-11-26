"""Timed jobs, started by the lanes cron-job.org triggers (GitHub's own schedule runs hours late or
not at all). Each lane run asks which chores are due by the clock; a due chore is claimed in the
database, so it runs once per period whichever trigger gets there first. GitHub's schedule stays as a
backup: by then the chore is usually claimed, and it does nothing.

    weekly recheck     Monday from 04:00 UTC (Sunday night US): each lane once with --recheck;
                       Workday a second time from 08:00 (one run reaches ~2/3 of its companies,
                       and rotation starts the second with the ones the first missed)
    open check         daily from 10:00 UTC (early morning US): New, Backlog and Later
    best open check    every 3 hours: Best bets and New

    python -m recon.chores --lane 1-2     prints key=true/false lines for $GITHUB_OUTPUT
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from recon.env import load_env
from recon.store import Store

KEYS = ["recheck_12", "recheck_other", "recheck_workday", "open_check", "open_check_best"]


def week_start(t: datetime, hour: int) -> datetime:
    """The latest Monday `hour`:00 UTC at or before t."""
    monday = (t - timedelta(days=t.weekday())).replace(hour=hour, minute=0, second=0, microsecond=0)
    return monday if monday <= t else monday - timedelta(days=7)


def day_start(t: datetime, hour: int) -> datetime:
    d = t.replace(hour=hour, minute=0, second=0, microsecond=0)
    return d if d <= t else d - timedelta(days=1)


def slot_start(t: datetime, hours: int = 3) -> datetime:
    return t.replace(hour=t.hour - t.hour % hours, minute=0, second=0, microsecond=0)


def due(store: Store, lane: str, t: datetime) -> dict[str, bool]:
    """Claims and returns the chores this lane run should do. lane "all": GitHub's backup schedule."""
    at = t.isoformat(timespec="seconds")
    claim = lambda name, since: store.claim(name, since.isoformat(timespec="seconds"), at)
    out = dict.fromkeys(KEYS, False)
    lanes = ["1-2", "3-other", "3-workday"] if lane == "all" else [lane]
    for name, key in [("1-2", "recheck_12"), ("3-other", "recheck_other")]:
        if name in lanes:
            out[key] = claim(f"recheck:{name}", week_start(t, 4))
    if "3-workday" in lanes:
        out["recheck_workday"] = (claim("recheck:3-workday", week_start(t, 4))
                                  or (week_start(t, 8) > week_start(t, 4)   # this Monday's 08:00 has passed
                                      and claim("recheck:3-workday-2", week_start(t, 8))))
    if lane in ("1-2", "all"):   # the 30-minute lane: on time to the half hour
        out["open_check"] = claim("open-check", day_start(t, 10))
        out["open_check_best"] = claim("open-check-best", slot_start(t))
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--lane", required=True, choices=["1-2", "3-other", "3-workday", "add", "all"])
    lane = p.parse_args().lane
    load_env()
    try:
        out = due(Store(url=os.environ.get("DATABASE_URL")), lane, datetime.now(timezone.utc))
    except Exception as e:   # never block a lane: no chores this time, the next run claims them
        print(f"chores: {type(e).__name__}", file=sys.stderr)
        out = dict.fromkeys(KEYS, False)
    print("\n".join(f"{k}={'true' if v else 'false'}" for k, v in out.items()))


if __name__ == "__main__":
    main()
