"""Plaid's replies, read as the app's own rows.

Pure functions: no database, no network. What was learned comparing Plaid with
Vanguard (November 2026) is built in:

- Plaid dates a buy or sale by its settlement: it is moved back one weekday to
  the trade day. Reinvestments, assignments and expiries keep Plaid's date.
- Holdings come priced at the previous close although dated today; each one is
  valued at its security's own ``close_price`` instead, and the account's total
  moves by the same amount.
- The same amount moving in and out on one day between an account's cash and
  margin sides is a move within the account, not money in or out.
- Cash held in a settlement fund (a security of type ``cash``) is cash: buying
  or selling it is a sweep, not a trade.

Every row Plaid sent is also returned as a ``RawActivity`` with what was done
with it, so a rule can be changed and the rows read again without asking Plaid.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from app.connectors.models import (
    ActivityBatch,
    NormalizedCashActivity,
    NormalizedPosition,
    NormalizedTrade,
    RawActivity,
    TradeAction,
    is_option_symbol,
)
from app.models.cash_activity import MARGIN_INTEREST
from app.services.corporate_actions import ASSIGNMENT_NOTE, EXPIRY_NOTE

SOURCE = "plaid"
ID_PREFIX = "plaid:"
_MULTIPLIER = Decimal(100)
SECURITY_TYPES = {
    "equity": "STOCK",
    "etf": "ETF",
    "mutual fund": "MUTUAL_FUND",
    "derivative": "OPTION",
    "fixed income": "OTHER",
}

# Plaid's investment transaction subtypes that are cash rows, and our type for
# each, with whether the money came from outside the account.
_CASH_SUBTYPES = {
    **{s: ("DIVIDEND", False) for s in (
        "dividend", "qualified dividend", "non-qualified dividend", "long-term capital gain",
        "short-term capital gain", "unqualified gain", "return of principal",
    )},
    **{s: ("INTEREST", False) for s in ("interest", "interest receivable")},
    **{s: ("FEE", False) for s in (
        "account fee", "fund fee", "legal fee", "management fee", "miscellaneous fee",
        "transfer fee", "trust fee",
    )},
    **{s: ("WITHHOLDING", False) for s in ("tax", "tax withheld", "non-resident tax")},
    "margin expense": (MARGIN_INTEREST, False),
    "deposit": ("CONTRIBUTION", True),
    "contribution": ("CONTRIBUTION", True),
    "withdrawal": ("WITHDRAWAL", True),
    "loan payment": ("WITHDRAWAL", True),
    "transfer": ("TRANSFER", True),
    "send": ("TRANSFER", True),
    "request": ("TRANSFER", True),
}
_REINVEST = ("reinvestment",)  # "dividend reinvestment", "interest reinvestment", …
_EVENTS = {"assignment": ASSIGNMENT_NOTE, "expire": EXPIRY_NOTE}


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _at(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=timezone.utc)


def _day(value) -> date:
    return date.fromisoformat(str(value)[:10])


def _money(value) -> Decimal:
    return Decimal(str(value or 0))


def option_symbol(security: Dict) -> Optional[str]:
    """An option's contract symbol (``ABC270115P00020000``), from Plaid's ticker
    where it is one already, else from its contract fields."""
    ticker = security.get("ticker_symbol") or ""
    if is_option_symbol(ticker):
        return ticker
    contract = security.get("option_contract") or {}
    if contract.get("underlying_security_ticker") and contract.get("expiration_date"):
        y, m, d = str(contract["expiration_date"])[:10].split("-")
        kind = str(contract.get("contract_type", "")).upper()[:1]
        strike = int(Decimal(str(contract.get("strike_price"))) * 1000)
        return f"{contract['underlying_security_ticker']}{y[2:]}{m}{d}{kind}{strike:08d}"
    return None


# ----------------------------------------------------------------------
# Investment transactions
# ----------------------------------------------------------------------


def read_investment_transactions(
    rows: List[Dict], securities: Dict[str, Dict], after: Optional[date] = None
) -> ActivityBatch:
    """One account's investment transactions as trades and cash rows. Rows dated
    on or before ``after`` are left out (already on file from another source)."""
    trades: List[NormalizedTrade] = []
    cash: List[NormalizedCashActivity] = []
    raw: List[RawActivity] = []
    skipped: Counter = Counter()

    for t in sorted(rows, key=lambda r: str(r.get("date"))):
        security = securities.get(t.get("security_id") or "", {})
        kind = (t.get("type") or "").lower()
        subtype = (t.get("subtype") or "").lower()
        name = t.get("name") or ""
        ticker = security.get("ticker_symbol")
        is_cash_security = security.get("type") == "cash" or security.get("is_cash_equivalent")
        holder = -_money(t.get("amount"))  # Plaid: positive is money out
        reinvest = any(word in subtype for word in _REINVEST) or name.startswith("Reinvestment")
        posted = _day(t.get("date"))
        day = previous_weekday(posted) if kind in ("buy", "sell") and not reinvest else posted
        if after is not None and day <= after:
            continue
        ext = ID_PREFIX + str(t["investment_transaction_id"])
        outcome, external, cash_amount = "skipped:unrecognized", False, Decimal(0)

        if name.startswith(("Sweep in", "Sweep out")) or (
            kind in ("buy", "sell") and is_cash_security
        ):
            outcome = "skipped:sweep"
        elif kind in ("buy", "sell") or (kind == "transfer" and subtype in _EVENTS):
            option = security.get("type") == "derivative"
            symbol = option_symbol(security) if option else ticker
            quantity = abs(_money(t.get("quantity")))
            if not symbol or quantity == 0:
                outcome = "skipped:unreadable"
            else:
                if subtype in _EVENTS:
                    action = TradeAction.BUY if _money(t.get("quantity")) > 0 else TradeAction.SELL
                    price, fees = Decimal(0), Decimal(0)
                    notes = f"{_EVENTS[subtype]} {security.get('name', '')}".strip()
                else:
                    action = TradeAction.BUY if kind == "buy" else TradeAction.SELL
                    price = _money(t.get("price")) * (_MULTIPLIER if option else 1)
                    fees = _money(t.get("fees"))
                    notes = (
                        f"Dividend reinvestment: {security.get('name', '')}"
                        if reinvest
                        else security.get("name", "")
                    )
                trades.append(
                    NormalizedTrade(
                        external_id=ext, symbol=symbol, action=action, quantity=quantity,
                        price=price, executed_at=_at(day), commission=fees, source=SOURCE,
                        security_type=SECURITY_TYPES.get(security.get("type") or "", "OTHER"),
                        notes=notes,
                    )
                )
                outcome, cash_amount = "trade", holder
        elif kind in ("cash", "fee", "transfer") and subtype in _CASH_SUBTYPES:
            cash_type, external = _CASH_SUBTYPES[subtype]
            if is_cash_security and cash_type in ("DIVIDEND", "INTEREST") and reinvest:
                outcome = "skipped:sweep"
            else:
                cash.append(
                    NormalizedCashActivity(
                        external_id=ext, type=cash_type, amount=holder, occurred_at=_at(day),
                        symbol=None if not ticker or ticker.startswith("CUR:") else ticker,
                        source=SOURCE, notes=name,
                    )
                )
                outcome, cash_amount = "cash", holder

        if outcome.startswith("skipped"):
            skipped[outcome.split(":", 1)[1]] += 1
        raw.append(
            RawActivity(
                source_id=ext, type=f"PLAID {kind}/{subtype}".upper()[:50], occurred_on=day,
                symbol=ticker, outcome=outcome, cash_amount=cash_amount,
                is_external_flow=external, payload=t,
            )
        )

    return _drop_internal_transfers(
        ActivityBatch(trades=trades, cash=cash, raw=raw, skipped=dict(skipped),
                      security_type_sources={})
    )


def _drop_internal_transfers(batch: ActivityBatch) -> ActivityBatch:
    """Same-day transfers of the same amount in and out are a move within the
    account: neither activity nor money in or out."""
    internal = set()
    transfers = [c for c in batch.cash if c.type == "TRANSFER"]
    for c in transfers:
        if c.external_id in internal or c.amount <= 0:
            continue
        twin = next(
            (o for o in transfers if o.external_id not in internal and o.external_id != c.external_id
             and o.occurred_at == c.occurred_at and o.amount == -c.amount),
            None,
        )
        if twin is not None:
            internal |= {c.external_id, twin.external_id}
    if not internal:
        return batch
    skipped = Counter(batch.skipped)
    skipped["internal transfer"] += len(internal)
    for r in batch.raw:
        if r.source_id in internal:
            r.outcome, r.cash_amount, r.is_external_flow = "skipped:internal transfer", Decimal(0), False
    return ActivityBatch(
        trades=batch.trades,
        cash=[c for c in batch.cash if c.external_id not in internal],
        raw=batch.raw,
        skipped=dict(skipped),
        security_type_sources={},
    )


# ----------------------------------------------------------------------
# Bank and card transactions
# ----------------------------------------------------------------------


def read_bank_transactions(rows: List[Dict], after: Optional[date] = None) -> ActivityBatch:
    """A bank or card account's transactions as money movements. Pending ones
    are left for when they post. Interest and bank fees are their own types."""
    cash: List[NormalizedCashActivity] = []
    raw: List[RawActivity] = []
    skipped: Counter = Counter()
    for t in sorted(rows, key=lambda r: str(r.get("date"))):
        if t.get("pending"):
            skipped["pending"] += 1
            continue
        day = _day(t.get("date"))
        if after is not None and day <= after:
            continue
        holder = -_money(t.get("amount"))
        category = t.get("personal_finance_category") or {}
        detailed = str(category.get("detailed") or "").upper()
        primary = str(category.get("primary") or "").upper()
        if detailed.startswith("INCOME_INTEREST"):
            kind, external = "INTEREST", False
        elif primary == "BANK_FEES":
            kind, external = "FEE", False
        else:
            kind, external = ("CONTRIBUTION" if holder > 0 else "WITHDRAWAL"), True
        ext = ID_PREFIX + str(t["transaction_id"])
        description = t.get("merchant_name") or t.get("name") or ""
        cash.append(
            NormalizedCashActivity(
                external_id=ext, type=kind, amount=holder, occurred_at=_at(day),
                source=SOURCE, notes=description,
            )
        )
        raw.append(
            RawActivity(
                source_id=ext, type=f"PLAID BANK {primary or 'OTHER'}"[:50], occurred_on=day,
                outcome="cash", cash_amount=holder, is_external_flow=external, payload=t,
            )
        )
    return ActivityBatch(trades=[], cash=cash, raw=raw, skipped=dict(skipped),
                         security_type_sources={})


# ----------------------------------------------------------------------
# Holdings and balances
# ----------------------------------------------------------------------


@dataclass
class DayFigures:
    """One account's day as the institution reports it, ready to record."""

    day: Optional[date]
    positions: List[NormalizedPosition] = field(default_factory=list)
    cash: Decimal = Decimal(0)
    total: Decimal = Decimal(0)


