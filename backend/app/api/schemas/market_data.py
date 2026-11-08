"""Market data status response schemas"""
from datetime import date, datetime
from typing import List, Optional, Union

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


class MdBenchmarkRef(BaseModel):
    symbol: str
    basis: str  # total (dividends in) | price (an index level)


class MdPeriod(BaseModel):
    period: str  # 2026-11, 2026-W45, 2026-Q4, 2026 or a date
    start: date
    end: date
    ret: float
    partial: bool
    excess: Optional[float] = None


class MdReturnSeries(BaseModel):
    symbol: str
    kind: str  # security | index
    basis: str
    first_day: date
    periods: List[MdPeriod]


class MdReturnsResponse(BaseModel):
    grain: str
    benchmark: Optional[MdBenchmarkRef] = None
    series: List[MdReturnSeries]
    unknown: List[str]


class MdStats(BaseModel):
    count: int
    mean: float
    median: float
    share_up: float
    stdev: float
    best: float
    worst: float


class MdBucket(MdStats):
    bucket: str
    order: Union[int, str]


class MdYears(BaseModel):
    first: int
    last: int
    count: int


class MdMonthToDate(BaseModel):
    trading_day: int
    years: int
    mean: float


class MdSeasonalityResponse(BaseModel):
    subject: str
    by: str
    month: Optional[int] = None
    kind: str
    basis: str
    members: Optional[int] = None
    survivorship: bool
    years: Optional[MdYears] = None
    buckets: List[MdBucket]
    month_to_date: Optional[List[MdMonthToDate]] = None


class MdConsistentRow(BaseModel):
    symbol: str
    years: int
    beat: int
    avg_excess: float
    median_excess: float
    worst_excess: float
    other_months_beat_share: Optional[float] = None
    sector: Optional[str] = None
    sector_beat_share: Optional[float] = None


class MdLongRun(MdStats):
    index: str
    basis: str


class MdConsistentResponse(BaseModel):
    month: int
    benchmark: MdBenchmarkRef
    min_years: int
    eligible: int
    found: int
    expected_by_luck: float
    index_long_run: Optional[MdLongRun] = None
    rows: List[MdConsistentRow]


class MdMover(BaseModel):
    symbol: str
    ret: float


class MdMoversResponse(BaseModel):
    grain: str
    period: Optional[str] = None
    basis: str
    count: int
    best: List[MdMover]
    worst: List[MdMover]
