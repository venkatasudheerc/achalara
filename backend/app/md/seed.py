"""Every security clients hold gets a row in the security master, as American:
every brokerage row so far is, and the ticker rule below is the US one.

Index files cover the big indices; client holdings also include ETFs, small
companies outside them, and funds. The app hands over the symbols
(``services/held_symbols.py``), so this package never reads client data.
"""
import re
from datetime import date
from typing import Dict, Iterable, Optional, Tuple

from sqlalchemy.orm import Session

from app.md.models import Security, SecuritySymbol, SecuritySymbolHist, US_MARKET
from app.utils.symbols import app_symbol

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


def seed_securities(
    db: Session, held: Iterable[Tuple[str, Optional[str]]], today: date
) -> int:
    """Add a security for each ``(symbol, type)`` not yet known; the number added."""
    wanted: Dict[str, str] = {}
    for symbol, kind in held:
        wanted.setdefault(app_symbol(symbol), KINDS.get((kind or "").upper(), "other"))
    known = {
        row[0]
        for row in db.query(SecuritySymbol.symbol).filter(
            SecuritySymbol.market_code == US_MARKET
        )
    }
    added = 0
    for symbol, kind in sorted(wanted.items()):
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
