"""Performance and seasonality from market data's daily closes.

Securities use adjusted closes (``price_adj_daily``: a total return, dividends
in); indices use their levels (``index_level_hist``: a price return). Nothing
weekly or monthly is stored; every figure is computed from daily rows on
request with ``utils/returns.py``. Every result says its basis and how many
years stand behind it.
"""
from collections import defaultdict
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.md.closes import universe
from app.md.levels import LEVELS
from app.md.models import (
    US_MARKET,
    IndexLevelHist,
    IndexMember,
    PriceAdjDaily,
    SecurityClassification,
    SecuritySymbol,
)
from app.utils.returns import (
    GRAINS,
    day_returns,
    excess,
    period_returns,
    seasonality as summarise_buckets,
    summarise,
    turn_of_month,
)
from app.utils.symbols import app_symbol

Close = Tuple[date, float]
BY = ("month", "weekday", "turn_of_month", "trading_day")
MONTH_NAMES = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
WEEKDAYS = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri"}


class UnknownSubject(ValueError):
    pass


def label(key, grain: str) -> str:
    if grain == "day":
        return key.isoformat()
    if grain == "week":
        return f"{key[0]}-W{key[1]:02d}"
    if grain == "month":
        return f"{key[0]}-{key[1]:02d}"
    if grain == "quarter":
        return f"{key[0]}-Q{key[1]}"
    return str(key[0])


# -- reading closes -------------------------------------------------------


def _security_id(db: Session, symbol: str) -> Optional[str]:
    row = (
        db.query(SecuritySymbol.security_id)
        .filter(
            SecuritySymbol.market_code == US_MARKET,
            SecuritySymbol.symbol == app_symbol(symbol),
        )
        .first()
    )
    return row[0] if row else None


def series(db: Session, symbol: str) -> Tuple[str, str, List[Close]]:
    """``(kind, basis, closes)`` for a security (adjusted) or an index level."""
    code = symbol.strip().upper()
    security_id = _security_id(db, code)
    if security_id is not None:
        rows = (
            db.query(PriceAdjDaily.price_date, PriceAdjDaily.adj_close)
            .filter(PriceAdjDaily.security_id == security_id)
            .order_by(PriceAdjDaily.price_date)
            .all()
        )
        if rows:
            return "security", "total", [(d, float(c)) for d, c in rows]
    if code in LEVELS:
        rows = (
            db.query(IndexLevelHist.price_date, IndexLevelHist.close)
            .filter(IndexLevelHist.symbol == code)
            .order_by(IndexLevelHist.price_date)
            .all()
        )
        if rows:
            return "index", "price", [(d, float(c)) for d, c in rows]
    raise UnknownSubject(f"No prices on file for {symbol}")


def month_end_closes(
    db: Session, security_ids: Optional[Iterable[str]] = None
) -> Dict[str, List[Close]]:
    """Each security's last adjusted close of every month, oldest first: what
    monthly returns need, without reading every day."""
    year = extract("year", PriceAdjDaily.price_date)
    month = extract("month", PriceAdjDaily.price_date)
    last = db.query(
        PriceAdjDaily.security_id.label("sid"),
        func.max(PriceAdjDaily.price_date).label("day"),
    ).group_by(PriceAdjDaily.security_id, year, month)
    if security_ids is not None:
        last = last.filter(PriceAdjDaily.security_id.in_(list(security_ids)))
    last = last.subquery()
    rows = (
        db.query(
            PriceAdjDaily.security_id, PriceAdjDaily.price_date, PriceAdjDaily.adj_close
        )
        .join(
            last,
            (PriceAdjDaily.security_id == last.c.sid)
            & (PriceAdjDaily.price_date == last.c.day),
        )
        .order_by(PriceAdjDaily.security_id, PriceAdjDaily.price_date)
    )
    out: Dict[str, List[Close]] = defaultdict(list)
    for security_id, day, close in rows:
        out[security_id].append((day, float(close)))
    return out


