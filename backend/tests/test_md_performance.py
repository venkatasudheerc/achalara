"""Performance and seasonality from market data: securities, indices and groups."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from app.md import performance as perf
from app.md.models import (
    IndexDef,
    IndexLevelHist,
    IndexMember,
    IndexMemberHist,
    PriceAdjDaily,
    Security,
    SecurityClassification,
    SecuritySymbol,
)

TODAY = date(2026, 11, 8)
NOW = TODAY
STAMP = datetime(2026, 11, 8)


def weekdays(first, last):
    day, out = first, []
    while day <= last:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def _security(db, symbol, closes, sector="IT", member=True):
    security = Security(name=symbol, kind="stock")
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    if not db.get(IndexDef, "XYZ"):
        db.add(
            IndexDef(code="XYZ", name="Example", owner="Example", method="fund_file")
        )
        db.flush()
    if member:
        db.add(IndexMember(index_code="XYZ", security_id=security.id, since=TODAY))
        db.add(
            IndexMemberHist(index_code="XYZ", security_id=security.id, valid_from=TODAY)
        )
    if sector:
        db.add(
            SecurityClassification(
                security_id=security.id, sector_code=sector, as_of=TODAY
            )
        )
    for day, close in closes:
        db.add(
            PriceAdjDaily(
                security_id=security.id,
                price_date=day,
                adj_close=Decimal(str(close)),
                fetched_at=STAMP,
            )
        )
    db.flush()
    return security


def monthly(path):
    """Daily closes, flat within each month, stepping to each month's level in ``path``:
    ``{(year, month): close}``."""
    closes = []
    for (year, month), close in sorted(path.items()):
        first = date(year, month, 1)
        last = (date(year + month // 12, month % 12 + 1, 1)) - timedelta(days=1)
        closes += [(d, close) for d in weekdays(first, last)]
    return closes


def _novembers(base, nov_gain, years=(2022, 2023, 2024, 2025)):
    """October at ``base``, November up by ``nov_gain``, other months flat."""
    path = {}
    level = 100.0
    for year in years:
        for month in range(1, 13):
            if month == 11:
                level *= 1 + nov_gain
            path[(year, month)] = level
    path[(2026, 1)] = level
    return monthly(path)


def test_returns_side_by_side_with_excess(db):
    _security(db, "AAA", monthly({(2026, 8): 100, (2026, 9): 110, (2026, 10): 121}))
    _security(db, "BBB", monthly({(2026, 8): 100, (2026, 9): 100, (2026, 10): 105}))
    out = perf.returns(db, ["AAA", "NOPE"], "month", benchmark="BBB", today=NOW)
    (aaa,) = out["series"]
    assert out["unknown"] == ["NOPE"] and aaa["basis"] == "total"
    periods = {p["period"]: p for p in aaa["periods"]}
    assert periods["2026-09"]["ret"] == pytest.approx(0.10)
    assert periods["2026-10"]["excess"] == pytest.approx(0.10 - 0.05)


def test_an_index_level_is_a_price_return(db):
    for day, close in monthly({(2026, 9): 4000, (2026, 10): 4400}):
        db.add(
            IndexLevelHist(
                symbol="SPX",
                price_date=day,
                close=close,
                source="test",
                fetched_at=datetime(2026, 11, 8),
            )
        )
    db.flush()
    out = perf.returns(db, ["SPX"], "month", today=NOW)
    assert out["series"][0]["kind"] == "index" and out["series"][0]["basis"] == "price"
    assert out["series"][0]["periods"][0]["ret"] == pytest.approx(0.10)


def test_month_of_year_seasonality_with_its_sample(db):
    _security(db, "AAA", _novembers(100, 0.05))
    out = perf.seasonality(db, "AAA", "month", today=NOW)
    nov = next(b for b in out["buckets"] if b["bucket"] == "Nov")
    assert nov["count"] == 4 and nov["mean"] == pytest.approx(0.05)
    assert nov["share_up"] == 1.0
    assert out["years"]["count"] >= 4 and out["survivorship"] is False


def test_november_day_by_day_skips_a_month_only_partly_on_file(db):
    closes = [
        (d, 100.0 + i)
        for i, d in enumerate(weekdays(date(2024, 11, 11), date(2025, 12, 31)))
    ]
    _security(db, "AAA", closes)
    out = perf.seasonality(db, "AAA", "trading_day", month=11, today=NOW)
    assert out["years"] == {
        "first": 2025,
        "last": 2025,
        "count": 1,
    }  # Nov 2024 began mid-month
    assert out["buckets"][0]["bucket"] == "trading day 1"
    assert out["month_to_date"][0]["trading_day"] == 1


def test_a_group_is_the_equal_weighted_average_of_its_members(db):
    _security(db, "AAA", _novembers(100, 0.10))
    _security(db, "BBB", _novembers(100, 0.00))
    out = perf.seasonality(db, "index:XYZ", "month", today=NOW)
    nov = next(b for b in out["buckets"] if b["bucket"] == "Nov")
    assert nov["mean"] == pytest.approx(0.05) and out["members"] == 2
    assert out["survivorship"] is True
    with pytest.raises(ValueError):
        perf.seasonality(db, "index:XYZ", "weekday", today=NOW)


def test_consistent_months_reports_what_luck_alone_would_give(db):
    _security(db, "WIN", _novembers(100, 0.08))
    _security(db, "MEH", _novembers(100, 0.01))
    _security(db, "BEN", _novembers(100, 0.02), member=False)  # the benchmark
    out = perf.consistent_months(db, 11, "BEN", 4, "XYZ", today=NOW)
    assert [r["symbol"] for r in out["rows"]] == ["WIN"]
    row = out["rows"][0]
    assert row["years"] == 4 and row["avg_excess"] == pytest.approx(0.06)
    assert row["sector"] == "IT" and row["sector_beat_share"] == pytest.approx(0.5)
    assert out["eligible"] == 2 and out["expected_by_luck"] == pytest.approx(
        2 * 0.5**4
    )


def test_movers_rank_the_latest_month_that_has_ended(db):
    _security(db, "UP", monthly({(2026, 9): 100, (2026, 10): 130, (2026, 11): 130}))
    _security(db, "DOWN", monthly({(2026, 9): 100, (2026, 10): 80, (2026, 11): 80}))
    out = perf.movers(db, "month", None, "XYZ", 5, today=NOW)
    assert out["period"] == "2026-10"
    assert [r["symbol"] for r in out["best"]] == ["UP", "DOWN"]
    assert out["worst"][0]["symbol"] == "DOWN"


def test_unknown_subjects_and_bad_choices_are_refused(db):
    with pytest.raises(perf.UnknownSubject):
        perf.seasonality(db, "NOPE", "month", today=NOW)
    with pytest.raises(ValueError):
        perf.seasonality(db, "SPX", "trading_day", today=NOW)
    with pytest.raises(ValueError):
        perf.returns(db, ["AAA"], "fortnight", today=NOW)
