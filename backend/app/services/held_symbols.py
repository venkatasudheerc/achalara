"""The symbols the app holds or has held, for the security master.

Client data stays on this side: market data is handed the list and never reads
trades or holdings itself. Only symbols and their types leave here, never
quantities or accounts. Options are left out, because they are priced and
classified through their underlying.
"""
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.models.perf import DailyHolding
from app.models.trade import Trade


def held_symbols(db: Session) -> List[Tuple[str, Optional[str]]]:
    """Each ``(symbol, security type)`` in trades, then in recorded holdings."""
    rows = list(db.query(Trade.symbol, Trade.security_type).distinct())
    rows += db.query(DailyHolding.symbol, DailyHolding.security_type).distinct()
    return [
        (symbol, kind)
        for symbol, kind in rows
        if symbol and not is_option_symbol(symbol)
    ]
