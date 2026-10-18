"""Every security clients hold gets a row in the security master.

Index files cover the big indices; client holdings also include ETFs, small
companies outside them, and funds. Options are left out: they are priced and
classified through their underlying.
"""
import re
from datetime import date
from typing import Dict

from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.md.models import Security, SecuritySymbol, SecuritySymbolHist
from app.md.readers import app_symbol
from app.models.perf import DailyHolding
from app.models.trade import Trade

# The trades' security types, in the security master's kinds.
KINDS = {
    "STOCK": "stock",
    "ETF": "etf",
    "ADR": "adr",
    "CLOSED_END_FUND": "fund",
    "MUTUAL_FUND": "fund",
    "PREFERRED": "preferred",
}


# A ticker as listed: a few letters or digits, optionally a share class
# (``BRK.B``), up to five letters for mutual funds (``ABCDX``). The brokerage
# sometimes writes a placeholder instead, such as ``~SOME COMPANY INC`` for a
# security in the middle of a corporate action; those are not securities.
_TICKER = re.compile(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z0-9]{1,3})?$")


def _symbol(raw: str) -> str:
    """Trades from sheets may carry an exchange prefix (``NASDAQ:AAPL``)."""
    return app_symbol((raw or "").split(":")[-1])


def seed_from_holdings(db: Session, today: date) -> int:
    """Add a security for each held symbol not yet known; the number added."""
    held: Dict[str, str] = {}
    for symbol, kind in db.query(Trade.symbol, Trade.security_type).distinct():
        if symbol and not is_option_symbol(symbol):
            held.setdefault(_symbol(symbol), KINDS.get((kind or "").upper(), "other"))
    for symbol, kind in db.query(
        DailyHolding.symbol, DailyHolding.security_type
    ).distinct():
        if symbol and not is_option_symbol(symbol):
            held.setdefault(_symbol(symbol), KINDS.get((kind or "").upper(), "other"))
    known = {row[0] for row in db.query(SecuritySymbol.symbol)}
    added = 0
    for symbol, kind in sorted(held.items()):
        if not _TICKER.match(symbol) or symbol in known:
            continue
        security = Security(name=symbol, kind=kind)
        db.add(security)
        db.flush()
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
        db.add(
            SecuritySymbolHist(
                security_id=security.id,
                symbol=symbol,
                valid_from=today,
                source="holdings",
            )
        )
        added += 1
    db.commit()
    return added
