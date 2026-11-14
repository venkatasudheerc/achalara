"""Vanguard's activity report: history from the custodian's own file.

A feed reaches back only so far, and an account's earlier history comes from
the owner's files. Vanguard's own
"custom activity report" (Excel) lists every trade and cash movement with its
trade date. This reads that file, finds the rows we do not already hold, and
adds only those, through the same routing and ingestion as a sync.

What counts as already held is decided on the economics, not on ids, since the
two sources share none: same side, same quantity, same price (to the cent per
share), on the same day and symbol; failing that, within two weekdays and under
any symbol, because the feed dates an option's expiry or assignment, and the
shares it delivered, on the next trading day (two weekdays on when a market
holiday falls between), and spells some symbols differently (a delisted stock by
its name, a renamed one by its new ticker). Cash rows match on amount within
three days.

Each added row is also kept in ``brokerage_activities`` with the cash it moved,
so the cash ledger's past balances include it. Those rows are marked
``vanguard:`` and are never handed to the feed's parser on a re-derive.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.connectors.models import (
    REPORT_ID_PREFIX,
    ActivityBatch,
    NormalizedCashActivity,
    NormalizedTrade,
    RawActivity,
    TradeAction,
    is_option_symbol,
)
from app.models.brokerage_connection import BrokerageAccount
from app.models.cash_activity import MARGIN_INTEREST, CashActivity
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.corporate_actions import ASSIGNMENT_NOTE, EXPIRY_NOTE
from app.services.opening_position import NOT_OPENING
from app.utils.symbols import app_symbol

SOURCE = "vanguard"
ID_PREFIX = REPORT_ID_PREFIX
_OPTION_MULTIPLIER = Decimal(100)
# A price on file and in the report are the same trade within a cent a share,
# or 0.05% of the price for the odd fraction (dividend reinvestments).
_CENT = Decimal("0.011")
_PRICE_SHARE = Decimal("0.0005")
_QUANTITY = Decimal("0.0001")
_CASH_DAYS = 3
# The next trading day, counting a market holiday between as a weekday.
_LOOSE_WEEKDAYS = 2

TRADE_KINDS = {
    "Buy": TradeAction.BUY,
    "Sell": TradeAction.SELL,
    "Buy to cover": TradeAction.BUY,
    "Sell short": TradeAction.SELL,
    "Buy to open": TradeAction.BUY,
    "Sell to open": TradeAction.SELL,
    "Buy to close": TradeAction.BUY,
    "Sell to close": TradeAction.SELL,
}
OPTION_EVENTS = {"Assignment": ASSIGNMENT_NOTE, "Expired": EXPIRY_NOTE}
# Cash rows: our type, and whether the money came from outside the account.
CASH_KINDS = {
    "Dividend": ("DIVIDEND", False),
    "Withholding": ("WITHHOLDING", False),
    "Fee": ("FEE", False),
    "Interest charge": (MARGIN_INTEREST, False),
    "Income": ("INTEREST", False),
    "Interest": ("INTEREST", False),
    "Corp Action (Cash in Lieu)": ("OTHER", False),
    "Funds Received": ("CONTRIBUTION", True),
    "Withdrawal": ("WITHDRAWAL", True),
    "Transfer (incoming)": ("TRANSFER", True),
    "Transfer (Outgoing)": ("TRANSFER", True),
}
# Cash moving between the account and its settlement fund: cash either way.
SWEEPS = {"Sweep in", "Sweep out"}
_TRANSFERS = {"Transfer (incoming)", "Transfer (Outgoing)"}


class ReportError(ValueError):
    """The file is not a Vanguard activity report this can read."""


@dataclass
class ReportRow:
    """One line of the report, as Vanguard wrote it."""

    line: int
    traded: date
    settled: Optional[date]
    symbol: str
    name: str
    kind: str
    account_type: str
    quantity: Optional[Decimal]
    price: Optional[Decimal]
    fees: Decimal
    amount: Optional[Decimal]

    def as_dict(self) -> Dict:
        return {
            "line": self.line,
            "trade_date": self.traded.isoformat(),
            "settlement_date": self.settled.isoformat() if self.settled else None,
            "symbol": self.symbol,
            "name": self.name,
            "type": self.kind,
            "account_type": self.account_type,
            "quantity": str(self.quantity) if self.quantity is not None else None,
            "price": str(self.price) if self.price is not None else None,
            "fees": str(self.fees),
            "amount": str(self.amount) if self.amount is not None else None,
        }


@dataclass
class Plan:
    """What an import would do: rows to add, rows already held, rows set aside."""

    rows: int = 0
    first: Optional[date] = None
    last: Optional[date] = None
    trades: List[Tuple[ReportRow, NormalizedTrade]] = field(default_factory=list)
    cash: List[Tuple[ReportRow, NormalizedCashActivity]] = field(default_factory=list)
    held_trades: int = 0
    held_cash: int = 0
    # Matched only by side, quantity and price, a day or two apart or under
    # another symbol: listed so a person can see each one.
    loose_matches: List[Tuple[ReportRow, Dict]] = field(default_factory=list)
    skipped: Counter = field(default_factory=Counter)
    # Rows this cannot represent (splits, mergers, kinds not seen before).
    needs_a_look: List[ReportRow] = field(default_factory=list)

    @property
    def new_days(self) -> Dict[date, int]:
        days: Counter = Counter()
        for row, _ in self.trades:
            days[row.traded] += 1
        for row, _ in self.cash:
            days[row.traded] += 1
        return dict(sorted(days.items()))


# ----------------------------------------------------------------------
# Reading the file
# ----------------------------------------------------------------------


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value) -> Optional[Decimal]:
    """``$1,000.0000``, ``-$5.10``, ``2,358.0000``; ``Free``, ``—`` and blank are none."""
    text = re.sub(r"\s", "", _text(value)).replace("$", "").replace(",", "")
    if text in ("", "—", "-", "Free"):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        raise ReportError(f"not a number: {value!r}") from None


def _day(value) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%m/%d/%Y").date()
    except ValueError:
        return None


def read_report(path: Path) -> List[ReportRow]:
    """The report's rows, from Vanguard's Excel download."""
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover - listed in requirements
        raise ReportError("openpyxl is needed to read the report") from exc
    try:
        sheet = load_workbook(path, read_only=True, data_only=True).active
    except Exception as exc:  # noqa: BLE001
        raise ReportError(f"cannot open {path.name} as an Excel file") from exc
    return parse_rows(list(sheet.iter_rows(values_only=True)))


def parse_rows(cells: List[tuple]) -> List[ReportRow]:
    """Rows of the sheet below its header line; notes and blank lines are passed over."""
    header_at = next(
        (
            i
            for i, row in enumerate(cells)
            if row and "Trade date" in [_text(c) for c in row]
        ),
        None,
    )
    if header_at is None:
        raise ReportError("no 'Trade date' header: is this Vanguard's activity report?")
    names = [_text(c) for c in cells[header_at]]

    def column(*options: str) -> int:
        for option in options:
            for i, name in enumerate(names):
                if name.lower().startswith(option.lower()):
                    return i
        raise ReportError(f"the report has no '{options[0]}' column")

    at = {
        "settled": column("Settlement date"),
        "traded": column("Trade date"),
        "symbol": column("Symbol"),
        "name": column("Name"),
        "kind": column("Transaction type", "Type"),
        "account_type": column("Account type"),
        "quantity": column("Quantity"),
        "price": column("Price"),
        "fees": column("Commission"),
        "amount": column("Amount"),
    }
    rows = []
    for offset, cells_row in enumerate(cells[header_at + 1 :], start=header_at + 2):
        if not cells_row:
            continue
        cell = lambda key: cells_row[at[key]] if at[key] < len(cells_row) else None  # noqa: E731
        traded = _day(cell("traded"))
        if traded is None:
            continue  # notes at the foot of the sheet
        symbol = _text(cell("symbol"))
        rows.append(
            ReportRow(
                line=offset,
                traded=traded,
                settled=_day(cell("settled")),
                symbol="" if symbol in ("—", "-") else symbol,
                name=_text(cell("name")),
                kind=_text(cell("kind")),
                account_type=_text(cell("account_type")),
                quantity=_number(cell("quantity")),
                price=_number(cell("price")),
                fees=_number(cell("fees")) or Decimal(0),
                amount=_number(cell("amount")),
            )
        )
    return rows


# ----------------------------------------------------------------------
# Reading the rows
# ----------------------------------------------------------------------


def _security_type(row: ReportRow) -> str:
    if is_option_symbol(row.symbol):
        return "OPTION"
    name = row.name.upper()
    if "ETF" in name.split() or name.endswith("ETF"):
        return "ETF"
    if "ADR" in name.split():
        return "ADR"
    return "STOCK"


def _at(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=timezone.utc)


def _internal_transfers(rows: List[ReportRow]) -> set:
    """Lines of transfer pairs within the account: the same amount moving between
    its cash and margin sides on one day. No money arrives or leaves."""
    paired = set()
    by_day: Dict[date, List[ReportRow]] = defaultdict(list)
    for row in rows:
        if row.kind in _TRANSFERS and row.amount is not None:
            by_day[row.traded].append(row)
    for day_rows in by_day.values():
        for row in day_rows:
            if row.line in paired or row.amount <= 0:
                continue
            twin = next(
                (
                    other
                    for other in day_rows
                    if other.line not in paired
                    and other.amount == -row.amount
                    and other.account_type != row.account_type
                ),
                None,
            )
            if twin is not None:
                paired |= {row.line, twin.line}
    return paired


def _external_id(row: ReportRow, occurrence: int) -> str:
    """Stable across files that overlap: the row's content and its place among
    identical rows on the same day."""
    content = "|".join(
        str(part)
        for part in (
            row.traded,
            row.kind,
            row.account_type,
            row.symbol,
            row.quantity,
            row.price,
            row.amount,
            occurrence,
        )
    )
    return ID_PREFIX + hashlib.sha1(content.encode()).hexdigest()[:24]


def read_rows(rows: List[ReportRow]) -> Tuple[list, list, Counter, List[ReportRow]]:
    """Trades and cash rows as the app holds them, with what was set aside."""
    trades: List[Tuple[ReportRow, NormalizedTrade]] = []
    cash: List[Tuple[ReportRow, NormalizedCashActivity]] = []
    skipped: Counter = Counter()
    needs_a_look: List[ReportRow] = []
    internal = _internal_transfers(rows)
    seen: Counter = Counter()

    for row in rows:
        signature = (row.traded, row.kind, row.account_type, row.symbol,
                     row.quantity, row.price, row.amount)
        seen[signature] += 1
        ext = _external_id(row, seen[signature])

        if row.kind in SWEEPS:
            skipped["sweep"] += 1
        elif row.line in internal:
            skipped["internal transfer"] += 1
        elif row.kind in TRADE_KINDS or (row.kind == "Reinvestment" and row.quantity):
            if not row.symbol or not row.quantity or row.price is None:
                needs_a_look.append(row)
                continue
            option = is_option_symbol(row.symbol)
            action = TRADE_KINDS.get(row.kind, TradeAction.BUY)
            notes = row.name
            if row.kind == "Reinvestment":
                notes = f"Dividend reinvestment: {row.name}"
            trades.append(
                (
                    row,
                    NormalizedTrade(
                        external_id=ext,
                        symbol=row.symbol,
                        action=action,
                        quantity=abs(row.quantity),
                        price=row.price * (_OPTION_MULTIPLIER if option else 1),
                        executed_at=_at(row.traded),
                        commission=row.fees,
                        source=SOURCE,
                        security_type=_security_type(row),
                        notes=notes,
                    ),
                )
            )
        elif row.kind in OPTION_EVENTS:
            if not row.symbol or not row.quantity:
                needs_a_look.append(row)
                continue
            # A written contract closes as a buy, a held one as a sale; the
            # shares that changed hands are rows of their own.
            trades.append(
                (
                    row,
                    NormalizedTrade(
                        external_id=ext,
                        symbol=row.symbol,
                        action=TradeAction.BUY if row.quantity > 0 else TradeAction.SELL,
                        quantity=abs(row.quantity),
                        price=Decimal(0),
                        executed_at=_at(row.traded),
                        source=SOURCE,
                        security_type="OPTION",
                        notes=f"{OPTION_EVENTS[row.kind]} {row.name}",
                    ),
                )
            )
        elif row.kind == "Reinvestment":
            skipped["sweep"] += 1  # the settlement fund's own dividend, kept as cash
        elif row.kind in CASH_KINDS:
            if row.amount is None:
                needs_a_look.append(row)
                continue
            cash_type, _ = CASH_KINDS[row.kind]
            cash.append(
                (
                    row,
                    NormalizedCashActivity(
                        external_id=ext,
                        type=cash_type,
                        amount=row.amount,
                        occurred_at=_at(row.traded),
                        symbol=row.symbol or None,
                        source=SOURCE,
                        notes=row.kind if not row.symbol else f"{row.kind}: {row.name}",
                    ),
                )
            )
        else:
            needs_a_look.append(row)
    return trades, cash, skipped, needs_a_look


# ----------------------------------------------------------------------
# What is already on file
# ----------------------------------------------------------------------


def _business_days_apart(a: date, b: date) -> int:
    lo, hi = sorted((a, b))
    days, current = 0, lo
    while current < hi:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def _same_price(ours: Decimal, theirs: Decimal, multiplier: Decimal) -> bool:
    tolerance = _CENT * multiplier + _PRICE_SHARE * abs(theirs)
    return abs(Decimal(str(ours)) - theirs) <= tolerance


class VanguardReportImport:
    """Plans and applies one report against one brokerage account."""

    def __init__(self, db: Session, connection_service):
        self.db = db
        self.connections = connection_service

    def account_sleeves(self, ba: BrokerageAccount) -> List[str]:
        return [
            row[0]
            for row in self.db.query(Sleeve.id).filter(Sleeve.account_id == ba.account_id)
        ]

    def plan(
        self,
        ba: BrokerageAccount,
        rows: List[ReportRow],
        start: Optional[date] = None,
        end: Optional[date] = None,
    ) -> Plan:
        rows = [
            r
            for r in rows
            if (start is None or r.traded >= start) and (end is None or r.traded <= end)
        ]
        plan = Plan(rows=len(rows))
        if rows:
            plan.first = min(r.traded for r in rows)
            plan.last = max(r.traded for r in rows)
        trades, cash, plan.skipped, plan.needs_a_look = read_rows(rows)

        sleeve_ids = self.account_sleeves(ba)
        # An opening position is not a transaction: a row is never matched to one.
        on_file = (
            self.db.query(Trade).filter(Trade.sleeve_id.in_(sleeve_ids), NOT_OPENING).all()
            if sleeve_ids
            else []
        )
        used: set = set()

        def find(trade: NormalizedTrade, near: bool, any_symbol: bool) -> Optional[Trade]:
            multiplier = _OPTION_MULTIPLIER if trade.security_type == "OPTION" else 1
            day = trade.executed_at.date()
            for ours in on_file:
                if ours.id in used or ours.action != trade.action.value:
                    continue
                if abs(Decimal(str(ours.quantity)) - trade.quantity) > _QUANTITY:
                    continue
                if not _same_price(ours.price, trade.price, Decimal(multiplier)):
                    continue
                if not any_symbol and app_symbol(ours.symbol) != app_symbol(trade.symbol):
                    continue
                if near:
                    if _business_days_apart(ours.trade_date, day) > _LOOSE_WEEKDAYS:
                        continue
                elif ours.trade_date != day:
                    continue
                return ours
            return None

        # Strictest first, so a looser pass never takes a row a stricter one
        # would have matched: the same day and symbol; the same symbol a day or
        # two apart; then another spelling of the symbol. An expiry or an
        # assignment carries no price, so it is matched on its own contract only.
        pending = list(trades)
        for near, any_symbol in ((False, False), (True, False), (True, True)):
            left = []
            for row, trade in pending:
                if any_symbol and trade.price == 0:
                    left.append((row, trade))
                    continue
                ours = find(trade, near, any_symbol)
                if ours is None:
                    left.append((row, trade))
                    continue
                used.add(ours.id)
                plan.held_trades += 1
                if near:
                    plan.loose_matches.append(
                        (row, {"date": ours.trade_date.isoformat(), "symbol": ours.symbol})
                    )
            pending = left
        plan.trades.extend(pending)

        cash_on_file = (
            self.db.query(CashActivity).filter(CashActivity.sleeve_id.in_(sleeve_ids)).all()
            if sleeve_ids
            else []
        )
        used_cash: set = set()
        for row, activity in cash:
            match = next(
                (
                    ours
                    for ours in cash_on_file
                    if ours.id not in used_cash
                    and abs(Decimal(str(ours.amount)) - activity.amount) < Decimal("0.005")
                    and abs((ours.activity_date - row.traded).days) <= _CASH_DAYS
                ),
                None,
            )
            if match is None:
                plan.cash.append((row, activity))
            else:
                used_cash.add(match.id)
                plan.held_cash += 1
        return plan

    def apply(
        self, ba: BrokerageAccount, plan: Plan, holdings: Optional[list] = None
    ) -> Dict:
        """Add the plan's rows, keep them as source rows, and bring the account's
        positions, cash history and daily record up to date. ``holdings``, the
        custodian's last recorded holdings, refreshes the reconciliation."""
        raw = []
        for row, trade in plan.trades:
            raw.append(self._raw(row, trade.external_id, row.amount or Decimal(0), False))
        for row, activity in plan.cash:
            external = CASH_KINDS[row.kind][1]
            raw.append(self._raw(row, activity.external_id, activity.amount, external))
        batch = ActivityBatch(
            trades=[t for _, t in plan.trades],
            cash=[c for _, c in plan.cash],
            raw=raw,
            skipped={},
            security_type_sources={},
        )
        return self.connections.ingest_batch(ba, batch, holdings=holdings)

    @staticmethod
    def _raw(row: ReportRow, ext: str, cash_amount: Decimal, external: bool) -> RawActivity:
        return RawActivity(
            source_id=ext,
            type=f"VANGUARD REPORT {row.kind}".upper()[:50],
            occurred_on=row.traded,
            symbol=row.symbol or None,
            outcome="trade" if row.kind not in CASH_KINDS else "cash",
            cash_amount=cash_amount,
            is_external_flow=external,
            payload=row.as_dict(),
        )
