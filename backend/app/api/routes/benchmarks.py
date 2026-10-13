"""Benchmark market data routes"""
import logging
import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.schemas.benchmark import BenchmarkPoint, BenchmarkResponse
from app.connectors.webull_connector import WebullConnector
from app.db.database import get_db
from app.services import benchmarks

router = APIRouter()
_log = logging.getLogger(__name__)

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^]{0,9}$")


@router.get("/{ticker}/performance", response_model=BenchmarkResponse)
def get_benchmark_performance(
    ticker: str,
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: Session = Depends(get_db),
) -> BenchmarkResponse:
    ticker = ticker.upper().strip()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=422, detail="Invalid ticker symbol")

    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=422, detail="start_date must be on or before end_date"
        )

    listed = benchmarks.find(ticker)
    if listed and listed["kind"] == benchmarks.INDEX:
        # An index is not served by the price source; its closes are on file.
        return BenchmarkResponse(
            ticker=ticker,
            timeseries=[
                BenchmarkPoint(date=day, close=close)
                for day, close in benchmarks.closes(db, ticker)
                if not (start_date and day < start_date)
                and not (end_date and day > end_date)
            ],
        )

    try:
        connector = WebullConnector()
        if not connector.is_configured():
            return BenchmarkResponse(
                ticker=ticker,
                timeseries=[],
                warning="Benchmark data source not configured — benchmark unavailable",
            )

        series = connector.fetch_price_series(ticker, weeks=260)
        if not series:
            return BenchmarkResponse(
                ticker=ticker,
                timeseries=[],
                warning=f"No benchmark data returned for {ticker}",
            )

        # Series is already (date, close), oldest first; apply the date window.
        points: list[BenchmarkPoint] = [
            BenchmarkPoint(date=bar_date, close=close_val)
            for bar_date, close_val in series
            if not (start_date and bar_date < start_date)
            and not (end_date and bar_date > end_date)
        ]

        return BenchmarkResponse(ticker=ticker, timeseries=points)

    except Exception as exc:
        _log.warning("Benchmark fetch failed for %s: %s", ticker, exc)
        return BenchmarkResponse(
            ticker=ticker,
            timeseries=[],
            warning=f"Failed to fetch benchmark data: {exc}",
        )
