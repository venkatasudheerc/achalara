# flake8: noqa: F811
"""One person's Plaid login feeds an account another person owns; the owner then links
their own login. Only what is new is added, and the shared account keeps its one feed.

Every name, number and figure here is invented.
"""
import pytest

from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount
from app.models.client import Client, PersonLink
from app.services.account_kind import account_kind, kind_from_plaid
from app.services.plaid_link_service import PlaidLinkError, PlaidLinkService
from tests.test_plaid import FakePlaid, plaid_keys  # fixtures, used by name

HOLDINGS = [
    {"account_id": "q-brk", "security_id": "s-aaa", "quantity": 100,
     "institution_price": 11.0, "institution_value": 1100.0, "cost_basis": 1000.0},
    {"account_id": "q-brk", "security_id": "s-cash", "quantity": 500,
     "institution_price": 1.0, "institution_value": 500.0},
]
BROKERAGE = {"name": "Brokerage Account", "mask": "4321", "type": "investment",
             "subtype": "brokerage", "balances": {"current": 1600.0}}


class OtherLogin(FakePlaid):
    """A second person's login at the same institution: its own item, and its
    own ids for the same accounts (as Plaid gives them)."""

    def __init__(self, accounts):
        super().__init__(accounts=accounts, holdings=[
            dict(h, account_id=accounts[0]["account_id"]) for h in HOLDINGS
        ])

    def exchange(self, public_token):
        return {"access_token": "access-secret-123", "item_id": "item-2"}


@pytest.fixture
def two(db):
    sarvani = Client(name="Sarvani Example", email="sarvani@example.com")
    sudheer = Client(name="Sudheer Example", email="sudheer@example.com")
    db.add_all([sarvani, sudheer])
    db.flush()
    # Sarvani has added Sudheer as her spouse, so she can say an account is his.
    db.add(PersonLink(client_id=sarvani.id, person_id=sudheer.id, relation="spouse"))
    db.commit()
    return sarvani, sudheer


def _sarvanis_login_feeds_a_brokerage_sudheer_owns(db, sarvani, sudheer):
    service = PlaidLinkService(db, FakePlaid(accounts=[dict(BROKERAGE, account_id="p-brk")]))
    found = service.finish(sarvani.id, "public-token")
    service.confirm(sarvani.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new", "kind": "taxable",
         "owner_ids": [sudheer.id]},
    ])
    return db.query(Account).one()


def _sudheers_login(db, sudheer):
    accounts = [
        dict(BROKERAGE, account_id="q-brk"),
        {"account_id": "q-529", "name": "College Savings 529", "mask": "0529", "type": "investment",
         "subtype": "529", "balances": {"current": 9000.0}},
        {"account_id": "q-401", "name": "Participant", "mask": "0401", "type": "investment",
         "subtype": "401k", "balances": {"current": 54000.0}},
    ]
    service = PlaidLinkService(db, OtherLogin(accounts))
    return service, service.finish(sudheer.id, "public-token")


def test_an_account_another_login_feeds_says_so_and_whose_login_it_is(db, two, plaid_keys):
    sarvani, sudheer = two
    _sarvanis_login_feeds_a_brokerage_sudheer_owns(db, sarvani, sudheer)
    _, found = _sudheers_login(db, sudheer)
    by_mask = {a["mask"]: a for a in found["accounts"]}

    fed = by_mask["4321"]
    assert fed["proposal"] == "same"
    assert fed["fed_by"] == {"institution": "Example Brokerage", "owner_name": "Sarvani Example", "own": False}
    assert fed["candidates"][0]["fed_by"]["owner_name"] == "Sarvani Example"
    # The genuinely new accounts have no feed, and are read as what they are.
    assert by_mask["0529"]["fed_by"] is None and by_mask["0529"]["kind"] == "kids"
    assert by_mask["0401"]["fed_by"] is None and by_mask["0401"]["kind"] == "retirement"
    assert by_mask["0529"]["proposal"] == by_mask["0401"]["proposal"] == "new"


def test_linking_the_fed_account_is_refused_by_name_and_adds_nothing(db, two, plaid_keys):
    sarvani, sudheer = two
    account = _sarvanis_login_feeds_a_brokerage_sudheer_owns(db, sarvani, sudheer)
    service, found = _sudheers_login(db, sudheer)
    fed = next(a for a in found["accounts"] if a["mask"] == "4321")

    with pytest.raises(PlaidLinkError) as refused:
        service.confirm(sudheer.id, found["connection_id"], [
            {"link_id": fed["link_id"], "action": "link", "account_id": account.id},
        ])
    assert refused.value.status_code == 409
    assert "Brokerage Account" in refused.value.detail and "4321" in refused.value.detail
    assert db.query(Account).count() == 1


