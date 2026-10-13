"""System status response schemas"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class StatusApp(BaseModel):
    environment: str
    started_at: datetime
    scheduler_enabled: bool


class StatusDatabase(BaseModel):
    ok: bool
    size_bytes: Optional[int] = None
    migration: Optional[str] = None


class StatusDisk(BaseModel):
    total_bytes: int
    free_bytes: int


class StatusJob(BaseModel):
    id: str
    label: str
    next_run_at: Optional[datetime] = None
    # The last run since the app started; empty until the job has run once.
    last_started_at: Optional[datetime] = None
    last_finished_at: Optional[datetime] = None
    last_ok: Optional[bool] = None
    last_error: Optional[str] = None


class StatusBrokerageAccount(BaseModel):
    id: str
    name: str
    number_last4: Optional[str] = None
    owner: Optional[str] = None
    status: str  # unmapped | mapped
    connection_status: str
    last_synced_at: Optional[datetime] = None
    next_sync_allowed_at: Optional[datetime] = None
    transactions_synced_through: Optional[date] = None
    # The latest day with the brokerage's own holdings and total on record.
    captured_through: Optional[date] = None
    holdings_differ: Optional[int] = None  # None until a reconciliation has run
    skipped_rows: int = 0


class StatusCapture(BaseModel):
    market_day: date  # the last finished market day
    accounts: int
    missing: List[str]  # accounts with no record for that day


class StatusIndex(BaseModel):
    symbol: str
    latest_date: Optional[date] = None
    days: int


class StatusData(BaseModel):
    clients: int
    accounts: int
    trades: int
    latest_trade_date: Optional[date] = None
    priced_symbols: int
    latest_price_date: Optional[date] = None
    indices: List[StatusIndex]


class StatusBackup(BaseModel):
    known: bool  # False when the server reports no backup result
    at: Optional[datetime] = None
    file: Optional[str] = None
    size_bytes: Optional[int] = None


class StatusLogEntry(BaseModel):
    at: datetime
    level: str
    source: str
    message: str


class SystemStatusResponse(BaseModel):
    generated_at: datetime
    # What needs a person to look, in plain words; empty when all is well.
    attention: List[str]
    app: StatusApp
    database: StatusDatabase
    disk: StatusDisk
    jobs: List[StatusJob]
    brokerage_accounts: List[StatusBrokerageAccount]
    capture: StatusCapture
    data: StatusData
    backup: StatusBackup
    # Warnings and errors since the app started, newest first.
    recent_log: List[StatusLogEntry]
