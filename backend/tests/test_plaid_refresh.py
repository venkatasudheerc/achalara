"""The daily Plaid refresh, and how far an account's record can be trusted."""
from datetime import date
from decimal import Decimal as D

from app.connectors.plaid_connector import PlaidError
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.cash_activity import CashActivity
from app.models.perf import DailyValuation
from app.models.sleeve import Sleeve
from app.services.account_health import account_health, cash_check
from app.services.performance_build_service import PerformanceBuildService
from app.services.plaid_link_service import PlaidLinkService
from app.services.plaid_refresh_service import PlaidRefreshService
from tests.test_plaid import FakePlaid, owner, plaid_keys  # noqa: F401  (fixtures)

CHECKING = [
    {"account_id": "p-chk", "name": "Everyday Checking", "mask": "1111",
     "type": "depository", "subtype": "checking", "balances": {"current": 2500.0}},
]
TUESDAY = date(2026, 11, 17)


class NextDay(FakePlaid):
    """The morning after: one row changed, one removed, one new, and the
    balance moved by exactly those."""

    def __init__(self):
        super().__init__(accounts=[dict(CHECKING[0], balances={"current": 2449.58})])
        self.asked_with = None

    def transactions_sync(self, access_token, cursor=""):
        self.asked_with = cursor
        return {
            "added": [
                {"transaction_id": "b3", "account_id": "p-chk", "date": "2026-11-16",
                 "amount": 50.0, "name": "Grocer", "pending": False},
            ],
            "modified": [
                # The payroll was 2,000; the bank corrected it to 2,000.00 dated a day later.
                {"transaction_id": "b1", "account_id": "p-chk", "date": "2026-11-04",
                 "amount": -2000.0, "name": "Payroll, corrected", "pending": False},
            ],
            "removed": [{"transaction_id": "b2", "account_id": "p-chk"}],
            "next_cursor": "c2",
        }


def _link_checking(db, owner):
    service = PlaidLinkService(db, FakePlaid(accounts=CHECKING))
    found = service.finish(owner.id, "public-token")
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new"},
    ])
    login = db.query(BrokerageConnection).one()
    login.transactions_cursor = "c1"
    db.commit()
    return db.query(Account).filter(Account.client_id == owner.id).one(), login


def _cash_rows(db, account):
    return {
        c.external_id: c
        for c in db.query(CashActivity).join(Sleeve).filter(Sleeve.account_id == account.id)
    }


def test_the_refresh_applies_what_changed_and_was_removed_and_keeps_the_cursor(db, owner, plaid_keys):
    account, login = _link_checking(db, owner)
    assert set(_cash_rows(db, account)) == {"plaid:b1", "plaid:b2"}

    fake = NextDay()
    assert PlaidRefreshService(db, fake).refresh(login, TUESDAY) == "refreshed"

    assert fake.asked_with == "c1" and login.transactions_cursor == "c2"
    rows = _cash_rows(db, account)
    assert set(rows) == {"plaid:b1", "plaid:b3"}
    assert rows["plaid:b1"].activity_date == date(2026, 11, 4)
    assert rows["plaid:b3"].amount == D("-50.00")
    # The morning's balance is recorded as where Monday ended.
    monday = (
        db.query(DailyValuation)
        .filter(DailyValuation.account_id == account.id, DailyValuation.sleeve_id.is_(None),
                DailyValuation.as_of_date == date(2026, 11, 16))
        .one()
    )
    assert (monday.basis, monday.total_value) == ("observed", D("2449.58"))


def test_a_login_that_needs_signing_in_is_marked_and_left_alone(db, owner, plaid_keys):
    _, login = _link_checking(db, owner)

    class SignedOut(FakePlaid):
        def accounts(self, access_token):
            raise PlaidError("ITEM_LOGIN_REQUIRED", "Sign in again")

    assert PlaidRefreshService(db, SignedOut()).refresh(login, TUESDAY) == "needs signing in"
    assert login.status == "broken" and login.disabled_at is not None
    assert PlaidRefreshService(db, NextDay()).refresh_all(TUESDAY) == {}


def _record(db, account, day, cash):
    """The institution's figure for a day, in place of the rebuilt one, as a capture does."""
    db.query(DailyValuation).filter(
        DailyValuation.account_id == account.id, DailyValuation.as_of_date == day
    ).delete()
    db.add(DailyValuation(account_id=account.id, as_of_date=day, securities_value=D(0),
                          cash_value=D(cash), total_value=D(cash), basis="observed"))
    db.commit()


def test_cash_that_agrees_with_every_recorded_day_is_complete(db, owner, plaid_keys):
    account, _ = _link_checking(db, owner)
    # 2,500 now, less the 2,000 paid in on the 3rd, plus the fee on the 4th.
    _record(db, account, date(2026, 11, 2), "500.42")
    assert cash_check(db, account, date(2026, 12, 1))["state"] == "complete"
    assert account_health(db, account, date(2026, 12, 1))["state"] == "complete"


def test_a_recorded_day_the_history_does_not_reach_means_a_movement_is_missing(db, owner, plaid_keys):
    account, _ = _link_checking(db, owner)
    # The bank said 900 on the 5th; the history works back to 2,500 then.
    _record(db, account, date(2026, 11, 5), "900.00")

    later = cash_check(db, account, date(2026, 12, 1))
    assert (later["state"], later["last_differed"]) == ("incomplete", date(2026, 11, 5))
    health = account_health(db, account, date(2026, 12, 1))
    assert health["state"] == "incomplete" and health["download_from"] == date(2026, 11, 5)
    # Within a few days it may still be posting.
    assert cash_check(db, account, date(2026, 11, 7))["state"] == "provisional"

    # And the start is not worked back through the gap: nothing is assumed.
    PerformanceBuildService(db).rebuild_account(account.id)
    first = (
        db.query(DailyValuation.as_of_date)
        .filter(DailyValuation.account_id == account.id, DailyValuation.sleeve_id.is_(None))
        .order_by(DailyValuation.as_of_date)
        .first()[0]
    )
    assert first == date(2026, 11, 3)
    link = db.query(BrokerageAccount).filter(BrokerageAccount.account_id == account.id).one()
    assert link.reconciliation["opening_problems"] == [
        "cash differs from the institution's record on 2026-11-05"
    ]
