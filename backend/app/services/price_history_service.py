"""Price history — daily closes for what has been held, and for benchmarks.

Without a close for each day a holding can only be valued at what it last
traded for, so its gains appear on the day it is next traded, not as they
happen. This service keeps ``perf.daily_price`` filled from the market-data
source for every security a sleeve has held, over the span it was held.

The source's closes are adjusted for later splits and dividends, and it
restates the whole series whenever a new one occurs. A stored series is
therefore only consistent with itself as fetched: a symbol is always replaced
whole, never topped up row by row.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.connectors.models import is_option_symbol
from app.connectors.webull_connector import WebullConnector
from app.models.perf import DailyPrice
from app.models.trade import Trade

logger = logging.getLogger(__name__)

SOURCE = "webull"

# Always kept, whatever is held: what a portfolio is compared against, and the
# calendar of market days (a day is a market day if SPY has a close for it).
BENCHMARKS = ("SPY", "QQQ", "AGG", "DIA")
CALENDAR_SYMBOL = "SPY"

# Kept either side of the span a security was held, so its first and last
# days always have a close to work from.
_MARGIN = timedelta(days=10)

# A series fetched more recently than this is not fetched again.
_FRESH_FOR = timedelta(hours=18)


def quotable(symbol: str) -> bool:
    """Whether the market-data source can be asked about ``symbol``.

    It quotes securities, not option contracts, and not the name-only
    stand-ins used for trades the brokerage sent without a ticker.
    """
    return bool(symbol) and not symbol.startswith("~") and not is_option_symbol(symbol)


class PriceHistoryService:
    """Fills and reads ``perf.daily_price``."""

    def __init__(self, db: Session, connector=None):
        self.db = db
        self.connector = connector or WebullConnector()

    # ------------------------------------------------------------------
    # What is needed
    # ------------------------------------------------------------------

    def needed_spans(self, today: Optional[date] = None) -> Dict[str, Tuple[date, date]]:
        """For each security ever held, the span of days a close is needed for.

        From shortly before its first trade to shortly after its last, or to
        today while any of it is still held.
        """
        today = today or date.today()
        spans: Dict[str, Tuple[date, date]] = {}
        rows = self.db.query(
            Trade.symbol,
            func.min(Trade.trade_date),
            func.max(Trade.trade_date),
            func.sum(Trade.quantity).filter(Trade.action == "BUY"),
            func.sum(Trade.quantity).filter(Trade.action == "SELL"),
        ).group_by(Trade.symbol)
        overall_first = today
        for symbol, first, last, bought, sold in rows:
            if not quotable(symbol):
                continue
            still_held = (bought or 0) != (sold or 0)
            end = today if still_held else min(today, last + _MARGIN)
            spans[symbol] = (first - _MARGIN, end)
            overall_first = min(overall_first, first - _MARGIN)
        for symbol in BENCHMARKS:
            spans[symbol] = (overall_first, today)
        return spans

    # ------------------------------------------------------------------
    # Filling
    # ------------------------------------------------------------------

    def backfill(
        self, symbols: Optional[Iterable[str]] = None, force: bool = False
    ) -> Dict[str, int]:
        """Fetch and store closes for every span that is not already covered.

        One request per symbol. Returns counts of symbols fetched, skipped
        because already covered, and for which the source had nothing.
        """
        result = {"fetched": 0, "covered": 0, "empty": 0, "rows": 0}
        if not self.connector.is_configured():
            logger.warning("Market-data source not configured; no prices fetched")
            return result

        spans = self.needed_spans()
        wanted = set(symbols) if symbols is not None else None
        stored = self._stored_extent()
        now = datetime.now(timezone.utc)

        for symbol, (start, end) in sorted(spans.items()):
            if wanted is not None and symbol not in wanted:
                continue
            if not force and self._covered(stored.get(symbol), start, end, now):
                result["covered"] += 1
                continue
            try:
                points = self.connector.fetch_daily_closes(symbol)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Price history fetch failed for %s: %s", symbol, exc)
                points = []
            kept = [(d, c) for d, c in points if start <= d <= end and c > 0]
            if not kept:
                result["empty"] += 1
                continue
            self.db.query(DailyPrice).filter(
                DailyPrice.symbol == symbol, DailyPrice.source == SOURCE
            ).delete(synchronize_session=False)
            self.db.bulk_insert_mappings(
                DailyPrice,
                [
                    {
                        "symbol": symbol,
                        "price_date": d,
                        "close": Decimal(str(c)),
                        "source": SOURCE,
                        "fetched_at": now,
                    }
                    for d, c in kept
                ],
            )
            self.db.commit()
            result["fetched"] += 1
            result["rows"] += len(kept)
        return result

    def _stored_extent(self) -> Dict[str, Tuple[date, date, Optional[datetime]]]:
        return {
            symbol: (first, last, fetched)
            for symbol, first, last, fetched in self.db.query(
                DailyPrice.symbol,
                func.min(DailyPrice.price_date),
                func.max(DailyPrice.price_date),
                func.max(DailyPrice.fetched_at),
            )
            .filter(DailyPrice.source == SOURCE)
            .group_by(DailyPrice.symbol)
        }

    @staticmethod
    def _covered(extent, start: date, end: date, now: datetime) -> bool:
        """Whether a stored series already serves the span needed."""
        if extent is None:
            return False
        first, last, fetched = extent
        if fetched is not None:
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            if now - fetched < _FRESH_FOR:
                return True
        # Weekends and holidays: a series ending within a few days of the
        # span's end has every market day in it.
        return last >= end - timedelta(days=4) and first <= start + timedelta(days=6)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def closes(self, symbols: Iterable[str]) -> Dict[str, List[Tuple[date, Decimal]]]:
        """Stored adjusted closes per symbol, oldest first."""
        symbols = [s for s in set(symbols) if quotable(s)]
        series: Dict[str, List[Tuple[date, Decimal]]] = {}
        if not symbols:
            return series
        for symbol, day, close in (
            self.db.query(DailyPrice.symbol, DailyPrice.price_date, DailyPrice.close)
            .filter(DailyPrice.symbol.in_(symbols), DailyPrice.source == SOURCE)
            .order_by(DailyPrice.symbol, DailyPrice.price_date)
        ):
            series.setdefault(symbol, []).append((day, Decimal(str(close))))
        return series

    def market_days(self, start: date, end: date) -> List[date]:
        """The days the market was open in [start, end].

        Taken from the benchmark's own closes; plain weekdays where those do
        not reach (nothing fetched yet, or the last day or two).
        """
        known = [
            row[0]
            for row in self.db.query(DailyPrice.price_date)
            .filter(
                DailyPrice.symbol == CALENDAR_SYMBOL,
                DailyPrice.source == SOURCE,
                DailyPrice.price_date >= start,
                DailyPrice.price_date <= end,
            )
            .order_by(DailyPrice.price_date)
        ]
        covered_to = known[-1] if known else start - timedelta(days=1)
        covered_from = known[0] if known else end + timedelta(days=1)
        days = list(known)
        cursor = start
        while cursor <= end:
            outside = cursor < covered_from or cursor > covered_to
            if outside and cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
        return sorted(set(days))
