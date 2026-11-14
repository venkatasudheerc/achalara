"""Vanguard's activity report: only the rows not already on file are added.

Every account, ticker and figure here is invented.
"""
from datetime import date, datetime, timezone
from decimal import Decimal as D

import pytest

from app.connectors.models import NormalizedCashActivity, NormalizedTrade, TradeAction
from app.models.account import Account
from app.models.brokerage_connection import (
    BrokerageAccount,
    BrokerageActivity,
    BrokerageConnection,
)
from app.models.cash_activity import CashActivity
from app.models.client import Client
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services.cash_activity_service import CashActivityService
from app.services.connection_service import ConnectionService
from app.services.ingestion_service import IngestionService
from app.services.vanguard_report import (
    ReportError,
    VanguardReportImport,
    parse_rows,
    read_report,
    read_rows,
)

HEADER = (
    "Settlement date", "Trade date", "Symbol", "Name", "Type", "Account type",
    "Quantity", "Price", "Commission & fees**", "Amount",
)


def _sheet(*rows):
    """A report as Vanguard lays it out: two lines of notes, a blank, the header."""
    return [
        ("Custom report created on: 11/12/2026.",) + (None,) * 9,
        ("This report only includes transactions that were settled from: ...",) + (None,) * 9,
        (None,) * 10,
        HEADER,
        *rows,
        ("**The fees displayed include ...",) + (None,) * 9,
    ]


def _row(traded, symbol, name, kind, account_type, qty="", price="", fees="", amount=""):
    return (traded, traded, symbol, name, kind, account_type, qty, price, fees, amount)


@pytest.fixture
def account(db):
    owner = Client(name="Pat Example", email="pat@example.com")
    db.add(owner)
    db.flush()
    acct = Account(client_id=owner.id, name="Pat Example — Brokerage Account")
    strategy = Strategy(name="Stocks")
    db.add_all([acct, strategy])
    db.flush()
    sleeve = Sleeve(account_id=acct.id, strategy_id=strategy.id)
    db.add(sleeve)
    db.flush()
    connection = BrokerageConnection(
        client_id=owner.id, source="snaptrade", external_user_id="u",
        external_connection_id="c",
    )
    db.add(connection)
    db.flush()
    ba = BrokerageAccount(
        connection_id=connection.id, external_account_ref="ref",
        name="Pat Example — Brokerage Account — 12345678", number_last4="5678",
        account_id=acct.id, default_sleeve_id=sleeve.id, status="mapped",
    )
    db.add(ba)
    db.commit()
    return ba


def _on_file(db, ba, day, symbol, action, qty, price, notes="", ext=None):
    db.add(
        Trade(
            sleeve_id=ba.default_sleeve_id, trade_date=day, symbol=symbol,
            action=action, quantity=D(str(qty)), price=D(str(price)),
            commission=D(0), notes=notes, external_id=ext or f"snap:{symbol}:{day}:{qty}",
        )
    )


def _importer(db):
    return VanguardReportImport(db, ConnectionService(db, connector=object()))


def test_the_sheet_is_read_below_its_header_and_its_money_columns_as_numbers():
    rows = parse_rows(
        _sheet(
            _row("10/5/2026", "AAA", "AAA CORP", "Buy", "MARGIN", "2,000.0000", "$12.3400", "Free", "-$24,680.0000"),
            _row("10/6/2026", "—", "CASH", "Fee", "CASH", "—", "—", "—", "-$0.0200"),
        )
    )
    assert [r.line for r in rows] == [5, 6]
    buy, fee = rows
    assert buy.traded == date(2026, 10, 5)
    assert (buy.quantity, buy.price, buy.fees, buy.amount) == (D("2000"), D("12.34"), D(0), D("-24680"))
    assert fee.symbol == "" and fee.quantity is None and fee.amount == D("-0.02")


def test_a_file_without_the_report_header_is_refused():
    with pytest.raises(ReportError):
        parse_rows([("Date", "Symbol", "Amount")])


def test_the_excel_download_is_read(tmp_path):
    from openpyxl import Workbook

    book = Workbook()
    for line in _sheet(_row("10/5/2026", "AAA", "AAA CORP", "Sell", "MARGIN", "-5.0000", "$10.0000", "$0.0200", "$49.9800")):
        book.active.append(list(line))
    path = tmp_path / "customActivityReport_12345678.xlsx"
    book.save(path)
    (row,) = read_report(path)
    assert (row.kind, row.quantity, row.amount) == ("Sell", D("-5"), D("49.98"))


