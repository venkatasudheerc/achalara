"""The daily refresh of every Plaid login: transactions, balances and holdings.

Runs once each weekday morning (``scheduler.py``, ``plaid_refresh``) and records
the day before: an early-morning balance is where the previous day ended. Bank
and card transactions come through Plaid's sync, which hands back what was
added, changed and removed since its cursor; changes and removals are applied
to what is on file, and the cursor is kept on the login. Investment
transactions are read again over a recent window, and what is already on file
is recognised by its id. Each account's day is then recorded through
``DailyCaptureService.record``, which rebuilds it.

A login Plaid says needs signing in again is marked ``broken`` and left alone
until the client repairs it; the other logins carry on.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.connectors import plaid_reader
from app.connectors.plaid_connector import PlaidClient, PlaidError, configured
from app.models.account import Account
from app.models.brokerage_connection import (
    BrokerageAccount,
    BrokerageActivity,
    BrokerageConnection,
)
from app.models.cash_activity import CashActivity
from app.models.sleeve import Sleeve
from app.services.account_kind import OWED, kind_of
from app.services.daily_capture_service import DailyCaptureService
from app.services.performance_build_service import last_market_day
from app.services.plaid_link_service import PlaidLinkService

logger = logging.getLogger(__name__)

SOURCE = "plaid"
# Investment transactions are read again over this window each day: a trade
# can reach Plaid a few days after it happened.
REFRESH_DAYS = 30
# Plaid's word that the login needs the client to sign in again.
NEEDS_SIGN_IN = {
    "ITEM_LOGIN_REQUIRED",
    "PENDING_EXPIRATION",
    "ACCESS_NOT_GRANTED",
    "INVALID_ACCESS_TOKEN",
    "ITEM_NOT_FOUND",
    "USER_PERMISSION_REVOKED",
}


class PlaidRefreshService:
    def __init__(self, db: Session, client: Optional[PlaidClient] = None):
        self.db = db
        self.links = PlaidLinkService(db, client)
        self.client = self.links.client
        self.connections = self.links.connections

    def refresh_all(self, today: Optional[date] = None) -> Dict[str, str]:
        """Refresh every Plaid login with an account in use. One failing does
        not stop the rest. Returns each login's outcome by id."""
        if not configured():
            return {}
        logins = (
            self.db.query(BrokerageConnection)
            .filter(
                BrokerageConnection.source == SOURCE,
                BrokerageConnection.status == "active",
            )
            .all()
        )
        outcomes: Dict[str, str] = {}
        for login in logins:
            try:
                outcomes[login.id] = self.refresh(login, today)
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.error("Plaid refresh failed for login %s: %s", login.id, type(exc).__name__)
                outcomes[login.id] = "failed"
        return outcomes

    def refresh(self, login: BrokerageConnection, today: Optional[date] = None) -> str:
        """Bring one login's accounts up to date and record yesterday."""
        today = today or date.today()
        day = last_market_day(today - timedelta(days=1))
        links = [l for l in login.brokerage_accounts if l.status == "mapped" and l.account_id]
        if not links:
            return "nothing mapped"
        token = self.links._access_token(login)
        banks = [l for l in links if l.plaid_type in ("depository", "credit")]
        invested = [l for l in links if l.plaid_type == "investment"]
        try:
            accounts = {a["account_id"]: a for a in self.client.accounts(token).get("accounts", [])}
            synced = (
                self.client.transactions_sync(token, login.transactions_cursor or "")
                if banks
                else None
            )
            history = held = None
            if invested:
                history = self.client.investment_transactions(
                    token, today - timedelta(days=REFRESH_DAYS), today
                )
                held = self.client.holdings(token)
        except PlaidError as error:
            if error.code in NEEDS_SIGN_IN:
                login.status = "broken"
                login.disabled_at = login.disabled_at or datetime.now(timezone.utc)
                login.status_checked_at = datetime.now(timezone.utc)
                self.db.commit()
                return "needs signing in"
            raise
        login.status_checked_at = datetime.now(timezone.utc)

        for link in links:
            account = self.db.get(Account, link.account_id)
            plaid = accounts.get(link.external_account_ref, {})
            owed = kind_of(account) in OWED
            if not plaid:
                logger.warning("Plaid did not list linked account %s today", link.id)
                continue
            if link in banks:
                mine = lambda rows: [r for r in rows if r.get("account_id") == link.external_account_ref]  # noqa: E731
                self._apply_changes(link, mine(synced.get("modified", [])), mine(synced.get("removed", [])))
                batch = plaid_reader.read_bank_transactions(
                    mine(synced.get("added", [])) + mine(synced.get("modified", []))
                )
                figures = plaid_reader.read_balance(plaid, owed)
                record_day = day
            elif link in invested:
                securities = {s["security_id"]: s for s in history.get("securities", [])}
                rows = [
                    r for r in history.get("investment_transactions", [])
                    if r.get("account_id") == link.external_account_ref
                ]
                batch = plaid_reader.read_investment_transactions(rows, securities)
                figures = plaid_reader.read_holdings(
                    plaid, held.get("holdings", []),
                    {s["security_id"]: s for s in held.get("securities", [])},
                )
                record_day = figures.day or day
            else:
                # A loan or other account Plaid gives a balance for and nothing else.
                batch = plaid_reader.read_bank_transactions([])
                figures = plaid_reader.read_balance(plaid, owed)
                record_day = day
            link.cash_balance = figures.cash
            link.cash_balance_at = datetime.now(timezone.utc)
            self.db.commit()
            if batch.trades or batch.cash or batch.raw:
                self.connections.ingest_batch(link, batch)
            link.transactions_synced_through = today
            link.last_synced_at = datetime.now(timezone.utc)
            self.db.commit()
            DailyCaptureService(self.db, self.connections).record(
                link, record_day, figures.positions, figures.cash, figures.total,
                valuation_adjustment=Decimal(0),
            )
        if synced is not None:
            # Only once everything it handed back is on file.
            login.transactions_cursor = synced.get("next_cursor") or login.transactions_cursor
        self.db.commit()
        return "refreshed"

    def _apply_changes(self, link: BrokerageAccount, modified: List[Dict], removed: List[Dict]) -> None:
        """A bank row Plaid changed is changed here; one it removed is removed.

        Both are found by Plaid's transaction id. A changed row that is now
        pending is removed until it posts again. New rows are added by the
        ingestion that follows, which also replaces the stored source rows."""
        sleeve_ids = [
            row[0] for row in self.db.query(Sleeve.id).filter(Sleeve.account_id == link.account_id)
        ]
        gone = {plaid_reader.ID_PREFIX + str(r["transaction_id"]) for r in removed if r.get("transaction_id")}
        gone |= {
            plaid_reader.ID_PREFIX + str(r["transaction_id"])
            for r in modified if r.get("pending") and r.get("transaction_id")
        }
        changed = plaid_reader.read_bank_transactions([r for r in modified if not r.get("pending")])
        by_id = {c.external_id: c for c in changed.cash}
        if sleeve_ids:
            for row in self.db.query(CashActivity).filter(
                CashActivity.sleeve_id.in_(sleeve_ids),
                CashActivity.external_id.in_(list(gone | set(by_id)) or [""]),
            ):
                if row.external_id in gone:
                    self.db.delete(row)
                    continue
                new = by_id[row.external_id]
                row.amount = new.amount
                row.type = new.type
                row.activity_date = new.occurred_at.date()
                row.notes = new.notes
        if gone:
            self.db.query(BrokerageActivity).filter(
                BrokerageActivity.brokerage_account_id == link.id,
                BrokerageActivity.source_activity_id.in_(list(gone)),
            ).delete(synchronize_session=False)
        self.db.flush()


def run_plaid_refresh(db: Session) -> Dict[str, str]:
    """Called by the scheduler job."""
    return PlaidRefreshService(db).refresh_all()
