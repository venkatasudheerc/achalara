"""When market-data jobs run. Read by the worker, and by System status for
the next run time (the web process never runs them)."""
from datetime import datetime, time
from typing import Callable, List, NamedTuple
from zoneinfo import ZoneInfo

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


def _identifiers_trigger() -> CronTrigger:
    # Before the market opens: new listings and ticker changes are in by then.
    return CronTrigger(hour=5, minute=0, timezone=TIMEZONE)


def _daily_closes_trigger() -> CronTrigger:
    # After the evening's last trade is settled; weekdays only.
    return CronTrigger(day_of_week="mon-fri", hour=20, minute=30, timezone=TIMEZONE)


def in_quiet_hours(now: datetime) -> bool:
    """8:30 AM to 6:00 PM Eastern on weekdays: no md job then, the client
    screens' live prices share the Webull key."""
    local = now.astimezone(ZoneInfo(TIMEZONE))
    return local.weekday() < 5 and time(8, 30) <= local.time() < time(18, 0)


def _classification_trigger() -> CronTrigger:
    # After the evening jobs; Saturday's run also refreshes older profiles.
    return CronTrigger(hour=22, minute=30, timezone=TIMEZONE)


MD_JOBS: List[MdJob] = [
    MdJob("md_seed_holdings", "Market data: held securities", _seed_trigger),
    MdJob("md_index_membership", "Market data: index membership", _membership_trigger),
    MdJob("md_identifiers", "Market data: identifiers", _identifiers_trigger),
    MdJob("md_daily_closes", "Market data: daily closes", _daily_closes_trigger),
    MdJob(
        "md_classification",
        "Market data: sectors and industries",
        _classification_trigger,
    ),
]
