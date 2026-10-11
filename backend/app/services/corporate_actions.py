"""Corporate actions — putting share counts on one basis.

A stock split changes how many shares a holding is without any trade. Trades
before it are in old shares and trades after it in new ones, so adding them up
as they stand gives nonsense: a position that looks sold ten times over.

The fix applied here is the one price histories use: restate everything before
a split in today's shares. A trade of 4 shares at 1,000 before a 10-for-1 split
is read as 40 shares at 100. Its cash is unchanged, so flows and returns are
unaffected; only the counts and per-share prices move onto the current basis,
where they agree with later trades and with split-adjusted price history.

Stored trades are never altered. The restatement happens on read, through
``adjusted_trades``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.brokerage_connection import BrokerageAccount, BrokerageActivity
from app.models.perf import CorporateAction
from app.models.sleeve import Sleeve
from app.models.trade import Trade


@dataclass(frozen=True)
class TradeView:
    """A trade as the calculations should see it: in today's shares.

    Carries the fields the calculations read from ``Trade``. A separate type
    so that restating a quantity can never be flushed back to the database.
    """

    id: str
    sleeve_id: str
    trade_date: date
    symbol: str
    action: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    security_type: Optional[str]


def split_factors(db: Session) -> Dict[str, List[Tuple[date, Decimal]]]:
    """Every recorded split, by symbol, oldest first."""
    factors: Dict[str, List[Tuple[date, Decimal]]] = {}
    for action in (
        db.query(CorporateAction)
        .filter(CorporateAction.action_type == "SPLIT")
        .order_by(CorporateAction.effective_date)
    ):
        factors.setdefault(action.symbol, []).append(
            (action.effective_date, Decimal(str(action.ratio)))
        )
    return factors


def _factor(splits: List[Tuple[date, Decimal]], traded_on: date) -> Decimal:
    """How many of today's shares one share traded on ``traded_on`` is.

    A trade dated on the split's effective date is already in new shares.
    """
    factor = Decimal(1)
    for effective, ratio in splits:
        if effective > traded_on:
            factor *= ratio
    return factor


def adjusted_trades(db: Session, trades: Iterable[Trade]) -> List[TradeView]:
    """``trades`` restated in today's shares, in the order given."""
    factors = split_factors(db)
    views: List[TradeView] = []
    for trade in trades:
        quantity = Decimal(str(trade.quantity))
        price = Decimal(str(trade.price))
        splits = factors.get(trade.symbol)
        if splits:
            factor = _factor(splits, trade.trade_date)
            if factor != 1:
                quantity *= factor
                price /= factor
        views.append(
            TradeView(
                id=trade.id,
                sleeve_id=trade.sleeve_id,
                trade_date=trade.trade_date,
                symbol=trade.symbol,
                action=trade.action,
                quantity=quantity,
                price=price,
                commission=Decimal(str(trade.commission or 0)),
                security_type=trade.security_type,
            )
        )
    return views


def record_splits(db: Session, brokerage_account_id: str) -> int:
    """Record the splits a brokerage account's stored activity reports.

    The brokerage reports a split as the number of shares it added. The ratio
    is that addition over what was held just before, which the trades give.
    A split is a fact about the security, so one account reporting it serves
    every account. Returns how many new splits were recorded.
    """
    account = (
        db.query(BrokerageAccount)
        .filter(BrokerageAccount.id == brokerage_account_id)
        .first()
    )
    if account is None or account.account_id is None:
        return 0
    sleeve_ids = [
        row[0]
        for row in db.query(Sleeve.id).filter(Sleeve.account_id == account.account_id)
    ]
    known = {
        (a.symbol, a.effective_date)
        for a in db.query(CorporateAction).filter(
            CorporateAction.action_type == "SPLIT"
        )
    }

    recorded = 0
    rows = (
        db.query(BrokerageActivity)
        .filter(
            BrokerageActivity.brokerage_account_id == brokerage_account_id,
            BrokerageActivity.type == "SPLIT",
            BrokerageActivity.symbol.isnot(None),
            BrokerageActivity.activity_date.isnot(None),
        )
        .order_by(BrokerageActivity.activity_date)
        .all()
    )
    for row in rows:
        if (row.symbol, row.activity_date) in known:
            continue
        try:
            added = Decimal(str((row.payload or {}).get("units")))
        except Exception:  # noqa: BLE001 - a malformed row is not a split
            continue
        # Shares held going into the split, in the basis of that day: earlier
        # splits already recorded are applied, this one is not yet.
        earlier = (
            db.query(Trade)
            .filter(
                Trade.sleeve_id.in_(sleeve_ids),
                Trade.symbol == row.symbol,
                Trade.trade_date < row.activity_date,
            )
            .all()
        )
        held = Decimal(0)
        for view in adjusted_trades(db, earlier):
            held += view.quantity if view.action == "BUY" else -view.quantity
        if held <= 0 or added <= 0:
            continue
        db.add(
            CorporateAction(
                symbol=row.symbol,
                effective_date=row.activity_date,
                action_type="SPLIT",
                ratio=(held + added) / held,
                source="brokerage",
            )
        )
        db.flush()
        known.add((row.symbol, row.activity_date))
        recorded += 1
    return recorded
