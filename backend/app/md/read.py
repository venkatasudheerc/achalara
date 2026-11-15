"""What the app may ask market data: the one way in from outside this package.

Nothing elsewhere in the app imports this package's tables (a test holds that),
so ``md`` can move to a database of its own by changing a setting. While it
shares the app's database these use the caller's session; once it has its own,
they open one, and a database that cannot be reached raises ``MdUnavailable``.
"""
from contextlib import contextmanager
from datetime import date, datetime
from typing import Dict, Iterable, List, NamedTuple, Optional

from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.md import insights as md_insights
from app.md import performance as md_performance
from app.md.database import MdSession, ReadSession, separate
from app.md.models import (
    JobRun,
    Security,
    SecurityClassification,
    SecuritySymbol,
    SecuritySymbolHist,
    Sector,
    US_MARKET,
)
from app.md.status_report import build_status, unavailable
from app.utils.symbols import app_symbol

STOCK_KINDS = ("stock", "adr", "preferred")


class MdUnavailable(Exception):
    """Market data has its own database, and it cannot be read."""


class LastRun(NamedTuple):
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    outcome: str
    note: Optional[str]


@contextmanager
def _session(app_db: Session):
    if not separate():
        yield app_db
        return
    own = MdSession()
    try:
        yield own
    except SQLAlchemyError as exc:
        raise MdUnavailable(type(exc).__name__) from exc
    finally:
        own.close()


def last_run(app_db: Session, job: str) -> Optional[LastRun]:
    """A job's most recent finished run, or None if it has never finished."""
    with _session(app_db) as db:
        row = (
            db.query(JobRun)
            .filter(JobRun.job == job, JobRun.outcome != "running")
            .order_by(JobRun.started_at.desc())
            .first()
        )
        if row is None:
            return None
        return LastRun(row.started_at, row.finished_at, row.outcome, row.note)


def has_run(app_db: Session, job: str) -> bool:
    """Whether a job has ever started."""
    with _session(app_db) as db:
        return db.query(JobRun.id).filter(JobRun.job == job).first() is not None


def stale_index_levels(app_db: Session) -> Optional[str]:
    """A line naming the indices with no new level lately (or none at all), or None."""
    from app.md.levels import describe_stale, stale_levels

    with _session(app_db) as db:
        return describe_stale(stale_levels(db, date.today()))


class TickerChange(NamedTuple):
    old: str
    new: str
    on: date  # the first day under the new ticker


def ticker_changes(app_db: Session) -> List[TickerChange]:
    """Every change of ticker market data has seen happen to one security (by its
    permanent id), in the app's spelling, oldest first. Only what was watched:
    a change from before a security was first followed is not here."""
    with _session(app_db) as db:
        rows = (
            db.query(SecuritySymbolHist.security_id, SecuritySymbolHist.symbol, SecuritySymbolHist.valid_from)
            .filter(SecuritySymbolHist.market_code == US_MARKET)
            .order_by(SecuritySymbolHist.security_id, SecuritySymbolHist.valid_from)
            .all()
        )
    changes: List[TickerChange] = []
    for (security, symbol, since), (later_security, later_symbol, later_since) in zip(rows, rows[1:]):
        old, new = app_symbol(symbol), app_symbol(later_symbol)
        if security == later_security and old != new:
            changes.append(TickerChange(old, new, later_since))
    return sorted(changes, key=lambda c: c.on)


def stocks_without_sector(app_db: Session, symbols: Iterable[str]) -> int:
    """How many of these symbols, in any spelling, are stocks with no sector."""
    wanted = {app_symbol(symbol) for symbol in symbols if symbol}
    with _session(app_db) as db:
        return (
            db.query(func.count(SecuritySymbol.symbol))
            .join(Security, Security.id == SecuritySymbol.security_id)
            .outerjoin(
                SecurityClassification,
                SecurityClassification.security_id == Security.id,
            )
            .filter(
                SecuritySymbol.market_code == US_MARKET,
                SecuritySymbol.symbol.in_(wanted),
                Security.kind.in_(STOCK_KINDS),
                SecurityClassification.sector_code.is_(None),
            )
            .scalar()
        )


class SectorOf(NamedTuple):
    kind: str
    sector_code: Optional[str]
    sector_name: Optional[str]


def sectors_for(app_db: Session, symbols: Iterable[str]) -> Dict[str, SectorOf]:
    """Each of these US symbols market data knows: its kind and, where it has
    one, its GICS sector. A symbol market data does not know is left out."""
    wanted = sorted({app_symbol(symbol) for symbol in symbols if symbol})
    found: Dict[str, SectorOf] = {}
    with _session(app_db) as db:
        for start in range(0, len(wanted), 500):
            rows = (
                db.query(SecuritySymbol.symbol, Security.kind, Sector.code, Sector.name)
                .join(Security, Security.id == SecuritySymbol.security_id)
                .outerjoin(
                    SecurityClassification,
                    SecurityClassification.security_id == Security.id,
                )
                .outerjoin(Sector, Sector.code == SecurityClassification.sector_code)
                .filter(
                    SecuritySymbol.market_code == US_MARKET,
                    SecuritySymbol.symbol.in_(wanted[start : start + 500]),
                )
                .all()
            )
            for symbol, kind, code, name in rows:
                found[app_symbol(symbol)] = SectorOf(kind, code, name)
    return found


def _status(app_db: Session) -> Dict:
    with _session(app_db) as db:
        return build_status(db, separate())


def market_data_status(app_db: Session) -> Dict:
    """The state of the schema for the Market data page, even if it cannot be read."""
    try:
        return _status(app_db)
    except MdUnavailable:
        return unavailable()


def research_tools() -> List[Dict]:
    """The research functions a chatbot may call: name, description, parameters.
    Reads nothing."""
    return [
        {"name": t.name, "description": t.description, "parameters": t.parameters}
        for t in md_insights.TOOLS
    ]


# -- research: read-only, through ReadSession only ---------------------------
#
# Everything below is for research and (later) the chatbot. It reads md only
# through ReadSession (the md_reader role, read-only sessions), never MdSession
# or the app's session, so nothing here can change data or reach client data.
# tests/test_research_guardrails.py fails if that changes.

UnknownSubject = md_performance.UnknownSubject


@contextmanager
def _read():
    db = ReadSession()
    try:
        yield db
    except SQLAlchemyError as exc:
        raise MdUnavailable(type(exc).__name__) from exc
    finally:
        db.close()


def market_returns(**kwargs) -> Dict:
    with _read() as db:
        return md_performance.returns(db, **kwargs)


def market_seasonality(**kwargs) -> Dict:
    with _read() as db:
        return md_performance.seasonality(db, **kwargs)


def consistent_months(**kwargs) -> Dict:
    with _read() as db:
        return md_performance.consistent_months(db, **kwargs)


def market_movers(**kwargs) -> Dict:
    with _read() as db:
        return md_performance.movers(db, **kwargs)


def research(name: str, **kwargs) -> Dict:
    """Run one research function from the registry by name."""
    tool = md_insights.TOOLS_BY_NAME.get(name)
    if tool is None:
        raise ValueError(f"Unknown research function {name}")
    with _read() as db:
        return tool.run(db, **kwargs)
