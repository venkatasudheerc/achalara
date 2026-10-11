"""Time Weighted Return (TWR) calculation service"""
from decimal import Decimal
from datetime import date, timedelta
from typing import Dict, List, Optional
import logging

from app.models.trade import Trade
from app.services.portfolio_calculation import _as_sleeve_ids


class TWRCalculationService:
    """Service for calculating Time Weighted Return.

    The window is cut into sub-periods at every date money moved. Up to each
    such date the holdings carried in are revalued, giving the return earned
    before the new money arrived:

        r_i = V_before_flows / V_previous - 1

    and the day's own gain or loss beyond the money that moved (commissions,
    income, a fill away from the day's last price) is measured on the capital
    then at work. All of these are linked through time:

        TWR = Product(1 + r_i) - 1

    Linking through time is what removes the effect of when and how much was
    invested, leaving the return on the holdings themselves. Returns are linked
    across *periods*, never across positions: every position's gain is already
    inside the portfolio value V.

    Money in is what BUYs cost; money out is SELL proceeds plus investment
    income. Between trades a holding is valued at its last traded price, since
    no price history is stored; the final value uses current prices when the
    caller supplies them, so the last sub-period brings holdings up to market.
    """

    def __init__(self, db):
        self.db = db
        self.logger = logging.getLogger(__name__)

    def calculate_twr(
        self,
        sleeve_ids,
        start_date: date,
        end_date: date,
        prices: Optional[Dict[str, Decimal]] = None,
        ledger=None,
    ):
        """
        Calculate Time Weighted Return over [start_date, end_date].

        ``prices`` are current market prices by symbol. Pass them only when the
        window runs up to the present; they value the holdings at its end.

        Returns TWR as a decimal (e.g. 0.10 for 10%), or None when there is
        nothing to measure (no trades, or no capital at work in the window).
        """
        try:
            points = self.growth_at(sleeve_ids, start_date, [end_date], prices, ledger)
            return points[0]["twr"] if points else None
        except Exception as e:
            self.logger.error(f"TWR calculation failed: {e}")
            return None

    def growth_at(
        self,
        sleeve_ids,
        start_date: date,
        checkpoints: List[date],
        prices: Optional[Dict[str, Decimal]] = None,
        ledger=None,
    ) -> List[Dict]:
        """Cumulative TWR from ``start_date`` to each checkpoint date.

        The one calculation behind every time-weighted figure — the headline,
        the weekly series and the monthly returns — so they cannot disagree.
        Returns ``{"date", "twr", "value"}`` per checkpoint, in date order;
        ``twr`` is None until there has been capital at work.

        ``prices`` are applied only to the final checkpoint, and only if no
        trade falls after it: current prices describe the present, not a past
        date. Every other value uses last traded prices.

        ``ledger`` is a ``CashLedger`` for accounts whose cash is known. Their
        value then includes cash, their trades and income stop being money in
        or out (they only move value between cash and securities), and
        deposits and withdrawals take that role. Sleeves outside the ledger
        keep the securities-only measure, so a mixed set still adds up.
        """
        from app.services.cash_activity_service import CashActivityService

        sleeve_ids = _as_sleeve_ids(sleeve_ids)
        checkpoints = sorted(checkpoints)
        if not checkpoints:
            return []
        horizon = checkpoints[-1]

        all_trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .order_by(Trade.trade_date, Trade.id)
            .all()
        )
        if not all_trades:
            return []
        # None means "not to the present"; an empty dict is the present with
        # nothing quoted.
        to_present = prices is not None and horizon >= all_trades[-1].trade_date
        trades = [t for t in all_trades if t.trade_date <= horizon]

        tracked = ledger.sleeve_ids if ledger is not None else set()
        untracked_ids = [sid for sid in sleeve_ids if sid not in tracked]
        # For a cash-tracked sleeve, income just lands in its cash.
        income: Dict[date, Decimal] = dict(
            CashActivityService(self.db).income_flows(
                untracked_ids, start_date, horizon
            )
        )

        def cash_on(day: date) -> Decimal:
            return ledger.balance_on(day) if ledger is not None else Decimal(0)

        quantity: Dict[str, Decimal] = {}
        last_price: Dict[str, Decimal] = {}

        def securities(market: Optional[Dict[str, Decimal]] = None) -> Decimal:
            total = Decimal(0)
            for symbol, qty in quantity.items():
                if qty == 0:
                    continue
                price = last_price[symbol]
                if market and symbol in market:
                    price = Decimal(str(market[symbol]))
                total += qty * price
            return total

        def apply(trade: Trade) -> None:
            qty = Decimal(str(trade.quantity))
            signed = qty if trade.action == "BUY" else -qty
            quantity[trade.symbol] = quantity.get(trade.symbol, Decimal(0)) + signed
            last_price[trade.symbol] = Decimal(str(trade.price))

        # Holdings carried into the window are its opening value.
        index = 0
        while index < len(trades) and trades[index].trade_date < start_date:
            apply(trades[index])
            index += 1
        opening_day = start_date - timedelta(days=1)
        previous_cash = cash_on(opening_day)
        previous_value = securities() + previous_cash

        by_date: Dict[date, List[Trade]] = {}
        for trade in trades[index:]:
            by_date.setdefault(trade.trade_date, []).append(trade)

        growth = 1.0
        measured = False
        points: List[Dict] = []
        pending = list(checkpoints)

        def emit(until: Optional[date]) -> None:
            """Record every checkpoint that falls before the next flow day."""
            while pending and (until is None or pending[0] < until):
                checkpoint = pending.pop(0)
                twr = growth - 1.0 if measured else None
                worth = previous_value
                if to_present and not pending and until is None:
                    # Bring holdings from their last traded prices up to market.
                    worth = securities(prices) + previous_cash
                    if ledger is not None:
                        worth += ledger.mark
                    if previous_value > 0:
                        twr = growth * float(worth / previous_value) - 1.0
                points.append({"date": checkpoint, "twr": twr, "value": float(worth)})

        cash_days = (
            ledger.change_dates(start_date, horizon) if ledger is not None else []
        )
        for day in sorted(set(by_date) | set(income) | set(cash_days)):
            emit(day)
            day_trades = by_date.get(day, [])

            # 1. Up to the moment money moves: the holdings carried in are
            #    repriced at what they traded for today.
            for trade in day_trades:
                last_price[trade.symbol] = Decimal(str(trade.price))
            before_flows = securities() + previous_cash
            if previous_value > 0:
                growth *= float(before_flows / previous_value)
                measured = True

            # 2. Across the flows: whatever was gained or lost beyond the
            #    money that moved, on the capital now at work.
            net_income = income.get(day, Decimal(0))
            money_out = max(net_income, Decimal(0))
            # A net fee day is money paid in, not negative money out.
            money_in = max(-net_income, Decimal(0))
            for trade in day_trades:
                if trade.sleeve_id not in tracked:
                    gross = Decimal(str(trade.quantity)) * Decimal(str(trade.price))
                    commission = Decimal(str(trade.commission or 0))
                    if trade.action == "BUY":
                        money_in += gross + commission
                    else:
                        money_out += gross - commission
                apply(trade)
            if ledger is not None:
                deposited = ledger.external.get(day, Decimal(0))
                money_in += max(deposited, Decimal(0))
                money_out += max(-deposited, Decimal(0))

            previous_cash = cash_on(day)
            end_value = securities() + previous_cash
            base = before_flows + money_in
            if base > 0:
                gained = end_value + money_out - money_in - before_flows
                growth *= 1.0 + float(gained / base)
                measured = True
            previous_value = end_value

        emit(None)
        return points
