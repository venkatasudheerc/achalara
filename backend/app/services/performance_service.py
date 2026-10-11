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
from app.services.cash_ledger import CashLedger
from app.services.performance_stats_service import PerformanceStatsService
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
        self.stats = PerformanceStatsService(db)

    # -- sleeve-set resolution ------------------------------------------------

    def sleeve_ids_for_account(self, account_id: str) -> List[str]:
        rows = self.db.query(Sleeve.id).filter(Sleeve.account_id == account_id).all()
        return [r[0] for r in rows]

    def account_ids_for_client(self, client_id: str) -> List[str]:
        rows = self.db.query(Account.id).filter(Account.client_id == client_id).all()
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
        cash_account_ids: Optional[List[str]] = None,
    ) -> Dict:
        """Summary metrics + value time-series for a set of sleeves.

        ``cash_account_ids`` names the accounts being viewed as a whole. Where
        their cash is known it is added to the value and the returns are
        measured on the total, with deposits and withdrawals as the only money
        in or out. Leave it out for a view of securities alone (a sleeve, a
        strategy).

        Returns an empty/zeroed payload when the sleeve set has no trades.
        """
        sleeve_ids = list(sleeve_ids)
        ledger = CashLedger.for_accounts(self.db, cash_account_ids or [])
        if prices is None:
            # The last price on file for each open position. Fetching live
            # quotes here made every performance view wait on the market-data
            # source; prices are refreshed by the daily capture and by the
            # positions views instead.
            prices = self._persisted_prices(sleeve_ids)

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
        # Current prices belong in the return only when the window runs up to
        # the present; a window ending in the past is valued as of then.
        to_present = end_date is None or end_date >= last_activity
        # Today's prices are a value as of today, so an open-ended window runs
        # to today even if nothing has happened since the last trade.
        s_end = end_date or max(last_activity, date.today())
        market = prices if to_present else None
        valued = self.portfolio.calculate_account_value(sleeve_ids, prices)

        # Where the daily record has been built, returns and the value series
        # are read from it. The calculation from trades below is the fallback
        # for sleeve sets that have no daily rows yet.
        stored = self._from_daily_rows(
            sleeve_ids, cash_account_ids, start_date, end_date
        )
        if stored is not None:
            return self._summary_payload(
                valued,
                trades,
                sleeve_ids,
                stored["start"],
                stored["end"],
                stored["twr"],
                stored["mwr"],
                stored["timeseries"],
                # The cash the brokerage reports, where it reports one; and,
                # until a day has been captured from it, the correction for
                # securities it holds that our trades do not show yet.
                float(ledger.reported) if ledger is not None else stored["cash"],
                stored["total"],
                (
                    float(ledger.pending)
                    if ledger is not None and not stored["observed"]
                    else None
                ),
            )

        try:
            mwr = self.mwr.calculate_mwr(sleeve_ids, s_start, s_end, market, ledger)
        except Exception as exc:
            _log.error("MWR failed for sleeves=%s: %s", sleeve_ids, exc)
            mwr = None
        try:
            twr = self.twr.calculate_twr(sleeve_ids, s_start, s_end, market, ledger)
        except Exception as exc:
            _log.error("TWR failed for sleeves=%s: %s", sleeve_ids, exc)
            twr = None

        timeseries = self.portfolio.value_series(sleeve_ids, prices)

        self._attach_net_flows(timeseries, trades, sleeve_ids, ledger)

        # The chart's running cost is an average-cost estimate; the headline
        # uses exact lots. End the chart on the headline's figure so the gap at
        # the last point is the unrealised gain shown above it.
        if timeseries and to_present:
            timeseries[-1]["cost_basis"] = valued.get("total_cost_basis", 0.0)

        # With cash known, every point of the chart is securities plus the
        # cash held that day. Cash is worth what it cost, so it joins both
        # lines and the gap between them stays the unrealised gain.
        cash_now = None
        pending = None
        if ledger is not None:
            for point in timeseries:
                held = float(ledger.balance_on(point["date"]))
                point["cash"] = held
                point["value"] += held
                point["cost_basis"] += held
            cash_now = float(ledger.reported)
            # Both corrections come from the brokerage's own current figures:
            # securities it holds that our trades do not show yet, and options
            # we can only price at their last trade.
            pending = float(ledger.pending + ledger.mark)
            if timeseries and to_present:
                timeseries[-1]["value"] += float(ledger.mark)

        return self._summary_payload(
            valued,
            trades,
            sleeve_ids,
            s_start,
            s_end,
            twr,
            mwr,
            timeseries,
            cash_now,
            (
                timeseries[-1]["value"]
                if ledger is not None and timeseries and to_present
                else None
            ),
            pending,
        )

    def _summary_payload(
        self,
        valued,
        trades,
        sleeve_ids,
        s_start,
        s_end,
        twr,
        mwr,
        timeseries,
        cash_now,
        total_value,
        pending,
    ) -> Dict:
        """Assemble the response: returns and series as given, the rest from
        the positions."""
        closed = valued.get("closed_positions", [])
        total_invested = sum(
            float(p.get("matched_quantity", 0)) * float(p.get("entry_price", 0))
            for p in closed
        )
        total_proceeds = sum(
            float(p.get("matched_quantity", 0)) * float(p.get("exit_price", 0))
            for p in closed
        )
        return {
            "summary": {
                "mwr_pct": float(mwr) if mwr is not None else None,
                "twr_pct": float(twr) if twr is not None else None,
                "twr_note": (
                    "N/A — no capital was at work in this period"
                    if twr is None
                    else None
                ),
                "total_return_pct": valued.get("total_return_pct"),
                "total_cost_basis": valued.get("total_cost_basis", 0.0),
                "total_market_value": valued.get("total_market_value", 0.0),
                "total_unrealized_gain": valued.get("total_unrealized_gain", 0.0),
                "cash_balance": cash_now,
                # Securities, cash and any brokerage corrections together, on
                # the same valuation as the chart and the returns.
                "total_value": total_value,
                "holdings_adjustment": pending,
                "total_invested": total_invested,
                "total_proceeds": total_proceeds,
                "total_realized_gain": valued.get("total_realized_gain", 0.0),
                "total_income": self.cash.total_income(sleeve_ids, s_start, s_end),
                "closed_positions_count": valued.get("closed_positions_count", 0),
                "trades_count": len(trades),
            },
            "start_date": s_start,
            "end_date": s_end,
            "timeseries": timeseries,
        }

    def _persisted_prices(self, sleeve_ids: List[str]) -> Dict[str, Decimal]:
        """The last price on file for each open position in the sleeve set."""
        if not sleeve_ids:
            return {}
        return {
            row.symbol: row.current_price
            for row in self.db.query(Position).filter(
                Position.sleeve_id.in_(sleeve_ids),
                Position.status == "OPEN",
                Position.current_price.isnot(None),
            )
        }

    def _daily_series(self, sleeve_ids, cash_account_ids):
        """The stored day-by-day series for this view, or None if not built.

        A view of whole accounts reads the account rows (which carry cash); a
        view of sleeves reads the sleeve rows.
        """
        if cash_account_ids:
            series = self.stats.daily(account_ids=cash_account_ids)
        else:
            series = self.stats.daily(sleeve_ids=sleeve_ids)
        return series or None

    def _from_daily_rows(self, sleeve_ids, cash_account_ids, start_date, end_date):
        """Returns and value series over the window, read from the daily rows."""
        series = self._daily_series(sleeve_ids, cash_account_ids)
        if series is None:
            return None
        window = [
            d
            for d in series
            if (start_date is None or d.date >= start_date)
            and (end_date is None or d.date <= end_date)
        ]
        if not window:
            return None
        before = [d for d in series if d.date < window[0].date]
        opening = before[-1].total if before else Decimal(0)

        contributed = Decimal(0)
        timeseries = []
        for day in window:
            contributed += day.net_flow
            timeseries.append(
                {
                    "date": day.date,
                    "value": float(day.total),
                    # No running cost is kept per day; the chart does not draw one.
                    "cost_basis": None,
                    "cash": float(day.cash) if day.cash is not None else None,
                    "net_flow": float(day.net_flow),
                    "net_contributions": float(contributed),
                }
            )
        last = window[-1]
        return {
            "start": start_date or window[0].date,
            "end": end_date or last.date,
            "twr": self.stats._twr(window),
            "mwr": self.stats._mwr(opening, window),
            "timeseries": timeseries,
            "cash": float(last.cash) if last.cash is not None else None,
            "total": float(last.total) if last.cash is not None else None,
            "observed": last.observed,
        }

    def _attach_net_flows(self, timeseries, trades, sleeve_ids, ledger) -> None:
        """Give each chart point the net money put in since the point before.

        A benchmark is only a fair comparison if it receives the same money on
        the same days; this is what lets the chart buy and sell the benchmark
        alongside. "Money in" is what it is for the returns: deposits less
        withdrawals where cash is tracked, and otherwise purchases less sale
        proceeds and income.
        """
        tracked = ledger.sleeve_ids if ledger is not None else set()
        by_date: Dict[date, Decimal] = {}
        for trade in trades:
            if trade.sleeve_id in tracked:
                continue
            gross = Decimal(str(trade.quantity)) * Decimal(str(trade.price))
            commission = Decimal(str(trade.commission or 0))
            signed = gross + commission if trade.action == "BUY" else commission - gross
            by_date[trade.trade_date] = (
                by_date.get(trade.trade_date, Decimal(0)) + signed
            )
        untracked = [sid for sid in sleeve_ids if sid not in tracked]
        for day, income in self.cash.income_flows(untracked):
            by_date[day] = by_date.get(day, Decimal(0)) - income
        if ledger is not None:
            for day, deposited in ledger.external.items():
                by_date[day] = by_date.get(day, Decimal(0)) + deposited

        days = sorted(by_date)
        index = 0
        for point in timeseries:
            total = Decimal(0)
            while index < len(days) and days[index] <= point["date"]:
                total += by_date[days[index]]
                index += 1
            point["net_flow"] = float(total)

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

    def monthly_returns(
        self, sleeve_ids: List[str], cash_account_ids: Optional[List[str]] = None
    ) -> List[Dict]:
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
        series = self._daily_series(sleeve_ids, cash_account_ids)
        if series is not None:
            return [
                {
                    "year": m["period_end"].year,
                    "month": m["period_end"].month,
                    "month_label": m["period_end"].strftime("%b %Y"),
                    "start_value": m["opening_value"],
                    "end_value": m["closing_value"],
                    "cash_in": max(m["net_flow"], 0.0),
                    "cash_out": max(-m["net_flow"], 0.0),
                    "net_cash_flow": m["net_flow"],
                    "realized_gain": 0.0,
                    "return_pct": (
                        round(m["twr_pct"] * 100, 2)
                        if m["twr_pct"] is not None
                        else None
                    ),
                    # With a close for every day, each month carries its own
                    # gains; nothing is deferred to the latest one.
                    "includes_unrealized": False,
                }
                for m in self.stats.periods(series, "month")
            ]
        prices = self._persisted_prices(sleeve_ids)
        ledger = CashLedger.for_accounts(self.db, cash_account_ids or [])

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
            for point in self.twr.growth_at(
                sleeve_ids, first_date, month_ends, prices, ledger
            )
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

        # No price history is stored, so open positions sit at their last
        # traded price until the final point brings them up to market. The
        # latest month therefore carries all the unrealised gain to date.
        if months:
            for entry in months:
                entry["includes_unrealized"] = False
            months[-1]["includes_unrealized"] = bool(prices)

        return months
