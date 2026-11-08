"""Daily closes: the day's prices as traded, captured each evening, never overwritten."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.md import closes
from app.md.closes import (
    DailyClosesService,
    track_fund,
    tracked,
    universe,
    untrack_fund,
)
from app.md.models import (
    IndexDef,
    IndexMember,
    IndexMemberHist,
    JobRun,
    Market,
    PriceDailyHist,
    Security,
    SecuritySymbol,
    TrackedFund,
)
from app.md.schedule import in_quiet_hours
from app.md.status_report import build_status
from app.md.webull import WebullInvalidSymbols, WebullRefused, WebullUnreachable

FRIDAY = date(2026, 11, 6)
# The regular session's last trade on that Friday, 4 PM Eastern.
CLOSE_MS = int(datetime(2026, 11, 6, 21, 0, tzinfo=timezone.utc).timestamp() * 1000)
EVENING = datetime(2026, 11, 7, 1, 30, tzinfo=timezone.utc)  # 8:30 PM Eastern, Friday
DURING = datetime(2026, 11, 6, 18, 0, tzinfo=timezone.utc)  # 1 PM Eastern, Friday
NEXT_MORNING = datetime(2026, 11, 9, 11, 0, tzinfo=timezone.utc)  # Monday, 6 AM


class FakeSnapshots:
    """Answers like Webull's snapshot endpoint, from what each test puts in it."""

    def __init__(self, prices, known=None, refuse_after=None, silent=False, stamp=None):
        self.prices = prices  # Webull spelling -> close
        self.known = known  # category -> set of Webull spellings it knows
        self.refuse_after = refuse_after
        self.silent = silent
        self.stamp = stamp or CLOSE_MS
        self.requests = 0
        self.asked = []

    def configured(self):
        return True

    def get(self, path, query):
        self.requests += 1
        if self.refuse_after is not None and self.requests > self.refuse_after:
            raise WebullRefused(path)
        if self.silent:
            raise WebullUnreachable(path)
        symbols = query["symbols"].split(",")
        category = query["category"]
        self.asked.append((category, symbols))
        if self.known is not None:
            unknown = {s for s in symbols if s not in self.known.get(category, set())}
            if unknown:
                raise WebullInvalidSymbols(path, unknown)
        return [
            {
                "symbol": s,
                "open": "9.5",
                "high": "10.5",
                "low": "9.0",
                "close": str(self.prices[s]),
                "volume": "1000",
                "last_trade_time": self.stamp,
            }
            for s in symbols
            if s in self.prices
        ]


def _security(db, symbol, kind="stock", market="US", status="active"):
    security = Security(name=symbol, kind=kind, market_code=market, status=status)
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol, market_code=market))
    db.flush()
    return security


def _member(db, security, left=False):
    if not db.get(IndexDef, "XYZ"):
        db.add(
            IndexDef(code="XYZ", name="Example", owner="Example", method="fund_file")
        )
        db.flush()
    db.add(
        IndexMemberHist(
            index_code="XYZ",
            security_id=security.id,
            valid_from=date(2026, 1, 2),
            valid_to=date(2026, 6, 1) if left else None,
        )
    )
    if not left:
        db.add(
            IndexMember(
                index_code="XYZ", security_id=security.id, since=date(2026, 1, 2)
            )
        )
    db.flush()


def _run(db, client, now=EVENING):
    note = DailyClosesService(db, client).run(now)
    return (
        note,
        db.query(JobRun)
        .filter(JobRun.job == closes.JOB)
        .order_by(JobRun.started_at.desc())
        .first(),
    )


def _closes(db):
    return {
        (symbol, row.price_date): row.close
        for row, symbol in db.query(PriceDailyHist, SecuritySymbol.symbol).join(
            SecuritySymbol, SecuritySymbol.security_id == PriceDailyHist.security_id
        )
    }


def test_who_is_priced(db):
    member = _security(db, "AAA")
    _member(db, member)
    leaver = _security(db, "BBB")
    _member(db, leaver, left=True)
    _security(db, "CCC")  # held only: priced by the app, not here
    fund = _security(db, "FFF", kind="etf")
    db.add(TrackedFund(security_id=fund.id, asset_group="gold", added_on=FRIDAY))
    dropped = _security(db, "GGG", kind="etf")
    db.add(
        TrackedFund(
            security_id=dropped.id,
            asset_group="gold",
            added_on=FRIDAY,
            removed_on=FRIDAY,
        )
    )
    mutual = _security(db, "MMMMX", kind="fund")
    _member(db, mutual)
    gone = _security(db, "DDD", status="delisted")
    _member(db, gone)
    db.add(
        Market(
            code="XABC",
            name="Example",
            country="GB",
            currency="GBP",
            timezone="Europe/London",
        )
    )
    abroad = _security(db, "EEE", market="XABC")
    _member(db, abroad)
    assert [row[1] for row in universe(db)] == ["AAA", "BBB", "FFF"]


def test_an_evening_run_records_the_day_as_traded(db):
    stock = _security(db, "XYZ.B")
    _member(db, stock)
    fund = _security(db, "FFF", kind="etf")
    db.add(TrackedFund(security_id=fund.id, asset_group="gold", added_on=FRIDAY))
    client = FakeSnapshots({"XYZ B": "10.25", "FFF": "50"})
    note, run = _run(db, client)
    assert _closes(db) == {
        ("XYZ.B", FRIDAY): Decimal("10.25"),
        ("FFF", FRIDAY): Decimal("50"),
    }
    assert ("US_ETF", ["FFF"]) in client.asked and (
        "US_STOCK",
        ["XYZ B"],
    ) in client.asked
    row = db.query(PriceDailyHist).filter(PriceDailyHist.security_id == stock.id).one()
    assert (row.open, row.high, row.low, row.volume) == (
        Decimal("9.5"),
        Decimal("10.5"),
        Decimal("9.0"),
        1000,
    )
    assert row.currency == "USD" and row.source == "webull_snapshot"
    assert run.outcome == "ok" and run.rows_written == 2 and run.requests == 2
    assert note.startswith("Closes for 2026-11-06: 2 recorded of 2 securities")


