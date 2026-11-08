"""Daily closes: each security's prices for the day as traded, captured each evening.

Webull's daily bars are forward-adjusted, and so is every free source's
history, so the price a stock actually traded at on a past day cannot be
fetched later. This job records it on the day, from the snapshot, for every
security ever in an index and every tracked fund. A day it misses is lost.

Each close is dated by its own last trade, so a holiday (when the snapshot
still shows the previous day) adds nothing, and a run during the session never
stores a price that is still moving.
"""
import logging
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.md.jobs import tracked_run
from app.md.models import (
    US_MARKET,
    IndexMemberHist,
    PriceDailyHist,
    Security,
    SecuritySymbol,
    SecuritySymbolHist,
    TrackedFund,
)
from app.md.webull import (
    WebullClient,
    WebullInvalidSymbols,
    WebullRefused,
    WebullUnreachable,
)
from app.utils.symbols import app_symbol, webull_symbol

logger = logging.getLogger(__name__)

JOB = "md_daily_closes"
SOURCE = "webull_snapshot"
PATH = "/market-data/stocks/snapshots/list"
BATCH = 100  # Webull's limit per request
MARKET_ZONE = ZoneInfo("America/New_York")
# A day's prices are final after this, Eastern; the regular session ends at 4 PM.
FINAL_AFTER = time(17, 0)
UNREACHABLE_LIMIT = 3  # failed requests in a row before the job stops for the night
ETF, STOCK = "US_ETF", "US_STOCK"
# Mutual funds and the like are not on Webull.
NOT_QUOTED = ("fund",)


def universe(db: Session) -> List[Tuple[str, str, str]]:
    """``(security_id, symbol, kind)`` for every US security ever in an index and
    every fund tracked now. A security stays priced after it leaves an index."""
    ever_member = db.query(IndexMemberHist.security_id)
    tracked = db.query(TrackedFund.security_id).filter(TrackedFund.removed_on.is_(None))
    rows = (
        db.query(Security.id, SecuritySymbol.symbol, Security.kind)
        .join(SecuritySymbol, SecuritySymbol.security_id == Security.id)
        .filter(
            Security.market_code == US_MARKET,
            Security.status != "delisted",
            Security.kind.notin_(NOT_QUOTED),
            or_(Security.id.in_(ever_member), Security.id.in_(tracked)),
        )
        .order_by(SecuritySymbol.symbol)
    )
    return [(row[0], row[1], row[2]) for row in rows]


def _number(value) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


