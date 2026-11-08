"""Adjusted history: loaded in full once, topped up nightly, refreshed when rewritten."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.md import adjusted
from app.md.adjusted import AdjustedHistoryService, earliest_kept, prune_prices
from app.md.models import (
    IndexDef,
    IndexMember,
    IndexMemberHist,
    JobRun,
    PriceAdjDaily,
    PriceDailyHist,
    Security,
    SecuritySymbol,
)
from app.md.status_report import build_status
from app.md.webull import WebullInvalidSymbols, WebullRefused

EVENING = datetime(
    2026, 11, 7, 1, 30, tzinfo=timezone.utc
)  # Fri 6 Nov, 8:30 PM Eastern
FRIDAY = date(2026, 11, 6)


def days(n, last=FRIDAY):
    """The last ``n`` weekdays up to ``last``, oldest first."""
    out, day = [], last
    while len(out) < n:
        if day.weekday() < 5:
            out.append(day)
        day -= timedelta(days=1)
    return out[::-1]


class FakeBars:
    """Webull's bars endpoint over a 'true' series per symbol, keeping only ``window`` days."""

    def __init__(self, series, window=None, known=None, refuse_after=None):
        self.series = series  # Webull spelling -> {date: close}
        self.window = window
        self.known = known
        self.refuse_after = refuse_after
        self.requests = 0
        self.bodies = []

    def configured(self):
        return True

    def post(self, path, body):
        self.requests += 1
        self.bodies.append(body)
        if self.refuse_after is not None and self.requests > self.refuse_after:
            raise WebullRefused(path)
        if self.known is not None:
            unknown = {s for s in body["symbols"] if s not in self.known}
            if unknown:
                raise WebullInvalidSymbols(path, unknown)
        result = []
        for symbol in body["symbols"]:
            kept = sorted(self.series.get(symbol, {}).items())
            if self.window:
                kept = kept[-self.window :]
            if "end_time" in body:
                end = datetime.fromtimestamp(
                    body["end_time"] / 1000, timezone.utc
                ).date()
                kept = [(d, c) for d, c in kept if d < end + timedelta(days=1)]
            kept = kept[-body["count"] :]
            result.append(
                {
                    "symbol": symbol,
                    "result": [
                        {"time": f"{d.isoformat()}T05:00:00.000+0000", "close": str(c)}
                        for d, c in reversed(kept)
                    ],
                }
            )
        return {"result": result}


def _security(db, symbol, kind="stock"):
    security = Security(name=symbol, kind=kind)
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    if not db.get(IndexDef, "XYZ"):
        db.add(
            IndexDef(code="XYZ", name="Example", owner="Example", method="fund_file")
        )
        db.flush()
    db.add(
        IndexMemberHist(index_code="XYZ", security_id=security.id, valid_from=FRIDAY)
    )
    db.add(IndexMember(index_code="XYZ", security_id=security.id, since=FRIDAY))
    db.flush()
    return security


def _stored(db, security):
    return {
        row.price_date: row.adj_close
        for row in db.query(PriceAdjDaily).filter(
            PriceAdjDaily.security_id == security.id
        )
    }


def _run(db, client, now=EVENING):
    note = AdjustedHistoryService(db, client).run(now)
    run = (
        db.query(JobRun)
        .filter(JobRun.job == adjusted.JOB)
        .order_by(JobRun.started_at.desc())
        .first()
    )
    return note, run


def test_a_new_security_gets_everything_webull_keeps(db, monkeypatch):
    monkeypatch.setattr(adjusted, "FULL", 5)  # so two pages are needed
    stock = _security(db, "AAA")
    truth = {d: Decimal(i + 10) for i, d in enumerate(days(8))}
    note, run = _run(db, FakeBars({"AAA": truth}))
    assert _stored(db, stock) == truth
    assert run.outcome == "ok" and "1 loaded in full" in note
    assert run.requests == 2  # the latest page, then the one before it


def test_the_days_on_file_agreeing_only_new_days_are_added(db):
    stock = _security(db, "AAA")
    history = {d: Decimal(i + 10) for i, d in enumerate(days(12))}
    first = {d: c for d, c in history.items() if d < FRIDAY}
    _run(db, FakeBars({"AAA": first}))
    note, run = _run(db, FakeBars({"AAA": history}))
    assert _stored(db, stock) == history
    assert run.rows_written == 1 and "1 of 1 topped up" in note


