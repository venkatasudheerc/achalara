"""Performance statistics — everything read from the daily valuation rows.

Periods, account activity, cumulative return, drawdowns, risk statistics and
calendar returns are all arithmetic on ``perf.daily_valuation``. Nothing here
is stored: one grain is kept, and every other view is derived from it by one
rule, so two views cannot disagree.

Conventions (chosen to match a custodian-style performance report):
  * daily return: Modified Dietz, flows at mid-day (``dietz_factor``)
  * period return: daily factors chained
  * periods longer than a year are annualised on a 365.25-day year; a year or
    less is cumulative
  * volatility: standard deviation of daily returns x sqrt(252); risk-free 0%
  * a roll-up adds values and flows across its members, then applies the same
    rules to the sums — returns are never averaged
"""
from __future__ import annotations

import calendar
import math
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.perf import DailyPrice, DailyValuation
from app.services.mwr_calculation import MWRCalculationService
from app.services.performance_build_service import (
    ZERO,
    dietz_factor,
    realized_factor,
)

GRAINS = ("day", "week", "month", "quarter", "year")

# How holdings are valued. "market": at each day's prices, so a return includes
# gains not yet taken. "realized": at what they cost, so a gain counts only on
# the day its position is closed (income counts when received either way).
BASES = ("market", "realized")
_YEAR_DAYS = 365.25
_TRADING_DAYS = 252


class Day:
    """One day of a sleeve, an account, or several of either added together."""

    __slots__ = (
        "date",
        "total",
        "securities",
        "cash",
        "flow_in",
        "flow_out",
        "fees",
        "factor",
        "unpriced",
        "observed",
        "provisional",
    )

    @property
    def net_flow(self) -> Decimal:
        return self.flow_in - self.flow_out


def _annualise(
    period_return: Optional[float], start: date, end: date
) -> Optional[float]:
    """Annualise a cumulative return when its period is longer than a year."""
    if period_return is None:
        return None
    days = (end - start).days
    if days <= 366 or period_return <= -1:
        return period_return
    return (1 + period_return) ** (_YEAR_DAYS / days) - 1


