"""Upload and import: a file from the custodian, read and added to one account.

One path for every way in (the client's portal, the advisor's account page and
the command line): read the file, show what would change, and only on a second
request write it. Nothing in a preview is kept, so the import reads the file
again and acts on what it finds then.

Files understood:
- Vanguard's activity report, downloaded as Excel or CSV;
- Achalara's own template (CSV): Date, Type, Symbol, Quantity, Price, Fees,
  Amount, for any other institution.

The file itself is never stored; the rows it adds are, as a sync's are.
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connectors.models import NormalizedPosition, is_option_symbol
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount
from app.models.perf import DailyHolding, DailyValuation
from app.models.sleeve import Sleeve
from app.models.trade import Trade
from app.services.corporate_actions import adjusted_trades
from app.services.connection_service import ConnectionService
from app.services.vanguard_report import (
    Plan,
    ReportError,
    ReportRow,
    VanguardReportImport,
    parse_rows,
    _number,
)

# Larger than any activity report seen (four years of a busy account is 0.5 MB).
MAX_FILE_BYTES = 5 * 1024 * 1024
_KINDS = ("xlsx", "csv")

# Achalara's template: its types, and the report's names for them.
TEMPLATE_COLUMNS = ("Date", "Type", "Symbol", "Quantity", "Price", "Fees", "Amount")
TEMPLATE_TYPES = {
    "buy": "Buy",
    "sell": "Sell",
    "reinvestment": "Reinvestment",
    "dividend": "Dividend",
    "interest": "Interest",
    "fee": "Fee",
    "tax withheld": "Withholding",
    "deposit": "Funds Received",
    "withdrawal": "Withdrawal",
    "transfer in": "Transfer (incoming)",
    "transfer out": "Transfer (Outgoing)",
}


# Share counts within this of each other agree (rounding of fractional shares).
_AGREE = Decimal("0.01")


def _compared(symbol: str) -> bool:
    """Whether a holding is compared with the custodian's record. Options are
    never listed there, nor is anything the feed names by its company with a
    leading "~": a security that no longer trades (taken over, delisted)."""
    return not is_option_symbol(symbol) and not symbol.startswith("~")


def _apply(position: Dict[str, Decimal], trade) -> None:
    signed = trade.quantity if trade.action == "BUY" else -trade.quantity
    position[trade.symbol] = position.get(trade.symbol, Decimal(0)) + Decimal(str(signed))


class AccountImportError(Exception):
    """A request that cannot be met, with the status a route should answer."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# ----------------------------------------------------------------------
# Reading an upload
# ----------------------------------------------------------------------


def _cells(filename: str, content: bytes) -> List[tuple]:
    kind = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if kind not in _KINDS:
        raise AccountImportError(
            415, "Upload the report as Excel (.xlsx) or CSV (.csv)."
        )
    if len(content) > MAX_FILE_BYTES:
        raise AccountImportError(413, "The file is larger than 5 MB.")
    if kind == "xlsx":
        from openpyxl import load_workbook

        try:
            sheet = load_workbook(
                io.BytesIO(content), read_only=True, data_only=True
            ).active
        except Exception:  # noqa: BLE001
            raise AccountImportError(422, "This file could not be opened as Excel.")
        return list(sheet.iter_rows(values_only=True))
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    return [tuple(row) for row in csv.reader(io.StringIO(text))]


def _template_rows(cells: List[tuple]) -> List[ReportRow]:
    """Achalara's template, as the report's rows."""
    names = [str(c or "").strip().lower() for c in cells[0]]
    missing = [c for c in ("Date", "Type") if c.lower() not in names]
    if missing:
        raise AccountImportError(
            422,
            "This file is neither a Vanguard activity report nor Achalara's template "
            f"(columns {', '.join(TEMPLATE_COLUMNS)}).",
        )
    at = {name: names.index(name.lower()) for name in TEMPLATE_COLUMNS if name.lower() in names}
    rows = []
    for line, row in enumerate(cells[1:], start=2):
        value = lambda name: (  # noqa: E731
            str(row[at[name]]).strip() if name in at and at[name] < len(row) and row[at[name]] is not None else ""
        )
        if not any(str(c or "").strip() for c in row):
            continue
        try:
            traded = _template_day(value("Date"))
        except ValueError:
            raise AccountImportError(422, f"Line {line}: the date {value('Date')!r} is not a date.")
        kind = TEMPLATE_TYPES.get(value("Type").lower())
        if kind is None:
            raise AccountImportError(
                422,
                f"Line {line}: the type {value('Type')!r} is not one of "
                f"{', '.join(t.capitalize() for t in TEMPLATE_TYPES)}.",
            )
        try:
            quantity, price = _number(value("Quantity")), _number(value("Price"))
            fees, amount = _number(value("Fees")) or Decimal(0), _number(value("Amount"))
        except ReportError:
            raise AccountImportError(422, f"Line {line}: a number could not be read.")
        if kind in ("Buy", "Sell", "Reinvestment"):
            if not value("Symbol") or not quantity or price is None:
                raise AccountImportError(
                    422, f"Line {line}: a trade needs a symbol, a quantity and a price."
                )
            quantity = abs(quantity) if kind != "Sell" else -abs(quantity)
            if amount is None:
                gross = abs(quantity) * price
                amount = -(gross + fees) if kind != "Sell" else gross - fees
        elif amount is None:
            raise AccountImportError(422, f"Line {line}: a {value('Type')} needs an amount.")
        rows.append(
            ReportRow(
                line=line,
                traded=traded,
                settled=None,
                symbol=value("Symbol").upper(),
                name=value("Symbol") or "CASH",
                kind=kind,
                account_type="CASH" if kind not in ("Buy", "Sell", "Reinvestment") else "MARGIN",
                quantity=quantity,
                price=price,
                fees=fees,
                amount=amount,
            )
        )
    return rows