def test_only_what_is_missing_is_planned(db, account):
    ba = account
    # On file: a trade on its own day, one under the feed's spelling of a
    # renamed ticker, an expiry and the shares an assignment delivered dated the
    # next trading day, and a dividend two days late.
    _on_file(db, ba, date(2026, 10, 1), "AAA", "BUY", 10, "50.00")
    _on_file(db, ba, date(2026, 10, 1), "NEWNAME", "SELL", 20, "30.00")
    _on_file(db, ba, date(2026, 10, 12), "BBB261009P00010000", "BUY", 2, 0, notes="Expired: PUT BBB")
    _on_file(db, ba, date(2026, 10, 12), "CCC261009P00005000", "BUY", 3, 0, notes="Assignment: PUT CCC")
    _on_file(db, ba, date(2026, 10, 12), "CCC", "BUY", 300, "5.00")
    db.add(CashActivity(sleeve_id=ba.default_sleeve_id, activity_date=date(2026, 10, 3),
                        type="DIVIDEND", symbol="AAA", amount=D("12.50"), external_id="snap:div"))
    db.commit()

    rows = parse_rows(
        _sheet(
            _row("10/1/2026", "AAA", "AAA CORP", "Buy", "MARGIN", "10.0000", "$50.0000", "Free", "-$500.0000"),
            _row("10/1/2026", "OLDNAME", "OLDNAME INC", "Sell", "MARGIN", "-20.0000", "$30.0049", "$0.0200", "$600.0800"),
            _row("10/9/2026", "BBB261009P00010000", "PUT BBB $10", "Expired", "SHORT", "2.0000"),
            _row("10/9/2026", "DDD261009P00010000", "PUT DDD $10", "Expired", "SHORT", "2.0000"),
            _row("10/9/2026", "CCC261009P00005000", "PUT CCC $5", "Assignment", "SHORT", "3.0000"),
            _row("10/9/2026", "CCC", "CCC INC", "Buy", "MARGIN", "300.0000", "$5.0000", "Free", "-$1,500.0000"),
            _row("10/1/2026", "AAA", "AAA CORP", "Dividend", "MARGIN", amount="$12.5000"),
            # A day the feed never sent.
            _row("10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN", "4.0000", "$25.0000", "Free", "-$100.0000"),
            _row("10/5/2026", "FFF", "FFF CORP", "Dividend", "MARGIN", amount="$3.0000"),
            # Within the account: never activity.
            _row("10/5/2026", "VMFXX", "Settlement Fund", "Sweep in", "CASH", amount="-$97.0000"),
            _row("10/5/2026", "", "CASH", "Transfer (Outgoing)", "MARGIN", amount="-$97.0000"),
            _row("10/5/2026", "", "CASH", "Transfer (incoming)", "CASH", amount="$97.0000"),
            _row("10/6/2026", "GGG", "GGG INC", "Corp Action (Merger)", "MARGIN", "-10.0000", amount="$400.0000"),
        )
    )
    plan = _importer(db).plan(ba, rows)

    assert [(t.symbol, t.action.value, t.quantity) for _, t in plan.trades] == [
        ("DDD261009P00010000", "BUY", D(2)),  # another contract expiring that day
        ("EEE", "BUY", D(4)),
        ("GGG", "SELL", D(10)),  # taken over for cash
    ]
    assert [(c.type, c.amount) for _, c in plan.cash] == [("DIVIDEND", D(3))]
    assert plan.held_trades == 5 and plan.held_cash == 1
    assert plan.skipped == {"sweep": 1, "internal transfer": 2}
    assert plan.needs_a_look == []
    eee = plan.trades[1][1]
    assert eee.price == D(25) and eee.security_type == "ETF"


def test_an_option_trade_is_priced_per_contract():
    rows = parse_rows(_sheet(
        _row("10/5/2026", "HHH261218P00020000", "PUT HHH $20", "Sell to open", "SHORT", "-5.0000", "$1.2500", "$5.0300", "$619.9700"),
    ))
    ((_, trade),) = read_rows(rows)[0]
    assert (trade.action, trade.quantity, trade.price, trade.security_type) == (
        TradeAction.SELL, D(5), D(125), "OPTION",
    )


def test_applying_adds_the_rows_once_and_keeps_their_cash_for_the_ledger(db, account):
    ba = account
    rows = parse_rows(_sheet(
        _row("10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN", "4.0000", "$25.0000", "Free", "-$100.0000"),
        _row("10/5/2026", "FFF", "FFF CORP", "Dividend", "MARGIN", amount="$3.0000"),
    ))
    importer = _importer(db)
    result = importer.apply(ba, importer.plan(ba, rows))
    assert (result["imported"], result["cash_imported"]) == (1, 1)

    stored = db.query(BrokerageActivity).filter(BrokerageActivity.brokerage_account_id == ba.id).all()
    assert sorted(r.cash_amount for r in stored) == [D("-100"), D("3")]
    assert all(r.source_activity_id.startswith("vanguard:") for r in stored)

    again = importer.plan(ba, rows)
    assert not again.trades and not again.cash


