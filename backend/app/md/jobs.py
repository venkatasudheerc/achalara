"""Running a market-data job: one at a time, and always on record.

Each run takes a Postgres advisory lock named after the job, so two copies
(a scheduled run and one started by hand) never overlap, and writes a
``md.job_run`` row that System status reads.
"""
import logging
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.md.models import JobRun

logger = logging.getLogger(__name__)


class JobAlreadyRunning(Exception):
    pass


def _lock_key(job: str) -> int:
    return zlib.crc32(f"md:{job}".encode())


@contextmanager
def tracked_run(db: Session, job: str):
    """Hold the job's lock and record the run; yields the ``JobRun`` to fill in."""
    postgres = db.get_bind().dialect.name == "postgresql"
    if (
        postgres
        and not db.execute(
            text("select pg_try_advisory_lock(:k)"), {"k": _lock_key(job)}
        ).scalar()
    ):
        raise JobAlreadyRunning(job)
    run = JobRun(job=job, started_at=datetime.now(timezone.utc), outcome="running")
    db.add(run)
    db.commit()
    try:
        yield run
        if run.outcome == "running":
            run.outcome = "ok"
    except Exception as exc:
        db.rollback()
        run = db.merge(run)
        run.outcome = "failed"
        run.note = f"{type(exc).__name__}: {exc}"[:2000]
        logger.error("Market-data job %s failed: %s", job, exc)
        raise
    finally:
        run.finished_at = datetime.now(timezone.utc)
        db.commit()
        if postgres:
            db.execute(text("select pg_advisory_unlock(:k)"), {"k": _lock_key(job)})
            db.commit()
