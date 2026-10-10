"""APScheduler background jobs: the daily Google Sheets and brokerage syncs."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.db.database import SessionLocal
from app.services.daily_sync import run_all_enabled_syncs
from app.services.connection_service import run_all_brokerage_syncs

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_wrapper() -> None:
    """Open a DB session, run syncs, close session."""
    db = SessionLocal()
    try:
        run_all_enabled_syncs(db)
    except Exception as exc:
        logger.error(f"Unhandled error in daily sync job: {exc}")
    finally:
        db.close()


def _brokerage_job_wrapper() -> None:
    """Open a DB session, sync mapped brokerage accounts, close session."""
    db = SessionLocal()
    try:
        run_all_brokerage_syncs(db)
    except Exception as exc:
        logger.error(f"Unhandled error in brokerage sync job: {exc}")
    finally:
        db.close()


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
    _scheduler.start()
    logger.info(
        "APScheduler started — sheets sync at 16:00 UTC, brokerage sync at 16:30 UTC"
    )


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
