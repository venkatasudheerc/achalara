# flake8: noqa: F811
"""A credit card's limits and what is due, from Plaid. All names and figures are invented."""
from datetime import date
from decimal import Decimal as D

from app.connectors.plaid_connector import PlaidError
from app.models.account import Account
from app.models.brokerage_connection import BrokerageConnection
from app.models.card_detail import CardDetail
from app.models.client import Client
from app.services import card_details
from app.services.plaid_link_service import PlaidLinkService
from app.services.plaid_refresh_service import PlaidRefreshService
from app.services.portal_service import PortalService
from tests.test_plaid import FakePlaid, owner, plaid_keys  # noqa: F401  (fixtures)

TUESDAY = date(2026, 11, 17)


def _card(limit=5000.0, available=4200.0, current=800.0):
    return {"account_id": "p-card", "name": "Rewards Card", "mask": "2222", "type": "credit",
            "subtype": "credit card",
            "balances": {"current": current, "available": available, "limit": limit}}


def _liability(**changes):
    row = {"account_id": "p-card", "cash_advance_limit": 1500, "minimum_payment_amount": 35.0,
           "next_payment_due_date": "2026-11-28", "last_payment_amount": 120.5,
           "last_payment_date": "2026-10-27", "last_statement_balance": 790.12,
           "is_overdue": False, "aprs": [], "last_statement_issue_date": None}
    row.update(changes)
    return row


class CardPlaid(FakePlaid):
    """A login with one card, and whatever liabilities the test hands it."""

    def __init__(self, card=None, liability=None, refuse=False):
        super().__init__(accounts=[card or _card()])
        self.liability = liability if liability is not None else _liability()
        self.refuse = refuse

    def liabilities(self, access_token):
        if self.refuse:
            raise PlaidError("PRODUCTS_NOT_SUPPORTED", "Not offered here")
        return {"liabilities": {"credit": [self.liability] if self.liability else []}}

    def transactions_sync(self, access_token, cursor=""):
        return {"added": [], "modified": [], "removed": [], "next_cursor": "c1"}


def _link(db, owner, plaid):
    service = PlaidLinkService(db, plaid)
    found = service.finish(owner.id, "public-token")
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new", "kind": "credit_card"},
    ])
    return db.query(Account).filter(Account.client_id == owner.id).one()


def test_the_cards_figures_are_read_from_balances_and_liabilities_each_as_sent():
    values = card_details.read(_card(), _liability())
    assert (values["credit_limit"], values["available_credit"]) == (D("5000.00"), D("4200.00"))
    assert (values["cash_advance_limit"], values["minimum_payment"]) == (D("1500.00"), D("35.00"))
    assert values["next_payment_due_date"] == date(2026, 11, 28)
    assert (values["last_payment_amount"], values["last_payment_date"]) == (D("120.50"), date(2026, 10, 27))
    assert (values["last_statement_balance"], values["is_overdue"]) == (D("790.12"), False)


def test_what_an_institution_does_not_send_is_none_and_never_guessed():
    values = card_details.read({"balances": {"current": 10.0}}, {"next_payment_due_date": "not a date"})
    assert set(values.values()) == {None}
    # No liabilities at all: the limit and the available credit still come from the balances.
    only_balances = card_details.read(_card(), None)
    assert only_balances["credit_limit"] == D("5000.00") and only_balances["minimum_payment"] is None


def test_linking_a_card_stores_its_details(db, owner, plaid_keys):
    account = _link(db, owner, CardPlaid())
    row = db.get(CardDetail, account.id)
    assert (row.credit_limit, row.cash_advance_limit, row.next_payment_due_date) == (
        D("5000.00"), D("1500.00"), date(2026, 11, 28)
    )
    assert row.refreshed_at is not None


def test_the_morning_refresh_replaces_them(db, owner, plaid_keys):
    account = _link(db, owner, CardPlaid())
    login = db.query(BrokerageConnection).one()
    later = CardPlaid(card=_card(available=3900.0, current=1100.0),
                      liability=_liability(next_payment_due_date="2026-12-28", minimum_payment_amount=41.0))
    assert PlaidRefreshService(db, later).refresh(login, TUESDAY) == "refreshed"
    rows = db.query(CardDetail).all()
    assert len(rows) == 1 and rows[0].account_id == account.id
    assert (rows[0].available_credit, rows[0].minimum_payment, rows[0].next_payment_due_date) == (
        D("3900.00"), D("41.00"), date(2026, 12, 28)
    )


def test_liabilities_refused_never_fails_a_refresh_and_the_balances_still_show(db, owner, plaid_keys):
    account = _link(db, owner, CardPlaid(refuse=True))
    row = db.get(CardDetail, account.id)
    assert (row.credit_limit, row.available_credit) == (D("5000.00"), D("4200.00"))
    assert row.minimum_payment is None and row.next_payment_due_date is None
    login = db.query(BrokerageConnection).one()
    assert PlaidRefreshService(db, CardPlaid(refuse=True)).refresh(login, TUESDAY) == "refreshed"


def test_a_card_with_nothing_owed_has_no_payment_due(db, owner, plaid_keys):
    plaid = CardPlaid(card=_card(available=5000.0, current=0.0),
                      liability=_liability(next_payment_due_date=None, minimum_payment_amount=0))
    account = _link(db, owner, plaid)
    row = db.get(CardDetail, account.id)
    assert row.next_payment_due_date is None and row.minimum_payment == D("0.00")


def test_a_bank_account_has_no_card_details(db, owner, plaid_keys):
    checking = {"account_id": "p-chk", "name": "Everyday Checking", "mask": "1111",
                "type": "depository", "subtype": "checking", "balances": {"current": 2500.0}}
    service = PlaidLinkService(db, FakePlaid(accounts=[checking]))
    found = service.finish(owner.id, "public-token")
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new"},
    ])
    assert db.query(CardDetail).count() == 0
    (shown,) = PortalService(db, owner.id).accounts()
    assert shown["card"] is None


def test_the_portal_shows_a_card_to_whoever_may_see_the_account_and_to_nobody_else(db, owner, plaid_keys):
    account = _link(db, owner, CardPlaid())
    (shown,) = PortalService(db, owner.id).accounts()
    assert shown["card"]["credit_limit"] == 5000.0 and shown["card"]["cash_advance_limit"] == 1500.0
    assert shown["card"]["next_payment_due_date"] == date(2026, 11, 28)
    assert shown["card"]["as_of"] is not None
    # No account number or credential travels with it.
    assert "account_number" not in shown["card"] and "access_token_enc" not in shown["card"]

    stranger = Client(name="Sam Example", email="sam@example.com")
    db.add(stranger)
    db.commit()
    assert PortalService(db, stranger.id).accounts() == []
    assert account.id not in {a["id"] for a in PortalService(db, stranger.id).accounts()}
