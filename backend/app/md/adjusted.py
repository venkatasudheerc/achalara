"""Adjusted history: every security's daily close adjusted for later splits and
dividends, the series all returns are computed from (a total return).

Webull's daily bars are adjusted this way and go back about five years. It
rewrites the whole series after each split or dividend, scaling every earlier
close by one factor. So each night:

- a security with nothing on file gets its whole history (two requests' worth);
- a security on file gets its last few days. If the days already on file agree,
  the new ones are added. If not, the series was rewritten: the whole window is
  fetched again and replaces those days, and every older day on file, beyond
  Webull's five years, is scaled by the same factor, so it stays consistent.

Prices as traded are a different table (``price_daily_hist``) and never touched here.
"""
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import func, insert, update
from sqlalchemy.orm import Session

from app.md.closes import ETF, STOCK, universe
from app.md.jobs import tracked_run
from app.md.models import PriceAdjDaily, PriceDailyHist
from app.md.webull import (
    WebullClient,
    WebullError,
    WebullInvalidSymbols,
    WebullRefused,
    WebullUnreachable,
)
from app.utils.symbols import webull_symbol

logger = logging.getLogger(__name__)

JOB = "md_adjusted_closes"
PATH = "/market-data/stocks/bars/list"
BATCH = 20  # Webull's limit per request
FULL = 1200  # the most bars one request returns
OVERLAP = 10  # days read again each night to notice a rewritten series
# Two closes agree when they differ by less than this share.
TOLERANCE = Decimal("0.000001")
MARKET_ZONE = ZoneInfo("America/New_York")
FINAL_AFTER = time(17, 0)
UNREACHABLE_LIMIT = 3

Bars = Dict[date, Decimal]


def _number(value) -> Optional[Decimal]:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None
    return number if number > 0 else None


def _agree(a: Decimal, b: Decimal) -> bool:
    return abs(a / b - 1) <= TOLERANCE


