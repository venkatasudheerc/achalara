"""The state of the ``md`` schema, for the Market data page.

Read from the database each time, so it cannot drift from what is there, and it
only reads. Reached from outside this package through ``read.market_data_status``.
"""
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.md.models import (
    SCHEMA,
    Company,
    IndexDef,
    IndexMember,
    JobRun,
    Security,
    SecurityClassification,
    SourceFile,
)
from app.md.schedule import MD_JOBS
from app.md.base import MdBase

STOCK_KINDS = ("stock", "adr", "preferred")
# Planned in MARKET_DATA.md § 1; each leaves this list once its model exists.
PLANNED_TABLES = (
    ("tracked_fund", "3a"),
    ("security_quote", "3a"),
    ("price_daily_hist", "3a"),
    ("statement_hist", "4"),
    ("fundamentals", "4"),
    ("fundamentals_hist", "4"),
    ("dividend_hist", "4"),
    ("earnings_hist", "4"),
    ("corporate_action_hist", "4"),
    ("fx_rate_hist", "when a market outside the US is added"),
)
_OPERATIONS = ("source_file", "job_run")
# Older than this needs a look. The funds publish on market days, so a long
# weekend is under five days; every job runs at least five days a week.
FILE_STALE_DAYS = 5
JOB_STALE_DAYS = 4


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _kind(table: str) -> str:
    if table in _OPERATIONS:
        return "operations"
    return "history" if table.endswith("_hist") else "current"


def _tables(db: Session) -> List[Dict]:
    postgres = db.get_bind().dialect.name == "postgresql"
    built = sorted(
        (table for table in MdBase.metadata.tables.values() if table.schema == SCHEMA),
        key=lambda table: table.name,
    )
    return [
        {
            "name": table.name,
            "kind": _kind(table.name),
            "rows": db.query(func.count()).select_from(table).scalar(),
            "size_bytes": db.execute(
                text("select pg_total_relation_size(:name)"),
                {"name": f"{SCHEMA}.{table.name}"},
            ).scalar()
            if postgres
            else None,
        }
        for table in built
    ]


def _not_built() -> List[Dict]:
    built = {
        table.name
        for table in MdBase.metadata.tables.values()
        if table.schema == SCHEMA
    }
    rows = [
        {"name": name, "phase": phase}
        for name, phase in PLANNED_TABLES
        if name not in built
    ]
    if "share_class_figi" not in Security.__table__.c:
        rows.append({"name": "security.share_class_figi", "phase": "2b"})
    return rows


def _jobs(db: Session, now: datetime, attention: List[str]) -> List[Dict]:
    rows = []
    for job in MD_JOBS:
        last = (
            db.query(JobRun)
            .filter(JobRun.job == job.id)
            .order_by(JobRun.started_at.desc())
            .first()
        )
        started = _aware(last.started_at) if last else None
        if last is None:
            attention.append(f"{job.label} has not run yet.")
        elif last.outcome == "failed":
            attention.append(f"{job.label} failed on its last run.")
        elif last.outcome != "running" and (now - started).days >= JOB_STALE_DAYS:
            days = round((now - started).total_seconds() / 86400)
            attention.append(f"{job.label} last ran {days} days ago.")
        rows.append(
            {
                "id": job.id,
                "label": job.label,
                "outcome": last.outcome if last else None,
                "started_at": started,
                "finished_at": _aware(last.finished_at) if last else None,
                "requests": last.requests if last else None,
                "rows_written": last.rows_written if last else None,
                "note": last.note if last else None,
                "next_run_at": job.trigger().get_next_fire_time(None, now),
            }
        )
    return rows