def _template_day(text: str) -> date:
    for pattern in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise ValueError(text)


def read_upload(filename: str, content: bytes) -> Tuple[str, List[ReportRow]]:
    """The file's rows and which kind of file it was."""
    cells = _cells(filename, content)
    if not cells:
        raise AccountImportError(422, "The file is empty.")
    is_report = any(
        row and "Trade date" in [str(c or "").strip() for c in row] for row in cells[:20]
    )
    if is_report:
        try:
            return "vanguard_activity", parse_rows(cells)
        except ReportError as error:
            raise AccountImportError(422, str(error))
    return "template", _template_rows(cells)


# ----------------------------------------------------------------------
# Importing into an account
# ----------------------------------------------------------------------


class AccountImportService:
    """Preview and import one uploaded file into one account."""

    def __init__(self, db: Session):
        self.db = db
        self.connections = ConnectionService(db, connector=object())
        self.importer = VanguardReportImport(db, self.connections)

    def _feed(self, account: Account) -> BrokerageAccount:
        ba = (
            self.db.query(BrokerageAccount)
            .filter(
                BrokerageAccount.account_id == account.id,
                BrokerageAccount.status == "mapped",
            )
            .first()
        )
        if ba is None or not ba.default_sleeve_id:
            raise AccountImportError(
                409, "This account is not set up to take files yet."
            )
        return ba

    @staticmethod
    def _check_names_account(filename: str, ba: BrokerageAccount, account: Account) -> None:
        """Vanguard names its download after the account's number: refuse a file
        that names a different account."""
        named = re.findall(r"\d{6,}", filename)
        if not named:
            return
        ours = "".join(ch for ch in f"{ba.name} {account.account_number or ''}" if ch.isdigit())
        if not any(number in ours for number in named):
            raise AccountImportError(
                422, f"This file is for the account ending {named[0][-4:]}, not this one."
            )

    def _plan(
        self, account: Account, filename: str, content: bytes
    ) -> Tuple[BrokerageAccount, str, Plan]:
        ba = self._feed(account)
        kind, rows = read_upload(filename, content)
        if kind == "vanguard_activity":
            self._check_names_account(filename, ba, account)
        if not rows:
            raise AccountImportError(422, "The file has no rows to read.")
        return ba, kind, self.importer.plan(ba, rows)

    def preview(self, account: Account, filename: str, content: bytes) -> Dict:
        _, kind, plan = self._plan(account, filename, content)
        return self._summary(account, kind, plan)

    def apply(self, account: Account, filename: str, content: bytes) -> Dict:
        ba, kind, plan = self._plan(account, filename, content)
        summary = self._summary(account, kind, plan)
        if plan.trades or plan.cash:
            result = self.importer.apply(ba, plan, self.last_holdings(account.id))
            summary["added_trades"] = result["imported"]
            summary["added_cash"] = result["cash_imported"]
        else:
            summary["added_trades"] = summary["added_cash"] = 0
        summary["check"] = self._check(ba, account)
        return summary

    # ------------------------------------------------------------------

    def last_holdings(self, account_id: str) -> Optional[List[NormalizedPosition]]:
        """The custodian's holdings on the last day they were recorded, or None."""
        last = (
            self.db.query(func.max(DailyHolding.as_of_date))
            .filter(DailyHolding.account_id == account_id)
            .scalar()
        )
        if last is None:
            return None
        return [
            NormalizedPosition(
                symbol=h.symbol,
                quantity=Decimal(str(h.quantity)),
                avg_cost=Decimal(str(h.avg_cost or 0)),
                market_price=Decimal(str(h.price)) if h.price is not None else None,
            )
            for h in self.db.query(DailyHolding).filter(
                DailyHolding.account_id == account_id, DailyHolding.as_of_date == last
            )
        ]

    def _check(self, ba: BrokerageAccount, account: Account) -> Optional[Dict]:
        """Our holdings against the custodian's last recorded ones, symbol by symbol."""
        last = (
            self.db.query(func.max(DailyHolding.as_of_date))
            .filter(DailyHolding.account_id == account.id)
            .scalar()
        )
        if last is None:
            return None
        self.db.refresh(ba)
        report = ba.reconciliation or {}
        last_agreed, first_differed = self._agreement(account)
        return {
            "as_of": last,
            "matched": report.get("matched", 0),
            "last_agreed": last_agreed,
            "first_differed": first_differed,
            "differences": [
                {
                    "symbol": row["symbol"],
                    "custodian_quantity": row["brokerage_quantity"],
                    "our_quantity": row["derived_quantity"],
                }
                for row in report.get("drifted", [])
                if _compared(row["symbol"])
            ],
        }

    def _agreement(self, account: Account) -> Tuple[Optional[date], Optional[date]]:
        """When our holdings last agreed with the custodian's record, and the first
        recorded day they differed after that (None while they agree now).

        Every day the custodian listed holdings is compared with what our trades
        add up to, symbol by symbol (options aside: the record never lists them).
        A record may or may not include that day's own trades, so it agrees if it
        matches either. A reported day that listed nothing means nothing was held.
        """
        sleeve_ids = [
            row[0] for row in self.db.query(Sleeve.id).filter(Sleeve.account_id == account.id)
        ]
        recorded: Dict[date, Dict[str, Decimal]] = defaultdict(dict)
        for day, symbol, quantity in self.db.query(
            DailyHolding.as_of_date, DailyHolding.symbol, DailyHolding.quantity
        ).filter(DailyHolding.account_id == account.id):
            if _compared(symbol):
                held = recorded[day]
                held[symbol] = held.get(symbol, Decimal(0)) + Decimal(str(quantity))
        if not recorded:
            return None, None
        first_listed = min(recorded)
        for (day,) in self.db.query(DailyValuation.as_of_date).filter(
            DailyValuation.account_id == account.id,
            DailyValuation.sleeve_id.is_(None),
            DailyValuation.basis == "observed",
            DailyValuation.as_of_date > first_listed,
        ):
            recorded.setdefault(day, {})

        trades = sorted(
            (
                t
                for t in adjusted_trades(
                    self.db,
                    self.db.query(Trade).filter(Trade.sleeve_id.in_(sleeve_ids)).all()
                    if sleeve_ids
                    else [],
                )
                if _compared(t.symbol)
            ),
            key=lambda t: t.trade_date,
        )

        def same(ours: Dict[str, Decimal], theirs: Dict[str, Decimal]) -> bool:
            return all(
                abs(ours.get(s, Decimal(0)) - theirs.get(s, Decimal(0))) <= _AGREE
                for s in set(ours) | set(theirs)
            )

        position: Dict[str, Decimal] = {}
        at = 0
        last_agreed = first_differed = None
        for day in sorted(recorded):
            while at < len(trades) and trades[at].trade_date < day:
                _apply(position, trades[at])
                at += 1
            before = dict(position)
            through = dict(position)
            later = at
            while later < len(trades) and trades[later].trade_date == day:
                _apply(through, trades[later])
                later += 1
            if same(before, recorded[day]) or same(through, recorded[day]):
                last_agreed, first_differed = day, None
            elif first_differed is None:
                first_differed = day
        return last_agreed, first_differed

    @staticmethod
    def _summary(account: Account, kind: str, plan: Plan) -> Dict:
        moved = [m for r, m in plan.loose_matches if m["date"] != r.traded.isoformat()]
        renamed = len(plan.loose_matches) - len(moved)
        days = []
        for day in plan.new_days:
            days.append(
                {
                    "date": day,
                    "trades": [
                        {
                            "action": t.action.value,
                            "symbol": t.symbol,
                            "quantity": float(t.quantity),
                            "price": float(t.price),
                        }
                        for r, t in plan.trades
                        if r.traded == day
                    ],
                    "cash": [
                        {"type": c.type, "symbol": c.symbol, "amount": float(c.amount)}
                        for r, c in plan.cash
                        if r.traded == day
                    ],
                }
            )
        return {
            "account_id": account.id,
            "file_kind": kind,
            "rows": plan.rows,
            "first_date": plan.first,
            "last_date": plan.last,
            "on_file_trades": plan.held_trades,
            "on_file_cash": plan.held_cash,
            "on_file_a_day_later": len(moved),
            "on_file_other_symbol": renamed,
            "set_aside": dict(plan.skipped),
            "to_add_trades": len(plan.trades),
            "to_add_cash": len(plan.cash),
            "days": days,
            "not_read": [
                {
                    "line": r.line,
                    "date": r.traded,
                    "type": r.kind,
                    "symbol": r.symbol or r.name,
                }
                for r in plan.needs_a_look
            ],
        }
