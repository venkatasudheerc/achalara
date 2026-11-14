"""Linking with Plaid, offline: a fake Plaid gives invented replies.

Every institution, account, ticker and figure here is invented.
"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import func
from cryptography.fernet import Fernet

from app.config import settings
from app.connectors import plaid_reader
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.client import Client
from app.models.perf import DailyHolding, DailyValuation
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services.plaid_link_service import PlaidLinkError, PlaidLinkService
from app.utils.secret_box import open_sealed, seal

INSTITUTION = "Example Brokerage"
SECURITIES = [
    {"security_id": "s-aaa", "ticker_symbol": "AAA", "type": "equity", "name": "AAA Corp",
     "close_price": 12.0, "close_price_as_of": "2026-11-12"},
    {"security_id": "s-bbb", "ticker_symbol": "BBB", "type": "etf", "name": "BBB Fund",
     "close_price": 50.0, "close_price_as_of": "2026-11-12"},
    {"security_id": "s-cash", "ticker_symbol": "MMFXX", "type": "cash", "name": "Settlement fund"},
]


CHECKING_ONLY = [
    {"account_id": "p-chk", "name": "Everyday Checking", "mask": "1111",
     "type": "depository", "subtype": "checking", "balances": {"current": 2500.0}},
]


class FakePlaid:
    """Plaid as the service sees it, with one login of three accounts."""

    def __init__(self, accounts=None, holdings=None):
        self.accounts_list = accounts or [
            {"account_id": "p-brk", "name": "Brokerage Account", "mask": "8069",
             "type": "investment", "subtype": "brokerage", "balances": {"current": 1600.0}},
            {"account_id": "p-chk", "name": "Everyday Checking", "mask": "1111",
             "type": "depository", "subtype": "checking", "balances": {"current": 2500.0}},
            {"account_id": "p-card", "name": "Rewards Card", "mask": "2222",
             "type": "credit", "subtype": "credit card", "balances": {"current": 300.0}},
        ]
        self.holdings_list = holdings if holdings is not None else [
            {"account_id": "p-brk", "security_id": "s-aaa", "quantity": 100,
             "institution_price": 11.0, "institution_value": 1100.0, "cost_basis": 1000.0},
            {"account_id": "p-brk", "security_id": "s-cash", "quantity": 500,
             "institution_price": 1.0, "institution_value": 500.0},
        ]

    def link_token(self, client_user_id, redirect_uri="", webhook="", access_token=""):
        return {"link_token": f"link-{client_user_id}", "expiration": "2026-11-13T20:00:00Z"}

    def exchange(self, public_token):
        return {"access_token": "access-secret-123", "item_id": "item-1"}

    def item(self, access_token):
        return {"item": {"institution_id": "ins_1", "products": ["transactions", "investments"]}}

    def institution(self, institution_id):
        return {"institution": {"name": INSTITUTION}}

    def accounts(self, access_token):
        assert access_token == "access-secret-123"
        return {"accounts": self.accounts_list}

    def holdings(self, access_token):
        return {"holdings": self.holdings_list, "securities": SECURITIES}

    def investment_transactions(self, access_token, start, end):
        return {
            "investment_transactions": [
                # Settled Monday 2 Nov: traded Friday 30 Oct.
                {"investment_transaction_id": "t1", "account_id": "p-brk", "security_id": "s-aaa",
                 "type": "buy", "subtype": "buy", "date": "2026-11-02", "quantity": 100,
                 "price": 10.0, "amount": 1000.0, "fees": 0, "name": "Buy AAA"},
            ],
            "securities": SECURITIES,
        }

    def transactions_sync(self, access_token, cursor=""):
        return {
            "added": [
                {"transaction_id": "b1", "account_id": "p-chk", "date": "2026-11-03",
                 "amount": -2000.0, "name": "Payroll", "pending": False},
                {"transaction_id": "b2", "account_id": "p-chk", "date": "2026-11-04",
                 "amount": 0.42, "name": "Monthly fee", "pending": False,
                 "personal_finance_category": {"primary": "BANK_FEES"}},
            ],
            "modified": [], "removed": [], "next_cursor": "c1",
        }

    def liabilities(self, access_token):
        return {"liabilities": {}}


@pytest.fixture
def plaid_keys(monkeypatch):
    monkeypatch.setattr(settings, "plaid_client_id", "client")
    monkeypatch.setattr(settings, "plaid_secret", "secret")
    monkeypatch.setattr(settings, "plaid_token_key", Fernet.generate_key().decode())
    monkeypatch.setattr(settings, "plaid_max_logins", 10)


@pytest.fixture
def owner(db):
    client = Client(name="Pat Example", email="pat@example.com")
    db.add(client)
    db.commit()
    return client


def _existing(db, owner, name, holdings=None, fed=False):
    """An account already here, as SnapTrade brought it in."""
    account = Account(client_id=owner.id, name=name)
    strategy = db.query(Strategy).first() or Strategy(name="Growth")
    db.add_all([account, strategy])
    db.flush()
    sleeve = Sleeve(account_id=account.id, strategy_id=strategy.id)
    db.add(sleeve)
    db.flush()
    connection = BrokerageConnection(client_id=owner.id, source="snaptrade", external_user_id="u",
                                     external_connection_id=f"c-{account.id}", institution=INSTITUTION)
    db.add(connection)
    db.flush()
    db.add(BrokerageAccount(connection_id=connection.id, external_account_ref=f"r-{account.id}",
                            name=name, number_last4="3920", account_id=account.id,
                            default_sleeve_id=sleeve.id, status="mapped" if fed else "unmapped"))
    for symbol, qty in (holdings or {}).items():
        db.add(DailyHolding(account_id=account.id, as_of_date=date(2026, 11, 12), symbol=symbol,
                            quantity=D(qty), price=D(1), market_value=D(qty)))
    db.commit()
    return account


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------


def test_a_trade_is_dated_on_the_trade_day_not_settlement():
    securities = {s["security_id"]: s for s in SECURITIES}
    batch = plaid_reader.read_investment_transactions(
        FakePlaid().investment_transactions("x", None, None)["investment_transactions"], securities
    )
    (trade,) = batch.trades
    assert trade.executed_at.date() == date(2026, 10, 30) and trade.symbol == "AAA"


def test_sweeps_and_transfers_within_the_account_are_not_activity():
    securities = {s["security_id"]: s for s in SECURITIES}
    rows = [
        {"investment_transaction_id": "s1", "security_id": "s-cash", "type": "buy", "subtype": "buy",
         "date": "2026-11-03", "quantity": 50, "price": 1, "amount": 50, "name": "Sweep in"},
        {"investment_transaction_id": "x1", "type": "cash", "subtype": "transfer", "date": "2026-11-03",
         "amount": -75, "name": "Transfer (incoming)"},
        {"investment_transaction_id": "x2", "type": "cash", "subtype": "transfer", "date": "2026-11-03",
         "amount": 75, "name": "Transfer (outgoing)"},
        {"investment_transaction_id": "d1", "security_id": "s-aaa", "type": "cash", "subtype": "dividend",
         "date": "2026-11-04", "amount": -3.5, "name": "Dividend"},
    ]
    batch = plaid_reader.read_investment_transactions(rows, securities)
    assert batch.trades == []
    assert [(c.type, c.amount) for c in batch.cash] == [("DIVIDEND", D("3.5"))]
    assert batch.skipped == {"sweep": 1, "internal transfer": 2}


def test_holdings_are_valued_at_each_securitys_close_and_the_total_moves_with_them():
    plaid = FakePlaid()
    figures = plaid_reader.read_holdings(
        plaid.accounts_list[0], plaid.holdings_list, {s["security_id"]: s for s in SECURITIES}
    )
    # 100 AAA at the close of 12 (not the late 11), 500 cash.
    assert figures.day == date(2026, 11, 12)
    assert [(p.symbol, p.market_price) for p in figures.positions] == [("AAA", D("12.0"))]
    assert (figures.cash, figures.total) == (D("500.0"), D("1700.00"))


def test_bank_rows_are_money_in_and_out_with_fees_on_their_own():
    batch = plaid_reader.read_bank_transactions(FakePlaid().transactions_sync("x")["added"])
    assert [(c.type, c.amount) for c in batch.cash] == [("CONTRIBUTION", D("2000.0")), ("FEE", D("-0.42"))]


def test_an_access_key_is_stored_sealed(plaid_keys):
    sealed = seal("access-secret-123")
    assert "access-secret-123" not in sealed and open_sealed(sealed) == "access-secret-123"


# ----------------------------------------------------------------------
# Linking and matching
# ----------------------------------------------------------------------


def test_finishing_a_link_keeps_the_key_sealed_and_proposes_for_each_account(db, owner, plaid_keys):
    # Already here: the brokerage (its name carries the real number) with the
    # same holdings, and an unrelated account that happens to end 1111.
    _existing(db, owner, "Pat Example — Brokerage Account — 12348069", {"AAA": 100})
    _existing(db, owner, "Pat Example — Old Savings — 99991111")

    found = PlaidLinkService(db, FakePlaid()).finish(owner.id, "public-token")

    connection = db.get(BrokerageConnection, found["connection_id"])
    assert connection.institution == INSTITUTION
    assert connection.access_token_enc and "access-secret-123" not in connection.access_token_enc
    by_mask = {a["mask"]: a for a in found["accounts"]}
    assert by_mask["8069"]["proposal"] == "same"  # last four + institution + holdings
    assert by_mask["1111"]["proposal"] == "choose"  # last four alone is not enough
    assert by_mask["2222"]["proposal"] == "new"
    assert (by_mask["1111"]["kind"], by_mask["2222"]["kind"], by_mask["2222"]["owed"]) == (
        "checking", "credit_card", True
    )


def test_holdings_that_disagree_leave_the_choice_to_the_person(db, owner, plaid_keys):
    _existing(db, owner, "Pat Example — Brokerage Account — 12348069", {"ZZZ": 5})
    found = PlaidLinkService(db, FakePlaid()).finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "8069")
    assert brokerage["proposal"] == "choose"
    assert brokerage["candidates"][0]["same_holdings"] is False


def test_a_new_account_is_added_of_its_kind_and_pulled(db, owner, plaid_keys):
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    links = {a["mask"]: a["link_id"] for a in found["accounts"]}

    done = service.confirm(owner.id, found["connection_id"], [
        {"link_id": links["8069"], "action": "new", "kind": "taxable"},
        {"link_id": links["1111"], "action": "new"},
        {"link_id": links["2222"], "action": "new"},
    ])
    assert done == {"linked": 0, "added": 3, "skipped": 0, "waiting": 0}

    accounts = {a.last_four: a for a in db.query(Account).filter(Account.client_id == owner.id)}
    assert {k: a.kind for k, a in accounts.items()} == {
        "8069": "taxable", "1111": "checking", "2222": "credit_card",
    }
    brokerage = accounts["8069"]
    assert accounts["8069"].institution == INSTITUTION
    trades = db.query(Trade).join(Sleeve).filter(Sleeve.account_id == brokerage.id).all()
    assert [(t.trade_date, t.symbol) for t in trades] == [(date(2026, 10, 30), "AAA")]
    day = (
        db.query(DailyValuation)
        .filter(DailyValuation.account_id == brokerage.id, DailyValuation.basis == "observed")
        .one()
    )
    assert (day.as_of_date, day.total_value, day.cash_value) == (date(2026, 11, 12), D("1700.00"), D("500.00"))
    # A card's balance is owed: it counts against what the client has.
    card = (
        db.query(DailyValuation)
        .filter(DailyValuation.account_id == accounts["2222"].id, DailyValuation.basis == "observed")
        .one()
    )
    assert card.total_value == D("-300.00")


def test_plaid_takes_over_an_account_another_feed_writes_to_as_a_clean_start(db, owner, plaid_keys):
    """Linking replaces the old feed: its records go, Plaid's history comes in,
    and the old link is set aside so it can never be mapped back."""
    from app.models.brokerage_connection import BrokerageActivity
    from app.models.cash_activity import CashActivity

    existing = _existing(db, owner, "Pat Example — Brokerage Account — 12348069", {"AAA": 100}, fed=True)
    old_link = db.query(BrokerageAccount).filter(BrokerageAccount.account_id == existing.id).one()
    sleeve = db.query(Sleeve).filter(Sleeve.account_id == existing.id).one()
    db.add_all([
        Trade(sleeve_id=sleeve.id, trade_date=date(2024, 3, 1), symbol="OLD", action="BUY",
              quantity=D(5), price=D(10), commission=D(0), external_id="snap-1"),
        CashActivity(sleeve_id=sleeve.id, activity_date=date(2024, 3, 1), type="CONTRIBUTION",
                     amount=D(50), external_id="snap-c1"),
        BrokerageActivity(brokerage_account_id=old_link.id, source_activity_id="snap-1",
                          activity_date=date(2024, 3, 1), type="BUY", outcome="trade", payload={}),
    ])
    db.commit()

    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "8069")
    assert next(c for c in brokerage["candidates"] if c["account_id"] == existing.id)["replaces"] == INSTITUTION

    done = service.confirm(owner.id, found["connection_id"], [
        {"link_id": brokerage["link_id"], "action": "link", "account_id": existing.id},
    ])
    assert done["linked"] == 1
    link = db.get(BrokerageAccount, brokerage["link_id"])
    assert (link.status, link.account_id, link.default_sleeve_id) == ("mapped", existing.id, sleeve.id)
    db.refresh(old_link)
    assert (old_link.status, old_link.account_id) == ("ignored", None)
    assert not db.query(BrokerageActivity).filter(BrokerageActivity.brokerage_account_id == old_link.id).count()
    # Only Plaid's history is on file now.
    trades = db.query(Trade).join(Sleeve).filter(Sleeve.account_id == existing.id).all()
    assert {t.symbol for t in trades if not (t.notes or "").startswith("Opening")} == {"AAA"}
    assert not db.query(CashActivity).filter(CashActivity.external_id == "snap-c1").count()
    assert db.get(Account, existing.id).last_four == "8069"


def test_a_shared_account_fed_elsewhere_can_only_be_moved_by_its_owner(db, owner, plaid_keys):
    from app.models.user import AccountAccess

    other = Client(name="Sam Example", email="sam@example.com")
    db.add(other)
    db.flush()
    theirs = _existing(db, other, "Sam Example — Brokerage Account — 12348069", {"AAA": 100}, fed=True)
    db.add(AccountAccess(client_id=owner.id, account_id=theirs.id))
    db.commit()
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "8069")

    with pytest.raises(PlaidLinkError) as refused:
        service.confirm(owner.id, found["connection_id"], [
            {"link_id": brokerage["link_id"], "action": "link", "account_id": theirs.id},
        ])
    assert refused.value.status_code == 403
    assert db.query(BrokerageAccount).filter(BrokerageAccount.account_id == theirs.id).one().status == "mapped"


def test_an_account_of_another_client_cannot_be_chosen(db, owner, plaid_keys):
    stranger = Client(name="Lee Example", email="lee@example.com")
    db.add(stranger)
    db.commit()
    theirs = _existing(db, stranger, "Lee Example — Brokerage — 55558069")
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "8069")
    assert brokerage["proposal"] == "new"  # never a candidate
    with pytest.raises(PlaidLinkError) as refused:
        service.confirm(owner.id, found["connection_id"], [
            {"link_id": brokerage["link_id"], "action": "link", "account_id": theirs.id},
        ])
    assert refused.value.status_code == 404


def test_the_plans_logins_are_counted_and_the_last_refused(db, owner, plaid_keys, monkeypatch):
    monkeypatch.setattr(settings, "plaid_max_logins", 1)
    service = PlaidLinkService(db, FakePlaid())
    assert service.start(owner.id)["logins_left"] == 1
    service.finish(owner.id, "public-token")
    with pytest.raises(PlaidLinkError) as full:
        service.start(owner.id)
    assert full.value.status_code == 409


def test_without_keys_linking_is_not_offered(client, owner, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "plaid_secret", "")
    response = client.get("/api/v1/portal/links/plaid", params={"as_client": owner.id})
    assert response.status_code == 200 and response.json()["available"] is False
    assert client.post("/api/v1/portal/links/plaid/start", params={"as_client": owner.id}).status_code == 503


def test_link_token_asks_for_two_years_of_transactions():
    """Plaid gives 90 days unless more is asked for when a login is linked."""
    from app.connectors.plaid_connector import PlaidClient

    sent = {}
    client = PlaidClient(env="sandbox")
    client._post = lambda path, body: sent.update(path=path, body=body) or {}
    client.link_token("client-1")
    assert sent["body"]["transactions"] == {"days_requested": 730}
    client.link_token("client-1", access_token="access-sandbox-x")
    assert "transactions" not in sent["body"]


def test_money_already_in_a_bank_account_is_its_opening_value_not_a_gain(db, owner, plaid_keys):
    """Plaid's history begins with money already there: the record opens at that
    balance the market day before the first transaction, with nothing moved."""
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    links = {a["mask"]: a["link_id"] for a in found["accounts"]}
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": links["8069"], "action": "skip"},
        {"link_id": links["1111"], "action": "new"},
        {"link_id": links["2222"], "action": "skip"},
    ])
    checking = db.query(Account).filter(Account.client_id == owner.id, Account.last_four == "1111").one()
    rows = {
        r.as_of_date: r
        for r in db.query(DailyValuation).filter(
            DailyValuation.account_id == checking.id, DailyValuation.sleeve_id.is_(None)
        )
    }
    first = min(rows)
    # 2,500 today, less the 2,000 paid in on the 3rd, plus the 0.42 fee on the 4th.
    assert (first, rows[first].total_value) == (date(2026, 11, 2), D("500.42"))
    assert rows[first].flow_in == 0 and rows[first].flow_out == 0
    assert rows[date(2026, 11, 3)].flow_in == D("2000")


HELD_BEFORE = [
    # 150 now, 100 of them bought on 30 Oct: 50 were already there.
    {"account_id": "p-brk", "security_id": "s-aaa", "quantity": 150,
     "institution_price": 11.0, "institution_value": 1650.0, "cost_basis": 1400.0},
    # Never traded in the history: held all along.
    {"account_id": "p-brk", "security_id": "s-bbb", "quantity": 20,
     "institution_price": 50.0, "institution_value": 1000.0, "cost_basis": 800.0},
    {"account_id": "p-brk", "security_id": "s-cash", "quantity": 500,
     "institution_price": 1.0, "institution_value": 500.0},
]


def _link_brokerage(db, owner):
    service = PlaidLinkService(db, FakePlaid(holdings=HELD_BEFORE))
    found = service.finish(owner.id, "public-token")
    links = {a["mask"]: a["link_id"] for a in found["accounts"]}
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": links["8069"], "action": "new", "kind": "taxable"},
        {"link_id": links["1111"], "action": "skip"},
        {"link_id": links["2222"], "action": "skip"},
    ])
    return db.query(Account).filter(Account.client_id == owner.id, Account.last_four == "8069").one()


def _account_rows(db, account):
    return {
        r.as_of_date: r
        for r in db.query(DailyValuation).filter(
            DailyValuation.account_id == account.id, DailyValuation.sleeve_id.is_(None)
        )
    }


def _opening_trades(db, account):
    from app.services.opening_position import OPENING_NOTE

    return {
        t.symbol: t
        for t in db.query(Trade).join(Sleeve).filter(
            Sleeve.account_id == account.id, Trade.notes.like(f"{OPENING_NOTE}%")
        )
    }


def test_an_investment_account_opens_with_what_it_held_before_its_history(db, owner, plaid_keys):
    """History reaches back only so far: the account opens the day before its
    first transaction holding what the institution's holdings work back to."""
    brokerage = _link_brokerage(db, owner)
    rows = _account_rows(db, brokerage)
    first = min(rows)
    assert first == date(2026, 10, 29)
    opening = rows[first]
    # 50 AAA at the 10.00 it next traded at, 20 BBB at 50.00, and the 1,500 cash
    # that paid for the 30 Oct purchase.
    assert opening.securities_value == D("1500.00")
    assert opening.cash_value == D("1500.00")
    assert opening.flow_in == 0 and opening.flow_out == 0
    # The institution's cost is kept for BBB, which nothing since has changed.
    assert opening.cost_value == D("500.00") + D("800.00")

    held = _opening_trades(db, brokerage)
    assert {s: (t.trade_date, t.quantity) for s, t in held.items()} == {
        "AAA": (date(2026, 10, 29), D(50)), "BBB": (date(2026, 10, 29), D(20)),
    }
    # An opening position is not a transaction: the activity list leaves it out.
    from app.services.portal_service import PortalService
    listed = PortalService(db, owner.id).activity(show="trades")
    assert {row["symbol"] for row in listed["rows"]} == {"AAA"}


