"""APScheduler background jobs: the Plaid refresh, price history, ticker changes,
index history and the status watch.

The Plaid refresh records each account's previous day early in the morning
(``plaid_refresh_service``); price history tops up the closes the rebuild values
holdings with.
"""
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from app.db.database import SessionLocal
from app.services import alerts, job_history, run_log
from app.services.index_history_service import IndexHistoryService
from app.services.plaid_refresh_service import run_plaid_refresh
from app.services.market_pattern_copy import refresh as refresh_market_pattern
from app.services.sector_copy import refresh as refresh_sectors
from app.services.ticker_changes import run_ticker_changes
from app.services.price_history_service import PriceHistoryService

logger = logging.getLogger(__name__)

MARKET_TIMEZONE = "America/New_York"

_scheduler: BackgroundScheduler | None = None


def _status_watch_wrapper() -> None:
    """Message the advisor about anything that has started or stopped needing a look."""
    db = SessionLocal()
    try:
        alerts.run_status_watch(db)
    except Exception as exc:
        logger.error(f"Unhandled error in the status watch: {exc}")
    finally:
        db.close()


@run_log.tracked("price_history")
def _price_history_wrapper() -> None:
    """Top up daily closes for every security held, which the rebuild values with."""
    db = SessionLocal()
    try:
        PriceHistoryService(db).backfill()
    except Exception as exc:
        logger.error(f"Price history top-up failed: {exc}")
    finally:
        db.close()


@run_log.tracked("plaid_refresh")
def _plaid_refresh_wrapper() -> None:
    """Bring every Plaid login up to date and record the day before."""
    db = SessionLocal()
    try:
        run_plaid_refresh(db)
    except Exception as exc:
        logger.error(f"Unhandled error in Plaid refresh job: {type(exc).__name__}")
    finally:
        db.close()


@run_log.tracked("ticker_changes")
def _ticker_changes_wrapper() -> None:
    """Record the ticker changes market data saw, and rebuild what they touch."""
    db = SessionLocal()
    try:
        run_ticker_changes(db)
    except Exception as exc:
        logger.error(f"Unhandled error in ticker changes job: {type(exc).__name__}")
    finally:
        db.close()


@run_log.tracked("sector_copy")
def _sector_copy_wrapper() -> None:
    """Copy market data's sector for each held symbol into the app."""
    db = SessionLocal()
    try:
        refresh_sectors(db)
    except Exception as exc:
        logger.error(f"Unhandled error in sector copy job: {type(exc).__name__}")
    finally:
        db.close()


@run_log.tracked("market_pattern_copy")
def _market_pattern_copy_wrapper() -> None:
    """Copy market data's S&P 500 record for this week and month into the app."""
    db = SessionLocal()
    try:
        refresh_market_pattern(db)
    except Exception as exc:
        logger.error(f"Unhandled error in market pattern copy job: {type(exc).__name__}")
    finally:
        db.close()


@run_log.tracked("index_history")
def _index_history_wrapper() -> None:
    """Add the day's bar to each market index kept for research."""
    db = SessionLocal()
    try:
        IndexHistoryService(db).refresh()
    except Exception as exc:
        logger.error(f"Unhandled error in index history job: {exc}")
    finally:
        db.close()


def index_history_trigger() -> OrTrigger:
    """When the indices' own bars are read: twice for each session.

    At 10pm US Eastern the session's close is in, so a comparison made that
    evening has the day. The source goes on completing the day's record (its
    volume, and now and then one index's bar) for hours after that, so the
    6am run the next morning reads it again once it is final.
    """
    return OrTrigger(
        [
            CronTrigger(
                day_of_week="mon-fri", hour=22, minute=0, timezone=MARKET_TIMEZONE
            ),
            CronTrigger(
                day_of_week="tue-sat", hour=6, minute=0, timezone=MARKET_TIMEZONE
            ),
        ]
    )


