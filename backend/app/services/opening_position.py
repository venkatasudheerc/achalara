"""What an account held before its history on file begins.

A feed's history reaches back only so far (Plaid two years at most), and a
client's file may reach further. An account can therefore begin its history
already holding money and shares. That position is worked back from the institution's latest record: each security's shares then,
less what was bought since and plus what was sold, and the cash less every
movement since. It is stored as **opening trades**, one buy per security dated
the market day before the first transaction, so positions, cost basis, the
holdings check, the cash ledger and the daily rebuild all see it, and as the
record's first day, at that cash and those shares, with nothing moved in.

Opening trades are derived, never fact. ``OpeningPositionService.refresh``
deletes and works them out again before every rebuild, so history added later
(a sync, a file) moves or removes them. They carry ``OPENING_NOTE`` and an id
starting ``OPENING_ID_PREFIX``; nothing else may create or change them, the
activity lists leave them out, and an import never matches a row against one.

Nothing is guessed. A security that works back to fewer than no shares, cash
below nothing in an account that is not owed money, or a day the institution
recorded cash that the history does not agree with (``account_health.cash_check``),
means a transaction is missing: it is reported and the account opens empty, as
before. A missing movement shifts every day before it, so an opening worked back
through one would be wrong by exactly that amount.
"""
from __future__ import annotations

import logging
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount
from app.models.cash_activity import CashActivity
from app.models.perf import DailyHolding
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.account_health import INCOMPLETE, cash_check
from app.services.account_kind import OWED, kind_of
from app.services.cash_ledger import CashLedger
from app.services.corporate_actions import (
    MERGER_NOTE,
    _factor,
    adjusted_trades,
    split_factors,
)

logger = logging.getLogger(__name__)

ZERO = Decimal(0)
OPENING_NOTE = "Opening position: "
OPENING_ID_PREFIX = "opening:"
# Shares this close to zero are none: fractional shares are kept to 8 places.
_NO_SHARES = Decimal("0.000001")

# For queries: every trade but the opening ones.
NOT_OPENING = or_(Trade.notes.is_(None), ~Trade.notes.like(f"{OPENING_NOTE}%"))


def is_opening(trade) -> bool:
    """Whether a stored trade is an opening position, not a transaction."""
    return (getattr(trade, "notes", None) or "").startswith(OPENING_NOTE)


def close_on(points: List[Tuple[date, Decimal]], day: date) -> Optional[Decimal]:
    """The latest close on or before ``day``, at most a week old."""
    index = bisect_right(points, (day, Decimal("Infinity"))) - 1
    if index < 0:
        return None
    found, close = points[index]
    return close if (day - found).days <= 7 else None


@dataclass
class OpeningShares:
    """A security already held before the first transaction on file, in
    today's shares."""

    symbol: str
    quantity: Decimal
    sleeve_id: str
    # A real price on a known day to tie the price history to: the first trade
    # of it at the market on file, else the institution's latest price.
    ref_price: Decimal
    ref_day: date
    # The institution's cost per share where nothing traded since could have
    # changed it; else unknown, and the opening day's price stands in.
    unit_cost: Optional[Decimal]
    security_type: Optional[str] = None


@dataclass
class Opening:
    """What an account held before its first transaction on file."""

    day: Optional[date] = None
    cash: Decimal = ZERO
    shares: Dict[str, OpeningShares] = field(default_factory=dict)
    # Why it cannot be worked out: a transaction is missing.
    problems: List[str] = field(default_factory=list)