def test_history_added_later_moves_the_opening_back_and_shrinks_it(db, owner, plaid_keys):
    """A file brings the real purchase of BBB on 1 Oct: BBB is no longer held
    before the history, and the record now opens the day before that."""
    from app.models.brokerage_connection import BrokerageActivity
    from app.services.performance_build_service import PerformanceBuildService

    brokerage = _link_brokerage(db, owner)
    link = db.query(BrokerageAccount).filter(BrokerageAccount.account_id == brokerage.id).one()
    db.add(Trade(sleeve_id=link.default_sleeve_id, trade_date=date(2026, 10, 1), symbol="BBB",
                 action="BUY", quantity=D(20), price=D(40), commission=D(0),
                 external_id="vanguard:x1"))
    db.add(BrokerageActivity(brokerage_account_id=link.id, source_activity_id="vanguard:x1",
                             activity_date=date(2026, 10, 1), type="BUY", symbol="BBB",
                             outcome="trade", payload={}, cash_amount=D("-800")))
    db.commit()

    PerformanceBuildService(db).rebuild_account(brokerage.id)

    assert {s: t.quantity for s, t in _opening_trades(db, brokerage).items()} == {"AAA": D(50)}
    rows = _account_rows(db, brokerage)
    first = min(rows)
    assert first == date(2026, 9, 30)
    # The 800 that paid for BBB was cash before it.
    assert rows[first].cash_value == D("2300.00")
    assert rows[first].flow_in == 0