def _indices(db: Session, today: date, attention: List[str]) -> List[Dict]:
    members = dict(
        db.query(IndexMember.index_code, func.count()).group_by(IndexMember.index_code)
    )
    latest = dict(
        db.query(SourceFile.name, func.max(SourceFile.as_of)).group_by(SourceFile.name)
    )
    rows = []
    for index in db.query(IndexDef).order_by(IndexDef.code):
        count = members.get(index.code, 0)
        in_range = (
            (index.expected_min or 0)
            <= count
            <= (index.expected_max if index.expected_max is not None else count)
        )
        if not in_range:
            attention.append(
                f"{index.code} has {count:,} members, outside what is expected."
            )
        rows.append(
            {
                "code": index.code,
                "name": index.name,
                "members": count,
                "expected_min": index.expected_min,
                "expected_max": index.expected_max,
                "in_range": in_range,
                "source": index.source or index.parts,
                "latest_file": latest.get((index.source or "").split(":")[-1]),
            }
        )
    newest = max(latest.values(), default=None)
    if newest is not None and (today - newest).days >= FILE_STALE_DAYS:
        attention.append(f"The newest index file is from {newest.isoformat()}.")
    return rows


def _coverage(db: Session) -> Dict:
    total = db.query(func.count(Security.id)).scalar()
    stocks = (
        db.query(func.count(Security.id))
        .filter(Security.kind.in_(STOCK_KINDS))
        .scalar()
    )

    def classified(column) -> int:
        return (
            db.query(func.count(column))
            .join(Security, Security.id == SecurityClassification.security_id)
            .filter(Security.kind.in_(STOCK_KINDS))
            .scalar()
        )

    return {
        "securities": total,
        "companies": db.query(func.count(Company.id)).scalar(),
        "measures": [
            {
                "label": "Webull id",
                "count": db.query(func.count(Security.webull_id)).scalar(),
                "of": total,
                "of_label": "securities",
            },
            {
                "label": "FIGI",
                "count": db.query(func.count(Security.figi)).scalar(),
                "of": total,
                "of_label": "securities",
            },
            {
                "label": "SEC company",
                "count": db.query(func.count(Security.company_id)).scalar(),
                "of": total,
                "of_label": "securities",
            },
            {
                "label": "Sector",
                "count": classified(SecurityClassification.sector_code),
                "of": stocks,
                "of_label": "stocks",
            },
            {
                "label": "Industry",
                "count": classified(SecurityClassification.industry_id),
                "of": stocks,
                "of_label": "stocks",
            },
        ],
        "by_kind": [
            {"name": kind, "count": count}
            for kind, count in sorted(
                db.query(Security.kind, func.count()).group_by(Security.kind),
                key=lambda row: -row[1],
            )
        ],
        "by_market": [
            {"name": market, "count": count}
            for market, count in sorted(
                db.query(Security.market_code, func.count()).group_by(
                    Security.market_code
                ),
                key=lambda row: -row[1],
            )
        ],
        "sector_sources": [
            {"name": source, "count": count}
            for source, count in sorted(
                db.query(SecurityClassification.sector_source, func.count()).group_by(
                    SecurityClassification.sector_source
                ),
                key=lambda row: -row[1],
            )
            if source
        ],
    }


def build_status(db: Session, own_database: bool, now: Optional[datetime] = None):
    """Everything the page shows."""
    now = now or datetime.now(timezone.utc)
    attention: List[str] = []
    jobs = _jobs(db, now, attention)
    indices = _indices(db, now.date(), attention)
    return {
        "generated_at": now,
        "available": True,
        "own_database": own_database,
        "attention": attention,
        "jobs": jobs,
        "indices": indices,
        "coverage": _coverage(db),
        "tables": _tables(db),
        "not_built": _not_built(),
    }


def unavailable(now: Optional[datetime] = None) -> Dict:
    """The page's answer when market data's own database cannot be read."""
    return {
        "generated_at": now or datetime.now(timezone.utc),
        "available": False,
        "own_database": True,
        "attention": ["Market data's database could not be read."],
        "jobs": [],
        "indices": [],
        "coverage": None,
        "tables": [],
        "not_built": [],
    }