def test_a_rewritten_series_is_refreshed_and_older_days_rescaled(db, monkeypatch):
    """A 2-for-1 split halves every earlier adjusted close at the source. Days on file
    beyond the source's window must be halved too, or a return across them is wrong."""
    monkeypatch.setattr(adjusted, "FULL", 6)
    stock = _security(db, "AAA")
    span = days(10)
    before = {d: Decimal(100 + i) for i, d in enumerate(span[:-1])}
    _run(db, FakeBars({"AAA": before}))  # all 9 days on file
    after = {d: c / 2 for d, c in before.items()}
    after[span[-1]] = Decimal("55")
    # The source now keeps only its last 6 days.
    note, run = _run(db, FakeBars({"AAA": after}, window=6))
    stored = _stored(db, stock)
    assert stored == {d: (after[d]) for d in span}  # older days halved, window replaced
    assert "1 rewritten by the source" in note and run.outcome == "ok"


def test_a_day_not_over_is_left_for_the_evening(db):
    stock = _security(db, "AAA")
    history = {d: Decimal(i + 10) for i, d in enumerate(days(3))}
    midday = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)
    _run(db, FakeBars({"AAA": history}), now=midday)
    assert FRIDAY not in _stored(db, stock) and len(_stored(db, stock)) == 2


def test_an_unknown_symbol_is_dropped_and_the_rest_loaded(db):
    stock = _security(db, "AAA")
    _security(db, "ZZZ")
    history = {d: Decimal(i + 10) for i, d in enumerate(days(3))}
    note, _ = _run(db, FakeBars({"AAA": history}, known={"AAA"}))
    assert _stored(db, stock) == history and "1 unknown to Webull (ZZZ)" in note


def test_a_refusal_stops_for_the_night(db, monkeypatch):
    monkeypatch.setattr(adjusted, "BATCH", 1)
    for symbol in ("AAA", "BBB", "CCC"):
        _security(db, symbol)
    history = {d: Decimal(10) for d in days(3)}
    client = FakeBars({s: history for s in ("AAA", "BBB", "CCC")}, refuse_after=1)
    note, run = _run(db, client)
    assert run.outcome == "failed" and "Webull refused" in note
    assert db.query(PriceAdjDaily.security_id).distinct().count() == 1


def test_bar_dates_are_market_days_in_summer_and_winter(db):
    stock = _security(db, "AAA")
    client = FakeBars({})
    summer = {
        "symbol": "AAA",
        "result": [{"time": "2026-07-02T04:00:00.000+0000", "close": "5"}],
    }
    client.post = lambda path, body: {"result": [summer]}
    _run(db, client)
    assert list(_stored(db, stock)) == [date(2026, 7, 2)]


@pytest.mark.parametrize(
    "years, expected", [(0, None), (3, date(2023, 11, 6)), (1, date(2025, 11, 6))]
)
def test_the_history_limit_is_off_by_default(years, expected):
    assert earliest_kept(FRIDAY, years) == expected


def test_the_limit_removes_only_stock_and_fund_prices(db):
    stock = _security(db, "AAA")
    old, recent = date(2022, 1, 3), FRIDAY
    for day in (old, recent):
        db.add(
            PriceAdjDaily(
                security_id=stock.id, price_date=day, adj_close=1, fetched_at=EVENING
            )
        )
        db.add(
            PriceDailyHist(
                security_id=stock.id,
                price_date=day,
                currency="USD",
                close=1,
                source="test",
            )
        )
    db.flush()
    assert "nothing removed" in prune_prices(db, FRIDAY, 0)
    assert db.query(PriceAdjDaily).count() == 2
    assert prune_prices(db, FRIDAY, 3).startswith("Removed 2 price rows")
    assert {r.price_date for r in db.query(PriceAdjDaily)} == {recent}
    assert {r.price_date for r in db.query(PriceDailyHist)} == {recent}
    assert db.query(IndexMemberHist).count() == 1  # never pruned


def test_the_market_data_page_shows_adjusted_coverage(db):
    _security(db, "AAA")
    _security(db, "BBB")
    _run(db, FakeBars({"AAA": {d: Decimal(10) for d in days(3)}}))
    measures = {
        m["label"]: m for m in build_status(db, False, EVENING)["coverage"]["measures"]
    }
    label = next(k for k in measures if k.startswith("Adjusted history"))
    assert (measures[label]["count"], measures[label]["of"]) == (1, 2)
