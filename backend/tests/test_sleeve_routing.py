"""Each kind of security goes to its own strategy: stocks, ETFs, mutual funds,
options, and cash that belongs to no security.

Offline. Accounts are fed through the Plaid reader and the real ingest, as a
refresh does; every name and figure is invented.
"""
from datetime import date
from decimal import Decimal

from app.connectors import plaid_reader
from app.connectors.models import NormalizedPosition
from app.models.account import Account
from app.models.brokerage_connection import (
    BrokerageAccount,
    BrokerageConnection,
)
from app.models.cash_activity import CashActivity
from app.models.client import Client
from app.models.perf import DailyHolding, DailyValuation
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services import sleeve_routing as routing
from app.services import strategy_split
from app.services.connection_service import ConnectionService
from app.services.daily_capture_service import DailyCaptureService
from app.services.performance_build_service import last_market_day
from app.services.trade_reassignment import reassign_symbols

D = Decimal

SECURITIES = {
    "s-aaa": {"security_id": "s-aaa", "ticker_symbol": "AAA", "type": "equity"},
    "s-bbb": {"security_id": "s-bbb", "ticker_symbol": "BBB", "type": "etf"},
    "s-fff": {"security_id": "s-fff", "ticker_symbol": "FFFXX", "type": "mutual fund"},
    "s-opt": {"security_id": "s-opt", "ticker_symbol": "AAA270115C00020000", "type": "derivative"},
    "s-oth": {"security_id": "s-oth", "ticker_symbol": "OOO", "type": "fixed income"},
}


def _cash(row_id, subtype, amount, day, security_id=None):
    """Plaid reports money into the account as a negative amount."""
    row = {"investment_transaction_id": row_id, "account_id": "a", "type": "cash",
           "subtype": subtype, "date": day, "amount": -amount, "quantity": 0,
           "price": 0, "fees": 0, "name": subtype.title()}
    if security_id:
        row["security_id"] = security_id
    return row


def _buy(row_id, security_id, quantity, price, day):
    return {"investment_transaction_id": row_id, "account_id": "a", "type": "buy",
            "subtype": "buy", "date": day, "security_id": security_id, "quantity": quantity,
            "price": price, "amount": quantity * price, "fees": 0, "name": "Buy"}


ROWS = [
    _cash("c1", "deposit", 50000, "2026-01-05"),
    _cash("c2", "interest", 4, "2026-01-05"),
    _buy("b1", "s-aaa", 10, 100, "2026-01-06"),
    _buy("b2", "s-bbb", 20, 50, "2026-01-06"),
    _buy("b3", "s-fff", 30, 10, "2026-01-06"),
    _buy("b4", "s-opt", 1, 2, "2026-01-06"),
    _buy("b5", "s-oth", 5, 20, "2026-01-06"),
    _cash("c3", "dividend", 7, "2026-01-07", "s-bbb"),
]


def _brokerage(db, name="Pat — Brokerage Account", kind=None):
    owner = Client(name="Pat", email="pat@example.com")
    db.add(owner)
    db.flush()
    account = Account(client_id=owner.id, name=name, kind=kind)
    db.add(account)
    db.flush()
    login = BrokerageConnection(client_id=owner.id, source="plaid", external_user_id=owner.id,
                                external_connection_id=f"item-{account.id}", institution="Example")
    db.add(login)
    db.flush()
    ba = BrokerageAccount(connection_id=login.id, external_account_ref="a", name=name,
                          account_id=account.id, status="mapped",
                          transactions_synced_through=date(2026, 1, 8))
    db.add(ba)
    db.flush()
    return account, ba


def _by_strategy(db, account):
    """Symbols and cash rows, by the strategy of the sleeve holding them."""
    names = {
        s.id: db.get(Strategy, s.strategy_id).name
        for s in db.query(Sleeve).filter(Sleeve.account_id == account.id)
    }
    trades, cash = {}, {}
    for t in db.query(Trade).filter(Trade.sleeve_id.in_(names)):
        trades.setdefault(names[t.sleeve_id], set()).add(t.symbol)
    for c in db.query(CashActivity).filter(CashActivity.sleeve_id.in_(names)):
        cash.setdefault(names[c.sleeve_id], set()).add((c.type, c.symbol))
    return trades, cash


def _ingest(db, ba, rows=ROWS):
    batch = plaid_reader.read_investment_transactions(rows, SECURITIES)
    ConnectionService(db).ingest_batch(ba, batch)


def _fed(db):
    account, ba = _brokerage(db)
    ba.default_sleeve_id, ba.sleeve_routes = routing.set_up(db, account)
    db.commit()
    _ingest(db, ba)
    return account, ba


# ---------------------------------------------------------------------------
# New accounts
# ---------------------------------------------------------------------------


