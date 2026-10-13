"""Benchmarks — what a portfolio's return may be compared with.

One list, read by every screen that offers a comparison. To offer another,
add a line here and make sure its closes are on file: a fund's in
``perf.daily_price`` (add it to ``price_history_service.BENCHMARKS``), an
index's in ``index_bars`` (add it to ``index_history_service.INDICES`` and
load its file).

A fund's closes include its dividends; an index level leaves them out, so an
index understates what holding the market would have earned. Each entry says
which it is, and the screens show it.
"""
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.index_bar import IndexBar
from app.models.perf import DailyPrice

FUND, INDEX = "fund", "index"
# What a return is compared with until another is chosen.
DEFAULT = "SPX"

BENCHMARKS: Tuple[Dict, ...] = (
    {"code": "SPX", "name": "S&P 500 index", "kind": INDEX},
    {"code": "NDX", "name": "Nasdaq-100 index", "kind": INDEX},
    {"code": "DJI", "name": "Dow Jones index", "kind": INDEX},
    {"code": "SPY", "name": "S&P 500 (SPY fund)", "kind": FUND},
    {"code": "QQQ", "name": "Nasdaq-100 (QQQ fund)", "kind": FUND},
    {"code": "DIA", "name": "Dow Jones (DIA fund)", "kind": FUND},
)


def choices() -> List[Dict]:
    """The list as a screen offers it."""
    return [
        {
            "code": entry["code"],
            "name": entry["name"],
            "includes_dividends": entry["kind"] == FUND,
        }
        for entry in BENCHMARKS
    ]


def find(code: Optional[str]) -> Optional[Dict]:
    """The listed benchmark with this code, or None."""
    wanted = (code or "").strip().upper()
    return next((entry for entry in BENCHMARKS if entry["code"] == wanted), None)


def closes(db: Session, code: str) -> List[Tuple[date, float]]:
    """A benchmark's daily closes, oldest first.

    A listed index is read from ``index_bars``; anything else, listed or not,
    from the fund closes in ``perf.daily_price``.
    """
    entry = find(code)
    if entry and entry["kind"] == INDEX:
        rows = (
            db.query(IndexBar.bar_date, IndexBar.close)
            .filter(IndexBar.symbol == entry["code"])
            .order_by(IndexBar.bar_date)
        )
    else:
        rows = (
            db.query(DailyPrice.price_date, DailyPrice.close)
            .filter(
                DailyPrice.symbol == code.strip().upper(),
                DailyPrice.source == "webull",
            )
            .order_by(DailyPrice.price_date)
        )
    return [(day, float(close)) for day, close in rows]