def read_holdings(account: Dict, holdings: List[Dict], securities: Dict[str, Dict]) -> DayFigures:
    """An investment account's holdings, cash and total, each holding at its
    security's own close and the total moved by the same amount. Options are
    valued in the total but not listed, as the institution's record lists none."""
    held = [h for h in holdings if h.get("account_id") == account["account_id"]]
    listed_cash = [
        _money(h.get("institution_value"))
        for h in held
        if securities.get(h["security_id"], {}).get("type") == "cash"
    ]
    positions: List[NormalizedPosition] = []
    days: List[date] = []
    moved = Decimal(0)
    others = Decimal(0)
    for h in held:
        security = securities.get(h["security_id"], {})
        if security.get("type") == "cash":
            continue
        quantity = _money(h.get("quantity"))
        price = _money(h.get("institution_price"))
        value = _money(h.get("institution_value"))
        others += value
        close = security.get("close_price")
        if close is not None and security.get("close_price_as_of"):
            per_unit = value / (quantity * price) if quantity and price else Decimal(1)
            moved += (quantity * _money(close) * per_unit).quantize(Decimal("0.01")) - value
            price = _money(close)
            if security.get("type") != "derivative":
                days.append(_day(security["close_price_as_of"]))
        if security.get("type") == "derivative" or not security.get("ticker_symbol"):
            continue
        cost = _money(h.get("cost_basis")) / quantity if h.get("cost_basis") is not None and quantity else Decimal(0)
        positions.append(
            NormalizedPosition(
                symbol=security["ticker_symbol"], quantity=quantity, avg_cost=cost, market_price=price,
                security_type=SECURITY_TYPES.get(security.get("type") or "", "OTHER"),
            )
        )
    total = _money((account.get("balances") or {}).get("current")) + moved
    # The cash holding where one is listed (the settlement fund); else what the
    # total holds beyond the holdings (a margin account lists none, or a zero).
    cash = sum(listed_cash, Decimal(0)) if any(listed_cash) else total - others - moved
    return DayFigures(day=max(days) if days else None, positions=positions, cash=cash, total=total)


def read_balance(account: Dict, owed: bool) -> DayFigures:
    """A bank, card or loan account's balance as its day's figures. What is owed
    (a card's or loan's balance) is stored as a negative value."""
    current = _money((account.get("balances") or {}).get("current"))
    value = -current if owed else current
    return DayFigures(day=None, positions=[], cash=value, total=value)
