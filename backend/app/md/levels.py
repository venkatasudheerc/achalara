"""Index levels: each market index's daily closing level, for returns and seasonality.

A level leaves dividends out (a price return), unlike a fund's adjusted close.
From Yahoo's chart feed, the same one the app's benchmarks use, through the
shared ``utils.yahoo_chart``; kept here too so market data stands on its own.
A first run loads everything the source has (the S&P 500 from 1927); each run
after reads the last week again, so a late correction is taken.
"""
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.md.jobs import tracked_run
from app.md.models import IndexLevelHist
from app.utils import yahoo_chart

logger = logging.getLogger(__name__)

JOB = "md_index_levels"
SOURCE = "yahoo"


@dataclass(frozen=True)
class IndexLevel:
    """One index whose daily level market data collects. ``code`` is ours (shown with a
    leading ``^``, stored without it); ``source`` is Yahoo's symbol."""

    code: str
    source: str
    name: str
    country: str  # ISO 3166: US, IN
    currency: str  # the level's currency: a return is in it, before any currency move
    group: str  # how the page groups it
    volatility: bool = False  # expected volatility, not a price


US = "Indices (US)"
IN_BROAD = "India: broad market"
IN_SECTOR = "India: sectors and themes"

# The one list of index levels. Add an index here only; Yahoo must serve its history
# (several Indian sector indices are served for today only and are left out).
INDEX_LEVELS_INFO = (
    IndexLevel("SPX", "^GSPC", "S&P 500", "US", "USD", US),
    IndexLevel("NDX", "^NDX", "Nasdaq-100", "US", "USD", US),
    IndexLevel("DJI", "^DJI", "Dow Jones Industrial Average", "US", "USD", US),
    IndexLevel("RUI", "^RUI", "Russell 1000", "US", "USD", US),
    IndexLevel("RUT", "^RUT", "Russell 2000", "US", "USD", US),
    IndexLevel("RUA", "^RUA", "Russell 3000", "US", "USD", US),
    IndexLevel("VIX", "^VIX", "Volatility Index (VIX)", "US", "USD", US, volatility=True),
    IndexLevel("NSEI", "^NSEI", "Nifty 50", "IN", "INR", IN_BROAD),
    IndexLevel("NSMIDCP", "^NSMIDCP", "Nifty Next 50", "IN", "INR", IN_BROAD),
    IndexLevel("CNX100", "^CNX100", "Nifty 100", "IN", "INR", IN_BROAD),
    IndexLevel("CNX200", "^CNX200", "Nifty 200", "IN", "INR", IN_BROAD),
    IndexLevel("CNX500", "^CRSLDX", "Nifty 500", "IN", "INR", IN_BROAD),
    IndexLevel("NSEMDCP50", "^NSEMDCP50", "Nifty Midcap 50", "IN", "INR", IN_BROAD),
    IndexLevel("INDIAVIX", "^INDIAVIX", "India VIX", "IN", "INR", IN_BROAD, volatility=True),
    IndexLevel("NSEBANK", "^NSEBANK", "Nifty Bank", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXIT", "^CNXIT", "Nifty IT", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXAUTO", "^CNXAUTO", "Nifty Auto", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXFMCG", "^CNXFMCG", "Nifty FMCG", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXPHARMA", "^CNXPHARMA", "Nifty Pharma", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXMETAL", "^CNXMETAL", "Nifty Metal", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXREALTY", "^CNXREALTY", "Nifty Realty", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXENERGY", "^CNXENERGY", "Nifty Energy", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXFIN", "NIFTY_FIN_SERVICE.NS", "Nifty Financial Services", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXPSUBANK", "^CNXPSUBANK", "Nifty PSU Bank", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXINFRA", "^CNXINFRA", "Nifty Infrastructure", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXPSE", "^CNXPSE", "Nifty PSE", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXMNC", "^CNXMNC", "Nifty MNC", "IN", "INR", IN_SECTOR),
    IndexLevel("CNXCONSUM", "^CNXCONSUM", "Nifty India Consumption", "IN", "INR", IN_SECTOR),
)
INFO = {level.code: level for level in INDEX_LEVELS_INFO}
# Our code for each index level, and the source's symbol.
LEVELS = {level.code: level.source for level in INDEX_LEVELS_INFO}
_EARLIEST = date(1880, 1, 1)
_OVERLAP = timedelta(days=7)
MARKET_ZONE = ZoneInfo("America/New_York")
FINAL_AFTER = time(17, 0)


class IndexLevelService:
    def __init__(self, db: Session, fetch: Optional[Callable] = None):
        self.db = db
        self._fetch = fetch or yahoo_chart.fetch

    def run(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(timezone.utc)
        written: Dict[str, int] = {}
        failed: List[str] = []
        with tracked_run(self.db, JOB) as run:
            for code, source_symbol in LEVELS.items():
                latest = (
                    self.db.query(func.max(IndexLevelHist.price_date))
                    .filter(IndexLevelHist.symbol == code)
                    .scalar()
                )
                start = _EARLIEST if latest is None else latest - _OVERLAP
                try:
                    bars = yahoo_chart.parse_bars(self._fetch(source_symbol, start))
                except Exception as exc:  # noqa: BLE001 - one index failing is not all
                    logger.warning("Index level %s could not be fetched: %s", code, exc)
                    failed.append(code)
                    continue
                run.requests += 1
                written[code] = self._store(code, bars, now)
                self.db.commit()
            run.rows_written = sum(written.values())
            parts = [f"{code} {count:,}" for code, count in written.items()]
            run.note = "Index levels written: " + (", ".join(parts) or "none")
            if failed:
                run.note += f"; could not be read: {', '.join(failed)}"
                run.outcome = "failed"
            return run.note

    def _store(self, code: str, bars: List[Dict], now: datetime) -> int:
        """Write the final days given, replacing a day already on file."""
        here = now.astimezone(MARKET_ZONE)
        last_final = (
            here.date()
            if here.time() >= FINAL_AFTER
            else here.date() - timedelta(days=1)
        )
        bars = [bar for bar in bars if bar["bar_date"] <= last_final]
        if not bars:
            return 0
        on_file = {
            row.price_date: row
            for row in self.db.query(IndexLevelHist).filter(
                IndexLevelHist.symbol == code,
                IndexLevelHist.price_date >= bars[0]["bar_date"],
            )
        }
        for bar in bars:
            row = on_file.get(bar["bar_date"])
            if row is None:
                row = IndexLevelHist(symbol=code, price_date=bar["bar_date"])
                self.db.add(row)
            row.close, row.source, row.fetched_at = bar["close"], SOURCE, now
        return len(bars)


def run_index_levels(db: Session, now: Optional[datetime] = None) -> str:
    return IndexLevelService(db).run(now)
