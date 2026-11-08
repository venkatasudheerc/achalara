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
from typing import Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.md.jobs import tracked_run
from app.md.models import IndexLevelHist
from app.utils import yahoo_chart

logger = logging.getLogger(__name__)

JOB = "md_index_levels"  # the US indices (and every index when no market is named)
JOB_IN = "md_index_levels_in"  # the Indian indices, run after India's close
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


# When a market's day is over: its close is final this long after the closing bell, in the
# market's own time zone. India closes at 3:30 PM IST, about 5 or 6 AM in New York.
MARKET_CLOCK = {
    "US": (ZoneInfo("America/New_York"), time(17, 0)),
    "IN": (ZoneInfo("Asia/Kolkata"), time(16, 30)),
}

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

    def run(self, now: Optional[datetime] = None, market: Optional[str] = None) -> str:
        """Fetch the levels of one market's indices (``US``, ``IN``), or every index."""
        now = now or datetime.now(timezone.utc)
        written: Dict[str, int] = {}
        failed: List[str] = []
        wanted = [i for i in INDEX_LEVELS_INFO if market is None or i.country == market]
        with tracked_run(self.db, JOB_IN if market == "IN" else JOB) as run:
            for code, source_symbol in ((i.code, i.source) for i in wanted):
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
        # Final once the index's own market has closed for the day, in its own time zone.
        zone, final_after = MARKET_CLOCK.get(
            INFO[code].country if code in INFO else "US", (MARKET_ZONE, FINAL_AFTER)
        )
        here = now.astimezone(zone)
        last_final = (
            here.date()
            if here.time() >= final_after
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


def run_index_levels(
    db: Session, now: Optional[datetime] = None, market: Optional[str] = None
) -> str:
    """One market's index levels, or, with no market, each market in turn (each its own
    recorded run, as the scheduled jobs are)."""
    if market is not None:
        return IndexLevelService(db).run(now, market)
    return "; ".join(IndexLevelService(db).run(now, m) for m in ("US", "IN"))


STALE_AFTER_MARKET_DAYS = 4  # longer than the longest regular break, in either market


def _weekdays_between(earlier: date, later: date) -> int:
    """Weekdays after ``earlier`` up to and including ``later``."""
    days, day = 0, earlier
    while day < later:
        day += timedelta(days=1)
        if day.weekday() < 5:
            days += 1
    return days


def stale_levels(db: Session, today: date) -> List[Tuple[str, Optional[date]]]:
    """Indices with no new level for more than ``STALE_AFTER_MARKET_DAYS`` weekdays, or none
    at all: ``(name, latest day or None)``. A source can stop sending one index while the
    run as a whole still succeeds; this is how that is noticed."""
    latest = dict(
        db.query(IndexLevelHist.symbol, func.max(IndexLevelHist.price_date)).group_by(
            IndexLevelHist.symbol
        )
    )
    out = []
    for level in INDEX_LEVELS_INFO:
        day = latest.get(level.code)
        if day is None or _weekdays_between(day, today) > STALE_AFTER_MARKET_DAYS:
            out.append((level.name, day))
    return out


def describe_stale(stale: List[Tuple[str, Optional[date]]]) -> Optional[str]:
    """One plain line for a status page or an alert, or None when every index is current."""
    if not stale:
        return None
    missing = [name for name, day in stale if day is None]
    old = [f"{name} (since {day.isoformat()})" for name, day in stale if day is not None]
    parts = []
    if old:
        parts.append("No new index level: " + ", ".join(old))
    if missing:
        parts.append("No index levels on file yet: " + ", ".join(missing))
    return ". ".join(parts) + "."