def test_a_day_on_file_is_never_overwritten(db):
    stock = _security(db, "AAA")
    _member(db, stock)
    _run(db, FakeSnapshots({"AAA": "10"}))
    # A holiday: the snapshot still shows Friday, at another price.
    note, run = _run(db, FakeSnapshots({"AAA": "11"}), NEXT_MORNING)
    assert _closes(db) == {("AAA", FRIDAY): Decimal("10")}
    assert "1 already on file" in note and run.rows_written == 0


def test_a_price_still_moving_is_not_stored(db):
    stock = _security(db, "AAA")
    _member(db, stock)
    midday = int(DURING.timestamp() * 1000)
    note, _ = _run(db, FakeSnapshots({"AAA": "10"}, stamp=midday), DURING)
    assert _closes(db) == {} and "1 not final yet" in note
    # The same snapshot read after the next morning is Friday's, and final.
    _run(db, FakeSnapshots({"AAA": "10"}, stamp=midday), NEXT_MORNING)
    assert _closes(db) == {("AAA", FRIDAY): Decimal("10")}


def test_an_unknown_symbol_is_dropped_and_the_rest_priced(db):
    for symbol in ("AAA", "BBB", "ZZZ"):
        _member(db, _security(db, symbol))
    client = FakeSnapshots({"AAA": 1, "BBB": 2}, known={"US_STOCK": {"AAA", "BBB"}})
    note, run = _run(db, client)
    assert set(_closes(db)) == {("AAA", FRIDAY), ("BBB", FRIDAY)}
    assert "1 unknown to Webull (ZZZ)" in note and run.outcome == "ok"


def test_a_fund_filed_as_a_stock_is_asked_as_a_fund(db):
    _member(db, _security(db, "FFF"))  # kind says stock; Webull knows it as an ETF
    client = FakeSnapshots({"FFF": 5}, known={"US_ETF": {"FFF"}, "US_STOCK": set()})
    note, _ = _run(db, client)
    assert _closes(db) == {("FFF", FRIDAY): Decimal("5")}
    assert "unknown" not in note


def test_a_refusal_stops_the_night_and_keeps_what_was_captured(db, monkeypatch):
    monkeypatch.setattr(closes, "BATCH", 2)
    for symbol in ("AAA", "BBB", "CCC", "DDD"):
        _member(db, _security(db, symbol))
    client = FakeSnapshots({s: 1 for s in ("AAA", "BBB", "CCC", "DDD")}, refuse_after=1)
    note, run = _run(db, client)
    assert set(_closes(db)) == {("AAA", FRIDAY), ("BBB", FRIDAY)}
    assert run.outcome == "failed" and "Webull refused" in note
    assert client.requests == 2  # no retry after a refusal


def test_no_answer_stops_after_three_tries(db, monkeypatch):
    monkeypatch.setattr(closes, "BATCH", 1)
    for symbol in ("AAA", "BBB", "CCC", "DDD", "EEE"):
        _member(db, _security(db, symbol))
    client = FakeSnapshots({}, silent=True)
    note, run = _run(db, client)
    assert client.requests == 3 and run.outcome == "failed"
    assert "not answering" in note


def test_tracking_a_fund_adds_it_and_stopping_keeps_its_prices(db):
    track_fund(db, "slv", "silver", FRIDAY)
    fund = db.query(SecuritySymbol).filter(SecuritySymbol.symbol == "SLV").one()
    assert db.get(Security, fund.security_id).kind == "etf"
    assert list(tracked(db)) == [("SLV", "silver")]
    _run(db, FakeSnapshots({"SLV": "30"}))
    assert untrack_fund(db, "SLV", FRIDAY) is True
    assert untrack_fund(db, "SLV", FRIDAY) is False
    assert list(tracked(db)) == [] and _closes(db) == {("SLV", FRIDAY): Decimal("30")}
    track_fund(db, "SLV", "precious", FRIDAY)  # tracked again, under a new group
    assert list(tracked(db)) == [("SLV", "precious")]
    assert db.query(Security).count() == 1


def test_the_market_data_page_shows_the_latest_day(db):
    _member(db, _security(db, "AAA"))
    _member(db, _security(db, "BBB"))
    _run(db, FakeSnapshots({"AAA": "10"}))
    measures = {
        m["label"]: m for m in build_status(db, False, EVENING)["coverage"]["measures"]
    }
    close = measures["Close on 2026-11-06"]
    assert (close["count"], close["of"]) == (1, 2)


@pytest.mark.parametrize(
    "when, quiet",
    [
        (datetime(2026, 11, 6, 14, 0, tzinfo=timezone.utc), True),  # Fri 9 AM Eastern
        (datetime(2026, 11, 6, 23, 30, tzinfo=timezone.utc), False),  # Fri 6:30 PM
        (datetime(2026, 11, 7, 15, 0, tzinfo=timezone.utc), False),  # Saturday
        (datetime(2026, 11, 9, 13, 0, tzinfo=timezone.utc), False),  # Mon 8 AM
    ],
)
def test_quiet_hours(when, quiet):
    assert in_quiet_hours(when) is quiet
