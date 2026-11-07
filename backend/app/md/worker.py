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
from app.md.classification import run_classification
from app.md.database import MdSession
from app.md.identifiers import run_identifiers
from app.md.jobs import JobAlreadyRunning, tracked_run
from app.md.membership import JOB as MEMBERSHIP_JOB, run_index_membership
from app.md.models import JobRun
from app.md.schedule import MD_JOBS, TIMEZONE
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


JOBS = {
    "md_seed_holdings": _seed,
    MEMBERSHIP_JOB: _membership,
    "md_identifiers": _identifiers,
    "md_classification": _classification,
}


def _missed_today() -> bool:
    """Whether the membership job has not succeeded in the last 20 hours."""
    db = MdSession()
    try:
        last = (
            db.query(JobRun.finished_at)
            .filter(JobRun.job == MEMBERSHIP_JOB, JobRun.outcome == "ok")
            .order_by(JobRun.finished_at.desc())
            .first()
        )
        return last is None or datetime.now(timezone.utc) - last[0] > timedelta(
            hours=20
        )
    finally:
        db.close()


def main() -> None:
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    for job in MD_JOBS:
        scheduler.add_job(
            JOBS[job.id], job.trigger(), id=job.id, coalesce=True, max_instances=1
        )
    # Catch up once after a restart, so a deploy at 7am does not lose the day.
    start = datetime.now(timezone.utc) + timedelta(seconds=60)
    scheduler.add_job(_seed, "date", run_date=start, id="md_seed_start")
    if _missed_today():
        scheduler.add_job(
            _membership,
            "date",
            run_date=start + timedelta(seconds=30),
            id="md_membership_start",
        )
    logger.info("Market-data worker started: %s", ", ".join(j.id for j in MD_JOBS))
    scheduler.start()


if __name__ == "__main__":
    main()
