"""When market-data jobs run. Read by the worker, and by System status for
the next run time (the web process never runs them)."""
from typing import Callable, List, NamedTuple

from apscheduler.triggers.cron import CronTrigger

TIMEZONE = "America/New_York"


class MdJob(NamedTuple):
    id: str
    label: str
    trigger: Callable[[], CronTrigger]


def _membership_trigger() -> CronTrigger:
    # The funds publish the previous session's holdings overnight; morning
    # runs on Tuesday to Saturday pick up Monday to Friday.
    return CronTrigger(day_of_week="tue-sat", hour=7, minute=0, timezone=TIMEZONE)


def _seed_trigger() -> CronTrigger:
    return CronTrigger(hour=6, minute=45, timezone=TIMEZONE)


MD_JOBS: List[MdJob] = [
    MdJob("md_seed_holdings", "Market data: held securities", _seed_trigger),
    MdJob("md_index_membership", "Market data: index membership", _membership_trigger),
]
