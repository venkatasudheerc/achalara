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


def test_an_index_that_stops_updating_is_named(db):
    from datetime import date as day_

    from app.md.levels import describe_stale, stale_levels, INDEX_LEVELS_INFO

    friday = day_(2026, 11, 6)
    for level in INDEX_LEVELS_INFO:
        if level.code != "CNXREALTY":
            db.add(IndexLevelHist(symbol=level.code, price_date=friday, close=1, source="test", fetched_at=datetime(2026, 11, 6)))
    db.add(IndexLevelHist(symbol="CNXREALTY", price_date=day_(2026, 10, 30), close=1, source="test", fetched_at=datetime(2026, 11, 6)))
    db.flush()
    # The weekend and two quiet weekdays are normal: nothing to say on Wednesday.
    assert [n for n, _ in stale_levels(db, day_(2026, 11, 11)) if n != "Nifty Realty"] == []
    line = describe_stale(stale_levels(db, day_(2026, 11, 9)))
    assert line == "No new index level: Nifty Realty (since 2026-10-30)."
    # Five weekdays after Friday, every index is stale.
    assert len(stale_levels(db, day_(2026, 11, 13))) == len(INDEX_LEVELS_INFO)
    db.query(IndexLevelHist).filter(IndexLevelHist.symbol == "NSEI").delete()
    assert "No index levels on file yet: Nifty 50" in describe_stale(stale_levels(db, day_(2026, 11, 9)))


def test_each_market_runs_on_its_own_clock(db):
    from apscheduler.triggers.cron import CronTrigger

    from app.md.schedule import MD_JOBS

    rows = [(date(2026, 11, 5), 100), (date(2026, 11, 6), 101)]
    # 4:00 PM IST on Friday the 6th: India's day is not final yet; 5:00 PM it is.
    before = datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)
    after = datetime(2026, 11, 6, 11, 30, tzinfo=timezone.utc)
    fake = FakeYahoo(rows)
    IndexLevelService(db, fake).run(before, market="IN")
    assert set(_levels(db, "NSEI")) == {date(2026, 11, 5)}
    assert not _levels(db, "SPX")  # the Indian run leaves the US indices alone
    assert {s for s, _ in fake.asked} == {i.source for i in levels.INDEX_LEVELS_INFO if i.country == "IN"}
    IndexLevelService(db, FakeYahoo(rows)).run(after, market="IN")
    assert set(_levels(db, "NSEI")) == {date(2026, 11, 5), date(2026, 11, 6)}
    # At that hour New York's Friday is not over: the US run waits for its own close.
    IndexLevelService(db, FakeYahoo(rows)).run(after, market="US")
    assert set(_levels(db, "SPX")) == {date(2026, 11, 5)}
    jobs = {r.job for r in db.query(JobRun)}
    assert jobs == {levels.JOB, levels.JOB_IN}
    # The Indian job fires at 6 PM in Kolkata on weekdays, whatever New York's clock says.
    india = next(j for j in MD_JOBS if j.id == levels.JOB_IN).trigger()
    assert isinstance(india, CronTrigger)
    fire = india.get_next_fire_time(None, datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc))
    assert (fire.hour, fire.minute, str(fire.tzinfo)) == (18, 0, "Asia/Kolkata")
    assert india.get_next_fire_time(None, datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)).weekday() == 0  # Saturday -> Monday


def test_without_a_market_each_runs_and_is_recorded(db):
    from app.md.levels import run_index_levels

    import app.md.levels as mod
    original = mod.yahoo_chart.fetch
    mod.yahoo_chart.fetch = FakeYahoo([(date(2026, 11, 5), 100)])
    try:
        note = run_index_levels(db, EVENING)
    finally:
        mod.yahoo_chart.fetch = original
    assert "NSEI" in note and "SPX" in note
    assert sorted(r.job for r in db.query(JobRun)) == sorted([levels.JOB, levels.JOB_IN])
