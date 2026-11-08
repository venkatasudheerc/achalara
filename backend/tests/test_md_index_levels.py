"""Index levels in md: loaded in full once, then the last week read again each run."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.md import levels
from app.md.levels import IndexLevelService
from app.md.models import IndexLevelHist, JobRun

EVENING = datetime(
    2026, 11, 7, 1, 30, tzinfo=timezone.utc
)  # Fri 6 Nov, 8:30 PM Eastern
MIDDAY = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)  # Fri 6 Nov, 1 PM Eastern


def _payload(rows):
    """Yahoo's chart answer for (day, close) rows, stamped at the opening bell."""
    stamps = [
        int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc).timestamp())
        for d, _ in rows
    ]
    closes = [float(c) for _, c in rows]
    return {
        "chart": {
            "result": [
                {
                    "timestamp": stamps,
                    "indicators": {
                        "quote": [
                            {
                                "open": closes,
                                "high": closes,
                                "low": closes,
                                "close": closes,
                                "volume": [0] * len(rows),
                            }
                        ]
                    },
                }
            ]
        }
    }


class FakeYahoo:
    def __init__(self, rows, fail=()):
        self.rows, self.fail, self.asked = rows, fail, []

    def __call__(self, source_symbol, start):
        self.asked.append((source_symbol, start))
        if source_symbol in self.fail:
            raise OSError("no answer")
        return _payload([(d, c) for d, c in self.rows if d >= start])


def _levels(db, code="SPX"):
    return {
        row.price_date: row.close
        for row in db.query(IndexLevelHist).filter(IndexLevelHist.symbol == code)
    }


def test_a_first_run_loads_everything_and_later_runs_the_last_week(db):
    old = [(date(1928, 1, 3), 17.76), (date(2026, 11, 5), 6800.5)]
    fake = FakeYahoo(old)
    IndexLevelService(db, fake).run(EVENING)
    assert _levels(db) == {
        date(1928, 1, 3): Decimal("17.76"),
        date(2026, 11, 5): Decimal("6800.5"),
    }
    assert ("^GSPC", date(1880, 1, 1)) in fake.asked
    fake2 = FakeYahoo(old + [(date(2026, 11, 6), 6810.25)])
    IndexLevelService(db, fake2).run(EVENING)
    assert ("^GSPC", date(2026, 11, 5) - timedelta(days=7)) in fake2.asked
    assert _levels(db)[date(2026, 11, 6)] == Decimal("6810.25")


def test_a_late_correction_replaces_the_day(db):
    IndexLevelService(db, FakeYahoo([(date(2026, 11, 5), 6800.5)])).run(EVENING)
    IndexLevelService(db, FakeYahoo([(date(2026, 11, 5), 6801.0)])).run(EVENING)
    assert _levels(db) == {date(2026, 11, 5): Decimal("6801.0")}


def test_todays_level_waits_for_the_close(db):
    rows = [(date(2026, 11, 5), 6800.5), (date(2026, 11, 6), 6790.0)]
    IndexLevelService(db, FakeYahoo(rows)).run(MIDDAY)
    assert set(_levels(db)) == {date(2026, 11, 5)}


def test_one_index_failing_leaves_the_others(db):
    note = IndexLevelService(
        db, FakeYahoo([(date(2026, 11, 5), 100)], fail={"^NDX"})
    ).run(EVENING)
    assert set(_levels(db, "NDX")) == set() and set(_levels(db, "SPX")) == {
        date(2026, 11, 5)
    }
    run = db.query(JobRun).filter(JobRun.job == levels.JOB).one()
    assert run.outcome == "failed" and "could not be read: NDX" in note
    assert run.requests == len(levels.LEVELS) - 1