def test_a_position_that_works_back_below_nothing_is_reported_not_guessed():
    from app.services.opening_position import work_back_shares

    class _Trade:
        def __init__(self, symbol, action, quantity, day):
            self.symbol, self.action, self.quantity, self.trade_date = symbol, action, D(quantity), day
            self.price, self.at_market, self.id, self.sleeve_id = D(10), True, symbol + action, "s1"

    anchor = date(2026, 11, 12)
    # 30 bought in the history, 10 held now: a sale is missing.
    opening = work_back_shares(
        [_Trade("AAA", "BUY", 30, date(2026, 10, 1))], {"AAA": (D(10), D(12), "s1")}, anchor
    )
    assert opening.problems == ["AAA works back to -20 shares"] and not opening.shares


def test_a_bank_account_that_works_back_below_nothing_opens_empty(db, owner, plaid_keys):
    """1,000 now after 2,000 paid in: it held -1,000 before, so a withdrawal is
    missing. Nothing is assumed; a card owing money works back below nothing
    as it should."""
    accounts = [
        {"account_id": "p-chk", "name": "Everyday Checking", "mask": "1111",
         "type": "depository", "subtype": "checking", "balances": {"current": 1000.0}},
    ]
    service = PlaidLinkService(db, FakePlaid(accounts=accounts))
    found = service.finish(owner.id, "public-token")
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new"},
    ])
    checking = db.query(Account).filter(Account.client_id == owner.id).one()
    first = (
        db.query(func.min(DailyValuation.as_of_date))
        .filter(DailyValuation.account_id == checking.id, DailyValuation.sleeve_id.is_(None))
        .scalar()
    )
    assert first == date(2026, 11, 3)
    assert not db.query(Trade).join(Sleeve).filter(Sleeve.account_id == checking.id).count()
