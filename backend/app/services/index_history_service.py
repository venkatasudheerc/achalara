"""Index history — daily bars of the market indices, for research and benchmarks.

The S&P 500, the Dow and the Nasdaq-100 as far back as the source gives
them, loaded from downloaded files and topped up each day. Webull does not
serve indices, so the top-up comes from Yahoo's chart feed: free and
unofficial, with terms not yet cleared for figures shown to clients (an open
item before go-live). Nothing that values an account reads this table; an
index may be chosen as a benchmark through ``services/benchmarks.py``.
"""
import csv
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.index_bar import IndexBar
from app.utils.yahoo_chart import (
    FIELDS,
    parse_bars,
)  # noqa: F401  (parse_bars: callers)
from app.utils.yahoo_chart import bar as _bar
from app.utils.yahoo_chart import fetch as _fetch

logger = logging.getLogger(__name__)

SOURCE = "yahoo"

# Our symbol for each index, and the source's.
INDICES = {"SPX": "^GSPC", "DJI": "^DJI", "NDX": "^NDX"}

# Before any index was published; the source answers from its first day.
_EARLIEST = date(1880, 1, 1)
# A top-up reads these days again, so a late correction by the source is taken.
_OVERLAP = timedelta(days=7)
_MARKET_ZONE = ZoneInfo("America/New_York")
# The day's bar is final some time after the 4pm close.
_FINAL_AFTER = time(17, 0)


def read_csv_bars(path: str) -> List[Dict]:
    """The days in a downloaded file with Date, Open, High, Low, Close and Volume columns."""
    bars = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            named = {(key or "").strip().lower(): value for key, value in row.items()}
            day = date.fromisoformat(named["date"].strip())
            bar = _bar(day, *(_number(named.get(key)) for key in FIELDS))
            if bar is not None:
                bars.append(bar)
    return sorted(bars, key=lambda bar: bar["bar_date"])


def _number(text) -> Optional[float]:
    text = (text or "").strip()
    return float(text) if text and text.lower() not in ("null", "nan") else None


class IndexHistoryService:
    """Loads and tops up the stored bars of each index."""

    def __init__(self, db: Session, fetch: Optional[Callable] = None):
        self.db = db
        self._fetch = fetch or _fetch

    def refresh(
        self,
        symbols: Optional[List[str]] = None,
        full: bool = False,
        now: Optional[datetime] = None,
    ) -> Dict[str, int]:
        """Bring each index up to date; the number of days written, by index.

        An index with nothing on file is loaded from its first day, and so is
        every index when ``full`` is set. One request per index. An index the
        source fails on is logged and left as it was; the others still load.
        """
        now = now or datetime.now(timezone.utc)
        written: Dict[str, int] = {}
        for symbol in symbols or list(INDICES):
            symbol = symbol.strip().upper()
            if symbol not in INDICES:
                raise ValueError(
                    f"Unknown index {symbol}; choose from {', '.join(INDICES)}"
                )
            latest = (
                self.db.query(func.max(IndexBar.bar_date))
                .filter(IndexBar.symbol == symbol)
                .scalar()
            )
            start = _EARLIEST if full or latest is None else latest - _OVERLAP
            try:
                bars = parse_bars(self._fetch(INDICES[symbol], start))
            except Exception as exc:
                logger.error(f"Index history for {symbol} could not be fetched: {exc}")
                written[symbol] = 0
                continue
            written[symbol] = self._store(symbol, bars, now, SOURCE)
        self.db.commit()
        return written

    def _store(self, symbol: str, bars: List[Dict], now: datetime, source: str) -> int:
        """Write the days given, replacing a day already on file."""
        here = now.astimezone(_MARKET_ZONE)
        # Today's bar is still moving until the session has closed.
        last_final = (
            here.date()
            if here.time() >= _FINAL_AFTER
            else (here.date() - timedelta(days=1))
        )
        bars = [bar for bar in bars if bar["bar_date"] <= last_final]
        if not bars:
            return 0
        on_file = {
            row.bar_date: row
            for row in self.db.query(IndexBar).filter(
                IndexBar.symbol == symbol,
                IndexBar.bar_date >= bars[0]["bar_date"],
            )
        }
        for bar in bars:
            row = on_file.get(bar["bar_date"])
            if row is None:
                row = IndexBar(symbol=symbol, bar_date=bar["bar_date"])
                self.db.add(row)
            row.open, row.high, row.low = bar["open"], bar["high"], bar["low"]
            row.close, row.volume = bar["close"], bar["volume"]
            row.source, row.fetched_at = source, now
        return len(bars)

    def load_file(
        self, symbol: str, bars: List[Dict], source: str, replace: bool = False
    ) -> int:
        """Store an index's days from a downloaded file; how many were written.

        A day already on file is overwritten by the file's. With ``replace``
        everything on file for the index is removed first.
        """
        symbol = symbol.strip().upper()
        if symbol not in INDICES:
            raise ValueError(
                f"Unknown index {symbol}; choose from {', '.join(INDICES)}"
            )
        if not bars:
            raise ValueError("The file holds no days to load")
        if replace:
            self.db.query(IndexBar).filter(IndexBar.symbol == symbol).delete()
        written = self._store(symbol, bars, datetime.now(timezone.utc), source)
        self.db.commit()
        return written

    def extent(self) -> Dict[str, Dict]:
        """What is on file for each index: first and last day, and how many."""
        rows = (
            self.db.query(
                IndexBar.symbol,
                func.min(IndexBar.bar_date),
                func.max(IndexBar.bar_date),
                func.count(IndexBar.id),
                func.count(IndexBar.open),
            )
            .group_by(IndexBar.symbol)
            .all()
        )
        return {
            symbol: {"first": first, "last": last, "days": days, "with_open": opens}
            for symbol, first, last, days, opens in rows
        }