def test_an_invested_account_gets_a_sleeve_for_each_strategy(db):
    account, ba = _brokerage(db)
    default, routes = routing.set_up(db, account)

    names = {
        db.get(Strategy, s.strategy_id).name: s.id
        for s in db.query(Sleeve).filter(Sleeve.account_id == account.id)
    }
    assert set(names) == {"Stocks", "ETFs", "Mutual funds", "Options", "Cash"}
    assert default == names["Stocks"]
    assert routes["STOCK"] == routes["ADR"] == routes["OTHER"] == names["Stocks"]
    assert (routes["ETF"], routes["MUTUAL_FUND"], routes["OPTION"], routes["CASH"]) == (
        names["ETFs"], names["Mutual funds"], names["Options"], names["Cash"],
    )
    assert {s.accounting_method for s in db.query(Sleeve)} == {"FIFO"}


def test_setting_up_twice_reuses_what_is_there(db):
    account, _ = _brokerage(db)
    first = routing.set_up(db, account)
    second = routing.set_up(db, account)
    assert first == second
    assert db.query(Sleeve).filter(Sleeve.account_id == account.id).count() == 5
    assert db.query(Strategy).count() == 5


def test_a_bank_account_has_only_a_cash_sleeve(db):
    account, _ = _brokerage(db, name="Everyday Checking", kind="checking")
    default, routes = routing.set_up(db, account)
    sleeves = db.query(Sleeve).filter(Sleeve.account_id == account.id).all()
    assert [db.get(Strategy, s.strategy_id).name for s in sleeves] == ["Cash"]
    assert default == sleeves[0].id
    assert routes is None


def test_each_kind_of_security_goes_to_its_strategy(db):
    account, _ = _fed(db)
    trades, cash = _by_strategy(db, account)
    assert trades == {
        "Stocks": {"AAA", "OOO"},  # unclassified is read as a stock
        "ETFs": {"BBB"},
        "Mutual funds": {"FFFXX"},
        "Options": {"AAA270115C00020000"},
    }
    # Cash with no security is Cash; a dividend goes with its shares.
    assert cash["Cash"] == {("CONTRIBUTION", None), ("INTEREST", None)}
    assert cash["ETFs"] == {("DIVIDEND", "BBB")}


def test_a_dividend_on_shares_with_no_trade_in_the_rows_goes_to_their_strategy(db):
    account, ba = _brokerage(db)
    ba.default_sleeve_id, ba.sleeve_routes = routing.set_up(db, account)
    db.commit()
    _ingest(db, ba, [_cash("c9", "dividend", 3, "2026-01-07", "s-bbb")])
    _, cash = _by_strategy(db, account)
    assert cash == {"ETFs": {("DIVIDEND", "BBB")}}


def test_a_symbol_already_in_a_sleeve_stays_there_when_it_is_bought_again(db):
    account, ba = _fed(db)
    etfs = routing.sleeve_in(db, account.id, "ETFs")
    stocks = routing.sleeve_in(db, account.id, "Stocks")
    # Moved by hand: AAA is held in ETFs now.
    reassign_symbols(db, stocks.id, etfs.id, ["AAA"])
    _ingest(db, ba, [_buy("b9", "s-aaa", 1, 100, "2026-01-08")])
    trades, _ = _by_strategy(db, account)
    assert "AAA" in trades["ETFs"] and "AAA" not in trades["Stocks"]


def test_a_holding_nothing_traded_yet_is_recorded_under_its_strategy(db):
    account, ba = _fed(db)
    holdings = [
        NormalizedPosition(symbol="NEWFD", quantity=D(4), market_price=D(25),
                           avg_cost=D(20), security_type="MUTUAL_FUND"),
        NormalizedPosition(symbol="NEWST", quantity=D(2), market_price=D(10),
                           avg_cost=D(9), security_type="STOCK"),
    ]
    DailyCaptureService(db).record(ba, last_market_day(), holdings, D(1000), D(1120))
    names = {s.id: db.get(Strategy, s.strategy_id).name for s in db.query(Sleeve)}
    placed = {h.symbol: names[h.sleeve_id] for h in db.query(DailyHolding)}
    assert placed == {"NEWFD": "Mutual funds", "NEWST": "Stocks"}


def test_an_account_with_no_routes_keeps_everything_in_its_default_sleeve(db):
    """Accounts set up before routing, or by hand, behave exactly as they did."""
    account, ba = _brokerage(db)
    only = Sleeve(account_id=account.id, strategy_id=routing.strategy_named(db, "Growth").id,
                  accounting_method="FIFO")
    db.add(only)
    db.flush()
    ba.default_sleeve_id = only.id
    db.commit()
    _ingest(db, ba)
    assert {t.sleeve_id for t in db.query(Trade)} == {only.id}
    assert {c.sleeve_id for c in db.query(CashActivity)} == {only.id}


# ---------------------------------------------------------------------------
# Splitting an account linked as one sleeve
# ---------------------------------------------------------------------------


