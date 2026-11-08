"""Returns from daily closes: period edges, partial periods, day places, seasonality."""
from datetime import date

import pytest

from app.utils.returns import (
    compound,
    day_returns,
    excess,
    month_to_date_by_date,
    period_key,
    period_returns,
    seasonality,
    summarise,
    turn_of_month,
    typical_month_path,
)


def test_iso_weeks_cross_the_year():
    # Thursday 31 Dec 2026 and Friday 1 Jan 2027 are the same ISO week (2026-W53).
    assert period_key(date(2026, 12, 31), "week") == period_key(
        date(2027, 1, 1), "week"
    )
    assert period_key(date(2027, 1, 4), "week") == (2027, 1)
    with pytest.raises(ValueError):
        period_key(date(2026, 1, 1), "fortnight")


def test_a_month_runs_from_the_last_close_before_it():
    closes = [
        (date(2026, 9, 29), 100.0),
        (date(2026, 9, 30), 110.0),  # last close of September
        (date(2026, 10, 1), 120.0),
        (date(2026, 10, 30), 121.0),  # last close of October
        (date(2026, 11, 2), 133.1),
    ]
    rows = period_returns(closes, "month", as_of=date(2026, 11, 3))
    assert [r.key for r in rows] == [(2026, 10), (2026, 11)]
    assert rows[0].ret == pytest.approx(0.1)  # 121 / 110
    assert (rows[0].start, rows[0].end, rows[0].partial) == (
        date(2026, 10, 1),
        date(2026, 10, 30),
        False,
    )
    assert rows[1].ret == pytest.approx(0.1) and rows[1].partial is True


def test_unsorted_input_and_a_gap_give_the_same_answer():
    closes = [(date(2026, 10, 30), 121.0), (date(2026, 9, 30), 110.0)]
    assert period_returns(closes, "month")[0].ret == pytest.approx(0.1)


def test_days_know_their_place_in_the_month():
    october = [
        date(2026, 10, d) for d in range(1, 30) if date(2026, 10, d).weekday() < 5
    ]
    closes = (
        [(date(2026, 9, 30), 100.0)]
        + [(d, 100.0) for d in october]
        + [
            (date(2026, 10, 30), 101.0),  # Friday, October's last trading day
            (date(2026, 11, 2), 99.99),  # Monday, November's first
            (date(2026, 11, 3), 100.99),
        ]
    )
    rows = day_returns(closes)
    assert [r.day for r in rows][-3:] == [
        date(2026, 10, 30),
        date(2026, 11, 2),
        date(2026, 11, 3),
    ]
    last_oct, first_nov, second_nov = rows[-3:]
    assert last_oct.trading_day_of_month == len(october) + 1 == 22
    assert (last_oct.trading_days_left, turn_of_month(last_oct)) == (0, "last day")
    assert (first_nov.trading_day_of_month, first_nov.weekday) == (1, 1)
    assert first_nov.ret == pytest.approx(-0.01)
    assert turn_of_month(second_nov) == "day 2"


def test_seasonality_counts_and_averages_each_bucket():
    stats = seasonality([(11, 0.02), (11, -0.01), (11, 0.05), (12, 0.01)])
    assert list(stats) == [11, 12]
    nov = stats[11]
    assert nov["count"] == 3 and nov["share_up"] == pytest.approx(2 / 3)
    assert nov["mean"] == pytest.approx(0.02) and nov["median"] == pytest.approx(0.02)
    assert (nov["best"], nov["worst"]) == (0.05, -0.01)
    assert summarise([]) is None


def test_excess_and_compounding():
    assert excess({1: 0.05, 2: 0.01}, {1: 0.02}) == {1: pytest.approx(0.03)}
    assert compound([0.1, 0.1]) == pytest.approx(0.21)


def test_a_week_that_ended_on_friday_is_over_at_the_weekend():
    closes = [(date(2026, 10, 30), 100.0), (date(2026, 11, 6), 110.0)]
    saturday = period_returns(closes, "week", as_of=date(2026, 11, 7))
    friday_noon = period_returns(closes, "week", as_of=date(2026, 11, 5))
    assert saturday[-1].partial is False and friday_noon[-1].partial is True
    # November still has trading days after the 7th.
    assert period_returns(closes, "month", as_of=date(2026, 11, 7))[-1].partial is True


def test_a_month_only_partly_on_file_gives_no_day_places():
    """History starting on 9 Nov: that November's 'day 1' would really be its sixth."""
    closes = [(date(2021, 11, 9), 100.0), (date(2021, 11, 10), 101.0)] + [
        (date(2021, 12, 1), 102.0),
        (date(2021, 12, 2), 103.0),
    ]
    rows = day_returns(closes)
    assert [r.day for r in rows] == [date(2021, 12, 1), date(2021, 12, 2)]
    assert rows[0].trading_day_of_month == 1


def _weekday_closes(first, last, step):
    """A close every weekday, rising by ``step`` each day."""
    from datetime import timedelta

    closes, day, value = [], first, 100.0
    while day <= last:
        if day.weekday() < 5:
            value *= 1 + step
            closes.append((day, value))
        day += timedelta(days=1)
    return closes


def test_a_month_by_calendar_date_carries_the_weekend_forward():
    closes = [
        (date(2026, 10, 30), 100.0),  # Friday, October's last close
        (date(2026, 11, 2), 102.0),  # Monday: November 1 is a Sunday
        (date(2026, 11, 3), 101.0),
        (date(2026, 11, 6), 104.0),  # Friday
    ]
    path = dict(month_to_date_by_date(closes, 2026, 11))
    assert path[1] == 0.0  # before the month's first trade
    assert path[2] == pytest.approx(0.02)
    assert path[4] == pytest.approx(0.01)  # Wednesday with no close: Tuesday's
    assert path[6] == pytest.approx(0.04)
    assert max(path) == 6  # nothing past the last close on file
    assert month_to_date_by_date(closes[1:], 2026, 11) is None  # no close before


def test_a_typical_month_by_date_averages_whole_months_only():
    closes = _weekday_closes(date(2023, 10, 1), date(2026, 11, 6), 0.001)
    path = typical_month_path(closes, 11, as_of=date(2026, 11, 8))
    assert [p["day"] for p in path] == list(range(1, 31))
    assert {p["years"] for p in path} == {3}  # 2023-2025; the running 2026 is left out
    assert path[-1]["mean"] > path[10]["mean"] > 0
    # A month cut short on file is not whole and is left out.
    short = [c for c in closes if c[0] <= date(2025, 11, 14)]
    assert {p["years"] for p in typical_month_path(short, 11, date(2026, 11, 8))} == {2}
