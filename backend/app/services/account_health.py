"""How far an account's record can be trusted: complete, provisional or incomplete.

Three checks, each comparing what our transactions add up to with the
institution's own record:

- **The opening** (``opening_position``): the history before the first
  transaction works back to fewer than no shares, or to cash below nothing in an
  account not owed money. A transaction is missing before the history starts.
- **Holdings** (``AccountImportService.holdings_check``): each day the
  institution recorded holdings against what the trades add up to.
- **Cash** (``cash_check``): each day the institution recorded cash against the
  balance the transactions on file work back to. The record is worked back from
  today, so the latest day always agrees; an earlier day that differs means a
  movement between it and the next day that agrees is missing, and every day
  before it is out by that amount.

A difference in the last ``SETTLE_DAYS`` days may still clear as transactions
post, so it makes the account provisional, not incomplete. Nothing here changes
a figure; screens say how sure a figure is, and nudges are never built on an
account that is not complete.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount
from app.models.perf import DailyValuation
from app.services.cash_ledger import CashLedger

COMPLETE = "complete"
PROVISIONAL = "provisional"
INCOMPLETE = "incomplete"
# Calendar days a difference may take to clear while transactions post.
SETTLE_DAYS = 5
_CENT = Decimal("0.01")


def cash_check(db: Session, account: Account, today: Optional[date] = None) -> Optional[Dict]:
    """Each day the institution recorded the account's cash, against the balance
    the transactions on file work back to. None when there is nothing to compare.

    A day's figure may be taken before that day's movements show, so a day
    agrees when it matches the balance at its close or at the close before.
    """
    today = today or date.today()
    ledger = CashLedger.for_accounts(db, [account.id])
    if ledger is None:
        return None
    recorded = [
        (row.as_of_date, Decimal(str(row.cash_value)))
        for row in db.query(DailyValuation)
        .filter(
            DailyValuation.account_id == account.id,
            DailyValuation.sleeve_id.is_(None),
            DailyValuation.basis == "observed",
            DailyValuation.cash_value.isnot(None),
        )
        .order_by(DailyValuation.as_of_date)
    ]
    if not recorded:
        return None
    differing: List[date] = []
    for day, cash in recorded:
        at_close = ledger.balance_on(day) - ledger.pending
        before = ledger.balance_on(day - timedelta(days=1)) - ledger.pending
        if min(abs(cash - at_close), abs(cash - before)) > _CENT:
            differing.append(day)
    if not differing:
        return {"state": COMPLETE, "last_differed": None, "agrees_from": None}
    last = max(differing)
    agrees_from = next((day for day, _ in recorded if day > last), None)
    return {
        "state": PROVISIONAL if last >= today - timedelta(days=SETTLE_DAYS) else INCOMPLETE,
        "last_differed": last,
        "agrees_from": agrees_from,
    }


def account_health(db: Session, account: Account, today: Optional[date] = None) -> Dict:
    """The account's state, the reasons for it in plain words, and where a
    download should start to repair it (``download_from``)."""
    from app.services.account_import_service import AccountImportService

    today = today or date.today()
    states: List[str] = []
    reasons: List[str] = []
    starts: List[date] = []

    problems = [
        problem
        for link in db.query(BrokerageAccount).filter(BrokerageAccount.account_id == account.id)
        for problem in (link.reconciliation or {}).get("opening_problems") or []
    ]
    if problems:
        states.append(INCOMPLETE)
        reasons.append("A transaction is missing from the start of the history: it does not add up to what is held.")

    holdings = AccountImportService(db).holdings_check(account)
    if holdings and holdings["differences"]:
        since = holdings["first_differed"]
        recent = since is not None and since >= today - timedelta(days=SETTLE_DAYS)
        states.append(PROVISIONAL if recent else INCOMPLETE)
        reasons.append(
            "Recent trades are still arriving." if recent
            else f"Holdings differ from the institution's record since {since:%-d %b %Y}."
        )
        if not recent and holdings.get("download_from"):
            starts.append(holdings["download_from"])

    cash = cash_check(db, account, today)
    if cash and cash["state"] != COMPLETE:
        states.append(cash["state"])
        if cash["state"] == PROVISIONAL:
            reasons.append("Recent transactions are still posting.")
        else:
            reasons.append(
                f"Cash differs from the institution's record on {cash['last_differed']:%-d %b %Y}: "
                "a movement after it is missing."
            )
            starts.append(cash["last_differed"])

    state = INCOMPLETE if INCOMPLETE in states else PROVISIONAL if PROVISIONAL in states else COMPLETE
    return {
        "state": state,
        "reasons": reasons,
        "download_from": min(starts) if starts else None,
    }