class PerformanceStatsService:
    """Reads daily rows and derives every other performance figure."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # The daily series
    # ------------------------------------------------------------------

    def has_rows(
        self, sleeve_ids: Sequence[str] = (), account_ids: Sequence[str] = ()
    ) -> bool:
        return self._query(sleeve_ids, account_ids).first() is not None

    def _query(self, sleeve_ids, account_ids):
        query = self.db.query(DailyValuation)
        if account_ids:
            return query.filter(DailyValuation.account_id.in_(list(account_ids)))
        return query.filter(DailyValuation.sleeve_id.in_(list(sleeve_ids)))

    def daily(
        self,
        sleeve_ids: Sequence[str] = (),
        account_ids: Sequence[str] = (),
        basis: str = "market",
    ) -> List[Day]:
        """The day-by-day series for a set of sleeves or a set of accounts.

        A single member is read as stored. Several are added together per day
        and the day's return worked out again on the sums: a member that has
        not started yet simply adds nothing.

        On the ``realized`` basis every holding is carried at cost, so values
        and returns leave unrealised gains out: see ``BASES``.
        """
        if basis not in BASES:
            raise ValueError(f"basis must be one of {', '.join(BASES)}")
        realized = basis == "realized"
        rows = (
            self._query(sleeve_ids, account_ids)
            .order_by(DailyValuation.as_of_date)
            .all()
        )
        members = {row.sleeve_id or row.account_id for row in rows}
        single = len(members) <= 1

        by_date: Dict[date, Day] = {}
        last_total: Dict[str, Decimal] = {}
        dates = sorted({row.as_of_date for row in rows})
        rows_by_date: Dict[date, list] = {}
        for row in rows:
            rows_by_date.setdefault(row.as_of_date, []).append(row)

        previous_total = ZERO
        series: List[Day] = []
        for current in dates:
            day = Day()
            day.date = current
            day.total = day.securities = day.flow_in = day.flow_out = ZERO
            day.fees = day.unpriced = ZERO
            day.cash = None
            day.observed = True
            day.provisional = False
            day.factor = None
            present = set()
            # What a member arriving today brought with it. An account's first
            # row can open on a balance it already held (cash from before the
            # record starts), which is not a gain made on its first day.
            carried_in = ZERO
            for row in rows_by_date[current]:
                member = row.sleeve_id or row.account_id
                present.add(member)
                securities = Decimal(str(row.securities_value))
                total = Decimal(str(row.total_value))
                if realized and row.cost_value is not None:
                    # Carried at cost: the gain not yet taken drops out.
                    cost = Decimal(str(row.cost_value))
                    total += cost - securities
                    securities = cost
                if member not in last_total:
                    carried_in += total - (
                        Decimal(str(row.flow_in or 0)) - Decimal(str(row.flow_out or 0))
                    )
                last_total[member] = total
                day.securities += securities
                if row.cash_value is not None:
                    day.cash = (day.cash or ZERO) + Decimal(str(row.cash_value))
                day.flow_in += Decimal(str(row.flow_in or 0))
                day.flow_out += Decimal(str(row.flow_out or 0))
                day.fees += Decimal(str(row.advisory_fees or 0))
                day.unpriced += Decimal(str(row.unpriced_value or 0))
                day.observed = day.observed and row.basis == "observed"
                day.provisional = day.provisional or bool(row.is_provisional)
                if single and not realized:
                    day.factor = (
                        Decimal(str(row.return_factor))
                        if row.return_factor is not None
                        else None
                    )
            # A member with no row today (its history ended earlier, or a gap)
            # is carried at its last known value so the total does not drop.
            day.total = sum(last_total.values(), ZERO)
            if not single or realized:
                measure = realized_factor if realized else dietz_factor
                day.factor = measure(
                    previous_total + carried_in, day.total, day.flow_in, day.flow_out
                )
            previous_total = day.total
            by_date[current] = day
            series.append(day)
        return series

    # ------------------------------------------------------------------
    # Returns over a stretch of days
    # ------------------------------------------------------------------

    @staticmethod
    def _twr(days: Sequence[Day]) -> Optional[float]:
        """Chained return over ``days``; None if any day with capital has none."""
        growth = 1.0
        measured = False
        for day in days:
            if day.factor is None:
                # Nothing held and nothing moved: the day says nothing, and
                # does not break the chain. Otherwise the return is undefined.
                if day.total == 0 and day.flow_in == 0 and day.flow_out == 0:
                    continue
                if not measured and day.total >= 0:
                    continue
                return None
            growth *= float(day.factor)
            measured = True
        return growth - 1.0 if measured else None

    def _mwr(self, opening: Decimal, days: Sequence[Day]) -> Optional[float]:
        """Money-weighted return over ``days`` given the value going in."""
        if not days:
            return None
        start = days[0].date - timedelta(days=1)
        end = days[-1].date
        # From the investor's side a deposit is money paid out.
        flows = [(day.date, -day.net_flow) for day in days if day.net_flow != 0]
        closing = days[-1].total
        if opening <= 0 and not any(amount < 0 for _, amount in flows):
            return None
        return MWRCalculationService(self.db)._solve_irr(
            opening, flows, closing, start, end
        )

    # ------------------------------------------------------------------
    # Periods
    # ------------------------------------------------------------------

    @staticmethod
    def _period_key(day: date, grain: str):
        if grain == "day":
            return day
        if grain == "week":
            iso = day.isocalendar()
            return (iso[0], iso[1])
        if grain == "month":
            return (day.year, day.month)
        if grain == "quarter":
            return (day.year, (day.month - 1) // 3 + 1)
        return (day.year,)

    def periods(
        self,
        series: Sequence[Day],
        grain: str,
        start: Optional[date] = None,
        end: Optional[date] = None,
        benchmark: Optional[str] = None,
    ) -> List[Dict]:
        """One row per day, week, month, quarter or year.

        Cumulative and year-to-date returns run from the start of the series
        and of the calendar year, whatever window is asked for.
        """
        if grain not in GRAINS:
            raise ValueError(f"grain must be one of {', '.join(GRAINS)}")
        closes = self._benchmark_closes(benchmark) if benchmark else None

        groups: List[List[Day]] = []
        current_key = None
        for day in series:
            key = self._period_key(day.date, grain)
            if key != current_key:
                groups.append([])
                current_key = key
            groups[-1].append(day)

        rows: List[Dict] = []
        opening = ZERO
        cumulative = 1.0
        cumulative_ok = True
        ytd = 1.0
        ytd_ok = True
        ytd_year = None
        for group in groups:
            first, last = group[0], group[-1]
            twr = self._twr(group)
            if last.date.year != ytd_year:
                ytd, ytd_ok, ytd_year = 1.0, True, last.date.year
            if twr is None:
                active = any(d.total != 0 or d.flow_in != 0 for d in group)
                cumulative_ok = cumulative_ok and not active
                ytd_ok = ytd_ok and not active
            else:
                cumulative *= 1 + twr
                ytd *= 1 + twr
            closing = last.total
            net_flow = sum((d.net_flow for d in group), ZERO)

            if (start is None or last.date >= start) and (
                end is None or first.date <= end
            ):
                benchmark_return = (
                    self._benchmark_return(closes, first.date, last.date)
                    if closes
                    else None
                )
                rows.append(
                    {
                        "period_start": first.date,
                        "period_end": last.date,
                        "opening_value": float(opening),
                        "closing_value": float(closing),
                        "cash_value": float(last.cash)
                        if last.cash is not None
                        else None,
                        "net_flow": float(net_flow),
                        "gain": float(closing - opening - net_flow),
                        "twr_pct": twr,
                        "mwr_pct": self._mwr(opening, group),
                        "twr_cumulative_pct": cumulative - 1 if cumulative_ok else None,
                        "twr_ytd_pct": ytd - 1 if ytd_ok else None,
                        "benchmark_return_pct": benchmark_return,
                        "excess_return_pct": (
                            twr - benchmark_return
                            if twr is not None and benchmark_return is not None
                            else None
                        ),
                        "unpriced_pct": (
                            float(last.unpriced / abs(last.securities))
                            if last.securities
                            else 0.0
                        ),
                        "basis": (
                            "observed"
                            if all(d.observed for d in group)
                            else "reconstructed"
                            if not any(d.observed for d in group)
                            else "mixed"
                        ),
                        "is_provisional": any(d.provisional for d in group),
                    }
                )
            opening = closing
        return rows

    # ------------------------------------------------------------------
    # Benchmark
    # ------------------------------------------------------------------

    def _benchmark_closes(self, ticker: str):
        return [
            (day, float(close))
            for day, close in self.db.query(DailyPrice.price_date, DailyPrice.close)
            .filter(DailyPrice.symbol == ticker.upper(), DailyPrice.source == "webull")
            .order_by(DailyPrice.price_date)
        ]

    @staticmethod
    def _close_on(closes, day: date) -> Optional[float]:
        lo, hi, found = 0, len(closes) - 1, None
        while lo <= hi:
            mid = (lo + hi) // 2
            if closes[mid][0] <= day:
                found = closes[mid][1]
                lo = mid + 1
            else:
                hi = mid - 1
        return found

    def _benchmark_return(self, closes, first: date, last: date) -> Optional[float]:
        """The benchmark's return from the close before ``first`` to ``last``."""
        before = self._close_on(closes, first - timedelta(days=1))
        after = self._close_on(closes, last)
        if not before or not after:
            return None
        return after / before - 1

    # ------------------------------------------------------------------
    # The report's figures
    # ------------------------------------------------------------------

    def statistics(self, series: Sequence[Day], as_of: Optional[date] = None) -> Dict:
        """Everything an account performance report shows, as of a date."""
        series = [d for d in series if as_of is None or d.date <= as_of]
        # The record starts when there is first something to measure.
        while series and series[0].total == 0 and series[0].flow_in == 0:
            series = series[1:]
        if not series:
            return {"as_of": as_of, "inception": None}
        end = series[-1].date
        inception = series[0].date

        def window(first_day: date) -> List[Day]:
            return [d for d in series if d.date >= first_day]

        month_start = end.replace(day=1)
        quarter_start = date(end.year, 3 * ((end.month - 1) // 3) + 1, 1)
        year_start = date(end.year, 1, 1)
        try:
            one_year = end.replace(year=end.year - 1) + timedelta(days=1)
        except ValueError:  # 29 February
            one_year = end.replace(year=end.year - 1, day=28) + timedelta(days=1)
        windows = {
            "mtd": month_start,
            "qtd": quarter_start,
            "ytd": year_start,
            "one_year": one_year,
            "inception": inception,
        }

        returns: Dict[str, Optional[float]] = {}
        activity: Dict[str, Dict] = {}
        for name, first_day in windows.items():
            days = window(first_day)
            covered = bool(days) and (name == "inception" or inception <= first_day)
            if not covered and name != "inception":
                # The account is younger than the window: the figure would
                # repeat since-inception under another name.
                days = window(inception)
            before = [d for d in series if d.date < days[0].date] if days else []
            opening = before[-1].total if before else ZERO
            twr = self._twr(days)
            mwr = self._mwr(opening, days)
            span_start = (before[-1].date if before else days[0].date) if days else end
            returns[name] = _annualise(twr, span_start, end)
            net_flow = sum((d.net_flow for d in days), ZERO)
            closing = days[-1].total if days else ZERO
            activity[name] = {
                "beginning_value": float(opening),
                "net_flow": float(net_flow),
                "gain": float(closing - opening - net_flow),
                "ending_value": float(closing),
                "twr_pct": returns[name],
                "mwr_pct": _annualise(mwr, span_start, end),
                "covers_full_period": covered or name == "inception",
            }

        cumulative = self._cumulative(series)
        drawdowns = self._drawdowns(cumulative)
        monthly = self.periods(series, "month")
        yearly = self.periods(series, "year")
        month_returns = [m["twr_pct"] for m in monthly if m["twr_pct"] is not None]
        daily_returns = [float(d.factor) - 1 for d in series if d.factor is not None]
        observed_days = sum(1 for d in series if d.observed)

        annualised = returns["inception"]
        volatility = self._volatility(daily_returns)
        downside = self._downside(daily_returns)
        deepest = min(drawdowns, key=lambda p: p["drawdown"]) if drawdowns else None

        return {
            "as_of": end,
            "inception": inception,
            "ending_value": float(series[-1].total),
            "cash_value": (
                float(series[-1].cash) if series[-1].cash is not None else None
            ),
            "returns": returns,
            "activity": activity,
            "net_contributions": [
                {"date": d.date, "value": float(d.total), "contributed": float(c)}
                for d, c in zip(series, self._running_contributions(series))
            ],
            "cumulative": cumulative,
            "drawdowns": drawdowns,
            "risk": {
                "annualized_return": annualised,
                "volatility": volatility,
                "sharpe": (
                    annualised / volatility
                    if annualised is not None and volatility
                    else None
                ),
                "sortino": (
                    annualised / downside
                    if annualised is not None and downside
                    else None
                ),
                "max_drawdown": deepest["drawdown"] if deepest else None,
                "max_drawdown_date": deepest["date"] if deepest else None,
                "max_drawdown_start": self._peak_before(cumulative, deepest),
                "max_drawdown_recovered": self._recovery_after(cumulative, deepest),
                "best_month": max(month_returns) if month_returns else None,
                "worst_month": min(month_returns) if month_returns else None,
                "positive_months": (
                    sum(1 for r in month_returns if r > 0) / len(month_returns)
                    if month_returns
                    else None
                ),
            },
            "calendar_years": [
                {
                    "year": y["period_end"].year,
                    "twr_pct": y["twr_pct"],
                    "partial": y["period_start"] > date(y["period_end"].year, 1, 7)
                    or y["period_end"] < date(y["period_end"].year, 12, 24),
                }
                for y in yearly
            ],
            "monthly": [
                {
                    "year": m["period_end"].year,
                    "month": m["period_end"].month,
                    "twr_pct": m["twr_pct"],
                }
                for m in monthly
            ],
            "quality": {
                "days": len(series),
                "observed_days": observed_days,
                "observed_pct": observed_days / len(series),
                "provisional_days": sum(1 for d in series if d.provisional),
                "unpriced_pct": (
                    float(series[-1].unpriced / abs(series[-1].securities))
                    if series[-1].securities
                    else 0.0
                ),
                "unpriced_value": float(series[-1].unpriced),
            },
        }

    @staticmethod
    def _cumulative(series: Sequence[Day]) -> List[Dict]:
        points = []
        growth = 1.0
        for day in series:
            if day.factor is not None:
                growth *= float(day.factor)
            points.append({"date": day.date, "cumulative": growth - 1})
        return points

    @staticmethod
    def _drawdowns(cumulative: Sequence[Dict]) -> List[Dict]:
        points = []
        peak = 1.0
        for point in cumulative:
            level = 1 + point["cumulative"]
            peak = max(peak, level)
            points.append({"date": point["date"], "drawdown": level / peak - 1})
        return points

    @staticmethod
    def _peak_before(cumulative, deepest) -> Optional[date]:
        if not deepest or deepest["drawdown"] == 0:
            return None
        best, when = -1.0, None
        for point in cumulative:
            if point["date"] > deepest["date"]:
                break
            if point["cumulative"] >= best:
                best, when = point["cumulative"], point["date"]
        return when

    @staticmethod
    def _recovery_after(cumulative, deepest) -> Optional[date]:
        if not deepest or deepest["drawdown"] == 0:
            return None
        peak = max(p["cumulative"] for p in cumulative if p["date"] <= deepest["date"])
        for point in cumulative:
            if point["date"] > deepest["date"] and point["cumulative"] >= peak:
                return point["date"]
        return None

    @staticmethod
    def _running_contributions(series: Sequence[Day]) -> List[Decimal]:
        running, out = ZERO, []
        for day in series:
            running += day.net_flow
            out.append(running)
        return out

    @staticmethod
    def _volatility(returns: Sequence[float]) -> Optional[float]:
        if len(returns) < 2:
            return None
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return math.sqrt(variance) * math.sqrt(_TRADING_DAYS)

    @staticmethod
    def _downside(returns: Sequence[float]) -> Optional[float]:
        if len(returns) < 2:
            return None
        squared = sum(min(r, 0.0) ** 2 for r in returns) / len(returns)
        return math.sqrt(squared) * math.sqrt(_TRADING_DAYS) or None

    @staticmethod
    def month_label(year: int, month: int) -> str:
        return f"{calendar.month_abbr[month]} {year}"
