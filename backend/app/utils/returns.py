"""Returns from daily closes: periods, seasonality and excess over a benchmark.

Pure functions, no database, shared by the app's portfolio figures and market
data, so both cut weeks and months the same way: ISO weeks (Monday to Sunday)
and calendar months, quarters and years. A period's return runs from the last
close before it to its own last close.
"""
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean, median, pstdev
from typing import Dict, Hashable, Iterable, List, Optional, Sequence, Tuple

GRAINS = ("day", "week", "month", "quarter", "year")
Close = Tuple[date, float]


def period_key(day: date, grain: str):
    """Which day, ISO week, month, quarter or year ``day`` belongs to."""
    if grain == "day":
        return day
    if grain == "week":
        iso = day.isocalendar()
        return (iso[0], iso[1])
    if grain == "month":
        return (day.year, day.month)
    if grain == "quarter":
        return (day.year, (day.month - 1) // 3 + 1)
    if grain == "year":
        return (day.year,)
    raise ValueError(f"grain must be one of {', '.join(GRAINS)}")


def period_end(key, grain: str) -> date:
    """The last calendar day of a period."""
    if grain == "day":
        return key
    if grain == "week":
        return date.fromisocalendar(key[0], key[1], 7)
    if grain == "month":
        return date(key[0], key[1], calendar.monthrange(key[0], key[1])[1])
    if grain == "quarter":
        month = key[1] * 3
        return date(key[0], month, calendar.monthrange(key[0], month)[1])
    return date(key[0], 12, 31)


def still_running(key, grain: str, as_of: date) -> bool:
    """Whether a weekday is left in the period after ``as_of``: a week that ended
    on Friday is over on the Saturday."""
    end = period_end(key, grain)
    day = as_of + timedelta(days=1)
    while day <= end:
        if day.weekday() < 5:
            return True
        day += timedelta(days=1)
    return False


@dataclass(frozen=True)
class PeriodReturn:
    key: Hashable
    start: date  # first trading day in the period
    end: date  # last trading day in the period
    ret: float
    partial: bool  # trading days are left in the period after ``as_of``


def period_returns(
    closes: Sequence[Close], grain: str, as_of: Optional[date] = None
) -> List[PeriodReturn]:
    """Each period's return, oldest first. The first period has no close before
    it and is left out; a period with trading days left after ``as_of`` is
    marked partial."""
    groups: List[List[Close]] = []
    current = None
    for day, close in sorted(closes):
        key = period_key(day, grain)
        if key != current:
            groups.append([])
            current = key
        groups[-1].append((day, close))
    out = []
    for before, group in zip(groups, groups[1:]):
        previous, last = before[-1][1], group[-1][1]
        if not previous:
            continue
        key = period_key(group[0][0], grain)
        partial = bool(as_of) and still_running(key, grain, as_of)
        out.append(
            PeriodReturn(key, group[0][0], group[-1][0], last / previous - 1, partial)
        )
    return out


@dataclass(frozen=True)
class DayReturn:
    day: date
    ret: float
    weekday: int  # 1 Monday … 5 Friday (ISO)
    trading_day_of_month: int  # 1 for the month's first trading day
    trading_days_left: int  # 0 on the month's last trading day on file


def day_returns(closes: Sequence[Close]) -> List[DayReturn]:
    """Each day's return from the previous close, with its place in its month.
    The month of the first close is left out: its earlier days are not on file,
    so a day's place in it is not known. ``trading_days_left`` counts only days
    on file, so it is exact for months that have ended."""
    ordered = sorted(closes)
    if not ordered:
        return []
    first_month = (ordered[0][0].year, ordered[0][0].month)
    by_month: Dict[Tuple[int, int], List[date]] = {}
    for day, _ in ordered:
        by_month.setdefault((day.year, day.month), []).append(day)
    out = []
    for (_, previous), (day, close) in zip(ordered, ordered[1:]):
        if not previous or (day.year, day.month) == first_month:
            continue
        month = by_month[(day.year, day.month)]
        place = month.index(day)
        out.append(
            DayReturn(
                day,
                close / previous - 1,
                day.isoweekday(),
                place + 1,
                len(month) - place - 1,
            )
        )
    return out


def turn_of_month(row: DayReturn) -> Optional[str]:
    """The last trading day and first three are the turn of the month. The first
    three are checked first: in a month still running, the latest day on file is
    not yet its last."""
    if row.trading_day_of_month <= 3:
        return f"day {row.trading_day_of_month}"
    if row.trading_days_left == 0:
        return "last day"
    return None


def summarise(values: Iterable[float]) -> Optional[Dict]:
    """Count, mean, median, share up, spread, best and worst of some returns."""
    values = list(values)
    if not values:
        return None
    return {
        "count": len(values),
        "mean": mean(values),
        "median": median(values),
        "share_up": sum(1 for v in values if v > 0) / len(values),
        "stdev": pstdev(values) if len(values) > 1 else 0.0,
        "best": max(values),
        "worst": min(values),
    }


def seasonality(rows: Iterable[Tuple[Hashable, float]]) -> Dict[Hashable, Dict]:
    """``(bucket, return)`` pairs summarised per bucket, in bucket order."""
    buckets: Dict[Hashable, List[float]] = {}
    for bucket, value in rows:
        buckets.setdefault(bucket, []).append(value)
    return {bucket: summarise(buckets[bucket]) for bucket in sorted(buckets, key=str)}


def excess(
    returns: Dict[Hashable, float], benchmark: Dict[Hashable, float]
) -> Dict[Hashable, float]:
    """Period by period, where both have a return."""
    return {
        key: ret - benchmark[key] for key, ret in returns.items() if key in benchmark
    }


def compound(returns: Iterable[float]) -> float:
    total = 1.0
    for ret in returns:
        total *= 1 + ret
    return total - 1


def month_to_date_by_date(
    closes: Sequence[Close], year: int, month: int
) -> Optional[List[Tuple[int, float]]]:
    """Where a series stood after each calendar date of one month, from the last close
    of the month before: ``[(day, return), ...]``. A weekend or holiday carries the last
    close forward; a date before the month's first trade is 0. Dates after the last
    close on file are left out. None when no close before the month is on file, or the
    month has no close at all."""
    first = date(year, month, 1)
    ordered = sorted(closes)
    before = [c for d, c in ordered if d < first]
    inside = [(d, c) for d, c in ordered if d.year == year and d.month == month]
    if not before or not before[-1] or not inside:
        return None
    start = before[-1]
    out, i, current = [], 0, start
    for day in range(1, inside[-1][0].day + 1):
        while i < len(inside) and inside[i][0].day <= day:
            current = inside[i][1]
            i += 1
        out.append((day, current / start - 1))
    return out


def typical_month_path(
    closes: Sequence[Close], month: int, as_of: date
) -> List[Dict]:
    """For each calendar date of ``month``: where the series has stood, on average and
    at the median, across every whole such month on file, and in how many years.
    The month still running at ``as_of`` is left out."""
    by_day: Dict[int, List[float]] = {}
    years = sorted({d.year for d, _ in closes})
    for year in years:
        if still_running((year, month), "month", as_of) or date(year, month, 1) > as_of:
            continue
        path = month_to_date_by_date(closes, year, month)
        # Only a month on file to its end: its last close falls in its last trading days.
        if not path or path[-1][0] < calendar.monthrange(year, month)[1] - 4:
            continue
        for day, ret in path:
            by_day.setdefault(day, []).append(ret)
        # Carry the month's end to its last dates (a last trade before a weekend).
        for day in range(path[-1][0] + 1, calendar.monthrange(year, month)[1] + 1):
            by_day.setdefault(day, []).append(path[-1][1])
    return [
        {"day": d, "mean": mean(v), "median": median(v), "years": len(v)}
        for d, v in sorted(by_day.items())
    ]
