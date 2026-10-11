"""Performance orchestration across sleeve / account / client levels.

Computes a summary (MWR, TWR, total return, cost basis, market value) plus a
chart-ready value time-series for an arbitrary set of sleeves. Passing a single
sleeve gives a sleeve-level view; all of an account's sleeves give the account
roll-up; all of a client's sleeves give the client roll-up. Aggregate returns are
computed on the *merged* underlying cash-flow streams, not by averaging child
returns.
"""
import calendar
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.position import Position
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.mwr_calculation import MWRCalculationService
from app.services.twr_calculation import TWRCalculationService
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.cash_activity_service import CashActivityService
from app.connectors.webull_connector import WebullConnector
from app.connectors.models import is_option_symbol

import logging

_log = logging.getLogger(__name__)


class PerformanceService:
    """Builds multi-level performance payloads from sleeve sets."""

    def __init__(self, db: Session):
        self.db = db
        self.mwr = MWRCalculationService(db)
        self.twr = TWRCalculationService(db)
        self.portfolio = PortfolioCalculationService(db)
        self.cash = CashActivityService(db)

    # -- sleeve-set resolution ------------------------------------------------

    def sleeve_ids_for_account(self, account_id: str) -> List[str]:
        rows = self.db.query(Sleeve.id).filter(Sleeve.account_id == account_id).all()
        return [r[0] for r in rows]

    def sleeve_ids_for_client(self, client_id: str) -> List[str]:
        rows = (
            self.db.query(Sleeve.id)
            .join(Account, Sleeve.account_id == Account.id)
            .filter(Account.client_id == client_id)
            .all()
        )
        return [r[0] for r in rows]

    # -- core -----------------------------------------------------------------

    def _fetch_live_prices(self, sleeve_ids: List[str]) -> Dict[str, Decimal]:
        """Fetch live prices from Webull for open positions, persist them, and return.

        Falls back to the last persisted current_price for any symbol that fails
        or when Webull credentials are not configured.
        """
        open_positions = (
            self.db.query(Position)
            .filter(Position.sleeve_id.in_(sleeve_ids), Position.status == "OPEN")
            .all()
        )
        if not open_positions:
            return {}

        return self.fetch_and_persist_prices(open_positions)

    def fetch_and_persist_prices(
        self, open_positions: List[Position]
    ) -> Dict[str, Decimal]:
        """Fetch live Webull prices for a list of open Position rows, persist, and return.

        Seed from persisted current_price first so callers always get the last
        known price even when Webull is unconfigured or a symbol fails.
        Deduplicates symbols so each ticker is fetched at most once.
        """
        if not open_positions:
            return {}

        prices: Dict[str, Decimal] = {}
        # Seed from last persisted price (fallback for any live-fetch failure).
        seen_symbols: Dict[str, Position] = {}
        for p in open_positions:
            if p.current_price is not None:
                prices[p.symbol] = p.current_price
            # Keep one representative Position row per symbol for persistence.
            seen_symbols.setdefault(p.symbol, p)

        connector = WebullConnector()
        if not connector.is_configured():
            return prices

        for symbol, pos in seen_symbols.items():
            # The market-data source quotes securities, not option contracts.
            if is_option_symbol(symbol):
                continue
            try:
                live = connector.get_price(symbol)
                if live is not None:
                    live_decimal = Decimal(str(live))
                    prices[symbol] = live_decimal
                    # Persist to every open Position row for this symbol.
                    for p in open_positions:
                        if p.symbol == symbol:
                            p.current_price = live_decimal
            except Exception as exc:
                _log.warning("Webull price fetch failed for %s: %s", symbol, exc)

        try:
            self.db.commit()
        except Exception:
            self.db.rollback()

        return prices

    def performance(
        self,
        sleeve_ids: List[str],
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        prices: Optional[Dict[str, Decimal]] = None,
    ) -> Dict:
        """Summary metrics + value time-series for a set of sleeves.

        Returns an empty/zeroed payload when the sleeve set has no trades.
        """
        sleeve_ids = list(sleeve_ids)
        if prices is None:
            prices = self._fetch_live_prices(sleeve_ids) if sleeve_ids else {}

        trades = (
            self.db.query(Trade).filter(Trade.sleeve_id.in_(sleeve_ids)).all()
            if sleeve_ids
            else []
        )

        if not trades:
            return {
                "summary": {
                    "mwr_pct": None,
                    "twr_pct": None,
                    "total_return_pct": None,
                    "total_cost_basis": 0.0,
                    "total_market_value": 0.0,
                    "total_unrealized_gain": 0.0,
                    "total_income": 0.0,
                    "trades_count": 0,
                },
                "timeseries": [],
            }

        s_start = start_date or min(t.trade_date for t in trades)
        last_activity = self.cash.last_activity_date(sleeve_ids)
        s_end = end_date or last_activity

        # Current prices belong in the return only when the window runs up to
        # the present; a window ending in the past is valued as of then.
        to_present = end_date is None or end_date >= last_activity
        market = prices if to_present else None

        try:
            mwr = self.mwr.calculate_mwr(sleeve_ids, s_start, s_end, market)
        except Exception as exc:
            _log.error("MWR failed for sleeves=%s: %s", sleeve_ids, exc)
            mwr = None
        try:
            twr = self.twr.calculate_twr(sleeve_ids, s_start, s_end, market)
        except Exception as exc:
            _log.error("TWR failed for sleeves=%s: %s", sleeve_ids, exc)
            twr = None

        valued = self.portfolio.calculate_account_value(sleeve_ids, prices)
        timeseries = self.portfolio.value_series(sleeve_ids, prices)

        # Closed-position roll-ups
        closed = valued.get("closed_positions", [])
        total_invested = sum(
            float(p.get("matched_quantity", 0)) * float(p.get("entry_price", 0))
            for p in closed
        )
        total_proceeds = sum(
            float(p.get("matched_quantity", 0)) * float(p.get("exit_price", 0))
            for p in closed
        )
        total_realized_gain = valued.get("total_realized_gain", 0.0)

        twr_note = (
            "N/A — no capital was at work in this period" if twr is None else None
        )

        return {
            "summary": {
                "mwr_pct": float(mwr) if mwr is not None else None,
                "twr_pct": float(twr) if twr is not None else None,
                "twr_note": twr_note,
                "total_return_pct": valued.get("total_return_pct"),
                "total_cost_basis": valued.get("total_cost_basis", 0.0),
                "total_market_value": valued.get("total_market_value", 0.0),
                "total_unrealized_gain": valued.get("total_unrealized_gain", 0.0),
                "total_invested": total_invested,
                "total_proceeds": total_proceeds,
                "total_realized_gain": total_realized_gain,
                "total_income": self.cash.total_income(sleeve_ids, s_start, s_end),
                "closed_positions_count": valued.get("closed_positions_count", 0),
                "trades_count": len(trades),
            },
            "start_date": s_start,
            "end_date": s_end,
            "timeseries": timeseries,
        }

    def positions_payload(self, sleeve_ids: List[str]) -> Dict:
        """Fetch live prices, compute open-position values and totals.

        Returns a dict ready to be included in any positions response:
            positions_count, total_cost_basis, total_market_value,
            total_unrealized_gain, positions[].
        Single source of truth — used by client, account, and sleeve routes.
        """
        sleeve_ids = list(sleeve_ids)

        pos_result = (
            self.portfolio.calculate_positions(sleeve_ids)
            if sleeve_ids
            else {"open": [], "closed": []}
        )
        open_pos = pos_result["open"]

        open_position_rows = (
            (
                self.db.query(Position)
                .filter(Position.sleeve_id.in_(sleeve_ids), Position.status == "OPEN")
                .all()
            )
            if sleeve_ids
            else []
        )

        raw_prices = self.fetch_and_persist_prices(open_position_rows)
        prices = {sym: float(p) for sym, p in raw_prices.items()}

        result_positions = []
        total_cost = Decimal(0)
        total_market_value = Decimal(0)

        for pos in open_pos:
            symbol = pos["symbol"]
            cost = pos["cost_basis"]
            qty = pos["quantity"]
            # A short carries negative quantity and negative cost (the proceeds
            # received), so the ratio is still its per-share price.
            avg_cost = cost / qty if qty != 0 else Decimal(0)

            if symbol in prices:
                price = Decimal(str(prices[symbol]))
                market_value = qty * price
                unrealized_gain = market_value - cost
                unrealized_gain_pct = (
                    float(unrealized_gain / abs(cost) * 100) if cost != 0 else 0.0
                )
            else:
                price = None
                market_value = cost
                unrealized_gain = Decimal(0)
                unrealized_gain_pct = 0.0

            total_cost += cost
            total_market_value += market_value

            result_positions.append(
                {
                    "symbol": symbol,
                    "quantity": float(qty),
                    "cost_basis": float(cost),
                    "avg_cost": float(avg_cost),
                    "current_price": float(price) if price is not None else None,
                    "market_value": float(market_value),
                    "unrealized_gain": float(unrealized_gain),
                    "unrealized_gain_pct": unrealized_gain_pct,
                    "trades_count": pos["trades_count"],
                }
            )

        return {
            "total_cost_basis": float(total_cost),
            "total_market_value": float(total_market_value),
            "total_unrealized_gain": float(total_market_value - total_cost),
            "positions_count": len(result_positions),
            "positions": result_positions,
        }

    def monthly_returns(self, sleeve_ids: List[str]) -> List[Dict]:
        """Month-on-month return breakdown since inception.

        For each calendar month:
          - start_value: portfolio value at the last trade date of the prior month
            (0 for the inception month)
          - end_value:   portfolio value at the last trade date within the month,
            or at end-of-month if no trade fell in that month
          - cash_in / cash_out: gross BUY / SELL amounts during the month
          - realized_gain: net realized P&L from SELLs closed in the month
          - return_pct: the month's time-weighted return, from the same
            calculation as the headline TWR; None while no capital is at work

        Open positions are valued at live prices fetched in _fetch_live_prices.
        """
        sleeve_ids = list(sleeve_ids)
        prices = self._fetch_live_prices(sleeve_ids)

        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .order_by(Trade.trade_date)
            .all()
        )
        if not trades:
            return []

        first_date = min(t.trade_date for t in trades)
        # Run to the last trade or income payment, whichever is later, as the
        # headline window does.
        last_date = self.cash.last_activity_date(sleeve_ids)

        # Enumerate calendar months from inception to last trade month
        months = []
        year, month = first_date.year, first_date.month
        end_year, end_month = last_date.year, last_date.month

        # Pre-compute realized gains bucketed by (year, month) — avoids O(N) db
        # calls (one per calendar month) inside the loop below.
        all_closed = self.portfolio.calculate_positions(sleeve_ids)["closed"]
        realized_by_month: Dict[tuple, float] = {}
        for p in all_closed:
            if p["closed_at"]:
                key = (p["closed_at"].year, p["closed_at"].month)
                realized_by_month[key] = realized_by_month.get(key, 0.0) + float(
                    p["realized_gain"]
                )

        # Dividends and fees, bucketed by month; they leave the sleeve like
        # sale proceeds, so they are added to cash_out below.
        income_by_month: Dict[tuple, float] = {}
        for flow_date, amount in self.cash.income_flows(sleeve_ids):
            key = (flow_date.year, flow_date.month)
            income_by_month[key] = income_by_month.get(key, 0.0) + float(amount)

        # One pass of the shared time-weighted calculation, read at each month
        # end (the last one clamped to the last trade and valued at market).
        month_ends = []
        y, m = first_date.year, first_date.month
        while (y, m) <= (last_date.year, last_date.month):
            month_ends.append(min(date(y, m, calendar.monthrange(y, m)[1]), last_date))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        growth_by_date = {
            point["date"]: point
            for point in self.twr.growth_at(sleeve_ids, first_date, month_ends, prices)
        }

        prev_end_value = 0.0  # value carried from previous month
        prev_growth = 0.0  # cumulative TWR at the previous month end

        while (year, month) <= (end_year, end_month):
            month_last_day = calendar.monthrange(year, month)[1]
            month_start = date(year, month, 1)
            month_end = date(year, month, month_last_day)

            # Clamp to the actual data range
            effective_end = min(month_end, last_date)

            point = growth_by_date[effective_end]
            end_value = point["value"]
            growth = point["twr"]

            # Cash flows within this month
            month_trades = [
                t
                for t in trades
                if date(year, month, 1) <= t.trade_date <= effective_end
            ]
            cash_in = sum(
                float(t.quantity) * float(t.price) + float(t.commission)
                for t in month_trades
                if t.action == "BUY"
            )
            cash_out = sum(
                float(t.quantity) * float(t.price) - float(t.commission)
                for t in month_trades
                if t.action == "SELL"
            ) + income_by_month.get((year, month), 0.0)

            realized_this_month = realized_by_month.get((year, month), 0.0)

            # The month's return is the growth of the time-weighted series
            # across it, so months compound to the headline TWR.
            if growth is None:
                return_pct = None
            else:
                return_pct = ((1 + growth) / (1 + prev_growth) - 1) * 100
                prev_growth = growth

            month_label = date(year, month, 1).strftime("%b %Y")
            months.append(
                {
                    "year": year,
                    "month": month,
                    "month_label": month_label,
                    "start_value": prev_end_value,
                    "end_value": end_value,
                    "cash_in": cash_in,
                    "cash_out": cash_out,
                    "net_cash_flow": cash_in - cash_out,
                    "realized_gain": realized_this_month,
                    "return_pct": round(return_pct, 2)
                    if return_pct is not None
                    else None,
                }
            )

            prev_end_value = end_value

            # Advance to next month
            if month == 12:
                year, month = year + 1, 1
            else:
                month += 1

        return months
