"""Lots: which shares a sale closes, and what the brokerage reports for it.

Every closed lot carries two readings of the same cash.

The first is what happened: ``realized_gain`` is the proceeds less what was
paid, on the day the position closed. Performance and every total built on it
read this, and nothing below changes it.

The second is how a brokerage states cost and gain, which follows tax rules
that move gain between lots and years without changing a cent of cash:

* **Wash sales.** A loss on shares replaced within 30 days either side is
  disallowed, and carried in the replacement shares' cost and holding time.
* **Index options.** Gain is 60% long-term and 40% short-term however long the
  contract was held, and a contract open over a year end is treated as sold and
  bought back at that day's price.
* **Written options** bought back or expired are short-term.
* **Share exchanges.** Shares swapped for shares in a merger keep their cost
  and their opening date; nothing is realised.

These are the ``cost``, ``proceeds``, ``disallowed_loss``, ``reported_gain``,
``short_term_gain`` and ``long_term_gain`` of a closed lot, and ``tax_cost`` of
an open position. The scope is one security in one account, which is the scope
the brokerage itself applies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from app.connectors.models import is_option_symbol

FIFO = "FIFO"
MIN_TAX = "MIN_TAX"
LOT_METHODS = (FIFO, MIN_TAX)

# Held longer than this many days is long-term.
LONG_TERM_DAYS = 365
# Replacement shares bought this long before or after a loss disallow it.
WASH_WINDOW = timedelta(days=30)
# A year-end price may be dated up to this long before 31 December.
_MARK_REACH = timedelta(days=7)
# Shares one option contract covers; a stored option price is per contract.
_CONTRACT_SHARES = Decimal(100)
_LONG_SHARE = Decimal("0.6")

# Broad-based index options, by the root of the option symbol: split 60/40
# and marked at year end.
INDEX_OPTION_ROOTS = frozenset(
    {
        "SPX",
        "SPXW",
        "XSP",
        "NDX",
        "NDXP",
        "XND",
        "RUT",
        "RUTW",
        "MRUT",
        "VIX",
        "VIXW",
        "DJX",
        "OEX",
        "XEO",
    }
)
# Not index options, and usually read as ordinary equity options. They are
# split 60/40 here only because the brokerage's realised-gains list shows them
# that way (seen on written puts that expired). Nothing shows the brokerage
# marking them at a year end, so they are not marked.
SPLIT_ONLY_ROOTS = frozenset({"GLD", "SLV"})
_OPTION_ROOT = re.compile(r"^([A-Z0-9.]{1,6}?)\d{6}[CP]\d{8}$")

# Codes in a closed lot's ``adjustments``.
WASH = "wash"
MARK = "mark"
UNMARKED = "unmarked"
INDEX_OPTION = "index_option"
WRITTEN_OPTION = "written_option"

# A security's year-end prices as quoted (per share), oldest first.
Marks = Dict[str, List[Tuple[date, Decimal]]]


def _root(symbol: str) -> str:
    match = _OPTION_ROOT.match(symbol or "")
    return match.group(1) if match else ""


def is_index_option(symbol: str) -> bool:
    """Split 60/40 and marked to the year-end price."""
    return _root(symbol) in INDEX_OPTION_ROOTS


def is_split_option(symbol: str) -> bool:
    """Gain reported 60% long-term and 40% short-term whatever the time held."""
    return _root(symbol) in INDEX_OPTION_ROOTS | SPLIT_ONLY_ROOTS


@dataclass
class _Lot:
    quantity: Decimal
    unit: Decimal  # what was paid per unit (long) or received (short)
    opened_at: date
    tax_unit: Decimal  # the same, as the brokerage states it
    held_from: date  # where the holding time starts
    source: str  # the trade that opened it
    replacement: bool = False  # already carries a disallowed loss
    unmarked: bool = False  # crossed a year end with no price on file


@dataclass
class _Pending:
    """A loss still waiting to see whether the shares are bought back."""

    quantity: Decimal
    loss: Decimal  # per unit
    sold_on: date
    held_days: int
    source: str
    opened_at: date
    row: Dict


def _lot_fields(lot: _Lot) -> Dict:
    return {
        "quantity": lot.quantity,
        "unit": lot.unit,
        "opened_at": lot.opened_at,
        "tax_unit": lot.tax_unit,
        "held_from": lot.held_from,
        "replacement": lot.replacement,
    }


def carried_lots(
    lots: Sequence[Dict], given: Decimal, share: Decimal, quantity: Decimal
) -> List[Dict]:
    """The lots one leg of a share exchange starts with.

    ``lots`` are the oldest open lots of the shares given up, ``given`` how
    many shares were given up, ``share`` the part of them this leg stands for
    and ``quantity`` how many shares the leg received. Each lot keeps its
    dates and its total cost, restated over the new share count.
    """
    carried: List[Dict] = []
    left = given
    for lot in lots:
        if left <= 0:
            break
        taken = min(left, lot["quantity"])
        left -= taken
        new_quantity = taken / given * quantity
        scale = taken * share / new_quantity
        carried.append(
            {
                **lot,
                "quantity": new_quantity,
                "unit": lot["unit"] * scale,
                "tax_unit": lot["tax_unit"] * scale,
            }
        )
    return carried


def _year_end_price(marks: Marks, symbol: str, year: int) -> Optional[Decimal]:
    end = date(year, 12, 31)
    found = None
    for priced_on, close in marks.get(symbol, []):
        if end - _MARK_REACH <= priced_on <= end:
            found = close
    return found * _CONTRACT_SHARES if found is not None else None


def match_lots(
    trades: Sequence,
    *,
    as_of: date,
    method: str = FIFO,
    given_up: Iterable[str] = (),
    received: Optional[Dict[str, List[Dict]]] = None,
    marks: Optional[Marks] = None,
) -> Dict:
    """Match the trades of one sleeve into open positions and closed lots.

    ``trades`` are read in the order given, which must be by day with buys
    ahead of sells. A sale closes long lots of its symbol (oldest first, or in
    ``MIN_TAX`` order) and whatever it cannot cover opens a short lot; a
    purchase covers the oldest short lots first and the rest opens a long lot.

    A share-for-share merger is two legs. ``given_up`` names the sales that
    are really shares swapped away, and ``received`` gives, for each purchase
    that is really shares swapped in, the lots it carries (see
    ``carried_lots``). ``marks`` gives the year-end prices index options are
    marked to.

    Returns ``open``, ``closed``, ``unmatched_sells`` (symbols left net short),
    ``lots`` (the open long lots by symbol) and ``marked``: the year-end
    entries of index options, which belong in a list of reported gains but are
    not positions that closed.
    """
    given_up = frozenset(given_up)
    received = received or {}
    marks = marks or {}
    longs: Dict[str, List[_Lot]] = {}
    shorts: Dict[str, List[_Lot]] = {}
    pending: Dict[str, List[_Pending]] = {}
    closed: List[Dict] = []
    marked: List[Dict] = []
    trades_count: Dict[str, int] = {}

    def entry(
        symbol, qty, entry_price, exit_price, opened_at, closed_at, realized
    ) -> Dict:
        basis = qty * entry_price
        pct = (realized / basis * 100) if basis > 0 else Decimal(0)
        return {
            "symbol": symbol,
            "status": "CLOSED",
            "quantity": Decimal(0),
            "cost_basis": Decimal(0),
            "avg_cost": Decimal(0),
            "entry_price": float(entry_price),
            "exit_price": float(exit_price),
            "matched_quantity": float(qty),
            "realized_gain": realized,
            "realized_gain_pct": float(pct),
            "opened_at": opened_at,
            "closed_at": closed_at,
            "trades_count": 2,
        }

    def report(row, cost, proceeds, term, codes) -> Dict:
        gain = proceeds - cost
        long_part = gain * _LONG_SHARE if term == "mixed" else Decimal(0)
        row.update(
            cost=cost,
            proceeds=proceeds,
            disallowed_loss=Decimal(0),
            reported_gain=gain,
            term=term,
            long_term_gain=gain if term == "long" else long_part,
            short_term_gain=gain - long_part if term != "long" else Decimal(0),
            adjustments=codes,
        )
        return row

    def term_of(symbol: str, held_from: date, closed_at: date) -> str:
        if is_split_option(symbol):
            return "mixed"
        return "long" if (closed_at - held_from).days > LONG_TERM_DAYS else "short"

    def codes_of(symbol: str, lot: _Lot) -> List[str]:
        codes = []
        if is_index_option(symbol):
            codes.append(INDEX_OPTION)
        if lot.unmarked:
            codes.append(UNMARKED)
        if lot.replacement:
            codes.append(WASH)
        return codes

    def absorb(book: List[_Lot], lot: _Lot, wanted: Decimal, loss: _Pending) -> Decimal:
        """Carry up to ``wanted`` units of a disallowed loss in ``lot``."""
        taken = min(lot.quantity, wanted)
        if taken < lot.quantity:
            target = replace(lot, quantity=taken)
            lot.quantity -= taken
            book.insert(book.index(lot), target)
        else:
            target = lot
        target.tax_unit += loss.loss
        target.held_from -= timedelta(days=loss.held_days)
        target.replacement = True
        amount = taken * loss.loss
        row = loss.row
        row["disallowed_loss"] += amount
        row["reported_gain"] += amount
        row[f"{row['term']}_term_gain"] += amount
        if WASH not in row["adjustments"]:
            row["adjustments"].append(WASH)
        return taken

    def replace_from(symbol: str, loss: _Pending, on: date) -> None:
        """Set ``loss`` against shares held that were bought near the sale."""
        book = longs.get(symbol, [])
        for lot in list(book):
            if loss.quantity <= 0:
                return
            if lot.replacement or lot.source == loss.source:
                continue
            if not (loss.sold_on - WASH_WINDOW <= lot.opened_at <= on):
                continue
            loss.quantity -= absorb(book, lot, loss.quantity, loss)

    def open_long(trade, quantity: Decimal, unit: Decimal) -> None:
        symbol = trade.symbol
        longs.setdefault(symbol, []).append(
            _Lot(quantity, unit, trade.trade_date, unit, trade.trade_date, trade.id)
        )
        waiting = [
            loss
            for loss in pending.get(symbol, [])
            if loss.quantity > 0 and trade.trade_date - loss.sold_on <= WASH_WINDOW
        ]
        for loss in waiting:
            replace_from(symbol, loss, trade.trade_date)
        if symbol in pending:
            pending[symbol] = [loss for loss in waiting if loss.quantity > 0]

    def sale_order(book: List[_Lot], unit_proceeds: Decimal, on: date) -> List[_Lot]:
        if method != MIN_TAX:
            return list(book)

        def rank(lot: _Lot):
            gain = unit_proceeds - lot.tax_unit
            is_long = (on - lot.held_from).days > LONG_TERM_DAYS
            # The source gives days, not times: shares bought the same day
            # are taken as bought after the sale, and used only if needed.
            today = lot.opened_at == on
            if gain < 0:
                return (today, 1 if is_long else 0, gain)
            if gain == 0:
                return (today, 3 if is_long else 2, gain)
            return (today, 4 if is_long else 5, gain)

        return sorted(book, key=rank)  # stable: equal lots stay oldest first

    def buy(trade, quantity: Decimal, price: Decimal, unit_cost: Decimal) -> None:
        symbol = trade.symbol
        remaining = quantity
        book = shorts.get(symbol, [])
        while remaining > 0 and book:
            lot = book[0]
            matched = min(remaining, lot.quantity)
            row = entry(
                symbol,
                matched,
                lot.unit,
                price,
                lot.opened_at,
                trade.trade_date,
                matched * (lot.unit - unit_cost),
            )
            # Closing a short is short-term however long it was open.
            codes = codes_of(symbol, lot)
            term = "mixed" if is_split_option(symbol) else "short"
            if is_option_symbol(symbol) and term == "short":
                codes.append(WRITTEN_OPTION)
            closed.append(
                report(row, matched * unit_cost, matched * lot.tax_unit, term, codes)
            )
            lot.quantity -= matched
            remaining -= matched
            if lot.quantity <= 0:
                book.pop(0)
        if remaining > 0:
            open_long(trade, remaining, unit_cost)

    def sell(trade, quantity: Decimal, price: Decimal, unit_proceeds: Decimal) -> None:
        symbol = trade.symbol
        remaining = quantity
        book = longs.get(symbol, [])
        losses: List[_Pending] = []
        for lot in sale_order(book, unit_proceeds, trade.trade_date):
            if remaining <= 0:
                break
            matched = min(remaining, lot.quantity)
            row = entry(
                symbol,
                matched,
                lot.unit,
                price,
                lot.opened_at,
                trade.trade_date,
                matched * (unit_proceeds - lot.unit),
            )
            term = term_of(symbol, lot.held_from, trade.trade_date)
            closed.append(
                report(
                    row,
                    matched * lot.tax_unit,
                    matched * unit_proceeds,
                    term,
                    codes_of(symbol, lot),
                )
            )
            if unit_proceeds < lot.tax_unit and term != "mixed":
                losses.append(
                    _Pending(
                        matched,
                        lot.tax_unit - unit_proceeds,
                        trade.trade_date,
                        (trade.trade_date - lot.held_from).days,
                        lot.source,
                        lot.opened_at,
                        row,
                    )
                )
            lot.quantity -= matched
            remaining -= matched
            if lot.quantity <= 0:
                book.remove(lot)
        # Replacement shares go to the oldest of the lots sold first, whatever
        # order the sale took them in.
        losses.sort(key=lambda loss: loss.opened_at)
        for loss in losses:
            replace_from(symbol, loss, trade.trade_date)
            if loss.quantity > 0:
                pending.setdefault(symbol, []).append(loss)
        if remaining > 0:
            shorts.setdefault(symbol, []).append(
                _Lot(
                    remaining,
                    unit_proceeds,
                    trade.trade_date,
                    unit_proceeds,
                    trade.trade_date,
                    trade.id,
                )
            )

    def apply(trade) -> None:
        quantity = Decimal(str(trade.quantity))
        if quantity <= 0:
            return
        price = Decimal(str(trade.price))
        fee = Decimal(str(trade.commission or 0)) / quantity
        if trade.action == "BUY":
            buy(trade, quantity, price, price + fee)
        else:
            sell(trade, quantity, price, price - fee)

    def give_up(trade) -> None:
        """Take the shares swapped away out of the book: nothing is realised."""
        wanted = Decimal(str(trade.quantity))
        book = longs.get(trade.symbol, [])
        while wanted > 0 and book:
            lot = book[0]
            taken = min(wanted, lot.quantity)
            lot.quantity -= taken
            wanted -= taken
            if lot.quantity <= 0:
                book.pop(0)

    def receive(trade, carried: List[Dict]) -> None:
        """Open the shares received with the cost and dates they carry."""
        book = longs.setdefault(trade.symbol, [])
        for lot in carried:
            book.append(_Lot(source=trade.id, **lot))
        book.sort(key=lambda lot: lot.opened_at)

    def mark_year(year: int) -> None:
        """Treat index options open at the year end as sold and bought back."""
        end = date(year, 12, 31)
        for books, written in ((longs, False), (shorts, True)):
            for symbol, book in books.items():
                if not book or not is_index_option(symbol):
                    continue
                price = _year_end_price(marks, symbol, year)
                for lot in book:
                    if price is None:
                        lot.unmarked = True
                        continue
                    cost, proceeds = lot.quantity * lot.tax_unit, lot.quantity * price
                    if written:
                        cost, proceeds = proceeds, cost
                    row = entry(
                        symbol,
                        lot.quantity,
                        lot.tax_unit,
                        price,
                        lot.opened_at,
                        end,
                        Decimal(0),
                    )
                    marked.append(
                        report(row, cost, proceeds, "mixed", [INDEX_OPTION, MARK])
                    )
                    lot.tax_unit = price

    year: Optional[int] = None
    for trade in trades:
        if year is None:
            year = trade.trade_date.year
        while year < trade.trade_date.year:
            mark_year(year)
            year += 1
        trades_count[trade.symbol] = trades_count.get(trade.symbol, 0) + 1
        if trade.id in given_up:
            give_up(trade)
        elif trade.id in received:
            receive(trade, received[trade.id])
        else:
            apply(trade)
    while year is not None and date(year, 12, 31) <= as_of:
        mark_year(year)
        year += 1

    open_positions = []
    net_short = 0
    for symbol in sorted(set(longs) | set(shorts)):
        # A symbol never holds long and short lots at once: each side is only
        # opened after the other is exhausted.
        long_lots, short_lots = longs.get(symbol, []), shorts.get(symbol, [])

        def total(field: str) -> Decimal:
            return sum(
                (lot.quantity * getattr(lot, field) for lot in long_lots), Decimal(0)
            ) - sum(
                (lot.quantity * getattr(lot, field) for lot in short_lots), Decimal(0)
            )

        quantity = sum((lot.quantity for lot in long_lots), Decimal(0)) - sum(
            (lot.quantity for lot in short_lots), Decimal(0)
        )
        if quantity == 0:
            continue
        if quantity < 0:
            net_short += 1
        cost = total("unit")
        open_positions.append(
            {
                "symbol": symbol,
                "status": "OPEN",
                "quantity": quantity,
                "cost_basis": cost,
                "avg_cost": cost / quantity,
                "tax_cost": total("tax_unit"),
                "trades_count": trades_count.get(symbol, 0),
            }
        )

    return {
        "open": open_positions,
        "closed": closed,
        "marked": marked,
        "lots": {
            symbol: [_lot_fields(lot) for lot in book]
            for symbol, book in longs.items()
            if book
        },
        "unmatched_sells": net_short,
    }