def _one_sleeve_account(db):
    """An account as linked before routing: everything in one "Unallocated" sleeve."""
    account, ba = _brokerage(db)
    sleeve = Sleeve(account_id=account.id, strategy_id=routing.strategy_named(db, "Unallocated").id,
                    accounting_method="FIFO")
    db.add(sleeve)
    db.flush()
    ba.default_sleeve_id = sleeve.id
    db.commit()
    _ingest(db, ba)
    holdings = [
        NormalizedPosition(symbol="AAA", quantity=D(10), market_price=D(100), avg_cost=D(100), security_type="STOCK"),
        NormalizedPosition(symbol="BBB", quantity=D(20), market_price=D(50), avg_cost=D(50), security_type="ETF"),
        NormalizedPosition(symbol="FFFXX", quantity=D(30), market_price=D(10), avg_cost=D(10), security_type="MUTUAL_FUND"),
    ]
    DailyCaptureService(db).record(ba, last_market_day(), holdings, D(47000), D(49300))
    return account, ba, sleeve


def _account_total(db, account):
    day = (
        db.query(DailyValuation)
        .filter(DailyValuation.account_id == account.id, DailyValuation.basis == "observed")
        .order_by(DailyValuation.as_of_date.desc())
        .first()
    )
    return day.as_of_date, day.total_value


def test_a_plan_says_what_would_move_and_writes_nothing(db):
    account, ba, sleeve = _one_sleeve_account(db)
    plan = strategy_split.plan(db, ba)

    assert plan.becomes == "Stocks"
    assert {m.to_strategy: m.symbols for m in plan.moves} == {
        "ETFs": ["BBB"], "Mutual funds": ["FFFXX"], "Options": ["AAA270115C00020000"],
    }
    assert plan.unnamed_cash == 2  # the deposit and the interest
    assert db.get(Strategy, sleeve.strategy_id).name == "Unallocated"
    assert db.query(Sleeve).filter(Sleeve.account_id == account.id).count() == 1
    assert ba.sleeve_routes is None


def test_splitting_moves_each_kind_out_and_keeps_the_accounts_own_figures(db):
    account, ba, sleeve = _one_sleeve_account(db)
    before = _account_total(db, account)
    held = {s: q for s, q in db.query(Trade.symbol, Trade.quantity)}

    strategy_split.apply(db, ba)

    trades, cash = _by_strategy(db, account)
    assert trades == {
        "Stocks": {"AAA", "OOO"},
        "ETFs": {"BBB"},
        "Mutual funds": {"FFFXX"},
        "Options": {"AAA270115C00020000"},
    }
    assert cash["Cash"] == {("CONTRIBUTION", None), ("INTEREST", None)}
    assert cash["ETFs"] == {("DIVIDEND", "BBB")}
    # The old sleeve is the Stocks sleeve now, so stock history did not move.
    assert db.get(Strategy, sleeve.strategy_id).name == "Stocks"
    assert ba.default_sleeve_id == sleeve.id
    assert ba.sleeve_routes["ETF"] != sleeve.id
    # Recorded holdings moved with their symbols.
    names = {s.id: db.get(Strategy, s.strategy_id).name for s in db.query(Sleeve)}
    assert {h.symbol: names[h.sleeve_id] for h in db.query(DailyHolding)} == {
        "AAA": "Stocks", "BBB": "ETFs", "FFFXX": "Mutual funds",
    }
    # Nothing was gained or lost by the sorting.
    assert _account_total(db, account) == before
    assert {s: q for s, q in db.query(Trade.symbol, Trade.quantity)} == held


def test_a_split_account_is_not_split_again(db):
    account, ba, _ = _one_sleeve_account(db)
    strategy_split.apply(db, ba)
    again = strategy_split.plan(db, ba)
    assert again.nothing_to_do
    strategy_split.apply(db, ba)
    assert db.query(Sleeve).filter(Sleeve.account_id == account.id).count() == 5


def test_rows_arriving_after_a_split_go_to_their_strategy(db):
    account, ba, _ = _one_sleeve_account(db)
    strategy_split.apply(db, ba)
    _ingest(db, ba, [_buy("b8", "s-bbb", 2, 50, "2026-01-08"),
                     _buy("b9", "s-fff", 3, 10, "2026-01-08")])
    trades, _ = _by_strategy(db, account)
    assert trades["ETFs"] == {"BBB"} and trades["Mutual funds"] == {"FFFXX"}


def test_a_bank_account_becomes_a_cash_sleeve(db):
    account, ba = _brokerage(db, name="Everyday Checking", kind="checking")
    sleeve = Sleeve(account_id=account.id, strategy_id=routing.strategy_named(db, "Unallocated").id,
                    accounting_method="FIFO")
    db.add(sleeve)
    db.flush()
    ba.default_sleeve_id = sleeve.id
    db.commit()
    plan = strategy_split.apply(db, ba)
    assert plan.becomes == "Cash" and not plan.moves
    assert db.get(Strategy, sleeve.strategy_id).name == "Cash"
    assert db.query(Sleeve).filter(Sleeve.account_id == account.id).count() == 1
