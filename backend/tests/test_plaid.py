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


class FakePlaid:
    """Plaid as the service sees it, with one login of three accounts."""

    def __init__(self, accounts=None, holdings=None):
        self.accounts_list = accounts or [
            {"account_id": "p-brk", "name": "Brokerage Account", "mask": "4321",
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

    def link_token(self, client_user_id, redirect_uri="", webhook="", access_token="", select_accounts=False):
        self.last_link_token = {"access_token": access_token, "select_accounts": select_accounts}
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
    _existing(db, owner, "Pat Example — Brokerage Account — 12344321", {"AAA": 100})
    _existing(db, owner, "Pat Example — Old Savings — 99991111")

    found = PlaidLinkService(db, FakePlaid()).finish(owner.id, "public-token")

    connection = db.get(BrokerageConnection, found["connection_id"])
    assert connection.institution == INSTITUTION
    assert connection.access_token_enc and "access-secret-123" not in connection.access_token_enc
    by_mask = {a["mask"]: a for a in found["accounts"]}
    assert by_mask["4321"]["proposal"] == "same"  # last four + institution + holdings
    assert by_mask["1111"]["proposal"] == "choose"  # last four alone is not enough
    assert by_mask["2222"]["proposal"] == "new"
    assert (by_mask["1111"]["kind"], by_mask["2222"]["kind"], by_mask["2222"]["owed"]) == (
        "checking", "credit_card", True
    )


def test_holdings_that_disagree_leave_the_choice_to_the_person(db, owner, plaid_keys):
    _existing(db, owner, "Pat Example — Brokerage Account — 12344321", {"ZZZ": 5})
    found = PlaidLinkService(db, FakePlaid()).finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "4321")
    assert brokerage["proposal"] == "choose"
    assert brokerage["candidates"][0]["same_holdings"] is False


def test_a_new_account_is_added_of_its_kind_and_pulled(db, owner, plaid_keys):
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    links = {a["mask"]: a["link_id"] for a in found["accounts"]}

    done = service.confirm(owner.id, found["connection_id"], [
        {"link_id": links["4321"], "action": "new", "kind": "taxable"},
        {"link_id": links["1111"], "action": "new"},
        {"link_id": links["2222"], "action": "new"},
    ])
    assert done == {"linked": 0, "added": 3, "skipped": 0, "waiting": 0}

    accounts = {a.last_four: a for a in db.query(Account).filter(Account.client_id == owner.id)}
    assert {k: a.kind for k, a in accounts.items()} == {
        "4321": "taxable", "1111": "checking", "2222": "credit_card",
    }
    brokerage = accounts["4321"]
    assert accounts["4321"].institution == INSTITUTION
    # A feed's sales take the oldest shares first, never round-trip pairing.
    assert {s.accounting_method for s in db.query(Sleeve).filter(Sleeve.account_id == brokerage.id)} == {"FIFO"}
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


def test_an_account_another_link_already_feeds_is_not_linked_again(db, owner, plaid_keys):
    """Two feeds never write to one account: a second link would count its
    transactions twice, under ids of its own."""
    existing = _existing(db, owner, "Pat Example — Brokerage Account — 12344321", {"AAA": 100}, fed=True)
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "4321")

    with pytest.raises(PlaidLinkError) as refused:
        service.confirm(owner.id, found["connection_id"], [
            {"link_id": brokerage["link_id"], "action": "link", "account_id": existing.id},
        ])
    assert refused.value.status_code == 409
    assert db.get(BrokerageAccount, brokerage["link_id"]).status != "mapped"


def test_an_account_of_another_client_cannot_be_chosen(db, owner, plaid_keys):
    stranger = Client(name="Lee Example", email="lee@example.com")
    db.add(stranger)
    db.commit()
    theirs = _existing(db, stranger, "Lee Example — Brokerage — 55554321")
    service = PlaidLinkService(db, FakePlaid())
    found = service.finish(owner.id, "public-token")
    brokerage = next(a for a in found["accounts"] if a["mask"] == "4321")
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
        {"link_id": links["4321"], "action": "skip"},
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
    # The balance is what the holdings and cash add up to, as Plaid reports it.
    accounts = FakePlaid().accounts_list
    accounts[0] = dict(accounts[0], balances={"current": 3150.0})
    service = PlaidLinkService(db, FakePlaid(accounts=accounts, holdings=HELD_BEFORE))
    found = service.finish(owner.id, "public-token")
    links = {a["mask"]: a["link_id"] for a in found["accounts"]}
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": links["4321"], "action": "new", "kind": "taxable"},
        {"link_id": links["1111"], "action": "skip"},
        {"link_id": links["2222"], "action": "skip"},
    ])
    return db.query(Account).filter(Account.client_id == owner.id, Account.last_four == "4321").one()


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