class DailyClosesService:
    def __init__(self, db: Session, webull: Optional[WebullClient] = None):
        self.db = db
        self.webull = webull or WebullClient()
        self.recorded = self.on_file = self.not_final = 0
        self.unknown: Set[str] = set()
        self.dates: Set[date] = set()
        self.stopped: Optional[str] = None
        self._unreachable = 0

    def run(self, now: Optional[datetime] = None) -> str:
        now = now or datetime.now(timezone.utc)
        with tracked_run(self.db, JOB) as run:
            if not self.webull.configured():
                run.note = "Webull is not configured; nothing captured"
                run.outcome = "skipped"
                return run.note
            securities = universe(self.db)
            currency = dict(
                self.db.query(Security.id, Security.currency).filter(
                    Security.id.in_([row[0] for row in securities])
                )
            )
            by_category: Dict[str, Dict[str, str]] = {ETF: {}, STOCK: {}}
            for security_id, symbol, kind in securities:
                category = ETF if kind == "etf" else STOCK
                by_category[category][webull_symbol(symbol)] = security_id
            rejected: Dict[str, Dict[str, str]] = {ETF: {}, STOCK: {}}
            for category, wanted in by_category.items():
                rejected[category] = self._capture(category, wanted, currency, now)
            # A security filed under the wrong kind is asked once in the other category.
            for category, other in ((ETF, STOCK), (STOCK, ETF)):
                if rejected[category] and not self.stopped:
                    self.unknown |= set(
                        self._capture(other, rejected[category], currency, now)
                    )
            run.requests = self.webull.requests
            run.rows_written = self.recorded
            run.note = self.summary(len(securities))
            if self.stopped:
                run.outcome = "failed"
            return run.note

    def _capture(
        self,
        category: str,
        wanted: Dict[str, str],
        currency: Dict[str, str],
        now: datetime,
    ) -> Dict[str, str]:
        """Record what Webull gives for ``wanted``; the symbols it does not know."""
        unknown: Dict[str, str] = {}
        symbols = sorted(wanted)
        for start in range(0, len(symbols), BATCH):
            if self.stopped:
                break
            batch = symbols[start : start + BATCH]
            while batch and not self.stopped:
                try:
                    rows = self.webull.get(
                        PATH, {"symbols": ",".join(batch), "category": category}
                    )
                    self._unreachable = 0
                except WebullInvalidSymbols as refused:
                    gone = [symbol for symbol in batch if symbol in refused.symbols]
                    if not gone:
                        break  # names nothing we asked for; leave this batch
                    for symbol in gone:
                        unknown[symbol] = wanted[symbol]
                    batch = [
                        symbol for symbol in batch if symbol not in refused.symbols
                    ]
                    continue
                except WebullRefused:
                    self.stopped = "Webull refused (too many requests)"
                    break
                except WebullUnreachable:
                    self._unreachable += 1
                    if self._unreachable >= UNREACHABLE_LIMIT:
                        self.stopped = "Webull not answering"
                    break
                for item in rows if isinstance(rows, list) else []:
                    security_id = wanted.get(item.get("symbol"))
                    if security_id:
                        self._record(security_id, item, currency, now)
                self.db.commit()
                break
        return unknown

    def _record(self, security_id: str, item: dict, currency, now: datetime) -> None:
        close = _number(item.get("close"))
        stamp = item.get("last_trade_time")
        if close is None or close <= 0 or not stamp:
            return
        traded = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc)
        day = traded.astimezone(MARKET_ZONE).date()
        local_now = now.astimezone(MARKET_ZONE)
        if day > local_now.date() or (
            day == local_now.date() and local_now.time() < FINAL_AFTER
        ):
            self.not_final += 1
            return
        if self.db.get(PriceDailyHist, (security_id, day)) is not None:
            self.on_file += 1
            return
        volume = _number(item.get("volume"))
        self.db.add(
            PriceDailyHist(
                security_id=security_id,
                price_date=day,
                currency=currency.get(security_id) or "USD",
                open=_number(item.get("open")),
                high=_number(item.get("high")),
                low=_number(item.get("low")),
                close=close,
                volume=int(volume) if volume is not None else None,
                last_trade_at=traded,
                source=SOURCE,
            )
        )
        self.recorded += 1
        self.dates.add(day)

    def summary(self, asked: int) -> str:
        days = ", ".join(sorted(d.isoformat() for d in self.dates)) or "no new day"
        parts = [
            f"Closes for {days}: {self.recorded:,} recorded of {asked:,} securities",
            f"{self.on_file:,} already on file",
        ]
        if self.not_final:
            parts.append(f"{self.not_final:,} not final yet, left for the evening run")
        if self.unknown:
            names = sorted(self.unknown)
            shown = ", ".join(names[:10]) + (", …" if len(names) > 10 else "")
            parts.append(f"{len(names):,} unknown to Webull ({shown})")
        if self.stopped:
            parts.append(f"{self.stopped}; stopped for tonight")
        return "; ".join(parts)


def run_daily_closes(db: Session, now: Optional[datetime] = None) -> str:
    return DailyClosesService(db).run(now)


def track_fund(
    db: Session,
    symbol: str,
    group: str,
    today: date,
    note: Optional[str] = None,
) -> TrackedFund:
    """Start tracking a fund, adding it to the security master if it is new."""
    symbol = app_symbol(symbol)
    link = (
        db.query(SecuritySymbol)
        .filter(
            SecuritySymbol.market_code == US_MARKET, SecuritySymbol.symbol == symbol
        )
        .first()
    )
    if link is None:
        security = Security(name=symbol, kind="etf")
        db.add(security)
        db.flush()
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
        db.add(
            SecuritySymbolHist(
                security_id=security.id,
                symbol=symbol,
                valid_from=today,
                source="tracked_fund",
            )
        )
        security_id = security.id
    else:
        security_id = link.security_id
    fund = db.get(TrackedFund, security_id)
    if fund is None:
        fund = TrackedFund(security_id=security_id, asset_group=group, added_on=today)
        db.add(fund)
    else:
        fund.asset_group, fund.removed_on = group, None
    if note is not None:
        fund.note = note
    db.commit()
    return fund


def untrack_fund(db: Session, symbol: str, today: date) -> bool:
    """Stop tracking a fund; its row and prices stay. False if it was not tracked."""
    link = (
        db.query(SecuritySymbol)
        .filter(
            SecuritySymbol.market_code == US_MARKET,
            SecuritySymbol.symbol == app_symbol(symbol),
        )
        .first()
    )
    fund = db.get(TrackedFund, link.security_id) if link else None
    if fund is None or fund.removed_on is not None:
        return False
    fund.removed_on = today
    db.commit()
    return True


def tracked(db: Session) -> Iterable[Tuple[str, str]]:
    """``(symbol, group)`` for every fund tracked now."""
    return (
        db.query(SecuritySymbol.symbol, TrackedFund.asset_group)
        .join(TrackedFund, TrackedFund.security_id == SecuritySymbol.security_id)
        .filter(TrackedFund.removed_on.is_(None))
        .order_by(TrackedFund.asset_group, SecuritySymbol.symbol)
        .all()
    )
