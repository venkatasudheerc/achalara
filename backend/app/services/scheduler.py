"""APScheduler background jobs: the daily syncs and the daily capture.

Each market day's holdings, cash and total can only be recorded on the day, so
the capture job also runs once at start-up if the day has not been captured —
a server that was down at the scheduled time still gets the day, provided it
comes up before the next one.
"""
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.database import SessionLocal
from app.services import alerts, run_log
from app.services.daily_sync import run_all_enabled_syncs
from app.services.connection_service import run_all_brokerage_syncs, run_link_check
from app.services.daily_capture_service import DailyCaptureService, run_daily_capture
from app.services.index_history_service import IndexHistoryService
from app.services.price_history_service import PriceHistoryService

logger = logging.getLogger(__name__)

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


@run_log.tracked("daily_brokerage_sync")
def _brokerage_job_wrapper() -> None:
    """Open a DB session, sync mapped brokerage accounts, close session."""
    db = SessionLocal()
    try:
        run_all_brokerage_syncs(db)
    except Exception as exc:
        logger.error(f"Unhandled error in brokerage sync job: {exc}")
    finally:
        db.close()


@run_log.tracked("brokerage_link_check")
def _link_check_wrapper() -> None:
    """Ask the source whether each brokerage link is still sharing data."""
    db = SessionLocal()
    try:
        run_link_check(db)
    except Exception as exc:
        logger.error(f"Unhandled error in brokerage link check: {exc}")
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


@run_log.tracked("daily_capture")
def _capture_job_wrapper() -> None:
    """Record the day: prices first, then each account's holdings and totals."""
    db = SessionLocal()
    try:
        try:
            PriceHistoryService(db).backfill()
        except Exception as exc:
            db.rollback()
            logger.error(f"Price history top-up failed: {exc}")
        run_daily_capture(db)
    except Exception as exc:
        logger.error(f"Unhandled error in daily capture job: {exc}")
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


@run_log.tracked("capture_catch_up")
def _catch_up_wrapper() -> None:
    """Capture now if the latest market day has not been recorded yet."""
    db = SessionLocal()
    try:
        needed = DailyCaptureService(db).needs_capture()
    except Exception as exc:
        logger.error(f"Could not check whether a capture is due: {exc}")
        needed = False
    finally:
        db.close()
    if needed:
        logger.info("Latest market day not captured yet — capturing now")
        _capture_job_wrapper()


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return

    _scheduler = BackgroundScheduler()
    # Run at 4 PM UTC daily (matches ROADMAP default)
    _scheduler.add_job(
        _job_wrapper,
        CronTrigger(hour=16, minute=0),
        id="daily_sheets_sync",
        replace_existing=True,
    )
    # Brokerage transactions are a day-delayed daily batch, so once a day is
    # as fresh as the source gets. Runs after the sheets job.
    _scheduler.add_job(
        _brokerage_job_wrapper,
        CronTrigger(hour=16, minute=30),
        id="daily_brokerage_sync",
        replace_existing=True,
    )
    # A brokerage ends a session without notice; every six hours is soon
    # enough to say so, and well inside what the source allows.
    _scheduler.add_job(
        _link_check_wrapper,
        CronTrigger(hour="*/6", minute=10),
        id="brokerage_link_check",
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
    # After the US close (21:00 UTC) and the brokerage's own daily refresh.
    _scheduler.add_job(
        _capture_job_wrapper,
        CronTrigger(day_of_week="mon-fri", hour=23, minute=30),
        id="daily_capture",
        replace_existing=True,
    )
    # The indices' own bars, once the session's figures are final.
    _scheduler.add_job(
        _index_history_wrapper,
        CronTrigger(day_of_week="mon-fri", hour=23, minute=45),
        id="index_history",
        replace_existing=True,
    )
    # Once, shortly after start-up: catch the day if the schedule was missed.
    _scheduler.add_job(
        _catch_up_wrapper,
        "date",
        run_date=datetime.now(timezone.utc) + timedelta(seconds=30),
        id="capture_catch_up",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "APScheduler started — sheets sync 16:00 UTC, brokerage sync 16:30 UTC, "
        "daily capture 23:30 UTC and index history 23:45 UTC on weekdays"
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
