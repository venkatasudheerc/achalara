"""System status — one reading of whether everything is running as it should.

For the advisor's status page: the daily jobs, the brokerage accounts, how
fresh the data is, the last backup, and the latest warnings. ``attention``
lists, in plain words, whatever needs a person to look.
"""
import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.account import Account
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.client import Client
from app.models.index_bar import IndexBar
from app.models.perf import DailyPrice, DailyValuation
from app.models.trade import Trade
from app.services import run_log, scheduler
from app.services.auth_service import display_name
from app.services.connection_service import MIN_SYNC_INTERVAL
from app.services.performance_build_service import last_market_day

JOBS = (
    ("daily_sheets_sync", "Sheet sync"),
    ("brokerage_link_check", "Brokerage link check"),
    ("daily_brokerage_sync", "Brokerage sync"),
    ("daily_capture", "Daily capture"),
    ("index_history", "Index history"),
    ("capture_catch_up", "Catch-up capture at start"),
)
# A backup older than this, or transactions further behind than this, is pointed out.
BACKUP_MAX_AGE = timedelta(hours=36)
TRANSACTIONS_MAX_LAG = timedelta(days=5)
DISK_MIN_FREE_SHARE = 0.15


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    """SQLite hands timestamps back without a zone; they were stored in UTC."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class StatusService:
    def __init__(self, db: Session):
        self.db = db

    def status(self, now: Optional[datetime] = None) -> Dict:
        now = now or datetime.now(timezone.utc)
        attention: List[str] = []
        database = self._database(attention)
        jobs = self._jobs(attention)
        links = self._brokerage_links(attention)
        accounts = self._brokerage_accounts(now, attention)
        capture = self._capture(now.date(), accounts, attention)
        backup = self._backup(now, attention)
        disk = self._disk(attention)
        if settings.python_env == "production" and not settings.scheduler_enabled:
            attention.append("The daily jobs are switched off on this server.")
        return {
            "generated_at": now,
            "attention": attention,
            "app": {
                "environment": settings.python_env,
                "started_at": run_log.started_at(),
                "scheduler_enabled": settings.scheduler_enabled,
            },
            "database": database,
            "disk": disk,
            "jobs": jobs,
            "brokerage_links": links,
            "brokerage_accounts": accounts,
            "capture": capture,
            "data": self._data(),
            "backup": backup,
            "recent_log": run_log.recent(),
        }

    def _database(self, attention: List[str]) -> Dict:
        reading = {"ok": True, "size_bytes": None, "migration": None}
        try:
            self.db.execute(text("select 1"))
            if self.db.get_bind().dialect.name == "postgresql":
                reading["size_bytes"] = self.db.execute(
                    text("select pg_database_size(current_database())")
                ).scalar()
                reading["migration"] = self.db.execute(
                    text("select version_num from alembic_version")
                ).scalar()
        except Exception:
            self.db.rollback()
            reading["ok"] = False
            attention.append("The database did not answer.")
        return reading

    def _jobs(self, attention: List[str]) -> List[Dict]:
        times = scheduler.job_times()
        jobs = []
        for job_id, label in JOBS:
            run = run_log.last_run(job_id) or {}
            if run and not run["ok"]:
                attention.append(f"{label} failed on its last run.")
            jobs.append(
                {
                    "id": job_id,
                    "label": label,
                    "next_run_at": times.get(job_id),
                    "last_started_at": run.get("started_at"),
                    "last_finished_at": run.get("finished_at"),
                    "last_ok": run.get("ok"),
                    "last_error": run.get("error"),
                }
            )
        return jobs

    def _brokerage_links(self, attention: List[str]) -> List[Dict]:
        """Each brokerage login on file, and whether the source still shares it."""
        counts = dict(
            self.db.query(
                BrokerageAccount.connection_id, func.count(BrokerageAccount.id)
            )
            .filter(BrokerageAccount.status != "ignored")
            .group_by(BrokerageAccount.connection_id)
        )
        rows = (
            self.db.query(BrokerageConnection, Client)
            .outerjoin(Client, BrokerageConnection.client_id == Client.id)
            .filter(BrokerageConnection.status != "deleted")
            .order_by(BrokerageConnection.institution)
        )
        links = []
        for connection, client in rows:
            name = connection.institution or "Brokerage"
            disabled_at = _aware(connection.disabled_at)
            if connection.status != "active":
                since = f" on {disabled_at.date().isoformat()}" if disabled_at else ""
                attention.append(
                    f"The {name} link stopped sharing data{since}. "
                    "Sign in to it again from the client's page."
                )
            links.append(
                {
                    "id": connection.id,
                    "institution": name,
                    "source": connection.source,
                    "status": connection.status,
                    "checked_at": _aware(connection.status_checked_at),
                    "disabled_at": disabled_at,
                    "client_id": connection.client_id,
                    "client": client.name if client else None,
                    "accounts": counts.get(connection.id, 0),
                }
            )
        return links

    def _brokerage_accounts(self, now: datetime, attention: List[str]) -> List[Dict]:
        captured = dict(
            self.db.query(
                DailyValuation.account_id, func.max(DailyValuation.as_of_date)
            )
            .filter(
                DailyValuation.account_id.isnot(None),
                DailyValuation.basis == "observed",
            )
            .group_by(DailyValuation.account_id)
        )
        rows = (
            self.db.query(BrokerageAccount, BrokerageConnection, Account, Client)
            .join(
                BrokerageConnection,
                BrokerageAccount.connection_id == BrokerageConnection.id,
            )
            .outerjoin(Account, BrokerageAccount.account_id == Account.id)
            .outerjoin(Client, Account.client_id == Client.id)
            .filter(BrokerageAccount.status != "ignored")
            .order_by(Client.name, BrokerageAccount.name)
        )
        accounts = []
        for ba, connection, account, owner in rows:
            # Never the full account number, which the brokerage puts in the name.
            name = display_name(account or ba)
            last = _aware(ba.last_synced_at)
            reconciliation = ba.reconciliation or {}
            through = ba.transactions_synced_through
            if (
                ba.status == "mapped"
                and through is not None
                and now.date() - through > TRANSACTIONS_MAX_LAG
            ):
                attention.append(
                    f"Transactions for {name} stop at {through.isoformat()}."
                )
            accounts.append(
                {
                    "id": ba.id,
                    "name": name,
                    "number_last4": ba.number_last4,
                    "owner": owner.name if owner else None,
                    "status": ba.status,
                    "connection_status": connection.status,
                    "last_synced_at": last,
                    "next_sync_allowed_at": last + MIN_SYNC_INTERVAL if last else None,
                    "transactions_synced_through": through,
                    "captured_through": captured.get(ba.account_id),
                    "holdings_differ": len(reconciliation.get("drifted") or [])
                    if ba.reconciliation
                    else None,
                    "skipped_rows": sum(
                        (reconciliation.get("skipped_rows") or {}).values()
                    ),
                }
            )
        return accounts

    def _capture(self, today: date, accounts: List[Dict], attention: List[str]) -> Dict:
        """Whether every mapped account has the last finished market day on record."""
        day = last_market_day(today - timedelta(days=1))
        mapped = [
            a
            for a in accounts
            if a["status"] == "mapped" and a["connection_status"] == "active"
        ]
        missing = [
            a["name"]
            for a in mapped
            if a["captured_through"] is None or a["captured_through"] < day
        ]
        if missing:
            attention.append(
                f"{len(missing)} of {len(mapped)} accounts have no record for {day.isoformat()}."
            )
        return {"market_day": day, "accounts": len(mapped), "missing": missing}

    def _data(self) -> Dict:
        prices = self.db.query(
            func.count(func.distinct(DailyPrice.symbol)),
            func.max(DailyPrice.price_date),
        ).one()
        indices = (
            self.db.query(
                IndexBar.symbol, func.max(IndexBar.bar_date), func.count(IndexBar.id)
            )
            .group_by(IndexBar.symbol)
            .order_by(IndexBar.symbol)
        )
        return {
            "clients": self.db.query(func.count(Client.id)).scalar(),
            "accounts": self.db.query(func.count(Account.id)).scalar(),
            "trades": self.db.query(func.count(Trade.id)).scalar(),
            "latest_trade_date": self.db.query(func.max(Trade.trade_date)).scalar(),
            "priced_symbols": prices[0],
            "latest_price_date": prices[1],
            "indices": [
                {"symbol": symbol, "latest_date": latest, "days": days}
                for symbol, latest, days in indices
            ],
        }

    def _backup(self, now: datetime, attention: List[str]) -> Dict:
        """The nightly backup's last result, as the server's script reported it."""
        unknown = {"known": False, "at": None, "file": None, "size_bytes": None}
        if not settings.status_dir:
            return unknown
        try:
            report = json.loads((Path(settings.status_dir) / "backup.json").read_text())
            at = datetime.fromisoformat(report["at"].replace("Z", "+00:00"))
        except (OSError, ValueError, KeyError):
            attention.append("No database backup has been reported yet.")
            return unknown
        if now - at > BACKUP_MAX_AGE:
            attention.append(
                f"The last database backup was on {at.date().isoformat()}."
            )
        return {
            "known": True,
            "at": at,
            "file": report.get("file"),
            "size_bytes": report.get("size_bytes"),
        }

    def _disk(self, attention: List[str]) -> Dict:
        usage = shutil.disk_usage("/")
        if usage.free / usage.total < DISK_MIN_FREE_SHARE:
            attention.append("The server's disk is nearly full.")
        return {"total_bytes": usage.total, "free_bytes": usage.free}
