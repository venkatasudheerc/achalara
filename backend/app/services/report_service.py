"""The account investment performance report.

Every figure comes from ``PerformanceStatsService``; this module only lays
them out. The page is HTML rendered to PDF, with charts drawn as SVG.
"""
from __future__ import annotations

import calendar
import io
import re
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.brokerage_connection import BrokerageAccount
from app.services.performance_stats_service import PerformanceStatsService

_TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

# Brand tokens, as in the frontend's tailwind config.
PINE = "#2F5D4A"
PINE_DEEP = "#1E3A2F"
GAIN = "#2E8B6B"
LOSS = "#C2703D"
STONE = "#8A968F"
GOLD = "#C9A24B"

ADVISOR_PLACEHOLDER = (
    "Advisor and firm details have not been set up yet. They will appear here."
)
FIRM_DISCLOSURES_PLACEHOLDER = "Firm disclosures have not been set up yet."


class ReportUnavailable(Exception):
    """The report cannot be produced for this account as things stand."""


def _money(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"-${abs(value):,.0f}" if value < 0 else f"${value:,.0f}"


def _pct(value: Optional[float], digits: int = 2) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _long(day: Optional[date]) -> str:
    return f"{day:%B} {day.day}, {day.year}" if day else "—"


def _short(day: Optional[date]) -> str:
    return f"{day:%b} {day.day}, {day.year}" if day else "—"


def _display_name(name: str) -> str:
    """An account's name without any full account number in it.

    Custodians put the number in the name ("... Brokerage Account — 12345678");
    a report shows only the masked last four.
    """
    cleaned = re.sub(r"\s*[—–-]\s*\d{6,}\b", "", name)
    return re.sub(r"\b\d{6,}\b", "", cleaned).strip(" —–-") or name


class ReportService:
    """Builds the performance report for one account."""

    def __init__(self, db: Session):
        self.db = db
        self.stats = PerformanceStatsService(db)

    def html(self, client, account, as_of: Optional[date] = None) -> str:
        from jinja2 import Environment, FileSystemLoader, select_autoescape

        environment = Environment(
            loader=FileSystemLoader(str(_TEMPLATES)),
            autoescape=select_autoescape(["html"]),
        )
        template = environment.get_template("performance_report.html")
        return template.render(**self.context(client, account, as_of))

    def pdf(self, client, account, as_of: Optional[date] = None) -> bytes:
        try:
            from weasyprint import HTML
        except Exception as exc:  # noqa: BLE001 - missing system libraries
            raise ReportUnavailable(
                "PDF rendering is not available on this server (WeasyPrint needs "
                f"the Pango library): {exc}"
            )
        return HTML(string=self.html(client, account, as_of)).write_pdf()

    # ------------------------------------------------------------------

    def context(self, client, account, as_of: Optional[date] = None) -> Dict:
        figures = self.stats.statistics(
            self.stats.daily(account_ids=[account.id]), as_of
        )
        if not figures.get("inception"):
            raise ReportUnavailable(
                "No daily performance record exists for this account yet"
            )
        end, inception = figures["as_of"], figures["inception"]
        returns, activity, risk = (
            figures["returns"],
            figures["activity"],
            figures["risk"],
        )
        annualised = (end - inception).days > 366
        quality = figures["quality"]

        linked = (
            self.db.query(BrokerageAccount)
            .filter(BrokerageAccount.account_id == account.id)
            .first()
        )
        number = (
            f"····{linked.number_last4}" if linked and linked.number_last4 else None
        )

        return {
            "client_name": client.name,
            "account_name": _display_name(account.name),
            "account_number": number,
            "as_of_long": _long(end),
            "inception_long": _long(inception),
            "prepared_by": "— (advisor details not yet set up)",
            "footer_left": f"{client.name} · As of {_long(end)} · "
            "Past performance does not guarantee future results.",
            "ending_value": _money(figures["ending_value"]),
            "ending_note": (
                "Securities and cash"
                if figures["cash_value"] is not None
                else "Securities"
            ),
            "annualised": annualised,
            "r": {key: _pct(value) for key, value in returns.items()},
            "summary": self._summary(figures, annualised),
            "activity": {
                key: {
                    "beginning_value": _money(row["beginning_value"]),
                    "net_flow": _money(row["net_flow"]),
                    "adjustment": _money(row["adjustment"]),
                    "gain": _money(row["gain"]),
                    "ending_value": _money(row["ending_value"]),
                    "twr_pct": _pct(row["twr_pct"]),
                    "mwr_pct": _pct(row["mwr_pct"]),
                }
                for key, row in activity.items()
            },
            "activity_rows": [
                ("Beginning value", "beginning_value", ""),
                ("Net contributions and withdrawals", "net_flow", ""),
                ("Investment gain / loss", "gain", ""),
                *(
                    [("Valuation adjustment", "adjustment", "")]
                    if any(abs(row["adjustment"]) >= 0.5 for row in activity.values())
                    else []
                ),
                ("Ending value", "ending_value", "strong"),
                ("Time-weighted return", "twr_pct", ""),
                ("Money-weighted return", "mwr_pct", ""),
            ],
            "charts": self._charts(figures),
            "deepest": (
                f"{_pct(risk['max_drawdown'], 1)} on {_short(risk['max_drawdown_date'])}"
                if risk["max_drawdown"]
                else None
            ),
            "risk_rows": [
                (
                    "Annualized return" if annualised else "Return",
                    _pct(risk["annualized_return"]),
                ),
                ("Volatility (annualized)", _pct(risk["volatility"])),
                ("Sharpe ratio (rf 0.0%)", self._ratio(risk["sharpe"])),
                ("Sortino ratio", self._ratio(risk["sortino"])),
                ("Maximum drawdown", _pct(risk["max_drawdown"])),
                ("Best month", _pct(risk["best_month"])),
                ("Worst month", _pct(risk["worst_month"])),
                ("Positive months", _pct(risk["positive_months"], 0)),
            ],
            "drawdown_note": self._drawdown_note(risk),
            "years": [
                {
                    "label": f"{y['year']}{'*' if y['partial'] else ''}",
                    "value": _pct(y["twr_pct"]),
                }
                for y in figures["calendar_years"]
            ],
            "month_names": list(calendar.month_abbr)[1:],
            "month_grid": self._month_grid(figures),
            "advisor_block": ADVISOR_PLACEHOLDER,
            "firm_disclosures": FIRM_DISCLOSURES_PLACEHOLDER,
            "methodology": self._methodology(figures, quality),
        }

    @staticmethod
    def _ratio(value: Optional[float]) -> str:
        return "—" if value is None else f"{value:.2f}"

    @staticmethod
    def _drawdown_note(risk: Dict) -> str:
        if not risk["max_drawdown"]:
            return "There has been no decline from a previous peak."
        note = (
            f"Largest drawdown since inception: {_pct(risk['max_drawdown'], 1)} from "
            f"{_short(risk['max_drawdown_start'])} to {_short(risk['max_drawdown_date'])}"
        )
        if risk["max_drawdown_recovered"]:
            return note + f", recovered by {_short(risk['max_drawdown_recovered'])}."
        return note + "; it has not yet been recovered."

    def _summary(self, figures: Dict, annualised: bool) -> List[str]:
        """The opening paragraphs, assembled from the figures."""
        returns, activity, risk = (
            figures["returns"],
            figures["activity"],
            figures["risk"],
        )
        end = figures["as_of"]
        quarter = (end.month - 1) // 3 + 1
        ordinal = ["first", "second", "third", "fourth"][quarter - 1]
        first = (
            f"The account returned {_pct(returns['ytd'])} year to date through "
            f"{_long(end)}, and {_pct(returns['qtd'])} in the {ordinal} quarter so far. "
            f"Its value stands at {_money(figures['ending_value'])}."
        )
        if activity["one_year"]["covers_full_period"]:
            first += f" Over the last 12 months the account returned {_pct(returns['one_year'])}."

        since = activity["inception"]
        second = (
            f"Since inception on {_long(figures['inception'])}, "
            f"{_money(since['net_flow'])} has been contributed net of withdrawals, and the "
            f"account has earned {_pct(returns['inception'])}"
            f"{' a year' if annualised else ''} on a time-weighted basis."
        )
        if risk["max_drawdown"]:
            second += " " + self._drawdown_note(risk)
        if risk["best_month"] is not None:
            second += (
                f" Monthly results have ranged from {_pct(risk['worst_month'], 1)} to "
                f"{_pct(risk['best_month'], 1)}."
            )

        ytd = activity["ytd"]
        flow = ytd["net_flow"]
        if abs(flow) < 0.5:
            third = "There have been no contributions or withdrawals this year."
        elif flow > 0:
            third = f"Net of withdrawals, {_money(flow)} was added to the account this year."
        else:
            third = f"Net of contributions, {_money(-flow)} left the account this year."
        return [first, second, third]

    def _month_grid(self, figures: Dict) -> List[Dict]:
        by_year: Dict[int, Dict[int, Optional[float]]] = {}
        for month in figures["monthly"]:
            by_year.setdefault(month["year"], {})[month["month"]] = month["twr_pct"]
        totals = {y["year"]: y["twr_pct"] for y in figures["calendar_years"]}
        rows = []
        for year in sorted(by_year):
            cells = []
            for month in range(1, 13):
                value = by_year[year].get(month)
                cells.append(
                    {
                        "text": "" if value is None else f"{value * 100:.1f}",
                        "color": self._shade(value),
                    }
                )
            total = totals.get(year)
            rows.append(
                {
                    "year": year,
                    "cells": cells,
                    "total": "" if total is None else f"{total * 100:.1f}",
                }
            )
        return rows

    @staticmethod
    def _shade(value: Optional[float]) -> str:
        if value is None:
            return "transparent"
        strength = min(abs(value) / 0.10, 1.0) * 0.55 + 0.08
        red, green, blue = (46, 139, 107) if value >= 0 else (194, 112, 61)
        return f"rgba({red},{green},{blue},{strength:.2f})"

    def _methodology(self, figures: Dict, quality: Dict) -> List[tuple]:
        observed = quality["observed_days"]
        days = quality["days"]
        source = (
            f"{days} daily valuations from {_short(figures['inception'])} to "
            f"{_short(figures['as_of'])}. {observed} "
            f"{'was' if observed == 1 else 'were'} recorded from the custodian's own "
            "reported holdings, cash and account total on the day; the remainder were "
            "reconstructed from the account's transactions and daily closing prices, "
            "and are less certain."
        )
        if quality["unpriced_value"] >= 1:
            source += (
                f" At the report date, positions amounting to "
                f"{_money(quality['unpriced_value'])} have no daily price history "
                "(options and delisted securities) and are carried at the custodian's "
                "implied value or their last traded price."
            )
        if quality["provisional_days"]:
            source += (
                f" The most recent {quality['provisional_days']} day(s) are provisional: "
                "the custodian's transactions for them may still be arriving."
            )
        return [
            (
                "Data source",
                source
                + " This report was not reconciled to official custodial statements.",
            ),
            (
                "Time-weighted return (TWR)",
                "Daily returns are chained together geometrically. Each daily return uses "
                "the Modified Dietz method, with external cash flows weighted at mid-day. "
                "TWR removes the effect of contributions and withdrawals, so it shows how "
                "the investments performed.",
            ),
            (
                "Money-weighted return (MWR)",
                "The internal rate of return on the account's actual cash flows. It reflects "
                "when and how much money went in or out, so it can differ from TWR.",
            ),
            (
                "Fees",
                "No advisory fees are recorded for this account, so returns are shown on one "
                "basis only. Trading commissions are included in returns.",
            ),
            (
                "Accrued income",
                "Market values do not include accrued income: dividends and interest are "
                "counted when the cash is received.",
            ),
            (
                "Annualization",
                "Returns for periods longer than one year are annualized geometrically on a "
                "365.25-day year. Periods of one year or less are cumulative.",
            ),
            (
                "Risk statistics",
                "Volatility is the standard deviation of daily returns, annualized by the "
                "square root of 252. The Sharpe ratio is annualized return divided by "
                "volatility with a risk-free rate of 0.00%; the Sortino ratio uses downside "
                "deviation instead. Maximum drawdown is the largest peak-to-trough decline "
                "in cumulative return.",
            ),
            *(
                [
                    (
                        "Valuation adjustment",
                        "Where daily values reconstructed from transactions meet values "
                        "recorded from the custodian, the same holdings are valued "
                        "differently (options in particular) and the account's value "
                        "steps without any event on that day. That step is shown as a "
                        "valuation adjustment and is excluded from investment gain and "
                        "from every return.",
                    )
                ]
                if abs(figures["activity"]["inception"]["adjustment"]) >= 0.5
                else []
            ),
            ("Benchmark", "No benchmark comparison is included in this report."),
        ]

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------

    def _charts(self, figures: Dict) -> Dict[str, str]:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter

        def finish(fig) -> str:
            buffer = io.StringIO()
            fig.savefig(buffer, format="svg", bbox_inches="tight")
            plt.close(fig)
            svg = buffer.getvalue()
            return svg[svg.index("<svg") :]

        def frame(height: float):
            fig, axis = plt.subplots(figsize=(7.6, height))
            for side in ("top", "right", "left"):
                axis.spines[side].set_visible(False)
            axis.spines["bottom"].set_color(STONE)
            axis.grid(axis="y", color="#dfe6e1", linewidth=0.6)
            axis.tick_params(colors="#4b5852", labelsize=7, length=0)
            return fig, axis

        thousands = FuncFormatter(lambda v, _: f"${v / 1000:,.0f}K")
        percent = FuncFormatter(lambda v, _: f"{v * 100:.0f}%")
        charts: Dict[str, str] = {}

        growth = figures["net_contributions"]
        fig, axis = frame(2.5)
        days = [p["date"] for p in growth]
        axis.plot(
            days,
            [p["value"] for p in growth],
            color=PINE,
            linewidth=1.3,
            label="Market value",
        )
        axis.plot(
            days,
            [p["contributed"] for p in growth],
            color=STONE,
            linewidth=1.0,
            linestyle="--",
            label="Net contributions",
        )
        axis.yaxis.set_major_formatter(thousands)
        axis.legend(frameon=False, fontsize=7, loc="upper left", ncol=2)
        charts["growth"] = finish(fig)

        cumulative = figures["cumulative"]
        fig, axis = frame(2.3)
        axis.plot(
            [p["date"] for p in cumulative],
            [p["cumulative"] for p in cumulative],
            color=PINE,
            linewidth=1.3,
        )
        axis.axhline(0, color=STONE, linewidth=0.6)
        axis.yaxis.set_major_formatter(percent)
        charts["cumulative"] = finish(fig)

        drawdowns = figures["drawdowns"]
        fig, axis = frame(1.9)
        axis.fill_between(
            [p["date"] for p in drawdowns],
            [p["drawdown"] for p in drawdowns],
            0,
            color=LOSS,
            alpha=0.25,
            linewidth=0,
        )
        axis.plot(
            [p["date"] for p in drawdowns],
            [p["drawdown"] for p in drawdowns],
            color=LOSS,
            linewidth=1.0,
        )
        axis.yaxis.set_major_formatter(percent)
        charts["drawdown"] = finish(fig)

        years = [y for y in figures["calendar_years"] if y["twr_pct"] is not None]
        fig, axis = frame(2.0)
        labels = [f"{y['year']}{'*' if y['partial'] else ''}" for y in years]
        values = [y["twr_pct"] for y in years]
        bars = axis.bar(
            labels, values, color=[GAIN if v >= 0 else LOSS for v in values], width=0.55
        )
        for bar, value in zip(bars, values):
            # Above a gain; just inside the foot of a loss, clear of the axis.
            axis.annotate(
                f"{value * 100:.1f}%",
                (bar.get_x() + bar.get_width() / 2, value),
                ha="center",
                va="bottom",
                fontsize=7,
                color="#14201C" if value >= 0 else "white",
                xytext=(0, 2),
                textcoords="offset points",
            )
        axis.axhline(0, color=STONE, linewidth=0.6)
        axis.yaxis.set_major_formatter(percent)
        charts["years"] = finish(fig)
        return charts
