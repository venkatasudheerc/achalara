"""Job runs kept across restarts, and a run missed while the server was down."""
from datetime import datetime, timedelta, timezone

import pytest
from apscheduler.triggers.cron import CronTrigger

from app.models.job_run import JobRun
from app.services import job_history, run_log, scheduler
from app.services.status_service import StatusService

UTC = timezone.utc
# Every day at 06:30 UTC, made up within three hours.
MORNING = CronTrigger(hour=6, minute=30, timezone="UTC")
GRACE = timedelta(hours=3)


def _run(started: datetime, ok: bool = True, error: str = None) -> dict:
    return {
        "started_at": started,
        "finished_at": started + timedelta(minutes=1),
        "ok": ok,
        "error": error,
    }


def test_the_latest_run_on_file_is_the_one_given(db):
    job_history.record(
        db, "plaid_refresh", _run(datetime(2026, 10, 6, 6, 30, tzinfo=UTC))
    )
    job_history.record(
        db,
        "plaid_refresh",
        _run(datetime(2026, 10, 7, 6, 30, tzinfo=UTC), ok=False, error="no answer"),
    )
    job_history.record(
        db, "price_history", _run(datetime(2026, 10, 8, 23, 30, tzinfo=UTC))
    )

    last = job_history.last_run(db, "plaid_refresh")

    assert last["started_at"] == datetime(2026, 10, 7, 6, 30, tzinfo=UTC)
    assert (last["ok"], last["error"]) == (False, "no answer")
    assert job_history.last_run(db, "index_history") is None


def test_old_runs_are_dropped_as_new_ones_are_kept(db):
    old = datetime(2026, 6, 1, 6, 30, tzinfo=UTC)
    job_history.record(db, "plaid_refresh", _run(old))
    job_history.record(db, "price_history", _run(old))

    job_history.record(
        db, "plaid_refresh", _run(old + job_history.KEEP + timedelta(days=1))
    )

    kept = {(r.job_id) for r in db.query(JobRun).all()}
    assert db.query(JobRun).filter(JobRun.job_id == "plaid_refresh").count() == 1
    assert kept == {"plaid_refresh", "price_history"}  # another job's runs are left


@pytest.mark.parametrize(
    "now, last_started, expected",
    [
        # Down over 06:30, back at 07:10: yesterday's run is the last, today's is made up.
        (
            datetime(2026, 10, 7, 7, 10, tzinfo=UTC),
            datetime(2026, 10, 6, 6, 30, tzinfo=UTC),
            datetime(2026, 10, 7, 6, 30, tzinfo=UTC),
        ),
        # Today's run happened: nothing is missed.
        (
            datetime(2026, 10, 7, 7, 10, tzinfo=UTC),
            datetime(2026, 10, 7, 6, 30, 2, tzinfo=UTC),
            None,
        ),
        # Back only in the afternoon: too late to stand for the morning.
        (
            datetime(2026, 10, 7, 15, 0, tzinfo=UTC),
            datetime(2026, 10, 6, 6, 30, tzinfo=UTC),
            None,
        ),
        # A job that has never run has nothing to make up.
        (datetime(2026, 10, 7, 7, 10, tzinfo=UTC), None, None),
    ],
)
def test_a_run_is_missed_only_when_none_started_since_it_was_due(
    now, last_started, expected
):
    assert job_history.missed(MORNING, now, last_started, GRACE) == expected


def test_a_time_read_back_without_its_zone_is_still_compared(db):
    """SQLite returns stored times without a zone; they were written in UTC."""
    naive = datetime(2026, 10, 6, 6, 30)

    due = job_history.missed(
        MORNING, datetime(2026, 10, 7, 7, 0, tzinfo=UTC), naive, GRACE
    )

    assert due == datetime(2026, 10, 7, 6, 30, tzinfo=UTC)


def test_a_finished_run_is_handed_on_to_be_kept_and_a_failure_there_is_harmless():
    kept = []
    run_log.keep_runs(lambda job_id, run: kept.append((job_id, run["ok"])))
    try:

        @run_log.tracked("index_history")
        def job():
            assert run_log.is_running("index_history")
            return "done"

        assert job() == "done"
        assert kept == [("index_history", True)]
        assert not run_log.is_running("index_history")

        def broken(job_id, run):
            raise RuntimeError("the database is away")

        run_log.keep_runs(broken)
        assert job() == "done"  # the job's own result is untouched
    finally:
        run_log.keep_runs(None)


def test_status_shows_the_last_run_from_before_a_restart(db, monkeypatch):
    """Nothing has run since this start, but a run is on file from before it."""
    monkeypatch.setattr(run_log, "_runs", {})
    job_history.record(
        db,
        "ticker_changes",
        _run(datetime(2026, 10, 6, 10, 15, tzinfo=UTC), ok=False, error="x"),
    )

    status = StatusService(db).status(now=datetime(2026, 10, 6, 21, 0, tzinfo=UTC))

    job = next(j for j in status["jobs"] if j["id"] == "ticker_changes")
    assert job["last_started_at"] == datetime(2026, 10, 6, 10, 15, tzinfo=UTC)
    assert job["last_ok"] is False
    assert "Ticker changes failed on its last run." in status["attention"]


def test_catch_up_runs_what_fell_while_down_and_nothing_else(db, monkeypatch):
    ran = []
    grace = timedelta(hours=3)
    monkeypatch.setattr(
        scheduler,
        "_schedule",
        lambda: [
            ("plaid_refresh", lambda: ran.append("plaid_refresh"), MORNING, grace),
            ("ticker_changes", lambda: ran.append("ticker_changes"), MORNING, grace),
            ("index_history", lambda: ran.append("index_history"), MORNING, grace),
        ],
    )

    class _Session:
        """The test's session, left open when the scheduler closes its own."""

        def __getattr__(self, name):
            return getattr(db, name)

        def close(self):
            pass

    monkeypatch.setattr(scheduler, "SessionLocal", _Session)
    # Missed this morning; ran this morning; never ran.
    job_history.record(
        db, "plaid_refresh", _run(datetime(2026, 10, 6, 6, 30, tzinfo=UTC))
    )
    job_history.record(
        db, "ticker_changes", _run(datetime(2026, 10, 7, 6, 30, tzinfo=UTC))
    )

    done = scheduler.catch_up(now=datetime(2026, 10, 7, 7, 10, tzinfo=UTC))

    assert done == ran == ["plaid_refresh"]
