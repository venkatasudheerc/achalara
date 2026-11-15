"""A copy of market data's sector for each symbol the app holds.

The portal's sector view (Analysis) reads ``security_sectors``; it never reads
market data. This job fills the copy each morning, after market data's own
classification run, and keeps a row for a symbol market data has no sector for
(``sector_code`` empty) so that "not classified" is a fact on file. Nothing in
``perf`` reads it: returns and valuations are unchanged by sectors.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict

from sqlalchemy.orm import Session

from app.models.security_sector import SecuritySector
from app.services.held_symbols import held_symbols
from app.utils.symbols import app_symbol

logger = logging.getLogger(__name__)


def refresh(db: Session) -> int:
    """Bring the copy up to date for every symbol held or traded. Returns how
    many rows were added or changed; 0, and the copy as it was, when market data
    cannot be read."""
    from app.md import read as md_read

    symbols = {app_symbol(symbol) for symbol, _ in held_symbols(db)}
    try:
        known = md_read.sectors_for(db, symbols)
    except md_read.MdUnavailable:
        logger.warning("Sector copy: market data could not be read")
        return 0
    now = datetime.now(timezone.utc)
    have: Dict[str, SecuritySector] = {
        row.symbol: row for row in db.query(SecuritySector)
    }
    changed = 0
    for symbol in sorted(symbols):
        sector = known.get(symbol)
        values = (
            (sector.kind, sector.sector_code, sector.sector_name)
            if sector
            else (None, None, None)
        )
        row = have.get(symbol)
        if row is None:
            db.add(
                SecuritySector(
                    symbol=symbol,
                    kind=values[0],
                    sector_code=values[1],
                    sector_name=values[2],
                    refreshed_at=now,
                )
            )
            changed += 1
        elif (row.kind, row.sector_code, row.sector_name) != values:
            row.kind, row.sector_code, row.sector_name = values
            row.refreshed_at = now
            changed += 1
    db.commit()
    return changed