def _complete_months(
    closes: Sequence[Close], today: date
) -> Dict[Tuple[int, int], float]:
    """Monthly returns for months that have ended, keyed ``(year, month)``."""
    return {
        r.key: r.ret
        for r in period_returns(closes, "month", as_of=today)
        if not r.partial
    }


# -- period returns side by side ---------------------------------------------


def returns(
    db: Session,
    symbols: Sequence[str],
    grain: str,
    start: Optional[date] = None,
    end: Optional[date] = None,
    benchmark: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict:
    if grain not in GRAINS:
        raise ValueError(f"grain must be one of {', '.join(GRAINS)}")
    today = today or date.today()
    bench = None
    if benchmark:
        kind, basis, closes = series(db, benchmark)
        bench = {
            "symbol": benchmark.strip().upper(),
            "basis": basis,
            "returns": {
                r.key: r.ret for r in period_returns(closes, grain, as_of=today)
            },
        }
    out, unknown = [], []
    for symbol in symbols:
        try:
            kind, basis, closes = series(db, symbol)
        except UnknownSubject:
            unknown.append(symbol)
            continue
        rows = [
            r
            for r in period_returns(closes, grain, as_of=today)
            if (start is None or r.end >= start) and (end is None or r.start <= end)
        ]
        over = excess({r.key: r.ret for r in rows}, bench["returns"]) if bench else {}
        out.append(
            {
                "symbol": symbol.strip().upper(),
                "kind": kind,
                "basis": basis,
                "first_day": closes[0][0],
                "periods": [
                    {
                        "period": label(r.key, grain),
                        "start": r.start,
                        "end": r.end,
                        "ret": r.ret,
                        "partial": r.partial,
                        "excess": over.get(r.key),
                    }
                    for r in rows
                ],
            }
        )
    return {
        "grain": grain,
        "benchmark": {"symbol": bench["symbol"], "basis": bench["basis"]}
        if bench
        else None,
        "series": out,
        "unknown": unknown,
    }


# -- seasonality ------------------------------------------------------------


def _members(db: Session, subject: str) -> Tuple[str, List[str]]:
    """``index:SP500`` (members today) or ``sector:IT`` (stocks priced here)."""
    kind, _, code = subject.partition(":")
    code = code.strip().upper()
    if kind == "index":
        ids = [
            row[0]
            for row in db.query(IndexMember.security_id).filter(
                IndexMember.index_code == code
            )
        ]
    elif kind == "sector":
        priced = {row[0] for row in universe(db)}
        ids = [
            row[0]
            for row in db.query(SecurityClassification.security_id).filter(
                SecurityClassification.sector_code == code
            )
            if row[0] in priced
        ]
    else:
        raise UnknownSubject(f"Unknown group {subject}; use index:CODE or sector:CODE")
    if not ids:
        raise UnknownSubject(f"No members on file for {subject}")
    return kind, ids


def _group_months(
    db: Session, ids: List[str], today: date
) -> Dict[Tuple[int, int], float]:
    """Equal-weighted average of the members' monthly returns, month by month."""
    totals: Dict[Tuple[int, int], List[float]] = defaultdict(list)
    for closes in month_end_closes(db, ids).values():
        for key, ret in _complete_months(closes, today).items():
            totals[key].append(ret)
    return {key: sum(v) / len(v) for key, v in totals.items()}


def seasonality(
    db: Session,
    subject: str,
    by: str = "month",
    month: Optional[int] = None,
    today: Optional[date] = None,
) -> Dict:
    if by not in BY:
        raise ValueError(f"by must be one of {', '.join(BY)}")
    if by == "trading_day" and not month:
        raise ValueError("by=trading_day needs a month (1-12)")
    today = today or date.today()
    result: Dict = {"subject": subject, "by": by, "month": month, "members": None}
    if ":" in subject:
        if by != "month":
            raise ValueError("A group's seasonality is by month only")
        kind, ids = _members(db, subject)
        monthly = _group_months(db, ids, today)
        result.update(
            kind=f"{kind} members, equal-weighted",
            basis="total",
            members=len(ids),
            survivorship=True,
        )
        rows = [(key[1], ret) for key, ret in monthly.items()]
        years = sorted({key[0] for key in monthly})
    else:
        kind, basis, closes = series(db, subject)
        result.update(kind=kind, basis=basis, survivorship=False)
        if by == "month":
            monthly = _complete_months(closes, today)
            rows = [(key[1], ret) for key, ret in monthly.items()]
            years = sorted({key[0] for key in monthly})
        else:
            days = [
                d
                for d in day_returns(closes)
                if (d.day.year, d.day.month) < (today.year, today.month)
            ]
            if by == "weekday":
                rows = [(d.weekday, d.ret) for d in days]
            elif by == "turn_of_month":
                rows = [(turn_of_month(d) or "rest of month", d.ret) for d in days]
            else:
                chosen = [d for d in days if d.day.month == month]
                rows = [(d.trading_day_of_month, d.ret) for d in chosen]
                result["month_to_date"] = _month_to_date(chosen)
            years = sorted(
                {
                    d.day.year
                    for d in days
                    if by != "trading_day" or d.day.month == month
                }
            )
    stats = summarise_buckets(rows)
    result["years"] = (
        {"first": years[0], "last": years[-1], "count": len(years)} if years else None
    )
    result["buckets"] = [
        {"bucket": _bucket_label(bucket, by), "order": bucket, **values}
        for bucket, values in sorted(
            stats.items(), key=lambda item: _order(item[0], by)
        )
    ]
    return result


def _month_to_date(days) -> List[Dict]:
    """Each trading day's average return so far in the month, across years."""
    paths: Dict[int, List[float]] = defaultdict(list)
    running: Dict[int, float] = {}
    for d in sorted(days, key=lambda d: d.day):
        running[d.day.year] = (1 + running.get(d.day.year, 0.0)) * (1 + d.ret) - 1
        paths[d.trading_day_of_month].append(running[d.day.year])
    return [
        {"trading_day": t, "years": len(v), "mean": sum(v) / len(v)}
        for t, v in sorted(paths.items())
    ]


def _order(bucket, by: str):
    if by == "turn_of_month":
        return {"last day": 0, "day 1": 1, "day 2": 2, "day 3": 3}.get(bucket, 4)
    return bucket


def _bucket_label(bucket, by: str) -> str:
    if by == "month":
        return MONTH_NAMES[bucket - 1]
    if by == "weekday":
        return WEEKDAYS.get(bucket, str(bucket))
    if by == "trading_day":
        return f"trading day {bucket}"
    return str(bucket)


# -- across many stocks -----------------------------------------------------


def _universe_ids(db: Session, index: Optional[str]) -> List[str]:
    if index:
        return [
            row[0]
            for row in db.query(IndexMember.security_id).filter(
                IndexMember.index_code == index.strip().upper()
            )
        ]
    return [row[0] for row in universe(db)]


def _symbols(db: Session, ids: Iterable[str]) -> Dict[str, str]:
    return dict(
        db.query(SecuritySymbol.security_id, SecuritySymbol.symbol).filter(
            SecuritySymbol.security_id.in_(list(ids))
        )
    )


def consistent_months(
    db: Session,
    month: int,
    benchmark: str = "SPY",
    min_years: int = 4,
    universe_index: Optional[str] = None,
    limit: int = 50,
    today: Optional[date] = None,
) -> Dict:
    """Securities that beat ``benchmark`` in ``month`` every year on file, with
    what is needed to judge whether that is more than luck."""
    if not 1 <= month <= 12:
        raise ValueError("month must be 1-12")
    today = today or date.today()
    _, bench_basis, bench_closes = series(db, benchmark)
    bench = _complete_months(bench_closes, today)
    ids = _universe_ids(db, universe_index)
    closes = month_end_closes(db, ids)
    sectors = dict(
        db.query(
            SecurityClassification.security_id, SecurityClassification.sector_code
        ).filter(SecurityClassification.security_id.in_(ids))
    )
    eligible = 0
    luck = 0.0
    per: Dict[str, Dict] = {}
    sector_beats: Dict[str, List[bool]] = defaultdict(list)
    for security_id, series_ in closes.items():
        monthly = _complete_months(series_, today)
        over = excess(monthly, bench)
        chosen = {k: v for k, v in over.items() if k[1] == month}
        for value in chosen.values():
            if sectors.get(security_id):
                sector_beats[sectors[security_id]].append(value > 0)
        if len(chosen) < min_years:
            continue
        eligible += 1
        luck += 0.5 ** len(chosen)
        if not all(v > 0 for v in chosen.values()):
            continue
        others = [v > 0 for k, v in over.items() if k[1] != month]
        values = list(chosen.values())
        per[security_id] = {
            "years": len(values),
            "beat": len(values),
            "avg_excess": sum(values) / len(values),
            "median_excess": summarise(values)["median"],
            "worst_excess": min(values),
            "other_months_beat_share": sum(others) / len(others) if others else None,
            "sector": sectors.get(security_id),
        }
    names = _symbols(db, per)
    rows = [
        {
            "symbol": names.get(security_id, security_id),
            **values,
            "sector_beat_share": (
                sum(sector_beats[values["sector"]])
                / len(sector_beats[values["sector"]])
                if values["sector"] and sector_beats[values["sector"]]
                else None
            ),
        }
        for security_id, values in per.items()
    ]
    rows.sort(key=lambda r: r["avg_excess"], reverse=True)
    long_run = None
    if "SPX" in LEVELS:
        try:
            _, _, spx = series(db, "SPX")
            spx_months = [
                v for k, v in _complete_months(spx, today).items() if k[1] == month
            ]
            long_run = (
                {"index": "SPX", "basis": "price", **summarise(spx_months)}
                if spx_months
                else None
            )
        except UnknownSubject:
            long_run = None
    return {
        "month": month,
        "benchmark": {"symbol": benchmark.strip().upper(), "basis": bench_basis},
        "min_years": min_years,
        "eligible": eligible,
        "found": len(rows),
        "expected_by_luck": luck,
        "index_long_run": long_run,
        "rows": rows[:limit],
    }


def movers(
    db: Session,
    grain: str = "month",
    period: Optional[str] = None,
    universe_index: Optional[str] = None,
    limit: int = 20,
    today: Optional[date] = None,
) -> Dict:
    """The best and worst over one week or month, among index members or every
    security priced here. Without ``period``, the latest one that has ended."""
    if grain not in ("week", "month"):
        raise ValueError("grain must be week or month")
    today = today or date.today()
    ids = _universe_ids(db, universe_index)
    if grain == "month":
        data = month_end_closes(db, ids)
    else:
        since = date.fromordinal(today.toordinal() - 42)
        data = defaultdict(list)
        for sid, day, close in db.query(
            PriceAdjDaily.security_id, PriceAdjDaily.price_date, PriceAdjDaily.adj_close
        ).filter(PriceAdjDaily.security_id.in_(ids), PriceAdjDaily.price_date >= since):
            data[sid].append((day, float(close)))
    found: Dict[str, Dict[str, float]] = defaultdict(dict)  # period -> sid -> return
    ended = set()
    for sid, closes in data.items():
        for r in period_returns(closes, grain, as_of=today):
            name = label(r.key, grain)
            found[name][sid] = r.ret
            if not r.partial:
                ended.add(name)
    chosen = period or (max(ended) if ended else None)
    ranked = sorted(
        found.get(chosen, {}).items(), key=lambda item: item[1], reverse=True
    )
    names = _symbols(db, [sid for sid, _ in ranked])

    def rows(items):
        return [{"symbol": names.get(sid, sid), "ret": ret} for sid, ret in items]

    return {
        "grain": grain,
        "period": chosen,
        "basis": "total",
        "count": len(ranked),
        "best": rows(ranked[:limit]),
        "worst": rows(list(reversed(ranked[-limit:]))) if ranked else [],
    }