class AdjustedHistoryService:
    def __init__(self, db: Session, webull: Optional[WebullClient] = None):
        self.db = db
        self.webull = webull or WebullClient()
        self.updated = self.backfilled = self.restated = self.rows = 0
        self.unknown: Set[str] = set()
        self.stopped: Optional[str] = None
        self._unreachable = 0
        self._now = datetime.now(timezone.utc)

    # -- the run -----------------------------------------------------------

    def run(self, now: Optional[datetime] = None) -> str:
        self._now = now or datetime.now(timezone.utc)
        with tracked_run(self.db, JOB) as run:
            if not self.webull.configured():
                run.outcome, run.note = "skipped", "Webull is not configured"
                return run.note
            securities = universe(self.db)
            on_file = {
                row[0] for row in self.db.query(PriceAdjDaily.security_id).distinct()
            }
            groups: Dict[Tuple[str, bool], Dict[str, str]] = {}
            for security_id, symbol, kind in securities:
                category = ETF if kind == "etf" else STOCK
                groups.setdefault((category, security_id in on_file), {})[
                    webull_symbol(symbol)
                ] = security_id
            for (category, known), wanted in sorted(groups.items()):
                if self.stopped:
                    break
                self._each_batch(category, wanted, known)
            run.requests = self.webull.requests
            run.rows_written = self.rows
            run.note = self.summary(len(securities))
            if self.stopped:
                run.outcome = "failed"
            return run.note

    def _each_batch(self, category: str, wanted: Dict[str, str], known: bool) -> None:
        symbols = sorted(wanted)
        for start in range(0, len(symbols), BATCH):
            if self.stopped:
                return
            batch = symbols[start : start + BATCH]
            if known:
                bars = self._fetch(category, batch, OVERLAP)
                rewritten = [
                    symbol
                    for symbol, series in bars.items()
                    if not self._top_up(wanted[symbol], series)
                ]
                if rewritten and not self.stopped:
                    for symbol, series in self._fetch_full(category, rewritten).items():
                        self._replace(wanted[symbol], series)
            else:
                for symbol, series in self._fetch_full(category, batch).items():
                    self._insert(wanted[symbol], series)
                    self.backfilled += 1
            self.db.commit()

    # -- Webull ------------------------------------------------------------

    def _fetch(
        self,
        category: str,
        symbols: List[str],
        count: int,
        end_ms: Optional[int] = None,
    ) -> Dict[str, Bars]:
        """Final daily closes for ``symbols``, by Webull spelling; unknown ones dropped."""
        while symbols and not self.stopped:
            body = {
                "symbols": symbols,
                "category": category,
                "timespan": "D",
                "count": count,
            }
            if end_ms is not None:
                body["end_time"] = end_ms
            try:
                answer = self.webull.post(PATH, body)
                self._unreachable = 0
            except WebullInvalidSymbols as refused:
                gone = {s for s in symbols if s in refused.symbols}
                if not gone:
                    return {}
                self.unknown |= gone
                symbols = [s for s in symbols if s not in gone]
                continue
            except WebullRefused:
                self.stopped = "Webull refused (too many requests)"
                return {}
            except WebullUnreachable:
                self._unreachable += 1
                if self._unreachable >= UNREACHABLE_LIMIT:
                    self.stopped = "Webull not answering"
                return {}
            except WebullError:
                return {}  # e.g. asking further back than Webull keeps
            series: Dict[str, Bars] = {}
            for item in (answer or {}).get("result") or []:
                series[item.get("symbol")] = self._final(item.get("result") or [])
            return series
        return {}

    def _fetch_full(self, category: str, symbols: List[str]) -> Dict[str, Bars]:
        """Everything Webull keeps: the latest 1,200 days, then the rest before them."""
        series = self._fetch(category, symbols, FULL)
        older = [s for s, bars in series.items() if len(bars) >= FULL - 5]
        if older and not self.stopped:
            earliest = min(min(series[s]) for s in older)
            end = datetime.combine(earliest, time(), MARKET_ZONE)
            for symbol, bars in self._fetch(
                category, older, FULL, int(end.timestamp() * 1000) - 1
            ).items():
                series.setdefault(symbol, {}).update(
                    {day: close for day, close in bars.items() if day < earliest}
                )
        return series

    def _final(self, bars: List[dict]) -> Bars:
        local_now = self._now.astimezone(MARKET_ZONE)
        series: Bars = {}
        for bar in bars:
            close = _number(bar.get("close"))
            stamp = bar.get("time")
            if close is None or not stamp:
                continue
            day = (
                datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S")
                .replace(tzinfo=timezone.utc)
                .astimezone(MARKET_ZONE)
                .date()
            )
            if day > local_now.date() or (
                day == local_now.date() and local_now.time() < FINAL_AFTER
            ):
                continue
            series[day] = close
        return series

    # -- the table ---------------------------------------------------------

    def _stored(self, security_id: str, days) -> Bars:
        return dict(
            self.db.query(PriceAdjDaily.price_date, PriceAdjDaily.adj_close).filter(
                PriceAdjDaily.security_id == security_id,
                PriceAdjDaily.price_date.in_(list(days)),
            )
        )

    def _insert(self, security_id: str, series: Bars) -> None:
        if not series:
            return
        self.db.execute(
            insert(PriceAdjDaily),
            [
                {
                    "security_id": security_id,
                    "price_date": day,
                    "adj_close": close,
                    "fetched_at": self._now,
                }
                for day, close in sorted(series.items())
            ],
        )
        self.rows += len(series)

    def _top_up(self, security_id: str, series: Bars) -> bool:
        """Add new days if the days on file agree; False if the series was rewritten."""
        stored = self._stored(security_id, series)
        if any(not _agree(series[day], close) for day, close in stored.items()):
            return False
        self._insert(security_id, {d: c for d, c in series.items() if d not in stored})
        self.updated += 1
        return True

    def _replace(self, security_id: str, series: Bars) -> None:
        """Take a rewritten series: replace its days, rescale the older ones."""
        if not series:
            return
        first = min(series)
        stored = self._stored(security_id, series)
        common = sorted(day for day in series if day in stored)
        if common:
            factor = series[common[0]] / stored[common[0]]
            self.db.execute(
                update(PriceAdjDaily)
                .where(
                    PriceAdjDaily.security_id == security_id,
                    PriceAdjDaily.price_date < first,
                )
                .values(adj_close=PriceAdjDaily.adj_close * factor)
            )
        self.db.query(PriceAdjDaily).filter(
            PriceAdjDaily.security_id == security_id,
            PriceAdjDaily.price_date >= first,
        ).delete(synchronize_session=False)
        self._insert(security_id, series)
        self.restated += 1

    def summary(self, asked: int) -> str:
        parts = [
            f"Adjusted history: {self.updated:,} of {asked:,} topped up",
            f"{self.backfilled:,} loaded in full",
            f"{self.restated:,} rewritten by the source and refreshed",
            f"{self.rows:,} rows written",
        ]
        if self.unknown:
            names = sorted(self.unknown)
            shown = ", ".join(names[:10]) + (", …" if len(names) > 10 else "")
            parts.append(f"{len(names):,} unknown to Webull ({shown})")
        if self.stopped:
            parts.append(f"{self.stopped}; stopped for tonight")
        return "; ".join(parts)


def run_adjusted_history(db: Session, now: Optional[datetime] = None) -> str:
    return AdjustedHistoryService(db).run(now)


def earliest_kept(today: date, years: int) -> Optional[date]:
    """The first day kept under a limit of ``years``; None when everything is kept."""
    if years <= 0:
        return None
    try:
        return today.replace(year=today.year - years)
    except ValueError:  # 29 February
        return today.replace(year=today.year - years, day=28)


def prune_prices(db: Session, today: date, years: int) -> str:
    """Delete stock and fund prices older than ``years``. Only these two tables;
    index levels, membership, files and classification are never pruned."""
    cutoff = earliest_kept(today, years)
    with tracked_run(db, "md_prune_prices") as run:
        if cutoff is None:
            run.outcome, run.note = (
                "skipped",
                "No limit set (MD_HISTORY_YEARS); nothing removed",
            )
            return run.note
        removed = 0
        for table in (PriceAdjDaily, PriceDailyHist):
            removed += (
                db.query(table)
                .filter(table.price_date < cutoff)
                .delete(synchronize_session=False)
            )
        db.commit()
        run.rows_written = removed
        run.note = f"Removed {removed:,} price rows before {cutoff.isoformat()}"
        return run.note


def coverage(db: Session) -> Tuple[int, Optional[date]]:
    """Securities with adjusted history, and the earliest day on file."""
    count = db.query(func.count(func.distinct(PriceAdjDaily.security_id))).scalar()
    first = db.query(func.min(PriceAdjDaily.price_date)).scalar()
    return count or 0, first
