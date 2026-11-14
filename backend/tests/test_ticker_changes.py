"""Ticker changes: proposed from an account's own record, copied from market
data, confirmed by an admin. Every ticker, name and figure here is invented."""
from datetime import date
from decimal import Decimal as D

from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity, BrokerageConnection
from app.models.client import Client
from app.models.perf import CorporateAction, DailyHolding
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services import ticker_changes


def _account(db, names, held="NEW", stuck="OLD"):
    """Bought ``stuck`` until March 2025; today the custodian lists ``held``.
    ``names`` gives the company name the custodian's rows carry, by symbol."""
    owner = Client(name="Pat Example")
    strategy = Strategy(name="Core")
    db.add_all([owner, strategy])
    db.flush()
    account = Account(client_id=owner.id, name="Pat — Brokerage Account")
    db.add(account)
    db.flush()
    sleeve = Sleeve(account_id=account.id, strategy_id=strategy.id)
    login = BrokerageConnection(client_id=owner.id, source="plaid", external_user_id=owner.id,
                                external_connection_id="item-1", institution="Example")
    db.add_all([sleeve, login])
    db.flush()
    link = BrokerageAccount(connection_id=login.id, external_account_ref="a", name="INDIVIDUAL",
                            account_id=account.id, default_sleeve_id=sleeve.id, status="mapped",
                            reconciliation={"opening_problems": [f"{stuck} works back to -10 shares"]})
    db.add(link)
    db.flush()
    db.add(Trade(sleeve_id=sleeve.id, trade_date=date(2025, 3, 3), symbol=stuck, action="BUY",
                 quantity=D(10), price=D(50)))
    db.add(DailyHolding(account_id=account.id, as_of_date=date(2026, 11, 13), symbol=held,
                        quantity=D(10), price=D(60), market_value=D(600), sleeve_id=sleeve.id))
    for i, (symbol, name) in enumerate(names.items()):
        db.add(BrokerageActivity(brokerage_account_id=link.id, source_activity_id=f"r{i}",
                                 activity_date=date(2025, 3, 3), type="Buy", symbol=symbol,
                                 outcome="trade", payload={"symbol": symbol, "name": name}))
    db.commit()
    return account


def test_a_symbol_that_moved_to_another_ticker_of_the_same_company_is_proposed(db):
    _account(db, {"OLD": "EXAMPLE HOLDINGS INC", "NEW": "Example Holdings Inc"})
    (proposal,) = ticker_changes.proposals(db)
    assert (proposal["old"], proposal["new"], proposal["on"], proposal["accounts"]) == (
        "OLD", "NEW", date(2026, 11, 13), 1
    )
    assert proposal["company"] == "EXAMPLE HOLDINGS INC"


def test_nothing_is_proposed_without_the_same_company_name(db):
    _account(db, {"OLD": "EXAMPLE HOLDINGS INC", "NEW": "OTHER WIDGETS CORP"})
    assert ticker_changes.proposals(db) == []


def test_nothing_is_proposed_once_the_change_is_on_file(db):
    _account(db, {"OLD": "EXAMPLE HOLDINGS INC", "NEW": "EXAMPLE HOLDINGS INC"})
    db.add(CorporateAction(symbol="OLD", new_symbol="NEW", effective_date=date(2025, 6, 2),
                           action_type="RENAME", ratio=D(1), source="manual"))
    db.commit()
    assert ticker_changes.proposals(db) == []


def test_an_admin_confirms_a_proposal_and_the_accounts_are_rebuilt(db, client):
    _account(db, {"OLD": "EXAMPLE HOLDINGS INC", "NEW": "EXAMPLE HOLDINGS INC"})
    listed = client.get("/api/v1/admin/ticker-changes").json()
    assert [(p["old"], p["new"]) for p in listed] == [("OLD", "NEW")]

    done = client.post("/api/v1/admin/ticker-changes",
                       json={"old": "OLD", "new": "NEW", "on": listed[0]["on"]})
    assert done.status_code == 200, done.text
    assert done.json()["accounts_rebuilt"] == 1
    row = db.query(CorporateAction).filter(CorporateAction.action_type == "RENAME").one()
    assert (row.symbol, row.new_symbol, row.source) == ("OLD", "NEW", "confirmed")
    assert client.post("/api/v1/admin/ticker-changes",
                       json={"old": "OLD", "new": "old", "on": "2026-01-02"}).status_code == 422


def test_a_change_market_data_saw_is_copied_once(db):
    from app.md.models import Security, SecuritySymbolHist

    security = Security(name="Example Holdings Inc", kind="stock")
    db.add(security)
    db.flush()
    db.add_all([
        SecuritySymbolHist(security_id=security.id, symbol="OLD", valid_from=date(2024, 1, 2),
                           valid_to=date(2025, 6, 1), source="test"),
        SecuritySymbolHist(security_id=security.id, symbol="NEW", valid_from=date(2025, 6, 2),
                           source="test"),
    ])
    db.commit()

    assert ticker_changes.copy_from_market_data(db) == 1
    row = db.query(CorporateAction).filter(CorporateAction.action_type == "RENAME").one()
    assert (row.symbol, row.new_symbol, row.effective_date, row.source) == (
        "OLD", "NEW", date(2025, 6, 2), "market data"
    )
    assert ticker_changes.copy_from_market_data(db) == 0
