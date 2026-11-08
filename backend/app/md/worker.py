"""The market-data worker: ``python -m app.md.worker``.

Runs in its own container from the same image as the backend, so hours-long
data jobs never share the web process. It does not run migrations; the
backend does, and the worker waits for it in compose.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from app.md.config import settings
from app.db.database import SessionLocal
from app.md.adjusted import prune_prices, run_adjusted_history
from app.md.levels import run_index_levels
from app.md.views import refresh_return_views
from app.md.classification import run_classification
from app.md.config import settings as md_settings
from app.md.closes import JOB as CLOSES_JOB, run_daily_closes
from app.md.database import MdSession
from app.md.identifiers import run_identifiers
from app.md.jobs import JobAlreadyRunning, close_abandoned, tracked_run
from app.md.membership import JOB as MEMBERSHIP_JOB, run_index_membership
from app.md.models import JobRun
from app.md.schedule import MD_JOBS, TIMEZONE, in_quiet_hours
from app.md.seed import seed_securities
from app.services.held_symbols import held_symbols

logging.basicConfig(
    level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("app.md.worker")


def _seed() -> None:
    # The one place both databases are open: the app's for the symbols it holds.
    app_db = SessionLocal()
    db = MdSession()
    try:
        with tracked_run(db, "md_seed_holdings") as run:
            run.rows_written = seed_securities(db, held_symbols(app_db), date.today())
            run.note = f"{run.rows_written} securities added"
    except JobAlreadyRunning:
        logger.info("Held-securities seeding is already running")
    except Exception:  # noqa: BLE001
        logger.exception("Held-securities seeding failed")
    finally:
        db.close()
        app_db.close()


def _membership() -> None:
    db = MdSession()
    try:
        outcome = run_index_membership(db)
        logger.info("Index membership: %s", outcome.summary())
    except JobAlreadyRunning:
        logger.info("Index membership is already running")
    except Exception:  # noqa: BLE001
        logger.exception("Index membership failed")
    finally:
        db.close()


def _identifiers() -> None:
    db = MdSession()
    try:
        logger.info("Identifiers: %s", run_identifiers(db, date.today()))
    except JobAlreadyRunning:
        logger.info("Identifiers job is already running")
    except Exception:  # noqa: BLE001
        logger.exception("Identifiers job failed")
    finally:
        db.close()


def _classification() -> None:
    db = MdSession()
    try:
        saturday = date.today().weekday() == 5
        logger.info(
            "Classification: %s", run_classification(db, date.today(), refresh=saturday)
        )
    except JobAlreadyRunning:
        logger.info("Classification job is already running")
    except Exception:  # noqa: BLE001
        logger.exception("Classification job failed")
    finally:
        db.close()


def _daily_closes() -> None:
    db = MdSession()
    try:
        logger.info("Daily closes: %s", run_daily_closes(db))
    except JobAlreadyRunning:
        logger.info("Daily closes are already being captured")
    except Exception:  # noqa: BLE001
        logger.exception("Daily closes failed")
    finally:
        db.close()


def _adjusted_history() -> None:
    db = MdSession()
    try:
        logger.info("Adjusted history: %s", run_adjusted_history(db))
    except JobAlreadyRunning:
        logger.info("Adjusted history is already being fetched")
    except Exception:  # noqa: BLE001
        logger.exception("Adjusted history failed")
    finally:
        db.close()


def _index_levels() -> None:
    db = MdSession()
    try:
        logger.info("Index levels: %s", run_index_levels(db))
    except JobAlreadyRunning:
        logger.info("Index levels are already being fetched")
    except Exception:  # noqa: BLE001
        logger.exception("Index levels failed")
    finally:
        db.close()


def _refresh_returns() -> None:
    db = MdSession()
    try:
        logger.info("Return tables: %s", refresh_return_views(db))
    except JobAlreadyRunning:
        logger.info("Return tables are already being refreshed")
    except Exception:  # noqa: BLE001
        logger.exception("Return tables refresh failed")
    finally:
        db.close()


def _prune() -> None:
    db = MdSession()
    try:
        logger.info(
            "History limit: %s",
            prune_prices(db, date.today(), md_settings.md_history_years),
        )
    except JobAlreadyRunning:
        logger.info("History limit is already being applied")
    except Exception:  # noqa: BLE001
        logger.exception("History limit failed")
    finally:
        db.close()


JOBS = {
    "md_seed_holdings": _seed,
    MEMBERSHIP_JOB: _membership,
    "md_identifiers": _identifiers,
    "md_classification": _classification,
    CLOSES_JOB: _daily_closes,
    "md_adjusted_closes": _adjusted_history,
    "md_index_levels": _index_levels,
    "md_prune_prices": _prune,
    "md_refresh_returns": _refresh_returns,
}


def _missed(job: str) -> bool:
    """Whether ``job`` has not succeeded in the last 20 hours."""
    db = MdSession()
    try:
        last = (
            db.query(JobRun.finished_at)
            .filter(JobRun.job == job, JobRun.outcome == "ok")
            .order_by(JobRun.finished_at.desc())
            .first()
        )
        return last is None or datetime.now(timezone.utc) - last[0] > timedelta(
            hours=20
        )
    finally:
        db.close()


def _close_abandoned() -> None:
    db = MdSession()
    try:
        closed = close_abandoned(db)
        if closed:
            logger.info("Closed %s run(s) left running by a stopped process", closed)
    finally:
        db.close()


def main() -> None:
    _close_abandoned()
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    for job in MD_JOBS:
        scheduler.add_job(
            JOBS[job.id], job.trigger(), id=job.id, coalesce=True, max_instances=1
        )
    # Catch up once after a restart, so a deploy at 7am does not lose the day.
    start = datetime.now(timezone.utc) + timedelta(seconds=60)
    scheduler.add_job(_seed, "date", run_date=start, id="md_seed_start")
    if _missed(MEMBERSHIP_JOB):
        scheduler.add_job(
            _membership,
            "date",
            run_date=start + timedelta(seconds=30),
            id="md_membership_start",
        )
    # A missed evening's closes can still be taken from the snapshot until the
    # next session opens; never during the quiet hours.
    if _missed(CLOSES_JOB) and not in_quiet_hours(datetime.now(timezone.utc)):
        scheduler.add_job(
            _daily_closes,
            "date",
            run_date=start + timedelta(seconds=60),
            id="md_closes_start",
        )
    logger.info("Market-data worker started: %s", ", ".join(j.id for j in MD_JOBS))
    scheduler.start()


if __name__ == "__main__":
    main()