# Every scheduled job: its id, what it runs, when, and how long after a missed
# time it may still be made up (``catch_up``). A closing price or an index bar
# is the same whenever it is read, so those are made up for most of a day. The
# Plaid refresh reads each balance as where the day before ended, which holds
# only until the market opens at 9:30: three hours after its 6:30 run.
def _schedule() -> list:
    return [
        # After the US close (21:00 UTC): the day's closes for everything held.
        (
            "price_history",
            _price_history_wrapper,
            CronTrigger(day_of_week="mon-fri", hour=23, minute=30),
            timedelta(hours=12),
        ),
        # Plaid: early each weekday morning a balance is where the previous day
        # ended, so Tuesday to Saturday record Monday to Friday. A weekend's
        # movements arrive in Monday's record; a recorded day is never rewritten.
        (
            "plaid_refresh",
            _plaid_refresh_wrapper,
            CronTrigger(
                day_of_week="tue-sat", hour=6, minute=30, timezone=MARKET_TIMEZONE
            ),
            timedelta(hours=3),
        ),
        # After market data's identifiers job (5 AM) and before the Plaid refresh.
        (
            "ticker_changes",
            _ticker_changes_wrapper,
            CronTrigger(hour=6, minute=15, timezone=MARKET_TIMEZONE),
            timedelta(hours=12),
        ),
        # After market data's classification run (10:30 PM the evening before).
        (
            "sector_copy",
            _sector_copy_wrapper,
            CronTrigger(hour=6, minute=20, timezone=MARKET_TIMEZONE),
            timedelta(hours=12),
        ),
        # After market data's index levels (6:15 AM Eastern).
        (
            "market_pattern_copy",
            _market_pattern_copy_wrapper,
            CronTrigger(hour=6, minute=25, timezone=MARKET_TIMEZONE),
            timedelta(hours=12),
        ),
        (
            "index_history",
            _index_history_wrapper,
            index_history_trigger(),
            timedelta(hours=6),
        ),
    ]


def _keep_run(job_id: str, run: dict) -> None:
    """Store a finished run, so the next start knows when the job last ran."""
    db = SessionLocal()
    try:
        job_history.record(db, job_id, run)
    finally:
        db.close()


def catch_up(now: datetime | None = None) -> list:
    """Run each job whose time fell while the server was down, if still in time.

    Called once shortly after start-up. A deploy or a restart at 6:30 in the
    morning would otherwise lose that day's Plaid record for good: the next
    run records the day after. Returns the ids of the jobs it ran.
    """
    now = now or datetime.now(timezone.utc)
    ran = []
    for job_id, work, trigger, grace in _schedule():
        if run_log.is_running(job_id):
            continue
        db = SessionLocal()
        try:
            last = job_history.last_run(db, job_id)
        except Exception as exc:
            logger.warning(
                "Could not read the last run of %s: %s", job_id, type(exc).__name__
            )
            continue
        finally:
            db.close()
        due = job_history.missed(trigger, now, last and last["started_at"], grace)
        if due is None:
            continue
        logger.warning(
            "%s was due at %s while the server was not running; running it now.",
            job_id,
            due.isoformat(timespec="minutes"),
        )
        work()
        ran.append(job_id)
    return ran


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    run_log.keep_runs(_keep_run)
    # A job that cannot start on the second (the process busy, the machine
    # asleep) still runs within the hour, once, instead of being skipped.
    _scheduler = BackgroundScheduler(
        job_defaults={"misfire_grace_time": 3600, "coalesce": True}
    )
    # Alerts: look every ten minutes, and once shortly after start-up.
    _scheduler.add_job(
        _status_watch_wrapper,
        "interval",
        minutes=10,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
        id="status_watch",
        replace_existing=True,
    )
    for job_id, work, trigger, _grace in _schedule():
        _scheduler.add_job(work, trigger, id=job_id, replace_existing=True)
    # Once, two minutes after start: whatever was due while the server was down.
    _scheduler.add_job(
        catch_up,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(minutes=2),
        id="catch_up",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "APScheduler started: price history 23:30 UTC on weekdays, ticker changes "
        "06:15 and Plaid refresh 06:30 US Eastern (Plaid Tue-Sat), index history "
        "22:00 and 06:00 US Eastern; a run missed while down is made up at start"
    )


def job_times() -> dict:
    """When each scheduled job next runs, by job id; empty when not running."""
    if _scheduler is None:
        return {}
    return {job.id: job.next_run_time for job in _scheduler.get_jobs()}


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        run_log.keep_runs(None)
        logger.info("APScheduler stopped")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
