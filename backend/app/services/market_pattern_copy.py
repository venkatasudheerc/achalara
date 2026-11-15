"""A copy of market data's S&P 500 record for this week and month.

The Dashboard's market-pattern tile reads ``market_pattern_copies``; it never
reads market data. This job fills the copy each morning, after market data's
index levels (6:15 AM Eastern). If market data cannot be read the copy is left
as it was, and the tile stops showing it once it is older than ``STALE_DAYS``.
Nothing in ``perf`` reads it, and it holds no client data.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy.orm import Session

from app.models.market_pattern import MarketPatternCopy

logger = logging.getLogger(__name__)

KEY = "sp500"
# A copy older than this is not shown: the week or month it names may be over.
STALE_DAYS = 4


def _plain(value):
    """Dates as ISO text, so the record can be stored as JSON."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def refresh(db: Session, today: Optional[date] = None) -> bool:
    """Bring the copy up to date. False, and the copy as it was, when market data
    cannot be read or has no S&P 500 levels yet."""
    from app.md import read as md_read

    try:
        pattern = md_read.market_pattern(today=today)
    except md_read.MdUnavailable:
        logger.warning("Market pattern copy: market data could not be read")
        return False
    payload = _plain(pattern)
    row = db.get(MarketPatternCopy, KEY)
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(MarketPatternCopy(key=KEY, payload=payload, refreshed_at=now))
    else:
        row.payload, row.refreshed_at = payload, now
    db.commit()
    return True


def latest(db: Session, today: Optional[date] = None) -> Optional[Dict]:
    """The copy, unless it is missing or older than ``STALE_DAYS``."""
    row = db.get(MarketPatternCopy, KEY)
    if row is None:
        return None
    refreshed = row.refreshed_at
    if refreshed.tzinfo is None:
        refreshed = refreshed.replace(tzinfo=timezone.utc)
    now = datetime.combine(today, datetime.min.time(), timezone.utc) if today else datetime.now(timezone.utc)
    if now - refreshed > timedelta(days=STALE_DAYS):
        return None
    return row.payload
