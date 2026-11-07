"""Market data status response schemas"""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class MdJobStatus(BaseModel):
    id: str
    label: str
    outcome: Optional[str] = None  # ok | failed | skipped | running; None if never run
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    requests: Optional[int] = None
    rows_written: Optional[int] = None
    note: Optional[str] = None
    next_run_at: Optional[datetime] = None


class MdIndexStatus(BaseModel):
    code: str
    name: str
    members: int
    expected_min: Optional[int] = None
    expected_max: Optional[int] = None
    in_range: bool
    source: Optional[str] = None
    latest_file: Optional[date] = None


class MdCoverageMeasure(BaseModel):
    label: str
    count: int
    of: int
    of_label: str


class MdNamedCount(BaseModel):
    name: str
    count: int


class MdCoverage(BaseModel):
    securities: int
    companies: int
    measures: List[MdCoverageMeasure]
    by_kind: List[MdNamedCount]
    by_market: List[MdNamedCount]
    sector_sources: List[MdNamedCount]


class MdTableStatus(BaseModel):
    name: str
    kind: str  # current | history | operations
    rows: int
    size_bytes: Optional[int] = None


class MdNotBuilt(BaseModel):
    name: str
    phase: str


class MarketDataStatusResponse(BaseModel):
    generated_at: datetime
    available: bool
    own_database: bool
    attention: List[str]
    jobs: List[MdJobStatus]
    indices: List[MdIndexStatus]
    coverage: Optional[MdCoverage] = None
    tables: List[MdTableStatus]
    not_built: List[MdNotBuilt]
