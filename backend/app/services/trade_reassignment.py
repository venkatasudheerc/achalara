"""Move a symbol's history between sleeves of one account.

A linked brokerage account starts as a single sleeve. Splitting it by strategy
means moving securities out to other sleeves — by symbol, not by trade, because
moving a buy without its sells would leave both sleeves' lots unmatched.
"""
from __future__ import annotations

from typing import Dict, List

from sqlalchemy.orm import Session

from app.models.cash_activity import CashActivity
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.performance_build_service import rebuild_for_sleeves


def reassign_symbols(
    db: Session, from_sleeve_id: str, to_sleeve_id: str, symbols: List[str]
) -> Dict:
    """Move every trade and cash activity for ``symbols`` to another sleeve.

    Both sleeves must belong to the same account. The destination takes on the
    source's accounting method, so lots keep matching the way they did.

    Raises LookupError / ValueError so callers can translate to HTTP errors.
    """
    wanted = sorted({s.strip().upper() for s in symbols if s and s.strip()})
    if not wanted:
        raise ValueError("Name at least one symbol to move")
    if from_sleeve_id == to_sleeve_id:
        raise ValueError("Source and destination sleeves are the same")

    source = db.query(Sleeve).filter(Sleeve.id == from_sleeve_id).first()
    target = db.query(Sleeve).filter(Sleeve.id == to_sleeve_id).first()
    if source is None or target is None:
        raise LookupError("Sleeve not found")
    if source.account_id != target.account_id:
        raise ValueError("Trades can only move between sleeves of one account")

    target_has_trades = (
        db.query(Trade.id).filter(Trade.sleeve_id == target.id).first() is not None
    )
    if target_has_trades and target.accounting_method != source.accounting_method:
        raise ValueError(
            "Destination sleeve already holds trades matched a different way"
        )
    target.accounting_method = source.accounting_method

    trades_moved = (
        db.query(Trade)
        .filter(Trade.sleeve_id == source.id, Trade.symbol.in_(wanted))
        .update({Trade.sleeve_id: target.id}, synchronize_session=False)
    )
    cash_moved = (
        db.query(CashActivity)
        .filter(CashActivity.sleeve_id == source.id, CashActivity.symbol.in_(wanted))
        .update({CashActivity.sleeve_id: target.id}, synchronize_session=False)
    )
    db.commit()

    if trades_moved or cash_moved:
        positions = PortfolioCalculationService(db)
        for sleeve_id in (source.id, target.id):
            positions.persist_all_positions(sleeve_id)
        rebuild_for_sleeves(db, [source.id, target.id])

    return {
        "symbols": wanted,
        "trades_moved": trades_moved,
        "cash_activities_moved": cash_moved,
    }