def test_a_trade_it_cannot_name_is_set_aside_but_its_cash_still_counts():
    """Vanguard sends many option trades with no symbol: the trade is set aside
    and counted, and the premium it cost is still cash that left the account."""
    rows = [
        {"investment_transaction_id": "o1", "security_id": "s-unnamed", "type": "buy",
         "subtype": "buy", "date": "2026-11-05", "quantity": 1, "price": 31, "amount": 3100,
         "fees": 0, "name": "Buy to open"},
    ]
    batch = plaid_reader.read_investment_transactions(rows, {"s-unnamed": {"type": "derivative"}})
    assert batch.trades == [] and batch.skipped == {"unreadable": 1}
    (raw,) = batch.raw
    assert (raw.outcome, raw.cash_amount) == ("skipped:unreadable", D("-3100"))


# -- Checking a login for accounts not seen before ---------------------------


def _bare_login(db, owner, status="active"):
    """A login whose key is stored but which has no account rows yet, as when
    it was copied from another database or the link dialog was left half way."""
    login = BrokerageConnection(
        client_id=owner.id, source="plaid", external_user_id=owner.id,
        external_connection_id="item-1", institution=INSTITUTION, status=status,
        access_token_enc=seal("access-secret-123"),
    )
    db.add(login)
    db.commit()
    return login


def test_checking_a_login_with_no_accounts_offers_each_one(db, owner, plaid_keys):
    login = _bare_login(db, owner)
    found = PlaidLinkService(db, FakePlaid()).discover(owner.id, login.id)
    assert sorted(a["mask"] for a in found["accounts"]) == ["1111", "2222", "4321"]
    assert {l.status for l in db.query(BrokerageAccount)} == {"unmapped"}
    assert db.query(Account).count() == 0  # nothing is added until the client chooses


def test_checking_again_adds_only_what_is_new_and_leaves_the_rest_alone(db, owner, plaid_keys):
    plaid = FakePlaid()
    service = PlaidLinkService(db, plaid)
    found = service.finish(owner.id, "public-token")
    links = {a["mask"]: a["link_id"] for a in found["accounts"]}
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": links["4321"], "action": "new", "kind": "taxable"},
        {"link_id": links["1111"], "action": "skip"},
        {"link_id": links["2222"], "action": "skip"},
    ])
    before = {l.id: (l.name, l.status, l.account_id, l.default_sleeve_id) for l in db.query(BrokerageAccount)}
    # The institution now shares a fourth account, and has renamed the first.
    plaid.accounts_list = [
        {**plaid.accounts_list[0], "name": "Renamed Brokerage"}, *plaid.accounts_list[1:],
        {"account_id": "p-sav", "name": "Rainy Day Savings", "mask": "3333",
         "type": "depository", "subtype": "savings", "balances": {"current": 900.0}},
    ]

    assert service.discover_new(owner.id, found["connection_id"]) == 1
    db.commit()
    after = {l.id: (l.name, l.status, l.account_id, l.default_sleeve_id) for l in db.query(BrokerageAccount)}
    assert all(after[i] == row for i, row in before.items())  # known accounts are untouched
    new = [l for l in db.query(BrokerageAccount) if l.id not in before]
    assert [(l.name, l.status, l.account_id) for l in new] == [("Rainy Day Savings", "unmapped", None)]
    assert db.query(Account).count() == 1
    assert service.discover_new(owner.id, found["connection_id"]) == 0  # repeating is safe


def test_checking_every_login_counts_and_never_stops_at_one_that_cannot_be_read(db, owner, plaid_keys):
    good = _bare_login(db, owner)
    db.add(BrokerageConnection(
        client_id=owner.id, source="plaid", external_user_id=owner.id,
        external_connection_id="item-2", institution="Other Bank", status="broken",
        access_token_enc=seal("access-secret-123"),
    ))
    db.commit()
    out = PlaidLinkService(db, FakePlaid()).discover_mine(owner.id)
    assert out == {"checked": 1, "new_accounts": 3, "needs_sign_in": 1, "failed": 0}
    assert db.query(BrokerageAccount).filter(BrokerageAccount.connection_id == good.id).count() == 3


def test_a_login_plaid_says_needs_signing_in_is_not_read(db, owner, plaid_keys):
    from app.connectors.plaid_connector import PlaidError

    class Refusing(FakePlaid):
        def accounts(self, access_token):
            raise PlaidError("ITEM_LOGIN_REQUIRED", "Sign in again", 400)

    login = _bare_login(db, owner)
    with pytest.raises(PlaidLinkError) as raised:
        PlaidLinkService(db, Refusing()).discover(owner.id, login.id)
    assert raised.value.status_code == 409


def test_a_saved_key_that_does_not_open_is_said_plainly(db, owner, plaid_keys, monkeypatch):
    login = _bare_login(db, owner)
    monkeypatch.setattr(settings, "plaid_token_key", Fernet.generate_key().decode())
    with pytest.raises(PlaidLinkError) as raised:
        PlaidLinkService(db, FakePlaid()).discover(owner.id, login.id)
    assert raised.value.status_code == 503
    assert "access-secret-123" not in str(raised.value.detail)


