"""Research (market insights) response schemas."""
from datetime import date
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel


class RsStats(BaseModel):
    count: int
    mean: float
    median: float
    share_up: float
    best: float
    worst: float
    first_year: Optional[int] = None
    last_year: Optional[int] = None


class RsReturnRow(BaseModel):
    symbol: str
    label: str
    basis: str
    ret: float


class RsMover(BaseModel):
    symbol: str
    ret: float


class RsWeekResponse(BaseModel):
    as_of: date
    period: str
    start: date
    end: date
    # The week has trading days left: its returns so far, to the latest close.
    running: bool = False
    indices: List[RsReturnRow]
    funds: List[RsReturnRow]
    sectors: List[RsReturnRow]
    best: List[RsMover]
    worst: List[RsMover]
    notes: List[str]


class RsMonthRow(BaseModel):
    symbol: str
    label: str
    kind: str
    basis: str
    month_to_date: Optional[float] = None
    record: Optional[RsStats] = None


class RsMonthResponse(BaseModel):
    as_of: Optional[date] = None
    month: str
    month_name: str
    rows: List[RsMonthRow]
    notes: List[str]


class RsIndexRecord(BaseModel):
    symbol: str
    label: str
    basis: str
    record: RsStats


class RsBenchmark(BaseModel):
    symbol: str
    basis: str
    universe: Optional[str] = None


class RsPerformerRow(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    years: int
    median_excess: float
    worst_excess: float
    median_return: float


class RsTopPerformersResponse(BaseModel):
    month: int
    month_name: str
    universe: str
    benchmark: RsBenchmark
    min_years: int
    eligible: int
    found: int
    expected_by_luck: float
    rows: List[RsPerformerRow]
    notes: List[str]


class RsSectorResult(BaseModel):
    stocks: int
    observations: int
    beat_share: float
    median_excess: float
    median_return: float


class RsSectorRow(BaseModel):
    sector_code: str
    sector: str
    results: Dict[str, RsSectorResult]


class RsSectorsResponse(BaseModel):
    month: int
    month_name: str
    universes: List[str]
    benchmarks: List[RsBenchmark]
    sectors: List[RsSectorRow]
    notes: List[str]


class RsOutlookResponse(BaseModel):
    month: int
    month_name: str
    indices: List[RsIndexRecord]
    sectors: RsSectorsResponse
    steadiest: RsTopPerformersResponse
    notes: List[str]


class RsCell(BaseModel):
    month: int
    day: int
    value: float
    mean: float
    median: float
    days: int


class RsYears(BaseModel):
    first: int
    last: int
    count: int


class RsYearSpan(BaseModel):
    first: int
    last: int


class RsCalendarResponse(BaseModel):
    symbol: str
    kind: str
    basis: str
    stat: str
    available: Optional[RsYearSpan] = None
    years: RsYears
    cells: List[RsCell]
    best: List[RsCell]
    worst: List[RsCell]
    notes: List[str]


class RsMonthSummary(BaseModel):
    count: int
    mean: float
    median: float
    share_up: float
    share_down: float
    best: float
    worst: float
    abs_mean: float
    abs_best: float
    abs_worst: float


class RsGridYear(BaseModel):
    year: int
    months: Dict[str, float]
    running_month: Optional[int] = None
    ret: float
    complete: bool


class RsNamedMonth(BaseModel):
    year: int
    month: int
    ret: float


class RsMonthGridResponse(BaseModel):
    symbol: str
    kind: str
    basis: str
    available: RsYearSpan
    years: RsYears
    rows: List[RsGridYear]
    summary: Dict[str, Optional[RsMonthSummary]]
    year_summary: Optional[RsMonthSummary] = None
    best: Optional[RsNamedMonth] = None
    worst: Optional[RsNamedMonth] = None
    notes: List[str]


class RsIndex(BaseModel):
    code: str
    display: str
    name: str
    country: str
    currency: str
    group: str
    volatility: bool
    first_day: Optional[date] = None
    last_day: Optional[date] = None


class RsIndicesResponse(BaseModel):
    indices: List[RsIndex]
    notes: List[str]


class RsSearchResult(BaseModel):
    symbol: str
    name: Optional[str] = None
    kind: str
    sector: Optional[str] = None
    indices: List[str]


class RsSearchResponse(BaseModel):
    query: str
    results: List[RsSearchResult]


class RsPeriodReturn(BaseModel):
    period: str
    ret: float


class RsBucket(BaseModel):
    bucket: str
    order: Union[int, str]
    count: int
    mean: float
    median: float
    share_up: float
    stdev: float
    best: float
    worst: float


class RsMonthToDate(BaseModel):
    trading_day: int
    years: int
    mean: float


class RsPattern(BaseModel):
    subject: str
    by: str
    month: Optional[int] = None
    kind: str
    basis: str
    members: Optional[int] = None
    survivorship: bool
    years: Optional[RsYears] = None
    buckets: List[RsBucket]
    month_to_date: Optional[List[RsMonthToDate]] = None


class RsPathDay(BaseModel):
    day: int
    mean: float
    median: float
    years: int


class RsCurrentDay(BaseModel):
    day: int
    ret: float


class RsCurrentMonth(BaseModel):
    year: int
    through: date
    days: List[RsCurrentDay]


class RsMonthPath(BaseModel):
    typical: List[RsPathDay]
    years: int
    current: Optional[RsCurrentMonth] = None


class RsProfileResponse(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    kind: str
    basis: str
    indices: List[str]
    first_day: date
    last_day: date
    last_12_months: List[RsPeriodReturn]
    month_of_year: RsPattern
    month: int
    month_name: str
    month_by_trading_day: RsPattern
    month_path: RsMonthPath
    sector_month_of_year: Optional[RsPattern] = None
    notes: List[str]


class RsTool(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]
