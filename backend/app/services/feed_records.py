"""Clearing what a feed left in an account, for a clean start.

Plaid replaces any earlier feed (``PlaidLinkService._take_over``), and SnapTrade
is retired altogether (``retire_snaptrade``, the CLI's ``retire-snaptrade``).
Either way the account and its strategies stay; its transactions, cash rows,
positions and daily record go, and earlier history comes from the owner's files.
"""
from __future__ import annotations

from typing import Dict

from sqlalchemy.orm import Session

from app.models.brokerage_connection import (
    BrokerageAccount,
    BrokerageActivity,
    BrokerageConnection,
)
from app.models.cash_activity import CashActivity
from app.models.perf import DailyHolding, DailyValuation
from app.models.position import Position
from app.models.sleeve import Sleeve
from app.models.trade import Trade

SNAPTRADE = "snaptrade"


def clear_account_records(db: Session, account_id: str) -> Dict[str, int]:
    """Delete an account's transactions, cash rows, positions and daily record.
    Does not commit. Returns how many rows of each went."""
    sleeve_ids = [
        row[0] for row in db.query(Sleeve.id).filter(Sleeve.account_id == account_id)
    ] or [""]
    counts = {
        "trades": db.query(Trade).filter(Trade.sleeve_id.in_(sleeve_ids)).delete(
            synchronize_session=False
        ),
        "cash": db.query(CashActivity).filter(CashActivity.sleeve_id.in_(sleeve_ids)).delete(
            synchronize_session=False
        ),
        "positions": db.query(Position).filter(Position.sleeve_id.in_(sleeve_ids)).delete(
            synchronize_session=False
        ),
        "days": db.query(DailyValuation)
        .filter((DailyValuation.account_id == account_id) | DailyValuation.sleeve_id.in_(sleeve_ids))
        .delete(synchronize_session=False),
        "holdings": db.query(DailyHolding).filter(DailyHolding.account_id == account_id).delete(
            synchronize_session=False
        ),
    }
    return counts


def retire_snaptrade(db: Session, apply: bool = False) -> Dict:
    """Remove everything SnapTrade brought in: the records of every account it
    still feeds, its source rows, its links and its logins. The accounts and
    their strategies stay, empty until Plaid or a file fills them.

    Without ``apply`` nothing changes: the counts say what would go.
    """
    logins = db.query(BrokerageConnection).filter(BrokerageConnection.source == SNAPTRADE).all()
    links = (
        db.query(BrokerageAccount)
        .filter(BrokerageAccount.connection_id.in_([c.id for c in logins] or [""]))
        .all()
    )
    fed = sorted({l.account_id for l in links if l.account_id and l.status == "mapped"})
    summary = {
        "logins": len(logins),
        "links": len(links),
        "accounts_cleared": len(fed),
        "source_rows": db.query(BrokerageActivity)
        .filter(BrokerageActivity.brokerage_account_id.in_([l.id for l in links] or [""]))
        .count(),
        "removed": {},
    }
    if not apply:
        return summary
    removed: Dict[str, int] = {}
    for account_id in fed:
        for name, count in clear_account_records(db, account_id).items():
            removed[name] = removed.get(name, 0) + count
    db.query(BrokerageActivity).filter(
        BrokerageActivity.brokerage_account_id.in_([l.id for l in links] or [""])
    ).delete(synchronize_session=False)
    for login in logins:
        db.delete(login)  # its links go with it
    db.commit()
    summary["removed"] = removed
    return summary
