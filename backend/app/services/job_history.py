"""The lasting record of scheduled job runs, and what was missed while down.

``run_log`` keeps the running process's latest runs in memory and starts empty
at each restart. Each finished run is also written here (``job_runs``), so
System status still knows when a job last ran, and the scheduler can tell at
start-up that a run fell while the server was down and make it up.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.job_run import JobRun

logger = logging.getLogger(__name__)

# Runs older than this are removed as new ones are written.
KEEP = timedelta(days=90)
# How far back a missed run is looked for. Every job runs at least weekly.
_LOOK_BACK = timedelta(days=8)


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands a stored time back without its zone; it was written in UTC."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


def record(db: Session, job_id: str, run: Dict) -> None:
    """Keep one finished run, and drop this job's runs older than ``KEEP``."""
    db.add(
        JobRun(
            job_id=job_id,
            started_at=run["started_at"],
            finished_at=run["finished_at"],
            ok=run["ok"],
            error=run.get("error"),
        )
    )
    db.query(JobRun).filter(
        JobRun.job_id == job_id, JobRun.started_at < run["started_at"] - KEEP
    ).delete(synchronize_session=False)
    db.commit()


def last_run(db: Session, job_id: str) -> Optional[Dict]:
    """The job's latest run on file, shaped as ``run_log.last_run`` gives it."""
    row = (
        db.query(JobRun)
        .filter(JobRun.job_id == job_id)
        .order_by(JobRun.started_at.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "started_at": _aware(row.started_at),
        "finished_at": _aware(row.finished_at),
        "ok": row.ok,
        "error": row.error,
    }


def last_due(trigger, now: datetime) -> Optional[datetime]:
    """The latest time at or before ``now`` that the trigger was due to fire."""
    due = None
    moment = trigger.get_next_fire_time(None, now - _LOOK_BACK)
    while moment is not None and moment <= now:
        due = moment
        moment = trigger.get_next_fire_time(moment, moment + timedelta(seconds=1))
    return due


def missed(
    trigger, now: datetime, last_started: Optional[datetime], grace: timedelta
) -> Optional[datetime]:
    """The scheduled time of a run that was missed and may still be made up.

    A run is missed when nothing started at or after the time it was due. It
    may be made up only within ``grace`` of that time: past it, the job's own
    next run is the better one (a morning balance read in the afternoon is no
    longer where the day before ended). A job that has never run is not
    "missed": a new server has nothing to make up.
    """
    if last_started is None:
        return None
    due = last_due(trigger, now)
    if due is None or _aware(last_started) >= due:
        return None
    return due if now - due <= grace else None