def test_adding_only_the_new_ones_leaves_the_fed_account_and_its_feed_alone(db, two, plaid_keys):
    sarvani, sudheer = two
    account = _sarvanis_login_feeds_a_brokerage_sudheer_owns(db, sarvani, sudheer)
    sarvanis_feed = db.query(BrokerageAccount).one()
    before = (sarvanis_feed.status, sarvanis_feed.account_id, sarvanis_feed.default_sleeve_id)
    service, found = _sudheers_login(db, sudheer)
    by_mask = {a["mask"]: a for a in found["accounts"]}

    done = service.confirm(sudheer.id, found["connection_id"], [
        {"link_id": by_mask["4321"]["link_id"], "action": "skip"},
        {"link_id": by_mask["0529"]["link_id"], "action": "new"},
        {"link_id": by_mask["0401"]["link_id"], "action": "new"},
    ])
    assert done == {"linked": 0, "added": 2, "skipped": 1, "waiting": 0}

    added = {a.last_four: a for a in db.query(Account).filter(Account.last_four.in_(["0529", "0401"]))}
    assert (added["0529"].kind, added["0401"].kind) == ("kids", "retirement")
    db.refresh(sarvanis_feed)
    assert (sarvanis_feed.status, sarvanis_feed.account_id, sarvanis_feed.default_sleeve_id) == before
    assert db.query(Account).count() == 3
    # The shared account is still fed by exactly one link.
    assert db.query(BrokerageAccount).filter(
        BrokerageAccount.account_id == account.id, BrokerageAccount.status == "mapped"
    ).count() == 1


def test_an_account_the_viewers_own_other_login_feeds_is_marked_as_theirs(db, two, plaid_keys):
    _, sudheer = two
    first = PlaidLinkService(db, FakePlaid(accounts=[dict(BROKERAGE, account_id="p-brk")]))
    found = first.finish(sudheer.id, "public-token")
    first.confirm(sudheer.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new", "kind": "taxable"},
    ])
    _, again = _sudheers_login(db, sudheer)
    fed = next(a for a in again["accounts"] if a["mask"] == "4321")
    assert fed["fed_by"]["own"] is True and fed["fed_by"]["owner_name"] == "Sudheer Example"


@pytest.mark.parametrize("subtype,name,expected", [
    ("529", "College Savings 529", "kids"),
    ("education savings account", "Education", "kids"),
    ("401k", "Participant", "retirement"),
    ("roth 401k", "Participant", "retirement"),
])
def test_a_529_and_a_401k_are_read_as_kids_and_retirement(subtype, name, expected):
    assert kind_from_plaid("investment", subtype, name) == expected


def test_a_529_and_a_401k_are_read_from_their_names_too():
    assert account_kind("Vanguard 529 College Savings Plan") == "kids"
    assert account_kind("Employer 401(k) Participant Account") == "retirement"


# -- Comparing two logins' trades (read only) ----------------------------------

from datetime import date  # noqa: E402

from app.models.brokerage_connection import BrokerageConnection  # noqa: E402
from app.models.trade import Trade  # noqa: E402
from app.services.feed_compare import compare  # noqa: E402


class OtherLoginWithTrades(OtherLogin):
    def __init__(self, accounts, tx_id, quantity=100):
        super().__init__(accounts)
        self.tx_id, self.quantity = tx_id, quantity

    def investment_transactions(self, access_token, start, end):
        from tests.test_plaid import SECURITIES
        return {
            "investment_transactions": [
                {"investment_transaction_id": self.tx_id, "account_id": "q-brk", "security_id": "s-aaa",
                 "type": "buy", "subtype": "buy", "date": "2026-11-02", "quantity": self.quantity,
                 "price": 10.0, "amount": self.quantity * 10.0, "fees": 0, "name": "Buy AAA"},
            ],
            "securities": SECURITIES,
        }


@pytest.mark.parametrize("tx_id,quantity,expected", [
    ("t1", 100, {"same_id": 1, "same_trade_other_id": 0, "not_on_file": 0}),       # Plaid's id is the same
    ("other-id", 100, {"same_id": 0, "same_trade_other_id": 1, "not_on_file": 0}),  # same trade, another id
    ("other-id", 50, {"same_id": 0, "same_trade_other_id": 0, "not_on_file": 1}),   # a different trade
])
def test_comparing_two_logins_says_how_their_trades_match_and_changes_nothing(
    db, two, plaid_keys, tx_id, quantity, expected
):
    sarvani, sudheer = two
    _sarvanis_login_feeds_a_brokerage_sudheer_owns(db, sarvani, sudheer)
    accounts = [dict(BROKERAGE, account_id="q-brk")]
    fake = OtherLoginWithTrades(accounts, tx_id, quantity)
    PlaidLinkService(db, fake).finish(sudheer.id, "public-token")
    login = db.query(BrokerageConnection).filter(BrokerageConnection.client_id == sudheer.id).one()
    before = (db.query(Trade).count(), db.query(Account).count(), db.query(BrokerageAccount).count())

    (row,) = compare(db, login, days=60, client=fake, today=date(2026, 11, 12))

    assert {k: row[k] for k in expected} == expected
    assert row["fed_by"]["owner_name"] == "Sarvani Example"
    assert (db.query(Trade).count(), db.query(Account).count(), db.query(BrokerageAccount).count()) == before
