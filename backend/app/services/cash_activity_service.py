"""Cash activity service — dividends, fees and other non-trade money movements.

Performance here is securities-only: a sleeve's value is its open positions,
BUYs are money put in and SELLs are money taken out. There is no cash balance.
Income fits that model as money taken out without selling anything; deposits
and withdrawals do not belong in it at all, so they are stored but never
counted as returns.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.connectors.models import NormalizedCashActivity
from app.models.cash_activity import INCOME_TYPES, CashActivity
from app.models.trade import Trade

logger = logging.getLogger(__name__)


class CashActivityService:
    """Persists cash activities and exposes the ones that count as returns."""

    def __init__(self, db: Session):
        self.db = db

    def ingest(
        self,
        activities: List[NormalizedCashActivity],
        sleeve_id: str,
        dedup_sleeve_ids: Optional[List[str]] = None,
    ) -> Dict:
        """Persist new cash activities into a sleeve, skipping known ones.

        ``dedup_sleeve_ids`` widens the duplicate check beyond the target
        sleeve, as in ``IngestionService.ingest_to_sleeve``. Does not commit;
        the caller owns the transaction.
        """
        scope = dedup_sleeve_ids or [sleeve_id]
        existing = {
            row[0]
            for row in self.db.query(CashActivity.external_id).filter(
                CashActivity.sleeve_id.in_(scope)
            )
        }
        imported = 0
        earliest: Optional[date] = None
        for activity in activities:
            if activity.external_id in existing:
                continue
            existing.add(activity.external_id)
            activity_date = activity.occurred_at.date()
            self.db.add(
                CashActivity(
                    sleeve_id=sleeve_id,
                    activity_date=activity_date,
                    type=activity.type,
                    symbol=activity.symbol,
                    amount=activity.amount,
                    notes=activity.notes,
                    external_id=activity.external_id,
                )
            )
            imported += 1
            if earliest is None or activity_date < earliest:
                earliest = activity_date
        self.db.flush()
        return {
            "imported": imported,
            "duplicates": len(activities) - imported,
            "earliest_activity_date": earliest,
        }

    def list_for_sleeves(self, sleeve_ids: List[str]) -> List[Dict]:
        """Every cash activity in the sleeve set, newest first.

        Each carries ``counts_toward_returns`` so a reader can tell income that
        feeds MWR/TWR from money that is only recorded.
        """
        if not sleeve_ids:
            return []
        traded = self._traded_symbols(sleeve_ids)
        rows = (
            self.db.query(CashActivity)
            .filter(CashActivity.sleeve_id.in_(sleeve_ids))
            .order_by(CashActivity.activity_date.desc(), CashActivity.id)
            .all()
        )
        return [
            {
                "id": row.id,
                "sleeve_id": row.sleeve_id,
                "activity_date": row.activity_date,
                "type": row.type,
                "symbol": row.symbol,
                "amount": float(row.amount),
                "notes": row.notes,
                "counts_toward_returns": _counts(row, traded),
            }
            for row in rows
        ]

    def income_flows(
        self,
        sleeve_ids: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Tuple[date, Decimal]]:
        """Net investment income per day, signed from the holder's side.

        Fees always count. Dividends, interest and tax withheld count only when
        paid on a security the sleeve set has traded: income on anything else
        (interest on the settlement fund, say) is a return on cash that this
        model does not hold, and counting it would credit the sleeve with gains
        on money it never had invested.
        """
        if not sleeve_ids:
            return []
        query = self.db.query(CashActivity).filter(
            CashActivity.sleeve_id.in_(sleeve_ids),
            CashActivity.type.in_(INCOME_TYPES),
        )
        if start_date is not None:
            query = query.filter(CashActivity.activity_date >= start_date)
        if end_date is not None:
            query = query.filter(CashActivity.activity_date <= end_date)
        activities = query.all()
        if not activities:
            return []

        traded = self._traded_symbols(sleeve_ids)
        daily: Dict[date, Decimal] = {}
        for activity in activities:
            if not _counts(activity, traded):
                continue
            daily[activity.activity_date] = daily.get(
                activity.activity_date, Decimal(0)
            ) + Decimal(str(activity.amount))
        return sorted(daily.items())

    def _traded_symbols(self, sleeve_ids: List[str]) -> set:
        return {
            row[0]
            for row in self.db.query(Trade.symbol)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .distinct()
        }

    def total_income(
        self,
        sleeve_ids: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> float:
        """Sum of ``income_flows`` over the window."""
        return float(
            sum(
                (
                    amount
                    for _, amount in self.income_flows(sleeve_ids, start_date, end_date)
                ),
                Decimal(0),
            )
        )


def _counts(activity: CashActivity, traded_symbols: set) -> bool:
    """Whether an activity is investment income or cost for its sleeve set."""
    if activity.type not in INCOME_TYPES:
        return False
    return activity.type == "FEE" or activity.symbol in traded_symbols
