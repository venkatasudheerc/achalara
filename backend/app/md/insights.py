"""Market insights: what the Research page shows, and later the chatbot's only tools.

Each function answers one question from market data and says how much stands
behind the answer: ``as_of``, ``basis`` (``total`` for securities, dividends in;
``price`` for index levels) and ``notes``, short plain-language caveats. The page
and a future chatbot present them the same way, so neither can say more than the
data does. ``TOOLS`` lists every function with a description and its parameters
as JSON Schema; the chatbot's tool definitions are made from it.

These read md only; the session they are given is read-only (``read.ReadSession``).
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.md import performance as perf
from app.md.models import (
    US_MARKET,
    Company,
    IndexMember,
    Industry,
    Security,
    SecurityClassification,
    SecuritySymbol,
)
from app.md.sectors import SECTORS
from app.utils.returns import day_returns, period_returns, summarise
from app.utils.symbols import app_symbol

# Each index's own fund: the fair benchmark for its members (a total return).
BENCHMARK_FOR = {"SP500": "SPY", "R1000": "IWB", "R2000": "IWM", "R3000": "VTI"}
UNIVERSES = tuple(BENCHMARK_FOR)
INDEX_LEVELS = (
    ("SPX", "S&P 500"),
    ("NDX", "Nasdaq-100"),
    ("DJI", "Dow"),
    ("RUT", "Russell 2000"),
)
FUNDS = (
    ("SPY", "S&P 500 fund"),
    ("QQQ", "Nasdaq-100 fund"),
    ("IWM", "Russell 2000 fund"),
    ("EFA", "Developed markets fund"),
    ("EEM", "Emerging markets fund"),
    ("AGG", "US bonds fund"),
    ("TLT", "Long Treasuries fund"),
    ("GLD", "Gold fund"),
    ("SLV", "Silver fund"),
)
# The sector funds, one per GICS sector.
SECTOR_FUNDS = {
    "XLK": "IT",
    "XLF": "FIN",
    "XLV": "HC",
    "XLY": "CD",
    "XLP": "CS",
    "XLE": "EN",
    "XLI": "IND",
    "XLB": "MAT",
    "XLU": "UT",
    "XLRE": "RE",
    "XLC": "COM",
}
SECTOR_NAMES = {code: name for code, name, _ in SECTORS}
PRICE_NOTE = "Index levels leave dividends out; funds and stocks include them."


def _months_label(month: int) -> str:
    return perf.MONTH_NAMES[month - 1]


def _check_month(month: int) -> int:
    if not 1 <= int(month) <= 12:
        raise ValueError("month must be 1-12")
    return int(month)


def _check_universe(universe: str) -> str:
    code = (universe or "").strip().upper()
    if code not in BENCHMARK_FOR:
        raise ValueError(f"universe must be one of {', '.join(UNIVERSES)}")
    return code


def _try_series(db: Session, symbol: str):
    try:
        return perf.series(db, symbol)
    except perf.UnknownSubject:
        return None


def _ended(closes, grain: str, today: date):
    """The returns of periods that have ended, keyed by period."""
    return {
        r.key: r for r in period_returns(closes, grain, as_of=today) if not r.partial
    }


def _stats(values: Sequence[float]) -> Optional[Dict]:
    stats = summarise(values)
    if stats is None:
        return None
    return {
        k: stats[k] for k in ("count", "mean", "median", "share_up", "best", "worst")
    }


# -- this week, this month, next month ----------------------------------------


def this_week(db: Session, today: Optional[date] = None) -> Dict:
    """The latest week that has ended: indices, funds, sectors and the S&P 500's
    best and worst members."""
    today = today or date.today()
    anchor = _try_series(db, "SPY") or _try_series(db, "SPX")
    if anchor is None:
        raise perf.UnknownSubject("No prices on file yet")
    ended = _ended(anchor[2], "week", today)
    if not ended:
        raise perf.UnknownSubject("No complete week on file yet")
    key = max(ended)
    week = ended[key]

    def row(symbol, label_):
        found = _try_series(db, symbol)
        if not found:
            return None
        r = _ended(found[2], "week", today).get(key)
        return (
            {"symbol": symbol, "label": label_, "basis": found[1], "ret": r.ret}
            if r
            else None
        )

    indices = [r for r in (row(s, n) for s, n in INDEX_LEVELS) if r]
    funds = [r for r in (row(s, n) for s, n in FUNDS) if r]
    sectors = [
        r for r in (row(s, SECTOR_NAMES[c]) for s, c in SECTOR_FUNDS.items()) if r
    ]
    sectors.sort(key=lambda r: r["ret"], reverse=True)
    movers = perf.movers(db, "week", perf.label(key, "week"), "SP500", 5, today=today)
    return {
        "as_of": week.end,
        "period": perf.label(key, "week"),
        "start": week.start,
        "end": week.end,
        "indices": indices,
        "funds": funds,
        "sectors": sectors,
        "best": movers["best"],
        "worst": movers["worst"],
        "notes": [
            PRICE_NOTE,
            "Sectors are the 11 sector funds (XLK, XLF, …); best and worst are S&P 500 members.",
        ],
    }


def _month_record(closes, month: int, today: date) -> Optional[Dict]:
    """How this calendar month has gone in every year on file that has ended."""
    values = [r.ret for k, r in _ended(closes, "month", today).items() if k[1] == month]
    stats = _stats(values)
    if stats:
        years = sorted(k[0] for k in _ended(closes, "month", today) if k[1] == month)
        stats.update(first_year=years[0], last_year=years[-1])
    return stats


def this_month(db: Session, today: Optional[date] = None) -> Dict:
    """The month so far against how the same month has usually gone."""
    today = today or date.today()
    rows = []
    as_of = None
    for symbol, label_ in [("SPX", "S&P 500")] + [
        (s, SECTOR_NAMES[c]) for s, c in SECTOR_FUNDS.items()
    ]:
        found = _try_series(db, symbol)
        if not found:
            continue
        kind, basis, closes = found
        running = [
            r
            for r in period_returns(closes, "month", as_of=today)
            if r.key == (today.year, today.month)
        ]
        mtd = running[0] if running else None
        if mtd:
            as_of = max(as_of or mtd.end, mtd.end)
        rows.append(
            {
                "symbol": symbol,
                "label": label_,
                "kind": kind,
                "basis": basis,
                "month_to_date": mtd.ret if mtd else None,
                "record": _month_record(closes, today.month, today),
            }
        )
    return {
        "as_of": as_of,
        "month": f"{today.year}-{today.month:02d}",
        "month_name": _months_label(today.month),
        "rows": rows,
        "notes": [
            "The month is still running; its figure changes until it ends.",
            "The S&P 500's record goes back to 1928; each sector fund's to about five "
            "years, so a sector's 'usual' rests on a handful of months.",
            PRICE_NOTE,
        ],
    }


def month_outlook(
    db: Session, month: Optional[int] = None, today: Optional[date] = None
) -> Dict:
    """How a calendar month has gone in the past: the indices over decades, the
    sectors and the steadiest S&P 500 members over the years on file."""
    today = today or date.today()
    month = _check_month(month or (today.month % 12 + 1))
    indices = []
    for symbol, label_ in INDEX_LEVELS:
        found = _try_series(db, symbol)
        if found:
            record = _month_record(found[2], month, today)
            if record:
                indices.append(
                    {
                        "symbol": symbol,
                        "label": label_,
                        "basis": "price",
                        "record": record,
                    }
                )
    return {
        "month": month,
        "month_name": _months_label(month),
        "indices": indices,
        "sectors": sector_scorecard(db, month, "SP500", today=today),
        "steadiest": top_performers(db, month, "SP500", limit=10, today=today),
        "notes": [
            "This describes the past, not what will happen.",
            "Index records span decades; stock and sector records about five years.",
        ],
    }


# -- the calendar grid --------------------------------------------------------


def calendar_grid(
    db: Session,
    symbol: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    stat: str = "mean",
    today: Optional[date] = None,
) -> Dict:
    """Average (or median) daily change by calendar date, with the days behind each cell."""
    if stat not in ("mean", "median"):
        raise ValueError("stat must be mean or median")
    today = today or date.today()
    kind, basis, closes = perf.series(db, symbol)
    cells: Dict[Tuple[int, int], List[float]] = defaultdict(list)
    years = set()
    for d in day_returns(closes):
        if (d.day.year, d.day.month) >= (today.year, today.month):
            continue
        if start_year and d.day.year < start_year:
            continue
        if end_year and d.day.year > end_year:
            continue
        cells[(d.day.month, d.day.day)].append(d.ret)
        years.add(d.day.year)
    if not cells:
        raise perf.UnknownSubject(f"No complete months on file for {symbol}")
    out = [
        {
            "month": m,
            "day": d,
            "value": (sum(v) / len(v)) if stat == "mean" else median(v),
            "mean": sum(v) / len(v),
            "median": median(v),
            "days": len(v),
        }
        for (m, d), v in sorted(cells.items())
    ]
    most = max(c["days"] for c in out)
    notes = [
        f"Each cell is the {stat} daily change on that date, from the previous close.",
        "Weekends and holidays have no cell: their move shows on the next trading day.",
    ]
    if most < 20:
        notes.append(
            f"At most {most} days stand behind any cell, so one event can decide it; "
            "this shows what happened on those dates, not a seasonal pattern."
        )
    if stat == "mean":
        notes.append("An average can rest on one large day; the median cannot.")
    ranked = sorted(out, key=lambda c: c["value"])
    return {
        "symbol": symbol.strip().upper(),
        "kind": kind,
        "basis": basis,
        "stat": stat,
        "years": {"first": min(years), "last": max(years), "count": len(years)},
        "cells": out,
        "best": list(reversed(ranked[-5:])),
        "worst": ranked[:5],
        "notes": notes,
    }


def _month_summary(values: Sequence[float]) -> Optional[Dict]:
    """Average, median, share up and down, best and worst, and the same by size."""
    if not values:
        return None
    sizes = [abs(v) for v in values]
    return {
        "count": len(values),
        "mean": sum(values) / len(values),
        "median": median(values),
        "share_up": sum(v > 0 for v in values) / len(values),
        "share_down": sum(v < 0 for v in values) / len(values),
        "best": max(values),
        "worst": min(values),
        "abs_mean": sum(sizes) / len(sizes),
        "abs_best": max(sizes),
        "abs_worst": min(sizes),
    }


def month_grid(
    db: Session,
    symbol: str,
    start_year: Optional[int] = None,
    end_year: Optional[int] = None,
    today: Optional[date] = None,
) -> Dict:
    """Each month's return, year by year, with each calendar month's record beneath."""
    today = today or date.today()
    kind, basis, closes = perf.series(db, symbol)
    months = period_returns(closes, "month", as_of=today)
    if not months:
        raise perf.UnknownSubject(f"No whole month on file for {symbol}")
    available = {"first": months[0].key[0], "last": months[-1].key[0]}
    if start_year and end_year and start_year > end_year:
        raise ValueError("start_year is after end_year")
    chosen = [
        m
        for m in months
        if (not start_year or m.key[0] >= start_year)
        and (not end_year or m.key[0] <= end_year)
    ]
    if not chosen:
        raise ValueError(
            f"{symbol} has months on file from {available['first']} to {available['last']}"
        )
    by_year: Dict[int, List] = defaultdict(list)
    for m in chosen:
        by_year[m.key[0]].append(m)
    rows = []
    for year in sorted(by_year, reverse=True):
        on_file = by_year[year]
        growth = 1.0
        for m in on_file:
            growth *= 1 + m.ret
        ended = [m for m in on_file if not m.partial]
        rows.append(
            {
                "year": year,
                "months": {str(m.key[1]): m.ret for m in on_file},
                "running_month": next((m.key[1] for m in on_file if m.partial), None),
                "ret": growth - 1,
                "complete": len(ended) == 12,
            }
        )
    ended = [m for m in chosen if not m.partial]
    summary = {
        str(month): _month_summary([m.ret for m in ended if m.key[1] == month])
        for month in range(1, 13)
    }
    years = [r["ret"] for r in rows if r["complete"]]
    best = max(ended, key=lambda m: m.ret, default=None)
    worst = min(ended, key=lambda m: m.ret, default=None)

    def _named(m):
        return m and {"year": m.key[0], "month": m.key[1], "ret": m.ret}

    notes = [
        "Each cell is the month's return, from the last close of the month before.",
        "A year not whole on file shows the return of its months on file; its row is marked.",
    ]
    if any(r["running_month"] for r in rows):
        notes.append(
            "The month still running is shown in its row but left out of the record below."
        )
    fewest = min((s["count"] for s in summary.values() if s), default=0)
    if fewest < 10:
        notes.append(
            f"Some months have only {fewest} years behind them: a few events decide "
            "their record, so read it as what happened, not as a pattern."
        )
    if kind == "security":
        notes.append(
            "Stock and fund prices go back about five years; indices go back decades."
        )
    notes.append(PRICE_NOTE)
    return {
        "symbol": symbol.strip().upper(),
        "kind": kind,
        "basis": basis,
        "available": available,
        "years": {
            "first": min(by_year),
            "last": max(by_year),
            "count": len(by_year),
        },
        "rows": rows,
        "summary": summary,
        "year_summary": _month_summary(years),
        "best": _named(best),
        "worst": _named(worst),
        "notes": notes,
    }


# -- across many stocks -------------------------------------------------------


def _members(db: Session, universe: str) -> List[str]:
    return [
        row[0]
        for row in db.query(IndexMember.security_id).filter(
            IndexMember.index_code == universe
        )
    ]


def _labels(db: Session, ids: Sequence[str]) -> Dict[str, Dict]:
    """Ticker, name, sector and industry for securities."""
    rows = (
        db.query(
            Security.id,
            SecuritySymbol.symbol,
            Security.name,
            Industry.name,
            SecurityClassification.sector_code,
        )
        .join(SecuritySymbol, SecuritySymbol.security_id == Security.id)
        .outerjoin(
            SecurityClassification, SecurityClassification.security_id == Security.id
        )
        .outerjoin(Industry, Industry.id == SecurityClassification.industry_id)
        .filter(Security.id.in_(list(ids)))
    )
    return {
        sid: {
            "symbol": symbol,
            "name": name if name != symbol else None,
            # The 11 GICS sectors are fixed: named from the list, not looked up.
            "sector": SECTOR_NAMES.get(code) if code else None,
            "industry": industry,
            "sector_code": code,
        }
        for sid, symbol, name, industry, code in rows
    }


def _benchmark_months(db: Session, universe: str, today: date) -> Tuple[str, Dict]:
    symbol = BENCHMARK_FOR[universe]
    found = _try_series(db, symbol)
    if not found:
        raise perf.UnknownSubject(f"No prices on file for the benchmark {symbol}")
    return symbol, {k: r.ret for k, r in _ended(found[2], "month", today).items()}


def top_performers(
    db: Session,
    month: int,
    universe: str = "SP500",
    min_years: int = 4,
    limit: int = 25,
    today: Optional[date] = None,
) -> Dict:
    """Members that beat their index's own fund in this month every year on file,
    by median margin, with how many would do so by chance alone."""
    today = today or date.today()
    month, universe = _check_month(month), _check_universe(universe)
    bench_symbol, bench = _benchmark_months(db, universe, today)
    ids = _members(db, universe)
    found, eligible, luck = [], 0, 0.0
    for sid, months in perf.monthly_returns(db, ids, today).items():
        margins = [
            ret - bench[k] for k, ret in months.items() if k[1] == month and k in bench
        ]
        returns_ = [ret for k, ret in months.items() if k[1] == month and k in bench]
        if len(margins) < min_years:
            continue
        eligible += 1
        luck += 0.5 ** len(margins)
        if all(m > 0 for m in margins):
            found.append(
                (
                    sid,
                    {
                        "years": len(margins),
                        "median_excess": median(margins),
                        "worst_excess": min(margins),
                        "median_return": median(returns_),
                    },
                )
            )
    found.sort(key=lambda item: item[1]["median_excess"], reverse=True)
    labels = _labels(db, [sid for sid, _ in found[:limit]])
    rows = [
        {**labels.get(sid, {"symbol": sid}), **values} for sid, values in found[:limit]
    ]
    for row in rows:
        row.pop("sector_code", None)
    return {
        "month": month,
        "month_name": _months_label(month),
        "universe": universe,
        "benchmark": {"symbol": bench_symbol, "basis": "total"},
        "min_years": min_years,
        "eligible": eligible,
        "found": len(found),
        "expected_by_luck": luck,
        "rows": rows,
        "notes": [
            f"{len(found)} of {eligible} beat {bench_symbol} in every {_months_label(month)} "
            "on file.",
            "Members are today's, so stocks that left the index are missing (survivors only).",
            "Ranked by the typical (median) margin, so one big year cannot carry a stock.",
        ],
    }


def sector_scorecard(
    db: Session,
    month: int,
    universe: str = "SP500",
    compare: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict:
    """For each sector: how often its stocks beat their index's fund in this month."""
    today = today or date.today()
    month = _check_month(month)
    universes = [_check_universe(universe)] + (
        [_check_universe(compare)] if compare else []
    )
    results: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    benchmarks = []
    for code in universes:
        bench_symbol, bench = _benchmark_months(db, code, today)
        benchmarks.append({"universe": code, "symbol": bench_symbol, "basis": "total"})
        ids = _members(db, code)
        sectors = dict(
            db.query(
                SecurityClassification.security_id, SecurityClassification.sector_code
            )
            .filter(SecurityClassification.security_id.in_(ids))
            .filter(SecurityClassification.sector_code.isnot(None))
        )
        margins: Dict[str, List[float]] = defaultdict(list)
        stocks: Dict[str, set] = defaultdict(set)
        for sid, months in perf.monthly_returns(db, ids, today).items():
            sector = sectors.get(sid)
            if not sector:
                continue
            for k, ret in months.items():
                if k[1] == month and k in bench:
                    margins[sector].append(ret - bench[k])
                    stocks[sector].add(sid)
        for sector, values in margins.items():
            results[sector][code] = {
                "stocks": len(stocks[sector]),
                "observations": len(values),
                "beat_share": sum(1 for v in values if v > 0) / len(values),
                "median_excess": median(values),
            }
    first = universes[0]
    rows = [
        {"sector_code": code, "sector": SECTOR_NAMES.get(code, code), "results": res}
        for code, res in results.items()
    ]
    rows.sort(
        key=lambda r: r["results"].get(first, {}).get("beat_share", -1), reverse=True
    )
    return {
        "month": month,
        "month_name": _months_label(month),
        "universes": universes,
        "benchmarks": benchmarks,
        "sectors": rows,
        "notes": [
            "Each stock-year counts once: a sector's share is how often its stocks beat "
            "their index's fund in that month.",
            "A share well above 50% across hundreds of stock-years is a pattern; one "
            "stock's handful of years is not.",
            "Members are today's (survivors only).",
        ],
    }


