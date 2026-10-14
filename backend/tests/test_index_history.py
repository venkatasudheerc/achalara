"""Daily bars of the market indices: reading the source's answer, loading, topping up."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models.index_bar import IndexBar
from app.services.index_history_service import (
    INDICES,
    IndexHistoryService,
    parse_bars,
    read_csv_bars,
)

# Well after the close on Friday 2 October 2026.
NOW = datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)


def _stamp(day: date) -> int:
    """The session's opening bell that day, as the source stamps a bar."""
    return int(
        datetime(day.year, day.month, day.day, 13, 30, tzinfo=timezone.utc).timestamp()
    )


def _payload(rows):
    """The source's answer for ``(day, open, high, low, close, volume)`` rows."""
    return {
        "chart": {
            "result": [
                {
                    "timestamp": [_stamp(r[0]) for r in rows],
                    "indicators": {
                        "quote": [
                            {
                                key: [r[i] for r in rows]
                                for i, key in enumerate(
                                    ("open", "high", "low", "close", "volume"), start=1
                                )
                            }
                        ]
                    },
                }
            ]
        }
    }


class _Source:
    """Stands in for the source; answers from the day asked for onwards."""

    def __init__(self, rows, failing=()):
        self.rows, self.failing, self.asked = rows, failing, []

    def __call__(self, source_symbol, start):
        self.asked.append((source_symbol, start))
        if source_symbol in self.failing:
            raise OSError("source is down")
        return _payload([r for r in self.rows if r[0] >= start])


ROWS = [
    (date(1950, 1, 3), 16.66, 16.66, 16.66, 16.66, 1260000),
    (date(2026, 10, 1), 100.0, 104.0, 99.0, 103.0, 5000),
    (date(2026, 10, 2), 103.0, 105.5, 102.0, 105.0, 6000),
]


def test_a_day_published_as_a_close_only_keeps_no_open_high_or_low():
    bars = parse_bars(_payload(ROWS))
    assert bars[0] == {
        "bar_date": date(1950, 1, 3),
        "open": None,
        "high": None,
        "low": None,
        "close": Decimal("16.6600"),
        "volume": 1260000,
    }
    assert bars[1]["open"] == Decimal("100.0000")
    assert bars[1]["high"] == Decimal("104.0000")


def test_a_day_with_no_close_is_left_out_and_an_empty_answer_gives_nothing():
    rows = [ROWS[1], (date(2026, 10, 2), None, None, None, None, None)]
    assert [b["bar_date"] for b in parse_bars(_payload(rows))] == [date(2026, 10, 1)]
    assert parse_bars({"chart": {"result": None}}) == []


def test_the_first_load_goes_back_to_the_start_and_a_top_up_only_a_few_days(db):
    source = _Source(ROWS)
    service = IndexHistoryService(db, fetch=source)
    assert service.refresh(["SPX"], now=NOW) == {"SPX": 3}
    assert source.asked[0][0] == INDICES["SPX"]
    assert source.asked[0][1] < date(1900, 1, 1)

    assert service.refresh(["SPX"], now=NOW) == {"SPX": 2}
    assert source.asked[1][1] == date(2026, 9, 25)
    held = service.extent()["SPX"]
    assert (held["first"], held["last"]) == (date(1950, 1, 3), date(2026, 10, 2))
    assert (held["days"], held["with_open"]) == (3, 2)


def test_a_day_the_source_corrects_is_replaced_not_added(db):
    IndexHistoryService(db, fetch=_Source(ROWS)).refresh(["SPX"], now=NOW)
    corrected = ROWS[:2] + [(date(2026, 10, 2), 103.0, 105.5, 102.0, 104.25, 6100)]
    IndexHistoryService(db, fetch=_Source(corrected)).refresh(["SPX"], now=NOW)
    rows = db.query(IndexBar).filter(IndexBar.bar_date == date(2026, 10, 2)).all()
    assert [(r.close, r.volume) for r in rows] == [(Decimal("104.2500"), 6100)]


def test_todays_bar_is_not_kept_while_the_session_is_open(db):
    # 11am in New York on 2 October: that day's bar is still moving.
    midday = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
    service = IndexHistoryService(db, fetch=_Source(ROWS))
    assert service.refresh(["SPX"], now=midday) == {"SPX": 2}
    assert service.extent()["SPX"]["last"] == date(2026, 10, 1)


def test_one_index_failing_does_not_stop_the_others(db):
    source = _Source(ROWS, failing=(INDICES["DJI"],))
    written = IndexHistoryService(db, fetch=source).refresh(["DJI", "NDX"], now=NOW)
    assert written == {"DJI": 0, "NDX": 3}
    assert set(IndexHistoryService(db).extent()) == {"NDX"}


def test_an_unknown_index_is_refused(db):
    try:
        IndexHistoryService(db, fetch=_Source(ROWS)).refresh(["FTSE"], now=NOW)
    except ValueError as error:
        assert "Unknown index" in str(error)
    else:
        raise AssertionError("an unknown index was accepted")


def test_a_downloaded_file_is_read_and_replaces_what_was_on_file(db, tmp_path):
    path = tmp_path / "dow.csv"
    path.write_text(
        "Date,Open,High,Low,Close,Adj Close,Volume\n"
        "1940-05-01,147.2,147.2,147.2,147.2,147.2,0\n"
        "2026-09-30,98.0,101.0,97.5,100.5,100.5,4200\n"
    )
    bars = read_csv_bars(str(path))
    assert bars[0] == {
        "bar_date": date(1940, 5, 1),
        "open": None,
        "high": None,
        "low": None,
        "close": Decimal("147.2000"),
        "volume": None,
    }
    service = IndexHistoryService(db, fetch=_Source(ROWS))
    service.refresh(["DJI"], now=NOW)
    assert service.load_file("dji", bars, "a-file", replace=True) == 2
    held = service.extent()["DJI"]
    assert (held["first"], held["last"], held["days"]) == (
        date(1940, 5, 1),
        date(2026, 9, 30),
        2,
    )
    assert {row.source for row in db.query(IndexBar)} == {"a-file"}


def test_the_indices_are_read_the_evening_of_a_session_and_again_the_next_morning():
    from zoneinfo import ZoneInfo

    from app.services.scheduler import index_history_trigger

    eastern = ZoneInfo("America/New_York")
    trigger = index_history_trigger()
    # From a Friday afternoon: that evening, Saturday morning, then Monday evening.
    moment = datetime(2026, 10, 9, 15, 0, tzinfo=eastern)
    fires = []
    for _ in range(3):
        moment = trigger.get_next_fire_time(None, moment + timedelta(seconds=1))
        fires.append(moment.astimezone(eastern).strftime("%a %H:%M"))
    assert fires == ["Fri 22:00", "Sat 06:00", "Mon 22:00"]
