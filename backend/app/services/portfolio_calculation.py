"""Portfolio calculation service"""
from sqlalchemy.orm import Session
from sqlalchemy import and_
from decimal import Decimal
from typing import Dict, List
from datetime import datetime, date, timezone
import logging

from app.models.trade import Trade
from app.models.position import Position
from app.models.sleeve import Sleeve


def _as_sleeve_ids(sleeve_ids) -> List[str]:
    """Accept a single id or a list of ids and normalize to a list."""
    if isinstance(sleeve_ids, str):
        return [sleeve_ids]
    return list(sleeve_ids)


class PortfolioCalculationService:
    """Service for calculating portfolio positions and values"""

    def __init__(self, db: Session):
        self.db = db
        self.logger = logging.getLogger(__name__)

    def calculate_positions(self, sleeve_ids, as_of_date: date = None) -> Dict:
        """
        Calculate open and closed positions across one or more sleeves.

        Each sleeve is matched by its own ``accounting_method``: ROUND_TRIP
        sleeves pair equal-quantity buys and sells (see
        ``_round_trip_positions``); FIFO sleeves consume oldest lots first (see
        ``_fifo_positions``). Open positions are then rolled up per symbol.

        Returns a dict with keys:
            open   — list of position dicts (quantity < 0 is a short)
            closed — list of closed-lot dicts (one per matched buy/sell pair)
            unmatched_sells — count of symbols a FIFO sleeve is left net short
        """
        sleeve_ids = _as_sleeve_ids(sleeve_ids)
        if as_of_date is None:
            as_of_date = date.today()

        fifo_ids = [
            row[0]
            for row in self.db.query(Sleeve.id).filter(
                Sleeve.id.in_(sleeve_ids), Sleeve.accounting_method == "FIFO"
            )
        ]
        if not fifo_ids:
            return self._round_trip_positions(sleeve_ids, as_of_date)

        round_trip_ids = [sid for sid in sleeve_ids if sid not in fifo_ids]
        results = [self._fifo_positions(sid, as_of_date) for sid in fifo_ids]
        if round_trip_ids:
            results.append(self._round_trip_positions(round_trip_ids, as_of_date))

        open_by_symbol: Dict[str, Dict] = {}
        closed: List[Dict] = []
        unmatched = 0
        for result in results:
            closed.extend(result["closed"])
            unmatched += result["unmatched_sells"]
            for pos in result["open"]:
                agg = open_by_symbol.get(pos["symbol"])
                if agg is None:
                    open_by_symbol[pos["symbol"]] = dict(pos)
                    continue
                agg["quantity"] += pos["quantity"]
                agg["cost_basis"] += pos["cost_basis"]
                agg["trades_count"] += pos["trades_count"]
                if agg["quantity"] != 0:
                    agg["avg_cost"] = agg["cost_basis"] / agg["quantity"]

        closed.sort(key=lambda p: p["closed_at"])
        return {
            # A long in one sleeve and an equal short in another net to nothing.
            "open": [p for p in open_by_symbol.values() if p["quantity"] != 0],
            "closed": closed,
            "unmatched_sells": unmatched,
        }

    def _fifo_positions(self, sleeve_id: str, as_of_date: date) -> Dict:
        """
        Positions for one sleeve using first-in-first-out lots, long and short.

        A SELL consumes the oldest long lots of its symbol; whatever it cannot
        cover opens a short lot. A BUY covers the oldest short lots first, and
        the rest opens a long lot. Lots are split when only partly consumed,
        and every lot (or part of one) closed is one closed entry, with both
        commissions apportioned by quantity.

        An open short is reported as an open position with negative quantity
        and negative cost basis (the proceeds received). ``unmatched_sells``
        counts the symbols left net short. A sale of shares bought before the
        history starts looks the same as a short sale here; reconciling against
        the brokerage's holdings is what tells them apart.
        """
        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id == sleeve_id, Trade.trade_date <= as_of_date)
            .order_by(Trade.trade_date, Trade.id)
            .all()
        )
        # Buys before sells within a day: the source reports dates, not times,
        # so a same-day round trip must not see its sell first.
        trades.sort(key=lambda t: (t.trade_date, t.action != "BUY"))

        # Per symbol, oldest first, as [qty_left, unit_value, opened_at]:
        # unit cost for a long lot, unit proceeds for a short one.
        longs: Dict[str, List[list]] = {}
        shorts: Dict[str, List[list]] = {}
        closed_positions: List[Dict] = []
        trades_count: Dict[str, int] = {}

        def close(symbol, qty, entry, exit_price, opened_at, closed_at, realized):
            basis = qty * entry
            rg_pct = (realized / basis * 100) if basis > 0 else Decimal(0)
            closed_positions.append(
                {
                    "symbol": symbol,
                    "status": "CLOSED",
                    "quantity": Decimal(0),
                    "cost_basis": Decimal(0),
                    "avg_cost": Decimal(0),
                    "entry_price": float(entry),
                    "exit_price": float(exit_price),
                    "matched_quantity": float(qty),
                    "realized_gain": realized,
                    "realized_gain_pct": float(rg_pct),
                    "opened_at": opened_at,
                    "closed_at": closed_at,
                    "trades_count": 2,
                }
            )

        for trade in trades:
            symbol = trade.symbol
            trades_count[symbol] = trades_count.get(symbol, 0) + 1
            qty = Decimal(str(trade.quantity))
            price = Decimal(str(trade.price))
            per_share_comm = Decimal(str(trade.commission or 0)) / qty
            remaining = qty

            if trade.action == "BUY":
                unit_cost = price + per_share_comm
                open_shorts = shorts.get(symbol, [])
                while remaining > 0 and open_shorts:
                    lot = open_shorts[0]
                    matched = min(remaining, lot[0])
                    # Sold first at lot[1], bought back now at unit_cost.
                    close(
                        symbol,
                        matched,
                        lot[1],
                        price,
                        lot[2],
                        trade.trade_date,
                        matched * (lot[1] - unit_cost),
                    )
                    lot[0] -= matched
                    remaining -= matched
                    if lot[0] <= 0:
                        open_shorts.pop(0)
                if remaining > 0:
                    longs.setdefault(symbol, []).append(
                        [remaining, unit_cost, trade.trade_date]
                    )
                continue

            unit_proceeds = price - per_share_comm
            open_longs = longs.get(symbol, [])
            while remaining > 0 and open_longs:
                lot = open_longs[0]
                matched = min(remaining, lot[0])
                close(
                    symbol,
                    matched,
                    lot[1],
                    price,
                    lot[2],
                    trade.trade_date,
                    matched * (unit_proceeds - lot[1]),
                )
                lot[0] -= matched
                remaining -= matched
                if lot[0] <= 0:
                    open_longs.pop(0)
            if remaining > 0:
                shorts.setdefault(symbol, []).append(
                    [remaining, unit_proceeds, trade.trade_date]
                )

        open_positions = []
        net_short_symbols = 0
        for symbol in sorted(set(longs) | set(shorts)):
            # A symbol never holds long and short lots at once: each side is
            # only opened after the other is exhausted.
            long_lots = longs.get(symbol, [])
            short_lots = shorts.get(symbol, [])
            total_qty = sum((lot[0] for lot in long_lots), Decimal(0)) - sum(
                (lot[0] for lot in short_lots), Decimal(0)
            )
            if total_qty == 0:
                continue
            total_cost = sum((lot[0] * lot[1] for lot in long_lots), Decimal(0)) - sum(
                (lot[0] * lot[1] for lot in short_lots), Decimal(0)
            )
            if total_qty < 0:
                net_short_symbols += 1
            open_positions.append(
                {
                    "symbol": symbol,
                    "status": "OPEN",
                    "quantity": total_qty,
                    "cost_basis": total_cost,
                    "avg_cost": total_cost / total_qty,
                    "trades_count": trades_count.get(symbol, 0),
                }
            )

        return {
            "open": open_positions,
            "closed": closed_positions,
            "unmatched_sells": net_short_symbols,
        }

    def _round_trip_positions(self, sleeve_ids: List[str], as_of_date: date) -> Dict:
        """
        Positions across one or more sleeves using **quantity-matched round-trips**.

        Each SELL is paired with the earliest unmatched BUY of the same symbol
        AND the same quantity within the sleeve set (a sleeve = account ×
        strategy, so this also scopes matching to one strategy). A matched pair
        is one CLOSED round-trip with realized_gain = (exit - entry) * qty minus
        both commissions. Any BUY left unmatched contributes to the OPEN
        position for that symbol.

        A SELL with no matching BUY is ignored (treated as out-of-scope data
        rather than an error).
        """
        trades = (
            self.db.query(Trade)
            .filter(
                and_(Trade.sleeve_id.in_(sleeve_ids), Trade.trade_date <= as_of_date)
            )
            .order_by(Trade.trade_date, Trade.id)
            .all()
        )

        # Per (symbol, quantity): queues of unmatched buys, in date order.
        # NOTE: matching is by EXACT quantity — a BUY of 100 only pairs with a
        # SELL of 100. Partial fills (100 BUY vs 60 + 40 SELLs) are NOT netted;
        # they remain unmatched. This is intentional: trades are imported as
        # discrete round-trips, not aggregated lots.
        open_buys: Dict[tuple, List[Trade]] = {}
        closed_positions: List[Dict] = []
        trades_count: Dict[str, int] = {}

        for trade in trades:
            symbol = trade.symbol
            trades_count[symbol] = trades_count.get(symbol, 0) + 1
            key = (symbol, Decimal(str(trade.quantity)))

            if trade.action == "BUY":
                open_buys.setdefault(key, []).append(trade)
            else:  # SELL — pair with the oldest unmatched BUY of same symbol+qty
                buys = open_buys.get(key)
                if not buys:
                    # SELL with no matching BUY in scope — ignore.
                    continue
                buy = buys.pop(0)
                qty = Decimal(str(trade.quantity))
                entry = Decimal(str(buy.price))
                exit_price = Decimal(str(trade.price))
                buy_comm = Decimal(str(buy.commission))
                sell_comm = Decimal(str(trade.commission))

                cost_basis = qty * entry + buy_comm
                proceeds = qty * exit_price - sell_comm
                realized = proceeds - cost_basis
                rg_pct = (realized / cost_basis * 100) if cost_basis > 0 else Decimal(0)

                closed_positions.append(
                    {
                        "symbol": symbol,
                        "status": "CLOSED",
                        "quantity": Decimal(0),
                        "cost_basis": Decimal(0),
                        "avg_cost": Decimal(0),
                        "entry_price": float(entry),
                        "exit_price": float(exit_price),
                        "matched_quantity": float(qty),
                        "realized_gain": realized,
                        "realized_gain_pct": float(rg_pct),
                        "opened_at": buy.trade_date,
                        "closed_at": trade.trade_date,
                        "trades_count": 2,
                    }
                )

        # Remaining unmatched buys roll up into open positions per symbol.
        open_by_symbol: Dict[str, Dict] = {}
        for (symbol, _qty), buys in open_buys.items():
            for buy in buys:
                bqty = Decimal(str(buy.quantity))
                bcost = bqty * Decimal(str(buy.price)) + Decimal(str(buy.commission))
                agg = open_by_symbol.setdefault(
                    symbol,
                    {
                        "quantity": Decimal(0),
                        "cost_basis": Decimal(0),
                    },
                )
                agg["quantity"] += bqty
                agg["cost_basis"] += bcost

        open_positions = []
        for symbol, agg in open_by_symbol.items():
            total_qty = agg["quantity"]
            if total_qty <= 0:
                continue
            total_cost = agg["cost_basis"]
            avg_cost = total_cost / total_qty if total_qty > 0 else Decimal(0)
            open_positions.append(
                {
                    "symbol": symbol,
                    "status": "OPEN",
                    "quantity": total_qty,
                    "cost_basis": total_cost,
                    "avg_cost": avg_cost,
                    "trades_count": trades_count.get(symbol, 0),
                }
            )

        return {
            "open": open_positions,
            "closed": closed_positions,
            "unmatched_sells": 0,
        }

    def calculate_position_value(self, position: Dict, current_price: Decimal) -> Dict:
        """Add market value and unrealized P&L to an open position dict."""
        qty = Decimal(str(position["quantity"]))
        cost_basis = Decimal(str(position["cost_basis"]))
        market_value = qty * current_price
        unrealized_gain = market_value - cost_basis
        unrealized_gain_pct = (
            (unrealized_gain / abs(cost_basis) * 100) if cost_basis != 0 else Decimal(0)
        )
        return {
            **position,
            "current_price": current_price,
            "market_value": market_value,
            "unrealized_gain": unrealized_gain,
            "unrealized_gain_pct": float(unrealized_gain_pct),
        }

    def calculate_account_value(
        self, sleeve_ids, current_prices: Dict[str, Decimal] = None
    ) -> Dict:
        """
        Calculate total portfolio value across one or more sleeves.

        Returns open and closed positions plus a summary dict.
        current_prices keys are symbols; values are Decimal prices.
        """
        if current_prices is None:
            current_prices = {}

        result = self.calculate_positions(sleeve_ids)
        open_pos = result["open"]
        closed_pos = result["closed"]

        valued_open = []
        total_cost = Decimal(0)
        total_market_value = Decimal(0)

        for pos in open_pos:
            symbol = pos["symbol"]
            cost_basis = Decimal(str(pos["cost_basis"]))

            if symbol in current_prices:
                price = Decimal(str(current_prices[symbol]))
                valued_pos = self.calculate_position_value(pos, price)
                market_value = Decimal(str(valued_pos["market_value"]))
            else:
                market_value = cost_basis
                valued_pos = {
                    **pos,
                    "current_price": None,
                    "market_value": market_value,
                    "unrealized_gain": Decimal(0),
                    "unrealized_gain_pct": 0,
                }

            total_cost += cost_basis
            total_market_value += market_value
            valued_open.append(valued_pos)

        total_unrealized_gain = total_market_value - total_cost
        total_return_pct = (
            (total_unrealized_gain / total_cost * 100) if total_cost > 0 else Decimal(0)
        )

        total_realized_gain = sum(Decimal(str(p["realized_gain"])) for p in closed_pos)

        return {
            "total_cost_basis": float(total_cost),
            "total_market_value": float(total_market_value),
            "total_unrealized_gain": float(total_unrealized_gain),
            "total_return_pct": float(total_return_pct),
            "total_realized_gain": float(total_realized_gain),
            "positions_count": len(valued_open),
            "closed_positions_count": len(closed_pos),
            "positions": valued_open,
            "closed_positions": closed_pos,
        }

    def value_series(self, sleeve_ids, current_prices: Dict[str, Decimal] = None):
        """
        Build a cumulative portfolio value time-series across one or more sleeves.

        Produces one point per distinct trade date: the total market value and
        cost basis of all open positions as of that date. Each symbol is valued
        at current_prices[symbol] when available, else its last trade price on
        or before that date.

        Returns:
            List of {"date": date, "value": float, "cost_basis": float}
        """
        sleeve_ids = _as_sleeve_ids(sleeve_ids)
        if current_prices is None:
            current_prices = {}

        trades = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .order_by(Trade.trade_date)
            .all()
        )
        if not trades:
            return []

        distinct_dates = sorted({t.trade_date for t in trades})

        series = []
        for as_of in distinct_dates:
            book: Dict[str, Dict] = {}
            for trade in trades:
                if trade.trade_date > as_of:
                    break
                symbol = trade.symbol
                qty = Decimal(str(trade.quantity))
                price = Decimal(str(trade.price))
                comm = Decimal(str(trade.commission))

                entry = book.setdefault(
                    symbol,
                    {"qty": Decimal(0), "cost": Decimal(0), "last_price": price},
                )
                entry["last_price"] = price

                if trade.action == "BUY":
                    entry["qty"] += qty
                    entry["cost"] += qty * price + comm
                else:
                    old_qty = entry["qty"]
                    if old_qty > 0:
                        cost_per_share = entry["cost"] / old_qty
                        entry["qty"] = old_qty - qty
                        entry["cost"] = max(Decimal(0), entry["qty"] * cost_per_share)
                    else:
                        entry["qty"] = old_qty - qty

            total_value = Decimal(0)
            total_cost = Decimal(0)
            for symbol, entry in book.items():
                if entry["qty"] <= 0:
                    continue
                price = current_prices.get(symbol, entry["last_price"])
                total_value += entry["qty"] * Decimal(str(price))
                total_cost += entry["cost"]

            series.append(
                {
                    "date": as_of,
                    "value": float(total_value),
                    "cost_basis": float(total_cost),
                }
            )

        return series

    def persist_positions(self, sleeve_id: str, positions: List[Dict]) -> None:
        """
        Persist calculated open positions for a single sleeve.
        Closed positions are written by persist_all_positions; this method
        only updates open rows (called after price updates).
        """
        now = datetime.now(timezone.utc)

        # Delete existing OPEN rows and rewrite them
        self.db.query(Position).filter(
            Position.sleeve_id == sleeve_id,
            Position.status == "OPEN",
        ).delete()

        for pos in positions:
            db_position = Position(
                sleeve_id=sleeve_id,
                symbol=pos["symbol"],
                status="OPEN",
                quantity=pos["quantity"],
                cost_basis=pos["cost_basis"],
                current_price=pos.get("current_price"),
                market_value=pos.get("market_value"),
                unrealized_gain=pos.get("unrealized_gain"),
                last_updated=now,
            )
            self.db.add(db_position)

        self.db.commit()

    def persist_all_positions(self, sleeve_id: str) -> None:
        """
        Recalculate and persist all open and closed positions for a sleeve.
        Called after trade imports/syncs so the positions table stays current.
        """
        now = datetime.now(timezone.utc)
        result = self.calculate_positions(sleeve_id)

        # Wipe and rewrite everything for this sleeve
        self.db.query(Position).filter(Position.sleeve_id == sleeve_id).delete()

        for pos in result["open"]:
            self.db.add(
                Position(
                    sleeve_id=sleeve_id,
                    symbol=pos["symbol"],
                    status="OPEN",
                    quantity=pos["quantity"],
                    cost_basis=pos["cost_basis"],
                    last_updated=now,
                )
            )

        for pos in result["closed"]:
            self.db.add(
                Position(
                    sleeve_id=sleeve_id,
                    symbol=pos["symbol"],
                    status="CLOSED",
                    quantity=Decimal(0),
                    cost_basis=Decimal(0),
                    realized_gain=pos["realized_gain"],
                    realized_gain_pct=pos["realized_gain_pct"],
                    closed_at=datetime.combine(
                        pos["closed_at"], datetime.min.time()
                    ).replace(tzinfo=timezone.utc),
                    last_updated=now,
                )
            )

        self.db.commit()