# -- one security ----------------------------------------------------------------


def find_security(db: Session, query: str, limit: int = 10) -> Dict:
    """Securities whose ticker or name matches, best first."""
    text = (query or "").strip()
    if len(text) < 1:
        raise ValueError("query is empty")
    ticker = app_symbol(text)
    like = f"%{text.lower()}%"
    rows = (
        db.query(
            Security.id,
            SecuritySymbol.symbol,
            Security.name,
            Security.kind,
            Company.name,
        )
        .join(SecuritySymbol, SecuritySymbol.security_id == Security.id)
        .outerjoin(Company, Company.id == Security.company_id)
        .filter(Security.market_code == US_MARKET)
        .filter(
            or_(
                SecuritySymbol.symbol == ticker,
                SecuritySymbol.symbol.like(f"{ticker}%"),
                func.lower(Security.name).like(like),
                func.lower(Company.name).like(like),
            )
        )
        .limit(200)
        .all()
    )

    def rank(row):
        symbol = row[1]
        return (symbol != ticker, not symbol.startswith(ticker), len(symbol), symbol)

    rows.sort(key=rank)
    rows = rows[:limit]
    labels = _labels(db, [r[0] for r in rows])
    indices = defaultdict(list)
    for sid, code in db.query(IndexMember.security_id, IndexMember.index_code).filter(
        IndexMember.security_id.in_([r[0] for r in rows])
    ):
        indices[sid].append(code)
    return {
        "query": text,
        "results": [
            {
                "symbol": symbol,
                "name": (name if name != symbol else None) or company,
                "kind": kind,
                "sector": labels.get(sid, {}).get("sector"),
                "indices": sorted(indices[sid]),
            }
            for sid, symbol, name, kind, company in rows
        ],
    }


