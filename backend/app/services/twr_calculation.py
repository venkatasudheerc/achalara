"""Time Weighted Return (TWR) calculation service"""
from decimal import Decimal
from datetime import date
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
    ):
        """
        Calculate Time Weighted Return over [start_date, end_date].

        ``prices`` are current market prices by symbol. Pass them only when the
        window runs up to the present; they value the holdings at its end.

        Returns TWR as a decimal (e.g. 0.10 for 10%), or None when there is
        nothing to measure (no trades, or no capital at work in the window).
        """
        from app.services.cash_activity_service import CashActivityService

        sleeve_ids = _as_sleeve_ids(sleeve_ids)
        try:
            trades = (
                self.db.query(Trade)
                .filter(Trade.sleeve_id.in_(sleeve_ids), Trade.trade_date <= end_date)
                .order_by(Trade.trade_date, Trade.id)
                .all()
            )
            if not trades:
                return None

            income: Dict[date, Decimal] = dict(
                CashActivityService(self.db).income_flows(
                    sleeve_ids, start_date, end_date
                )
            )

            quantity: Dict[str, Decimal] = {}
            last_price: Dict[str, Decimal] = {}

            def value(market: Optional[Dict[str, Decimal]] = None) -> Decimal:
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
            previous_value = value()

            by_date: Dict[date, List[Trade]] = {}
            for trade in trades[index:]:
                by_date.setdefault(trade.trade_date, []).append(trade)

            growth = 1.0
            measured = False
            for day in sorted(set(by_date) | set(income)):
                day_trades = by_date.get(day, [])

                # 1. Up to the moment money moves: the holdings carried in are
                #    repriced at what they traded for today.
                for trade in day_trades:
                    last_price[trade.symbol] = Decimal(str(trade.price))
                before_flows = value()
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
                    gross = Decimal(str(trade.quantity)) * Decimal(str(trade.price))
                    commission = Decimal(str(trade.commission or 0))
                    if trade.action == "BUY":
                        money_in += gross + commission
                    else:
                        money_out += gross - commission
                    apply(trade)

                end_value = value()
                base = before_flows + money_in
                if base > 0:
                    gained = end_value + money_out - money_in - before_flows
                    growth *= 1.0 + float(gained / base)
                    measured = True
                previous_value = end_value

            # Bring holdings from their last traded prices up to market.
            if prices and previous_value > 0:
                growth *= float(value(prices) / previous_value)
                measured = True

            return growth - 1.0 if measured else None

        except Exception as e:
            self.logger.error(f"TWR calculation failed: {e}")
            return None
