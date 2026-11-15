"""What the running process has done since it started: job runs and warnings.

Kept in memory, for the status page, and empty again at each restart. A
finished job run is also handed to whoever asked to keep it (``keep_runs``:
the scheduler stores it through ``job_history``), so the last run of each job
outlives a restart. Warnings do not: the container's own log is their record.
"""
import functools
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Deque, Dict, List, Optional

_MESSAGE_LIMIT = 400
_KEEP = 100

_started_at = datetime.now(timezone.utc)
_runs: Dict[str, Dict] = {}
_recent: Deque[Dict] = deque(maxlen=_KEEP)
# Events the brokerage source has sent, and the ids of those already acted on.
_webhooks: Deque[Dict] = deque(maxlen=50)
_webhook_ids: Deque[str] = deque(maxlen=500)
_current = threading.local()
_lock = threading.Lock()
# Jobs running now, and where a finished run is sent to be kept (nowhere until
# the scheduler says: tests and one-off commands keep runs in memory only).
_running: set = set()
_keep: Optional[Callable[[str, Dict], None]] = None


class _Recorder(logging.Handler):
    """Keeps the latest warnings and errors, and marks a job that logged an error."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()[:_MESSAGE_LIMIT]
        except Exception:
            message = str(record.msg)[:_MESSAGE_LIMIT]
        with _lock:
            _recent.append(
                {
                    "at": datetime.fromtimestamp(record.created, timezone.utc),
                    "level": record.levelname,
                    "source": record.name,
                    "message": message,
                }
            )
        if record.levelno >= logging.ERROR and getattr(_current, "job", None):
            _current.error = message


_recorder = _Recorder(level=logging.WARNING)


def install() -> None:
    """Start recording warnings and errors. Safe to call more than once."""
    root = logging.getLogger()
    if _recorder not in root.handlers:
        root.addHandler(_recorder)


def tracked(job_id: str) -> Callable:
    """Record each run of a scheduled job: when, and whether it logged an error.

    The jobs catch their own exceptions and log them, so an error in the log
    during the run is what marks it as failed.
    """

    def decorate(work: Callable) -> Callable:
        @functools.wraps(work)
        def run(*args, **kwargs):
            started = datetime.now(timezone.utc)
            # One job may run another (the catch-up runs the capture): the
            # outer one is put back afterwards, and takes on the inner's error.
            outer_job = getattr(_current, "job", None)
            outer_error = getattr(_current, "error", None)
            _current.job, _current.error = job_id, None
            with _lock:
                _running.add(job_id)
            try:
                return work(*args, **kwargs)
            except Exception as exc:
                _current.error = str(exc)[:_MESSAGE_LIMIT]
                raise
            finally:
                error = _current.error
                finished = {
                    "started_at": started,
                    "finished_at": datetime.now(timezone.utc),
                    "ok": error is None,
                    "error": error,
                }
                with _lock:
                    _runs[job_id] = finished
                    _running.discard(job_id)
                    keep = _keep
                if keep is not None:
                    # Keeping the run must never fail the job it describes.
                    try:
                        keep(job_id, dict(finished))
                    except Exception as exc:
                        logging.getLogger(__name__).warning(
                            "Could not keep the run of %s: %s",
                            job_id,
                            type(exc).__name__,
                        )
                _current.job, _current.error = outer_job, outer_error or error

        return run

    return decorate


def keep_runs(keep: Optional[Callable[[str, Dict], None]]) -> None:
    """Send every finished run to ``keep`` as well; ``None`` stops doing so."""
    global _keep
    with _lock:
        _keep = keep


def is_running(job_id: str) -> bool:
    with _lock:
        return job_id in _running


def started_at() -> datetime:
    return _started_at


def last_run(job_id: str) -> Optional[Dict]:
    with _lock:
        return dict(_runs[job_id]) if job_id in _runs else None


def recent(limit: int = 30) -> List[Dict]:
    """The latest warnings and errors, newest first."""
    with _lock:
        return list(_recent)[::-1][:limit]


def note_webhook(event: str, outcome: str) -> None:
    """Record that the brokerage source sent an event, and what was done."""
    with _lock:
        _webhooks.append(
            {"at": datetime.now(timezone.utc), "event": event, "outcome": outcome}
        )


def webhooks(limit: int = 20) -> List[Dict]:
    """The latest events from the brokerage source, newest first."""
    with _lock:
        return list(_webhooks)[::-1][:limit]


def first_delivery(webhook_id: str) -> bool:
    """Whether this event id is new; later deliveries of it are repeats."""
    with _lock:
        if webhook_id in _webhook_ids:
            return False
        _webhook_ids.append(webhook_id)
        return True