def security_profile(
    db: Session, symbol: str, month: Optional[int] = None, today: Optional[date] = None
) -> Dict:
    """One security: who it is, its last 12 months, its month-of-year pattern, one
    month day by day, and its sector's pattern for comparison."""
    today = today or date.today()
    month = _check_month(month or today.month)
    kind, basis, closes = perf.series(db, symbol)
    label = {
        "symbol": symbol.strip().upper(),
        "name": None,
        "sector": None,
        "industry": None,
    }
    indices: List[str] = []
    sector_code = None
    link = (
        db.query(SecuritySymbol.security_id)
        .filter(
            SecuritySymbol.market_code == US_MARKET,
            SecuritySymbol.symbol == app_symbol(symbol),
        )
        .first()
    )
    if link:
        info = _labels(db, [link[0]]).get(link[0], {})
        sector_code = info.pop("sector_code", None)
        label.update({k: v for k, v in info.items() if k != "symbol"})
        indices = sorted(
            row[0]
            for row in db.query(IndexMember.index_code).filter(
                IndexMember.security_id == link[0]
            )
        )
    months = sorted(_ended(closes, "month", today).items())[-12:]
    sector_pattern = None
    if sector_code:
        try:
            sector_pattern = perf.seasonality(
                db, f"sector:{sector_code}", "month", today=today
            )
        except (perf.UnknownSubject, ValueError):
            sector_pattern = None
    return {
        **label,
        "kind": kind,
        "basis": basis,
        "indices": indices,
        "first_day": closes[0][0],
        "last_day": closes[-1][0],
        "last_12_months": [
            {"period": perf.label(k, "month"), "ret": r.ret} for k, r in months
        ],
        "month_of_year": perf.seasonality(db, symbol, "month", today=today),
        "month": month,
        "month_name": _months_label(month),
        "month_by_trading_day": perf.seasonality(
            db, symbol, "trading_day", month=month, today=today
        ),
        "sector_month_of_year": sector_pattern,
        "notes": [
            "A stock's own record is about five years: a pattern in it may be chance; "
            "its sector's record across hundreds of stocks is sturdier.",
            PRICE_NOTE,
        ],
    }


