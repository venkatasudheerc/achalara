"""Feed rows that are rows of a custodian's file, already counted.

When a file and the feed both report a purchase, the app keeps the file's rows
and the feed's row is marked ``REPORT_TWIN`` with none of its cash
(``ConnectionService``). A feed row stored before it could be recognised (the
feed sent one row for several of the file's, one per source of a plan's money)
counts the purchase twice. ``repair`` finds those, removes the feed's trade,
marks its source row and rebuilds what read it.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Dict, List

from sqlalchemy.orm import Session

from app.connectors.models import REPORT_ID_PREFIX
from app.connectors.plaid_reader import ID_PREFIX as PLAID_PREFIX
from app.models.account import Account
from app.models.brokerage_connection import BrokerageActivity, BrokerageAccount
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.connection_service import REPORT_TWIN
from app.services.opening_position import NOT_OPENING
from app.services.twin_match import PRICE_TOLERANCE, WEEKDAYS, sum_to, weekdays_apart
from app.utils.symbols import app_symbol

logger = logging.getLogger(__name__)
_SAME_QUANTITY = Decimal("0.0001")


def _one_for_one(feed: Trade, reports: List[Trade]):
    for report in reports:
        if (
            report.action == feed.action
            and app_symbol(report.symbol) == app_symbol(feed.symbol)
            and abs(Decimal(str(report.quantity)) - Decimal(str(feed.quantity))) <= _SAME_QUANTITY
            and abs(Decimal(str(report.price)) - Decimal(str(feed.price))) <= PRICE_TOLERANCE
            and weekdays_apart(report.trade_date, feed.trade_date) <= WEEKDAYS
        ):
            return [report]
    return None


def find(db: Session, account_id: str) -> List[Dict]:
    """The feed trades of one account that the file's trades already count."""
    sleeve_ids = [row[0] for row in db.query(Sleeve.id).filter(Sleeve.account_id == account_id)]
    if not sleeve_ids:
        return []
    trades = db.query(Trade).filter(Trade.sleeve_id.in_(sleeve_ids), NOT_OPENING).all()
    reports = [t for t in trades if (t.external_id or "").startswith(REPORT_ID_PREFIX)]
    feed = sorted(
        (t for t in trades if (t.external_id or "").startswith(PLAID_PREFIX)),
        key=lambda t: (t.trade_date, t.id),
    )
    used: set = set()
    found: List[Dict] = []
    for trade in feed:
        free = [r for r in reports if r.id not in used]
        counted = _one_for_one(trade, free)
        if counted is None:
            parts = sum_to(
                Decimal(str(trade.quantity)), Decimal(str(trade.price)), trade.trade_date,
                [
                    (r, r.quantity, r.price, r.trade_date)
                    for r in free
                    if r.action == trade.action and app_symbol(r.symbol) == app_symbol(trade.symbol)
                ],
            )
            counted = parts
        if counted:
            used.update(r.id for r in counted)
            found.append({"feed": trade, "file": counted})
    return found


def repair(db: Session, apply: bool = False) -> Dict:
    """Every account's duplicates. Shows only unless ``apply``: then removes each
    feed trade, marks its source row (no cash, so the file's row alone counts it)
    and rebuilds the accounts touched. Safe to repeat."""
    from app.services.performance_build_service import rebuild_for_sleeves
    from app.services.portfolio_calculation import PortfolioCalculationService

    shown: List[Dict] = []
    touched: Dict[str, List[str]] = {}
    for account in db.query(Account).all():
        for item in find(db, account.id):
            feed = item["feed"]
            shown.append(
                {
                    "account_id": account.id,
                    "date": feed.trade_date,
                    "symbol": feed.symbol,
                    "action": str(getattr(feed.action, "value", feed.action)),
                    "quantity": Decimal(str(feed.quantity)),
                    "file_rows": len(item["file"]),
                }
            )
            if not apply:
                continue
            links = [row[0] for row in db.query(BrokerageAccount.id).filter(BrokerageAccount.account_id == account.id)]
            for record in db.query(BrokerageActivity).filter(
                BrokerageActivity.brokerage_account_id.in_(links),
                BrokerageActivity.source_activity_id == feed.external_id,
            ):
                record.outcome = REPORT_TWIN
                record.cash_amount = Decimal(0)
            db.delete(feed)
            touched[account.id] = [row[0] for row in db.query(Sleeve.id).filter(Sleeve.account_id == account.id)]
    if apply and touched:
        db.commit()
        for sleeve_ids in touched.values():
            for sleeve_id in sleeve_ids:
                PortfolioCalculationService(db).persist_all_positions(sleeve_id)
            rebuild_for_sleeves(db, sleeve_ids)
    return {"duplicates": shown, "rebuilt": len(touched) if apply else 0}
