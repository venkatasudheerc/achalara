"""APScheduler background jobs: the Plaid refresh, price history, sheet syncs,
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
from app.services import alerts, run_log
from app.services.daily_sync import run_all_enabled_syncs
from app.services.index_history_service import IndexHistoryService
from app.services.plaid_refresh_service import run_plaid_refresh
from app.services.price_history_service import PriceHistoryService

logger = logging.getLogger(__name__)

MARKET_TIMEZONE = "America/New_York"

_scheduler: BackgroundScheduler | None = None


@run_log.tracked("daily_sheets_sync")
def _job_wrapper() -> None:
    """Open a DB session, run syncs, close session."""
    db = SessionLocal()
    try:
        run_all_enabled_syncs(db)
    except Exception as exc:
        logger.error(f"Unhandled error in daily sync job: {exc}")
    finally:
        db.close()


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


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    # The sheets sync: 4 PM UTC daily
    _scheduler.add_job(
        _job_wrapper,
        CronTrigger(hour=16, minute=0),
        id="daily_sheets_sync",
        replace_existing=True,
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
    # After the US close (21:00 UTC): the day's closes for everything held.
    _scheduler.add_job(
        _price_history_wrapper,
        CronTrigger(day_of_week="mon-fri", hour=23, minute=30),
        id="price_history",
        replace_existing=True,
    )
    # Plaid: early each weekday morning a balance is where the previous day
    # ended, so Tuesday to Saturday record Monday to Friday. A weekend's
    # movements arrive in Monday's record; a recorded day is never rewritten.
    _scheduler.add_job(
        _plaid_refresh_wrapper,
        CronTrigger(day_of_week="tue-sat", hour=6, minute=30, timezone=MARKET_TIMEZONE),
        id="plaid_refresh",
        replace_existing=True,
    )
    _scheduler.add_job(
        _index_history_wrapper,
        index_history_trigger(),
        id="index_history",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "APScheduler started — sheets sync 16:00 UTC, "
        "price history 23:30 UTC on weekdays, Plaid refresh 06:30 US Eastern Tue-Sat, "
        "index history 22:00 and 06:00 US Eastern"
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
        logger.info("APScheduler stopped")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