def work_back_shares(
    trades,
    held: Dict[str, Tuple[Decimal, Optional[Decimal], Optional[str]]],
    anchor: date,
    off_market: Optional[set] = None,
    avg_costs: Optional[Dict[str, Decimal]] = None,
    default_sleeve_id: Optional[str] = None,
    through: Optional[date] = None,
) -> Opening:
    """Each security's shares before ``trades`` began, from what was ``held``
    on ``anchor`` (symbol -> quantity, price, sleeve), counting the trades up to
    ``through`` (the anchor itself unless said). Options and "~" names are not
    listed by the institution and are left out."""
    through = through or anchor
    opening = Opening()
    off_market = off_market or set()
    net: Dict[str, Decimal] = {}
    first_trade = {}
    for trade in trades:
        if trade.trade_date > through:
            continue
        signed = trade.quantity if trade.action == "BUY" else -trade.quantity
        net[trade.symbol] = net.get(trade.symbol, ZERO) + signed
        first_trade.setdefault(trade.symbol, trade)
    for symbol in sorted(set(held) | set(net)):
        if symbol.startswith("~") or is_option_symbol(symbol):
            continue
        quantity_now, price_now, sleeve_now = held.get(symbol, (ZERO, None, None))
        quantity = quantity_now - net.get(symbol, ZERO)
        if abs(quantity) < _NO_SHARES:
            continue
        if quantity < 0:
            opening.problems.append(f"{symbol} works back to {quantity.normalize():f} shares")
            continue
        at_market = next(
            (
                t for t in trades
                if t.symbol == symbol and t.trade_date <= through
                and t.at_market and t.id not in off_market and t.price > 0
            ),
            None,
        )
        if at_market is not None:
            ref_price, ref_day = at_market.price, at_market.trade_date
        elif price_now:
            ref_price, ref_day = price_now, anchor
        else:
            opening.problems.append(f"{symbol} has no price to start from")
            continue
        traded = symbol in net
        sleeve = sleeve_now or (first_trade[symbol].sleeve_id if traded else default_sleeve_id)
        if sleeve is None:
            opening.problems.append(f"{symbol} has no strategy to sit in")
            continue
        opening.shares[symbol] = OpeningShares(
            symbol=symbol,
            quantity=quantity,
            sleeve_id=sleeve,
            ref_price=ref_price,
            ref_day=ref_day,
            unit_cost=None if traded else (avg_costs or {}).get(symbol),
        )
    return opening


def opening_scale(
    held: OpeningShares,
    points: List[Tuple[date, Decimal]],
    dividends: List[Tuple[date, str, str, Decimal]],
    start: date,
) -> Optional[Decimal]:
    """The scale tying a held security's adjusted price history to its real
    price on ``start``: the real price over the close on ``held.ref_day``,
    raised by each dividend paid between, which the rebuild lowers it by again
    on its way forward."""
    ref_close = close_on(points, held.ref_day)
    if not ref_close:
        return None
    scale = held.ref_price / ref_close
    for paid_on, sleeve_id, symbol, amount in dividends:
        if symbol != held.symbol or sleeve_id != held.sleeve_id:
            continue
        if start < paid_on <= held.ref_day:
            close = close_on(points, paid_on)
            if close:
                scale += (amount / held.quantity) / close
    return scale


