"""Research: market insights from md, readable by every signed-in user.

Shared reference data (``deps._SHARED_READ_PREFIXES``): a client login may read
these, and nothing here writes. Every read goes through ``read.py``'s research
functions, which use the read-only ``ReadSession`` only.
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.api.schemas.market_data import (
    MdConsistentResponse,
    MdMoversResponse,
    MdReturnsResponse,
    MdSeasonalityResponse,
)
from app.api.schemas.research import (
    RsCalendarResponse,
    RsIndicesResponse,
    RsMonthGridResponse,
    RsMonthResponse,
    RsOutlookResponse,
    RsProfileResponse,
    RsSearchResponse,
    RsSectorsResponse,
    RsTool,
    RsTopPerformersResponse,
    RsWeekResponse,
)
from app.md import read as md_read

router = APIRouter()


def _answer(call, *args, **kwargs):
    """Run one research question; its refusals as the right HTTP answers."""
    try:
        return call(*args, **kwargs)
    except md_read.UnknownSubject as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except md_read.MdUnavailable:
        raise HTTPException(status_code=503, detail="Market data could not be read.")


@router.get("/this-week", response_model=RsWeekResponse)
def research_this_week():
    """The latest week that has ended: indices, funds, sectors, best and worst."""
    return _answer(md_read.research, "this_week")


@router.get("/this-month", response_model=RsMonthResponse)
def research_this_month():
    """This month so far against how the same month has usually gone."""
    return _answer(md_read.research, "this_month")


@router.get("/outlook", response_model=RsOutlookResponse)
def research_outlook(month: Optional[int] = Query(None, ge=1, le=12)):
    """How a calendar month has gone in the past (next month when not given)."""
    return _answer(md_read.research, "month_outlook", month=month)


@router.get("/calendar", response_model=RsCalendarResponse)
def research_calendar(
    symbol: str = Query("SPX"),
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    stat: str = Query("mean", description="mean or median"),
):
    """Average or median daily change by calendar date, with days behind each cell."""
    return _answer(
        md_read.research,
        "calendar_grid",
        symbol=symbol,
        start_year=start_year,
        end_year=end_year,
        stat=stat,
    )


@router.get("/indices", response_model=RsIndicesResponse)
def research_indices():
    """Every index whose level is on file, US and Indian, shown with a leading ^."""
    return _answer(md_read.research, "list_indices")


@router.get("/month-grid", response_model=RsMonthGridResponse)
def research_month_grid(
    symbol: str = Query("SPX"),
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
):
    """Each month's return year by year, with each calendar month's record beneath."""
    return _answer(
        md_read.research,
        "month_grid",
        symbol=symbol,
        start_year=start_year,
        end_year=end_year,
    )


@router.get("/top-performers", response_model=RsTopPerformersResponse)
def research_top_performers(
    month: int = Query(..., ge=1, le=12),
    universe: str = Query("SP500"),
    min_years: int = Query(4, ge=2, le=50),
    limit: int = Query(25, ge=1, le=100),
):
    """Members that beat their index's fund in this month every year on file."""
    return _answer(
        md_read.research,
        "top_performers",
        month=month,
        universe=universe,
        min_years=min_years,
        limit=limit,
    )


@router.get("/sectors", response_model=RsSectorsResponse)
def research_sectors(
    month: int = Query(..., ge=1, le=12),
    universe: str = Query("SP500"),
    compare: Optional[str] = None,
):
    """Each sector's beat rate in a month, for one index or two side by side."""
    return _answer(
        md_read.research,
        "sector_scorecard",
        month=month,
        universe=universe,
        compare=compare,
    )


@router.get("/securities", response_model=RsSearchResponse)
def research_find(
    q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)
):
    """Find securities by ticker or company name."""
    return _answer(md_read.research, "find_security", query=q, limit=limit)


@router.get("/securities/{symbol}", response_model=RsProfileResponse)
def research_profile(symbol: str, month: Optional[int] = Query(None, ge=1, le=12)):
    """One security's profile, month-of-year pattern and one month day by day."""
    return _answer(md_read.research, "security_profile", symbol=symbol, month=month)


@router.get("/returns", response_model=MdReturnsResponse)
def research_returns(
    symbols: str = Query(..., description="Comma-separated: tickers or index codes"),
    grain: str = Query("month"),
    start: Optional[date] = None,
    end: Optional[date] = None,
    benchmark: Optional[str] = None,
):
    """Returns side by side, with the excess over a benchmark."""
    wanted = [s.strip() for s in symbols.split(",") if s.strip()][:20]
    return _answer(
        md_read.market_returns,
        symbols=wanted,
        grain=grain,
        start=start,
        end=end,
        benchmark=benchmark,
    )


@router.get("/seasonality", response_model=MdSeasonalityResponse)
def research_seasonality(
    subject: str = Query(
        ..., description="A ticker, an index code, index:CODE or sector:CODE"
    ),
    by: str = Query(
        "month", description="month | weekday | turn_of_month | trading_day"
    ),
    month: Optional[int] = Query(None, ge=1, le=12),
):
    """How returns fall by month, weekday, turn of the month or day by day."""
    return _answer(md_read.market_seasonality, subject=subject, by=by, month=month)


@router.get("/consistent-months", response_model=MdConsistentResponse)
def research_consistent_months(
    month: int = Query(..., ge=1, le=12),
    benchmark: str = Query("SPY"),
    min_years: int = Query(4, ge=2, le=50),
    universe: Optional[str] = Query(
        None, description="An index code; all priced when empty"
    ),
    limit: int = Query(50, ge=1, le=500),
):
    """Securities that beat a chosen benchmark in this month every year on file."""
    return _answer(
        md_read.consistent_months,
        month=month,
        benchmark=benchmark,
        min_years=min_years,
        universe_index=universe,
        limit=limit,
    )


@router.get("/movers", response_model=MdMoversResponse)
def research_movers(
    grain: str = Query("month", description="week | month"),
    period: Optional[str] = Query(
        None, description="2026-10 or 2026-W44; latest ended"
    ),
    universe: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """The best and worst over one week or month."""
    return _answer(
        md_read.market_movers,
        grain=grain,
        period=period,
        universe_index=universe,
        limit=limit,
    )


@router.get("/tools", response_model=List[RsTool])
def research_tools():
    """Every research function with its description and parameters (JSON Schema):
    the list a chatbot's tools are made from."""
    return md_read.research_tools()
