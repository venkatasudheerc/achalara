"""Retiring SnapTrade: what it left goes, Plaid's accounts are untouched."""
from datetime import date
from decimal import Decimal as D

from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity, BrokerageConnection
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.feed_records import retire_snaptrade
from app.services.plaid_link_service import PlaidLinkService
from tests.test_plaid import CHECKING_ONLY, FakePlaid, _existing, owner, plaid_keys  # noqa: F401


def _trades(db, account):
    return db.query(Trade).join(Sleeve).filter(Sleeve.account_id == account.id).count()


def test_retiring_snaptrade_shows_first_then_removes_only_what_it_left(db, owner, plaid_keys):
    old = _existing(db, owner, "Pat Example — Brokerage Account — 12345678", fed=True)
    sleeve = db.query(Sleeve).filter(Sleeve.account_id == old.id).one()
    link = db.query(BrokerageAccount).filter(BrokerageAccount.account_id == old.id).one()
    db.add_all([
        Trade(sleeve_id=sleeve.id, trade_date=date(2024, 3, 1), symbol="OLD", action="BUY",
              quantity=D(5), price=D(10), commission=D(0), external_id="snap-1"),
        BrokerageActivity(brokerage_account_id=link.id, source_activity_id="snap-1",
                          activity_date=date(2024, 3, 1), type="BUY", outcome="trade", payload={}),
    ])
    db.commit()
    service = PlaidLinkService(db, FakePlaid(accounts=CHECKING_ONLY))
    found = service.finish(owner.id, "public-token")
    service.confirm(owner.id, found["connection_id"], [
        {"link_id": found["accounts"][0]["link_id"], "action": "new"},
    ])
    checking = db.query(Account).filter(Account.client_id == owner.id, Account.id != old.id).one()

    shown = retire_snaptrade(db)
    assert (shown["logins"], shown["accounts_cleared"], shown["source_rows"]) == (1, 1, 1)
    assert _trades(db, old) == 1  # nothing changed

    retire_snaptrade(db, apply=True)
    assert _trades(db, old) == 0
    assert db.get(Account, old.id) is not None  # the account and its strategy stay
    assert not db.query(BrokerageConnection).filter(BrokerageConnection.source == "snaptrade").count()
    assert db.query(BrokerageConnection).filter(BrokerageConnection.source == "plaid").count() == 1
    assert db.query(BrokerageAccount).filter(BrokerageAccount.account_id == checking.id).one().status == "mapped"