def test_only_the_owner_can_check_a_login(db, owner, plaid_keys):
    login = _bare_login(db, owner)
    other = Client(name="Sam Example", email="sam@example.com")
    db.add(other)
    db.commit()
    with pytest.raises(PlaidLinkError) as raised:
        PlaidLinkService(db, FakePlaid()).discover(other.id, login.id)
    assert raised.value.status_code == 404


def test_choosing_accounts_to_share_opens_link_in_update_mode_with_selection(db, owner, plaid_keys):
    login = _bare_login(db, owner)
    plaid = FakePlaid()
    PlaidLinkService(db, plaid).repair_start(owner.id, login.id, select_accounts=True)
    assert plaid.last_link_token == {"access_token": "access-secret-123", "select_accounts": True}


def test_update_mode_asks_for_account_selection_only_when_told_to():
    from app.connectors.plaid_connector import PlaidClient

    sent = {}
    client = PlaidClient(env="sandbox")
    client._post = lambda path, body: sent.update(path=path, body=body) or {}
    client.link_token("client-1", access_token="access-sandbox-x")
    assert "update" not in sent["body"]
    client.link_token("client-1", access_token="access-sandbox-x", select_accounts=True)
    assert sent["body"]["update"] == {"account_selection_enabled": True}
    client.link_token("client-1", select_accounts=True)  # a first link has no update mode
    assert "update" not in sent["body"]


def test_a_login_lists_how_many_accounts_wait_to_be_chosen(db, owner, plaid_keys):
    from app.services.portal_service import PortalService

    login = _bare_login(db, owner)
    PlaidLinkService(db, FakePlaid()).discover(owner.id, login.id)
    listed = PortalService(db, owner.id).connections()["connections"]
    assert [(c["id"], c["waiting_accounts"]) for c in listed] == [(login.id, 3)]


def test_a_holding_with_no_ticker_is_kept_under_its_name_and_the_account_s_cash_is_not():
    """A target-date trust has a name and no ticker; the settlement fund, cash and an
    option with no contract details are not holdings to name."""
    securities = {
        "tr": {"security_id": "tr", "type": "equity", "ticker_symbol": None, "name": "Target Retire 2050 Trust"},
        "fund": {"security_id": "fund", "type": "mutual fund", "ticker_symbol": "ZZZFX", "name": "Example Fund"},
        "settle": {"security_id": "settle", "type": "mutual fund", "ticker_symbol": None,
                   "name": "EXAMPLE CASH DEPOSIT (Settlement Fund)"},
        "cash": {"security_id": "cash", "type": "cash", "ticker_symbol": None, "name": "Cash"},
        "opt": {"security_id": "opt", "type": "derivative", "ticker_symbol": None, "name": "ABC 01/15/27 1 Call"},
    }
    held = [
        {"account_id": "a1", "security_id": key, "quantity": 10, "institution_price": 5, "institution_value": 50}
        for key in securities
    ]
    figures = plaid_reader.read_holdings({"account_id": "a1", "balances": {"current": 250}}, held, securities)
    assert [p.symbol for p in figures.positions] == ["#TARGET RETIRE 2050 TRUST", "ZZZFX"]


def test_a_name_kept_for_a_holding_is_plain_capitals_within_the_column():
    from app.utils.symbols import is_named_symbol, named_symbol

    assert named_symbol("Target Retire 2050 Trust") == "#TARGET RETIRE 2050 TRUST"
    assert named_symbol("Vanguard FTSE Social Index - Portfolio, Inc.") == "#VANGUARD FTSE SOCIAL INDEX PORTFOLIO INC"
    long = named_symbol("A" * 80)
    assert len(long) == 50 and is_named_symbol(long) and not is_named_symbol("AAPL")


def test_nothing_is_asked_of_a_price_source_or_market_data_about_a_name():
    from app.services.live_quotes import quotable

    assert quotable("VPMAX") and not quotable("#TARGET RETIRE 2050 TRUST")


def test_a_settlement_fund_sent_as_a_ticker_less_fund_is_the_accounts_cash_not_its_options():
    """Vanguard's cash deposit fund arrives as a mutual fund with no ticker. Left as it was, its
    balance was in the account's total with nothing listed, so it showed as "options"."""
    securities = {
        "sf": {"security_id": "sf", "type": "mutual fund", "ticker_symbol": None,
               "name": "EXAMPLE CASH DEPOSIT (Settlement Fund)"},
        "mm": {"security_id": "mm", "type": "mutual fund", "ticker_symbol": "ZZZXX", "name": "Example Money Market"},
    }
    held = [
        {"account_id": "a1", "security_id": "sf", "quantity": 50.15, "institution_price": 1, "institution_value": 50.15},
        {"account_id": "a1", "security_id": "mm", "quantity": 200, "institution_price": 1, "institution_value": 200},
    ]
    figures = plaid_reader.read_holdings({"account_id": "a1", "balances": {"current": 250.15}}, held, securities)
    # The fund is the cash; a money-market fund held as an investment is still a holding.
    assert (figures.cash, [p.symbol for p in figures.positions]) == (D("50.15"), ["ZZZXX"])