def test_the_feed_later_sending_a_day_the_report_filled_adds_nothing(db, account):
    ba = account
    rows = parse_rows(_sheet(
        _row("10/5/2026", "EEE", "EEE ETF", "Buy", "MARGIN", "4.0000", "$25.0000", "Free", "-$100.0000"),
        _row("10/5/2026", "EEE", "EEE ETF", "Sell", "MARGIN", "-4.0000", "$25.0000", "$0.0200", "$99.9800"),
        _row("10/5/2026", "FFF", "FFF CORP", "Dividend", "MARGIN", amount="$3.0000"),
    ))
    importer = _importer(db)
    importer.apply(ba, importer.plan(ba, rows))

    when = datetime(2026, 10, 5, tzinfo=timezone.utc)
    feed = [
        NormalizedTrade(external_id=f"snap-{a}", symbol="EEE", action=a, quantity=D(4),
                        price=D(25), executed_at=when, source="snaptrade")
        for a in (TradeAction.BUY, TradeAction.SELL)
    ]
    result = IngestionService(db).ingest_to_sleeve(
        feed, ba.default_sleeve_id, import_type="BROKERAGE"
    )
    assert (result["imported"], result["duplicates"]) == (0, 2)

    cash = CashActivityService(db).ingest(
        [NormalizedCashActivity(external_id="snap-div", type="DIVIDEND", amount=D(3),
                                occurred_at=when, symbol="FFF", source="snaptrade")],
        ba.default_sleeve_id,
    )
    assert cash["imported"] == 0



def test_splits_and_mergers_are_read_as_the_feed_read_them(db, account):
    """A split adds shares, and its ratio comes from what was held; a merger for
    cash is a sale at the cash per share; an exchange for shares is two legs
    whose cost carries across; a merger row without a symbol takes the
    symbol another row gives the same company."""
    from app.models.perf import CorporateAction
    from app.services.corporate_actions import MERGER_NOTE

    ba = account
    rows = parse_rows(
        _sheet(
            _row("2/1/2024", "WWW", "WWW STORES INC", "Buy", "MARGIN", "20.0000", "$150.0000", "Free", "-$3,000.0000"),
            _row("2/26/2024", "WWW", "WWW STORES INC", "Stock split", "MARGIN", "40.0000"),
            _row("3/1/2024", "DDDX", "DEEPCO PHARMACEUTICALS INC", "Buy", "MARGIN", "50.0000", "$20.0000", "Free", "-$1,000.0000"),
            _row("6/13/2024", "", "DEEPCO           CHG PHARMACEUTICALS", "Corp Action (Merger)", "MARGIN", "-50.0000", amount="$1,250.0000"),
            _row("4/1/2025", "OLDH", "OLD HOUSE INC", "Buy", "MARGIN", "100.0000", "$5.0000", "Free", "-$500.0000"),
            _row("1/9/2026", "NEWH", "NEW HOUSE INC CL A", "Corp Action (Merger)", "MARGIN", "150.0000"),
            _row("1/9/2026", "OLDH", "OLD HOUSE INC", "Corp Action (Merger)", "MARGIN", "-100.0000"),
        )
    )
    importer = _importer(db)
    plan = importer.plan(ba, rows)
    assert plan.needs_a_look == []
    assert [(r.symbol, r.quantity) for r in plan.splits] == [("WWW", D(40))]
    mergers = {t.symbol: (t.action.value, t.quantity, t.price) for _, t in plan.trades if t.notes.startswith(MERGER_NOTE)}
    assert mergers == {
        "DDDX": ("SELL", D(50), D(25)),
        "NEWH": ("BUY", D(150), D(0)),
        "OLDH": ("SELL", D(100), D(0)),
    }

    importer.apply(ba, plan)

    (split,) = db.query(CorporateAction).filter(CorporateAction.symbol == "WWW").all()
    assert (split.effective_date, split.ratio) == (date(2024, 2, 26), D(3))
    # The shares given up carried their cost to the shares received.
    legs = {t.symbol: t for t in db.query(Trade).filter(Trade.notes.like(f"{MERGER_NOTE}%"))}
    assert abs(legs["OLDH"].price * legs["OLDH"].quantity - D(500)) < D("0.01")
    assert abs(legs["NEWH"].price * legs["NEWH"].quantity - D(500)) < D("0.01")
    # Read again, the split is on file and nothing is added twice.
    again = importer.plan(ba, rows)
    assert again.splits == [] and again.held_splits == 1 and again.trades == []
