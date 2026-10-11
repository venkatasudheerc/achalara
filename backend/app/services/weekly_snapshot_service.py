"""Weekly portfolio snapshot persistence and retrieval.

Snapshots are written per-sleeve, one row per Monday that has trade activity
on or before it. At read time, snapshots are aggregated across the requested
sleeve set (sleeve / account / client / strategy) to produce a returns-series.

TWR per week uses the same sub-period HPR logic as TWRCalculationService but
scoped to each Monday boundary. MWR is solved from inception to each Monday
using MWRCalculationService. Both are stored as holding-period decimals.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional
import logging

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.trade import Trade
from app.models.weekly_snapshot import WeeklyPortfolioSnapshot
from app.services.portfolio_calculation import PortfolioCalculationService, _as_sleeve_ids
from app.services.mwr_calculation import MWRCalculationService
from app.services.cash_activity_service import CashActivityService

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
    """Compute and persist per-sleeve weekly snapshots."""

    def __init__(self, db: Session):
        self.db = db
        self.portfolio = PortfolioCalculationService(db)
        self.mwr_svc = MWRCalculationService(db)
        self.cash = CashActivityService(db)

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def rebuild_sleeve(self, sleeve_id: str, from_date: Optional[date] = None) -> int:
        """Recompute all snapshots for a sleeve from from_date forward.

        If from_date is None, deletes all snapshots and rebuilds from the
        sleeve's first trade. Returns the number of rows upserted.
        """
        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id == sleeve_id)
            .order_by(Trade.trade_date)
            .all()
        )
        if not trades:
            return 0

        inception_date = trades[0].trade_date
        last_trade_date = trades[-1].trade_date

        # Delete snapshots from from_date forward (or all if rebuilding fully).
        delete_from = from_date or date.min
        self.db.query(WeeklyPortfolioSnapshot).filter(
            WeeklyPortfolioSnapshot.sleeve_id == sleeve_id,
            WeeklyPortfolioSnapshot.week_start_date >= delete_from,
        ).delete(synchronize_session=False)

        mondays = _mondays_between(
            from_date or inception_date,
            max(last_trade_date, date.today()),
        )

        # Load pre-existing cumulative TWR up to the week before from_date so
        # we can continue geometric linking.
        prior_twr_cumul = 1.0
        if from_date:
            prior_monday = _monday_on_or_before(from_date) - timedelta(weeks=1)
            prior_snap = (
                self.db.query(WeeklyPortfolioSnapshot)
                .filter(
                    WeeklyPortfolioSnapshot.sleeve_id == sleeve_id,
                    WeeklyPortfolioSnapshot.week_start_date <= prior_monday,
                )
                .order_by(WeeklyPortfolioSnapshot.week_start_date.desc())
                .first()
            )
            if prior_snap and prior_snap.twr_cumul is not None:
                prior_twr_cumul = 1.0 + prior_snap.twr_cumul

        count = 0
        running_twr = prior_twr_cumul

        for monday in mondays:
            # Only write a snapshot if there are trades on or before this Monday.
            relevant_trades = [t for t in trades if t.trade_date <= monday]
            if not relevant_trades:
                continue

            snap = self._compute_snapshot(sleeve_id, monday, trades, running_twr, inception_date)
            if snap is None:
                continue

            running_twr = 1.0 + snap.twr_cumul if snap.twr_cumul is not None else running_twr
            self.db.add(snap)
            count += 1

        self.db.commit()
        return count

    def rebuild_all(self) -> Dict[str, int]:
        """Full rebuild across every sleeve that has trades."""
        from app.models.sleeve import Sleeve

        sleeve_ids = [r[0] for r in self.db.query(Sleeve.id).all()]
        results = {}
        for sid in sleeve_ids:
            results[sid] = self.rebuild_sleeve(sid)
        return results

    def recompute_from(self, sleeve_id: str, earliest_trade_date: date) -> int:
        """Recompute snapshots for sleeve_id from the Monday of earliest_trade_date."""
        from_monday = _monday_on_or_before(earliest_trade_date)
        return self.rebuild_sleeve(sleeve_id, from_date=from_monday)

    def returns_series(
        self,
        sleeve_ids: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
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

        points = TWRCalculationService(self.db).growth_at(
            sleeve_ids, inception, mondays, prices
        )
        final = mondays[-1] if mondays and mondays[-1] >= last_trade else None
        last_activity = self.cash.last_activity_date(sleeve_ids)

        result = []
        for point in points:
            monday = point["date"]
            if start_date and monday < start_date:
                continue
            if end_date and monday > end_date:
                continue
            if monday == final:
                # Same window and prices as the headline: up to the last trade
                # or income payment, holdings at market.
                mwr = self.mwr_svc.calculate_mwr(
                    sleeve_ids, inception, last_activity, prices
                )
            else:
                mwr = self.mwr_svc.calculate_mwr(sleeve_ids, inception, monday)
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

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _compute_snapshot(
        self,
        sleeve_id: str,
        monday: date,
        all_trades: List[Trade],
        running_twr: float,
        inception_date: date,
    ) -> Optional[WeeklyPortfolioSnapshot]:
        """Compute one snapshot row for (sleeve_id, monday)."""
        prev_monday = monday - timedelta(weeks=1)

        trades_this_week = [
            t for t in all_trades
            if prev_monday < t.trade_date <= monday
        ]
        trades_to_date = [t for t in all_trades if t.trade_date <= monday]

        if not trades_to_date:
            return None

        # Portfolio value at end of this week (as of monday).
        series_point = self._portfolio_value_at(sleeve_id, monday, all_trades)
        market_value = series_point.get("market_value", 0.0)
        cost_basis = series_point.get("cost_basis", 0.0)

        # Portfolio value at end of prior week.
        prev_series = self._portfolio_value_at(sleeve_id, prev_monday, all_trades)
        prev_mv = prev_series.get("market_value", 0.0)

        # Weekly cash flows.
        cash_in = sum(
            float(t.quantity) * float(t.price) + float(t.commission)
            for t in trades_this_week if t.action == "BUY"
        )
        cash_out = sum(
            float(t.quantity) * float(t.price) - float(t.commission)
            for t in trades_this_week if t.action == "SELL"
        )

        # Dividends and fees received this week leave the sleeve like sale
        # proceeds do, so they join cash_out (a net fee week reduces it).
        cash_out += float(
            sum(
                (
                    amount
                    for _, amount in self.cash.income_flows(
                        [sleeve_id], prev_monday + timedelta(days=1), monday
                    )
                ),
                Decimal(0),
            )
        )

        # Realized gain this week.
        realized_gain = self._realized_gain_in_period(sleeve_id, prev_monday, monday, all_trades)

        # TWR for this sub-period (modified Dietz).
        twr_period = self._twr_period(prev_mv, market_value, cash_in, cash_out)

        # Geometric-link to cumulative TWR.
        if twr_period is not None:
            new_running = running_twr * (1.0 + twr_period)
            twr_cumul = new_running - 1.0
        else:
            twr_cumul = running_twr - 1.0

        # MWR from inception to this Monday.
        try:
            mwr_cumul = float(
                self.mwr_svc.calculate_mwr([sleeve_id], inception_date, monday)
            )
        except Exception:
            mwr_cumul = None

        return WeeklyPortfolioSnapshot(
            sleeve_id=sleeve_id,
            week_start_date=monday,
            twr_period=round(twr_period, 6) if twr_period is not None else None,
            twr_cumul=round(twr_cumul, 6) if twr_cumul is not None else None,
            mwr_cumul=round(mwr_cumul, 6) if mwr_cumul is not None else None,
            cost_basis=cost_basis,
            market_value=market_value,
            cash_in=cash_in,
            cash_out=cash_out,
            realized_gain=realized_gain,
        )

    def _portfolio_value_at(
        self, sleeve_id: str, as_of: date, all_trades: List[Trade]
    ) -> Dict:
        """Compute portfolio market value and cost basis as of a date."""
        book: Dict[str, Dict] = {}
        for trade in all_trades:
            if trade.trade_date > as_of:
                break
            symbol = trade.symbol
            qty = Decimal(str(trade.quantity))
            price = Decimal(str(trade.price))
            comm = Decimal(str(trade.commission))

            entry = book.setdefault(
                symbol, {"qty": Decimal(0), "cost": Decimal(0), "last_price": price}
            )
            entry["last_price"] = price

            if trade.action == "BUY":
                entry["qty"] += qty
                entry["cost"] += qty * price + comm
            else:
                old_qty = entry["qty"]
                if old_qty > 0:
                    cost_per = entry["cost"] / old_qty
                    entry["qty"] = old_qty - qty
                    entry["cost"] = max(Decimal(0), entry["qty"] * cost_per)
                else:
                    entry["qty"] = old_qty - qty

        total_mv = Decimal(0)
        total_cost = Decimal(0)
        for symbol, e in book.items():
            if e["qty"] > 0:
                total_mv += e["qty"] * e["last_price"]
                total_cost += e["cost"]

        return {"market_value": float(total_mv), "cost_basis": float(total_cost)}

    def _twr_period(
        self, start_mv: float, end_mv: float, cash_in: float, cash_out: float
    ) -> Optional[float]:
        """Modified Dietz sub-period HPR.

        HPR = (end_value + cash_out - cash_in - start_value) / (start_value + cash_in)
        Returns None if the denominator is zero (e.g., inception week).
        """
        denominator = start_mv + cash_in
        if denominator <= 0:
            if cash_in > 0:
                # Inception week: treat deployed capital as the base.
                numerator = end_mv - cash_in + cash_out
                return numerator / cash_in if cash_in else None
            return None
        numerator = end_mv + cash_out - cash_in - start_mv
        return numerator / denominator

    def _realized_gain_in_period(
        self,
        sleeve_id: str,
        period_start: date,
        period_end: date,
        all_trades: List[Trade],
    ) -> float:
        """Realized gain from closed round-trips whose SELL date falls in (period_start, period_end]."""
        result = self.portfolio.calculate_positions([sleeve_id], as_of_date=period_end)
        return sum(
            float(p["realized_gain"])
            for p in result["closed"]
            if p["closed_at"] and period_start < p["closed_at"] <= period_end
        )