# -- the registry ---------------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: Dict
    run: Callable


def _schema(properties: Dict, required: Sequence[str] = ()) -> Dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


MONTH = {"type": "integer", "minimum": 1, "maximum": 12, "description": "1 = January"}
UNIVERSE = {
    "type": "string",
    "enum": list(UNIVERSES),
    "description": "SP500, R1000, R2000 or R3000 (today's members)",
}
SYMBOL = {
    "type": "string",
    "description": "A ticker (SCHW, SPY) or index code (SPX, NDX, DJI, RUT, RUI, RUA)",
}

TOOLS: Tuple[Tool, ...] = (
    Tool(
        "this_week",
        "The latest week that has ended: index and fund returns, the 11 sectors, and the "
        "S&P 500's best and worst members.",
        _schema({}),
        this_week,
    ),
    Tool(
        "this_month",
        "This month so far for the S&P 500 and each sector, beside how the same month has "
        "usually gone.",
        _schema({}),
        this_month,
    ),
    Tool(
        "month_outlook",
        "How a calendar month has gone in the past: index records over decades, sectors' "
        "beat rates and the steadiest S&P 500 members. Describes the past only.",
        _schema({"month": MONTH}),
        month_outlook,
    ),
    Tool(
        "calendar_grid",
        "Average or median daily change by calendar date (like 'the best day of the "
        "year'), with the days behind each cell.",
        _schema(
            {
                "symbol": SYMBOL,
                "start_year": {"type": "integer"},
                "end_year": {"type": "integer"},
                "stat": {"type": "string", "enum": ["mean", "median"]},
            },
            ["symbol"],
        ),
        calendar_grid,
    ),
    Tool(
        "month_grid",
        "Every month's return year by year for one symbol, with each calendar month's "
        "average, median, share up and down, best and worst, and the year's return.",
        _schema(
            {
                "symbol": SYMBOL,
                "start_year": {"type": "integer"},
                "end_year": {"type": "integer"},
            },
            ["symbol"],
        ),
        month_grid,
    ),
    Tool(
        "top_performers",
        "Members of an index that beat the index's own fund in a given month every year "
        "on file, by median margin, with sector, industry and the number luck would give.",
        _schema(
            {
                "month": MONTH,
                "universe": UNIVERSE,
                "min_years": {"type": "integer", "minimum": 2, "maximum": 50},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            ["month"],
        ),
        top_performers,
    ),
    Tool(
        "sector_scorecard",
        "For each sector, how often its stocks beat their index's fund in a given month, "
        "for one index or two side by side.",
        _schema({"month": MONTH, "universe": UNIVERSE, "compare": UNIVERSE}, ["month"]),
        sector_scorecard,
    ),
    Tool(
        "security_profile",
        "One security: name, sector, industry, indices, last 12 months, month-of-year "
        "pattern, a month day by day, and its sector's pattern.",
        _schema({"symbol": SYMBOL, "month": MONTH}, ["symbol"]),
        security_profile,
    ),
    Tool(
        "find_security",
        "Find securities by ticker or company name ('Schwab' finds SCHW).",
        _schema(
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            ["query"],
        ),
        find_security,
    ),
    Tool(
        "returns",
        "Day, week, month, quarter or year returns for up to 20 symbols side by side, "
        "with the excess over a benchmark.",
        _schema(
            {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 20,
                },
                "grain": {
                    "type": "string",
                    "enum": ["day", "week", "month", "quarter", "year"],
                },
                "benchmark": {"type": "string"},
            },
            ["symbols"],
        ),
        perf.returns,
    ),
    Tool(
        "seasonality",
        "How one symbol's returns fall by month, weekday, turn of the month, or day by day "
        "within a month; or a group's (index:CODE, sector:CODE) by month.",
        _schema(
            {
                "subject": {"type": "string"},
                "by": {
                    "type": "string",
                    "enum": ["month", "weekday", "turn_of_month", "trading_day"],
                },
                "month": MONTH,
            },
            ["subject"],
        ),
        perf.seasonality,
    ),
    Tool(
        "movers",
        "The best and worst over one week or month among an index's members.",
        _schema(
            {
                "grain": {"type": "string", "enum": ["week", "month"]},
                "period": {"type": "string"},
                "universe_index": UNIVERSE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 100},
            }
        ),
        perf.movers,
    ),
)
TOOLS_BY_NAME = {tool.name: tool for tool in TOOLS}
