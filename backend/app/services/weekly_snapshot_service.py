"""Weekly returns series, computed from trades on request.

The fallback behind the returns-series chart for sleeve sets that have no
rows in ``perf.daily_valuation`` yet. It runs the same two calculations as the
headline figures, so the two agree. Nothing is stored here; the weekly
snapshot table this module once wrote has been replaced by the daily rows.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.trade import Trade
from app.services.portfolio_calculation import _as_sleeve_ids
from app.services.mwr_calculation import MWRCalculationService
from app.services.cash_activity_service import CashActivityService
from app.services.cash_ledger import CashLedger

logger = logging.getLogger(__name__)


def _monday_on_or_before(d: date) -> date:
    """Return the Monday on or before date d."""
    return d - timedelta(days=d.weekday())


def _mondays_between(start: date, end: date) -> List[date]:
    """All Mondays in [start, end] inclusive (at least one)."""
    first = _monday_on_or_before(start)
    if first < start:
        first += timedelta(weeks=1)
    mondays = []
    cur = first
    while cur <= end:
        mondays.append(cur)
        cur += timedelta(weeks=1)
    return mondays


class WeeklySnapshotService:
    """Cumulative TWR and MWR at each Monday, from trades."""

    def __init__(self, db: Session):
        self.db = db
        self.mwr_svc = MWRCalculationService(db)
        self.cash = CashActivityService(db)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def returns_series(
        self,
        sleeve_ids: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        cash_account_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Cumulative TWR and MWR since inception, at each Monday and today.

        Computed from the trades of the whole sleeve set with the same two
        calculations as the headline figures (``TWRCalculationService`` and
        ``MWRCalculationService``), so the last point of the chart and the
        headline agree, at every level. Stored snapshot rows are not read:
        averaging per-sleeve figures cannot reproduce a return on the merged
        portfolio.

        The final point is valued at current prices; earlier ones use last
        traded prices.

        Returns list of {"date": str, "twr_cumul": float, "mwr_cumul": float}
        sorted ascending by date, filtered to [start_date, end_date].
        """
        from app.models.position import Position
        from app.services.twr_calculation import TWRCalculationService

        sleeve_ids = _as_sleeve_ids(sleeve_ids)
        if not sleeve_ids:
            return []
        bounds = (
            self.db.query(func.min(Trade.trade_date), func.max(Trade.trade_date))
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .one()
        )
        inception, last_trade = bounds
        if inception is None:
            return []

        # End on today as well as on Mondays, so the series closes at the same
        # moment, and the same market prices, as the headline figures.
        as_of = max(last_trade, date.today())
        mondays = _mondays_between(inception, as_of)
        if not mondays or mondays[-1] != as_of:
            mondays.append(as_of)
        prices = {
            row.symbol: Decimal(str(row.current_price))
            for row in self.db.query(Position).filter(
                Position.sleeve_id.in_(sleeve_ids),
                Position.status == "OPEN",
                Position.current_price.isnot(None),
            )
        }

        ledger = CashLedger.for_accounts(self.db, cash_account_ids or [])
        points = TWRCalculationService(self.db).growth_at(
            sleeve_ids, inception, mondays, prices, ledger
        )
        final = mondays[-1] if mondays and mondays[-1] >= last_trade else None

        result = []
        for point in points:
            monday = point["date"]
            if start_date and monday < start_date:
                continue
            if end_date and monday > end_date:
                continue
            if monday == final:
                # Same window and prices as the headline: up to today, holdings
                # at market.
                mwr = self.mwr_svc.calculate_mwr(
                    sleeve_ids, inception, as_of, prices, ledger
                )
            else:
                mwr = self.mwr_svc.calculate_mwr(
                    sleeve_ids, inception, monday, None, ledger
                )
            result.append(
                {
                    "date": monday.isoformat(),
                    "twr_cumul": (
                        round(point["twr"], 6) if point["twr"] is not None else None
                    ),
                    "mwr_cumul": round(float(mwr), 6) if mwr is not None else None,
                }
            )
        return result