class OpeningPositionService:
    """Works out and stores an account's opening position."""

    def __init__(self, db: Session):
        self.db = db

    def refresh(self, account_id: str) -> Opening:
        """Delete the account's opening trades and work them out again. Returns
        the opening, with ``day`` set when the record should start there. Why it
        could not be worked out is kept on the account's links
        (``reconciliation["opening_problems"]``) for its health check."""
        opening = self._work_out(account_id)
        for link in self.db.query(BrokerageAccount).filter(
            BrokerageAccount.account_id == account_id
        ):
            report = dict(link.reconciliation or {})
            if report.get("opening_problems", []) != opening.problems:
                report["opening_problems"] = list(opening.problems)
                link.reconciliation = report
        self.db.commit()
        return opening

    def _work_out(self, account_id: str) -> Opening:
        from app.services.performance_build_service import last_market_day

        account = self.db.get(Account, account_id)
        sleeve_ids = [
            row[0] for row in self.db.query(Sleeve.id).filter(Sleeve.account_id == account_id)
        ]
        if account is None or not sleeve_ids:
            return Opening()
        owed = kind_of(account) in OWED
        old = self.db.query(Trade).filter(
            Trade.sleeve_id.in_(sleeve_ids), Trade.notes.like(f"{OPENING_NOTE}%")
        )
        had_opening = old.count() > 0
        old.delete(synchronize_session=False)
        self.db.flush()
        factors = split_factors(self.db)

        stored = (
            self.db.query(Trade)
            .filter(Trade.sleeve_id.in_(sleeve_ids))
            .order_by(Trade.trade_date, Trade.id)
            .all()
        )
        trades = adjusted_trades(self.db, stored)
        off_market = {t.id for t in stored if (t.notes or "").startswith(MERGER_NOTE)}
        ledger = CashLedger.for_accounts(self.db, [account_id])
        starts = [t.trade_date for t in trades[:1]]
        if ledger is not None and ledger.changes:
            starts.append(min(ledger.changes))
        if not starts:
            self._settle(account_id, had_opening)
            return Opening()
        first = min(starts)
        day = last_market_day(first - timedelta(days=1))

        opening = self._shares(account_id, sleeve_ids, trades, off_market)
        if not opening.problems and opening.shares:
            self._write(opening, day, first, account_id, sleeve_ids, factors)
        # The reconciliation carries holdings our trades do not explain as if
        # still cash; with the opening trades in or out, it is worked out again
        # from the institution's latest record before the cash is worked back.
        self._settle(account_id, had_opening or bool(opening.shares))
        if not opening.problems:
            ledger = CashLedger.for_accounts(self.db, [account_id])
            opening.cash = ledger.balance_on(first - timedelta(days=1)) if ledger else ZERO
            if opening.cash < 0 and not owed:
                opening.problems.append(f"cash works back to {opening.cash:.2f}")
            # Worked back from today, a movement missing later shifts every
            # earlier day: the opening is only as good as the history after it.
            cash = cash_check(self.db, account)
            if cash and cash["state"] == INCOMPLETE:
                opening.problems.append(
                    f"cash differs from the institution's record on {cash['last_differed'].isoformat()}"
                )
        if opening.problems:
            logger.warning(
                "Account %s cannot be worked back to its start (%s); it opens empty",
                account_id, "; ".join(opening.problems),
            )
            if opening.shares:
                self.db.query(Trade).filter(
                    Trade.sleeve_id.in_(sleeve_ids), Trade.notes.like(f"{OPENING_NOTE}%")
                ).delete(synchronize_session=False)
                self._settle(account_id, True)
            opening.shares, opening.cash = {}, ZERO
            return opening
        if opening.shares or opening.cash != ZERO:
            opening.day = day
        return opening

    def _write(self, opening: Opening, day: date, first: date, account_id: str,
               sleeve_ids: List[str], factors) -> None:
        """Store each opening holding as a buy on ``day``, in that day's shares."""
        from app.services.price_history_service import PriceHistoryService

        closes = PriceHistoryService(self.db).closes(set(opening.shares))
        dividends = self._dividends(sleeve_ids)
        for symbol, shares in opening.shares.items():
            unit = shares.unit_cost
            if unit is None:
                points = closes.get(symbol, [])
                scale = opening_scale(shares, points, dividends, day)
                close = close_on(points, day)
                unit = close * scale if close and scale else shares.ref_price
            factor = _factor(factors.get(symbol, []), day)
            self.db.add(
                Trade(
                    sleeve_id=shares.sleeve_id,
                    trade_date=day,
                    symbol=symbol,
                    action="BUY",
                    quantity=shares.quantity / factor,
                    price=(unit * factor).quantize(Decimal("0.000001")),
                    commission=ZERO,
                    notes=f"{OPENING_NOTE}held before {first.isoformat()}",
                    external_id=f"{OPENING_ID_PREFIX}{account_id}:{symbol}",
                    security_type=shares.security_type,
                )
            )
        self.db.flush()

    def _settle(self, account_id: str, changed: bool) -> None:
        """Commit, and where opening trades came or went, compare the trades
        with the institution's latest recorded holdings again."""
        self.db.commit()
        if not changed:
            return
        from app.connectors.models import NormalizedPosition
        from app.services.connection_service import ConnectionService

        latest = (
            self.db.query(func.max(DailyHolding.as_of_date))
            .filter(DailyHolding.account_id == account_id)
            .scalar()
        )
        if latest is None:
            return
        holdings = [
            NormalizedPosition(
                symbol=row.symbol,
                quantity=Decimal(str(row.quantity)),
                avg_cost=Decimal(str(row.avg_cost or 0)),
                market_price=Decimal(str(row.price)) if row.price is not None else None,
                security_type=row.security_type,
            )
            for row in self.db.query(DailyHolding).filter(
                DailyHolding.account_id == account_id, DailyHolding.as_of_date == latest
            )
        ]
        for link in self.db.query(BrokerageAccount).filter(
            BrokerageAccount.account_id == account_id,
            BrokerageAccount.status == "mapped",
            BrokerageAccount.reconciliation.isnot(None),
        ):
            kept = Decimal(str((link.reconciliation or {}).get("valuation_adjustment", 0)))
            try:
                ConnectionService(self.db, connector=object()).reconcile(
                    link.id, holdings=holdings, valuation_adjustment=kept
                )
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.warning("Reconciliation after the opening failed for %s: %s", link.id, exc)

    # ------------------------------------------------------------------

    def _shares(self, account_id, sleeve_ids, trades, off_market) -> Opening:
        """The opening shares, worked back from the latest recorded holdings
        that do it cleanly.

        Only days the transactions on file are complete through are used: a
        holding listed later may be a purchase not yet on file. A day's
        holdings may also be taken before that day's trades show, so each day is
        tried counting its own trades, then without them. When no day works
        back cleanly, the latest day's problems are reported."""
        complete = (
            self.db.query(func.max(BrokerageAccount.transactions_synced_through))
            .filter(BrokerageAccount.account_id == account_id)
            .scalar()
        )
        if complete is None:
            return Opening()
        days = [
            row[0]
            for row in self.db.query(DailyHolding.as_of_date)
            .filter(DailyHolding.account_id == account_id, DailyHolding.as_of_date <= complete)
            .distinct()
            .order_by(DailyHolding.as_of_date.desc())
        ]
        default_sleeve = self._default_sleeve(account_id, sleeve_ids)
        first_tried: Optional[Opening] = None
        for anchor in days:
            held, types = self._held(account_id, anchor)
            for through in (anchor, anchor - timedelta(days=1)):
                opening = work_back_shares(
                    trades, held, anchor, off_market,
                    avg_costs=self._costs(account_id, anchor),
                    default_sleeve_id=default_sleeve,
                    through=through,
                )
                first_tried = first_tried or opening
                if not opening.problems:
                    for symbol, shares in opening.shares.items():
                        shares.security_type = types.get(symbol)
                    return opening
        return first_tried or Opening()

    def _held(self, account_id: str, day: date):
        held: Dict[str, Tuple[Decimal, Optional[Decimal], Optional[str]]] = {}
        types: Dict[str, Optional[str]] = {}
        for row in self.db.query(DailyHolding).filter(
            DailyHolding.account_id == account_id, DailyHolding.as_of_date == day
        ):
            quantity, price, sleeve = held.get(row.symbol, (ZERO, None, None))
            held[row.symbol] = (
                quantity + Decimal(str(row.quantity)),
                Decimal(str(row.price)) if row.price is not None else price,
                row.sleeve_id or sleeve,
            )
            types[row.symbol] = row.security_type
        return held, types

    def _costs(self, account_id: str, day: date) -> Dict[str, Decimal]:
        return {
            row.symbol: Decimal(str(row.avg_cost))
            for row in self.db.query(DailyHolding).filter(
                DailyHolding.account_id == account_id,
                DailyHolding.as_of_date == day,
                DailyHolding.avg_cost.isnot(None),
            )
        }

    def _default_sleeve(self, account_id: str, sleeve_ids: List[str]) -> Optional[str]:
        """Where a holding with no trades sits: the feed's default strategy,
        else the account's only one."""
        link = (
            self.db.query(BrokerageAccount.default_sleeve_id)
            .filter(BrokerageAccount.account_id == account_id)
            .first()
        )
        if link and link[0]:
            return link[0]
        return sleeve_ids[0] if len(sleeve_ids) == 1 else None

    def _dividends(self, sleeve_ids: List[str]):
        return [
            (row.activity_date, row.sleeve_id, row.symbol, Decimal(str(row.amount)))
            for row in self.db.query(CashActivity).filter(
                CashActivity.sleeve_id.in_(sleeve_ids),
                CashActivity.type == "DIVIDEND",
                CashActivity.symbol.isnot(None),
            )
        ]
