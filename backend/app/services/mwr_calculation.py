"""Money Weighted Return (MWR) calculation service"""
from decimal import Decimal
from datetime import date, timedelta
from typing import List, Tuple

import logging

from app.services.portfolio_calculation import _as_sleeve_ids


class MWRCalculationService:
    """Service for calculating Money Weighted Return (Internal Rate of Return)"""

    def __init__(self, db):
        self.db = db
        self.logger = logging.getLogger(__name__)

    def calculate_mwr(
        self, sleeve_ids, start_date: date, end_date: date, prices=None, ledger=None
    ) -> float:
        """
        Calculate Money Weighted Return (Internal Rate of Return).

        For a round-trip trading portfolio (all positions closed), opening and
        closing value are both 0 and the IRR is solved entirely from the trade
        cash-flow stream: BUYs are outflows (negative), SELLs are inflows
        (positive).  When the portfolio carries open holdings across the period
        the closing market value is added as a terminal inflow.

        ``prices`` are current market prices by symbol. Pass them only when the
        window runs up to the present; without them holdings are valued at
        their last traded price, which leaves any gain since then out.

        ``ledger`` is a ``CashLedger`` for accounts whose cash is known: their
        value includes cash, their trades and income are no longer flows, and
        deposits and withdrawals are. See ``TWRCalculationService.growth_at``.

        Returns MWR as a decimal (e.g. 0.10 for 10%), or None when no money
        was ever invested in the window, so there is nothing to earn a rate on.
        """
        sleeve_ids = _as_sleeve_ids(sleeve_ids)
        try:
            tracked = ledger.sleeve_ids if ledger is not None else set()
            untracked = [sid for sid in sleeve_ids if sid not in tracked]
            held = [sid for sid in sleeve_ids if sid in tracked]

            opening_value = self._get_opening_value(untracked, start_date)
            flows_by_date = dict(self._get_cash_flows(untracked, start_date, end_date))
            closing_value = self._get_closing_value(sleeve_ids, end_date, prices)
            if ledger is not None:
                day_before = start_date - timedelta(days=1)
                opening_value += self._get_closing_value(
                    held, day_before
                ) + ledger.balance_on(day_before)
                closing_value += ledger.balance_on(end_date)
                if prices:
                    # At market, the total rests on the brokerage's holdings.
                    closing_value += ledger.pending
                for day, deposited in ledger.external.items():
                    if start_date <= day <= end_date:
                        # A deposit is money the investor puts in: an outflow
                        # from their side, like a BUY.
                        flows_by_date[day] = (
                            flows_by_date.get(day, Decimal(0)) - deposited
                        )
            cash_flows = sorted(flows_by_date.items())

            if not cash_flows and opening_value <= 0:
                return 0.0

            # A rate of return needs money put in. A stream that only ever
            # takes money out first — writing options, shorting — has none, and
            # solving it gives a rate with the sign of the result reversed.
            invested = opening_value
            most_invested = invested
            for _, flow in cash_flows:
                invested -= flow
                most_invested = max(most_invested, invested)
            if most_invested <= 0:
                return None

            irr = self._solve_irr(
                opening_value, cash_flows, closing_value, start_date, end_date
            )
            return irr

        except Exception as e:
            self.logger.error(
                "MWR calculation failed for sleeves=%s start=%s end=%s: %s",
                sleeve_ids,
                start_date,
                end_date,
                e,
            )
            return 0.0

    def _get_opening_value(self, sleeve_ids, start_date: date) -> Decimal:
        """Get value at start date across the given sleeves"""
        from app.models.trade import Trade

        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids), Trade.trade_date < start_date)
            .all()
        )

        value = Decimal(0)
        for trade in trades:
            qty = Decimal(str(trade.quantity))
            price = Decimal(str(trade.price))

            if trade.action == "BUY":
                value += qty * price
            else:
                value -= qty * price

        return value

    def _get_cash_flows(
        self, sleeve_ids, start_date: date, end_date: date
    ) -> List[Tuple[date, Decimal]]:
        """Get net cash flows (trades plus investment income) during period"""
        from app.models.trade import Trade

        trades = (
            self.db.query(Trade)
            .filter(
                Trade.sleeve_id.in_(sleeve_ids),
                Trade.trade_date >= start_date,
                Trade.trade_date <= end_date,
            )
            .order_by(Trade.trade_date)
            .all()
        )

        # Aggregate cash flows by date
        daily_flows = {}
        for trade in trades:
            flow_date = trade.trade_date
            qty = Decimal(str(trade.quantity))
            price = Decimal(str(trade.price))
            comm = Decimal(str(trade.commission))

            if flow_date not in daily_flows:
                daily_flows[flow_date] = Decimal(0)

            if trade.action == "BUY":
                daily_flows[flow_date] -= qty * price + comm
            else:  # SELL
                daily_flows[flow_date] += qty * price - comm

        # Dividends and fees: money out of (or into) the sleeve with no trade.
        from app.services.cash_activity_service import CashActivityService

        for flow_date, amount in CashActivityService(self.db).income_flows(
            sleeve_ids, start_date, end_date
        ):
            daily_flows[flow_date] = daily_flows.get(flow_date, Decimal(0)) + amount

        return [(date, flow) for date, flow in sorted(daily_flows.items())]

    def _get_closing_value(self, sleeve_ids, end_date: date, prices=None) -> Decimal:
        """Portfolio value at end_date: holdings at market, else last-trade price.

        A short position counts as a liability (negative value).

        For a fully-closed portfolio this returns 0, which is correct: the IRR
        is solved purely from the BUY/SELL cash-flow stream in _get_cash_flows.
        """
        from app.models.trade import Trade

        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids), Trade.trade_date <= end_date)
            .all()
        )

        net_qty: dict = {}
        # Track the latest-dated trade price per symbol in the same pass so we
        # don't re-query the DB once per open symbol (previously an N+1).
        last_price: dict = {}
        for trade in trades:
            symbol = trade.symbol
            qty = Decimal(str(trade.quantity))
            net_qty.setdefault(symbol, Decimal(0))
            if trade.action == "BUY":
                net_qty[symbol] += qty
            else:
                net_qty[symbol] -= qty

            prev = last_price.get(symbol)
            if prev is None or trade.trade_date >= prev[0]:
                last_price[symbol] = (trade.trade_date, Decimal(str(trade.price)))

        value = Decimal(0)
        for symbol, qty in net_qty.items():
            if qty == 0 or symbol not in last_price:
                continue
            if prices and symbol in prices:
                value += qty * Decimal(str(prices[symbol]))
            else:
                value += qty * last_price[symbol][1]

        return value

    def _solve_irr(
        self,
        opening: Decimal,
        flows: List,
        closing: Decimal,
        start_date: date,
        end_date: date,
    ) -> float:
        """Solve for IRR using Newton-Raphson method.

        When opening and closing values are both 0 (pure round-trip portfolio),
        anchors t=0 to the first cash flow so the IRR is well-defined.
        """
        days_per_year = 365.0

        # Determine the time anchor: the start of the first cash outflow.
        anchor = start_date
        if float(opening) == 0 and flows:
            anchor = flows[0][0]

        def npv(rate):
            total = -float(opening)
            for flow_date, amount in flows:
                days = (flow_date - anchor).days
                years = days / days_per_year
                total += float(amount) / ((1 + rate) ** years)
            if float(closing) != 0:
                days_total = (end_date - anchor).days
                years_total = days_total / days_per_year
                total += float(closing) / ((1 + rate) ** years_total)
            return total

        rate = 0.1
        for _ in range(200):
            npv_val = npv(rate)
            if abs(npv_val) < 1e-6:
                break
            h = 1e-5
            derivative = (npv(rate + h) - npv(rate - h)) / (2 * h)
            if abs(derivative) < 1e-10:
                break
            rate = rate - npv_val / derivative
            rate = max(-0.99, min(rate, 100.0))

        # Convert annualized IRR → holding-period return for the actual window
        # so MWR and TWR are on the same scale (both = return over the period).
        # If start and end are the same date (e.g. inception week with same-day
        # cash flows) there is no elapsed time and the return must be 0 — the
        # solver's initial guess of 0.1 would otherwise leak through unchanged.
        # Money that has all come back out stopped earning on the day the last
        # of it left; time after that is not part of the holding period.
        horizon = end_date
        if float(closing) == 0 and flows:
            horizon = min(end_date, flows[-1][0])
        total_days = (horizon - anchor).days
        if total_days <= 0:
            return 0.0
        holding_period_years = total_days / days_per_year
        rate = (1 + rate) ** holding_period_years - 1

        return rate
