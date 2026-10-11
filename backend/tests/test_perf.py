"""The perf schema: daily valuation, capture, statistics and the report.

Offline. Statistics are checked against hand-worked figures on daily rows
written directly; the build and capture are checked end to end through the
stub brokerage used in ``test_connections``.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.account import Account
from app.models.client import Client
from app.models.perf import CorporateAction, DailyHolding, DailyPrice, DailyValuation
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.services.connection_service import sync_brokerage_account
from app.services.corporate_actions import adjusted_trades
from app.services.daily_capture_service import DailyCaptureService
from app.services.performance_build_service import (
    PerformanceBuildService,
    dietz_factor,
    last_market_day,
)
from app.services.performance_stats_service import PerformanceStatsService
from app.services.portfolio_calculation import PortfolioCalculationService
from tests.test_connections import (  # noqa: F401 - fixtures
    _cash_account,
    _cash_row,
    _mapped_account,
    client_id,
    no_live_prices,
    sdk,
)

D = Decimal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _weekdays(start: date, count: int):
    days, cursor = [], start
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _account(db, name="Acct", email=None) -> Account:
    owner = Client(name=name, email=email or f"{name.lower()}@example.com")
    db.add(owner)
    db.flush()
    account = Account(client_id=owner.id, name=name)
    db.add(account)
    db.commit()
    return account


def _rows(db, account, values, flows=None, start=date(2025, 1, 6)):
    """Daily account rows with these closing values and net deposits."""
    flows = flows or {}
    previous = D(0)
    for index, day in enumerate(_weekdays(start, len(values))):
        total = D(str(values[index]))
        net = D(str(flows.get(index, 0)))
        flow_in, flow_out = max(net, D(0)), max(-net, D(0))
        db.add(
            DailyValuation(
                account_id=account.id,
                as_of_date=day,
                securities_value=total,
                cash_value=D(0),
                total_value=total,
                flow_in=flow_in,
                flow_out=flow_out,
                return_factor=dietz_factor(previous, total, flow_in, flow_out),
                basis="reconstructed",
            )
        )
        previous = total
    db.commit()


def _sleeve(db, account, strategy_name="S", method="FIFO") -> Sleeve:
    strategy = Strategy(name=strategy_name)
    db.add(strategy)
    db.flush()
    sleeve = Sleeve(
        account_id=account.id, strategy_id=strategy.id, accounting_method=method
    )
    db.add(sleeve)
    db.commit()
    return sleeve


def _trade(db, sleeve, day, action, qty, price, symbol="ABC"):
    db.add(
        Trade(
            sleeve_id=sleeve.id,
            trade_date=day,
            symbol=symbol,
            action=action,
            quantity=D(str(qty)),
            price=D(str(price)),
            commission=D(0),
        )
    )
    db.commit()


def _closes(db, symbol, start, closes):
    for day, close in zip(_weekdays(start, len(closes)), closes):
        db.add(
            DailyPrice(
                symbol=symbol, price_date=day, close=D(str(close)), source="webull"
            )
        )
    db.commit()


# ---------------------------------------------------------------------------
# The day's return
# ---------------------------------------------------------------------------


def test_dietz_counts_a_deposit_at_mid_day():
    # 1,000 grows to 1,650 on a day 500 is added: 150 gained on 1,250 at work.
    assert dietz_factor(D(1000), D(1650), D(500), D(0)) == D("1.12")


def test_dietz_has_no_return_without_capital():
    assert dietz_factor(D(0), D(0), D(0), D(0)) is None


def test_dietz_survives_a_day_of_heavy_turnover():
    # Mid-day weighting leaves no base here; the day is still measurable.
    factor = dietz_factor(D(100), D(0), D(0), D(210))
    assert factor == D("2.1")


# ---------------------------------------------------------------------------
# Statistics, on hand-worked daily rows
# ---------------------------------------------------------------------------


def test_period_returns_chain_their_days(db):
    account = _account(db)
    # +10%, flat, -5%, then +2% with no flows.
    _rows(db, account, [1000, 1100, 1100, 1045, 1065.9], flows={0: 1000})
    stats = PerformanceStatsService(db)
    series = stats.daily(account_ids=[account.id])

    days = stats.periods(series, "day")
    weeks = stats.periods(series, "week")

    assert [round(d["twr_pct"], 6) for d in days[1:]] == [0.1, 0.0, -0.05, 0.02]
    # One calendar week: its return is its days chained.
    assert len(weeks) == 1
    assert weeks[0]["twr_pct"] == pytest.approx(1.1 * 0.95 * 1.02 - 1)
    assert weeks[0]["opening_value"] == 0.0
    assert weeks[0]["closing_value"] == 1065.9
    assert weeks[0]["net_flow"] == 1000.0
    assert weeks[0]["gain"] == pytest.approx(65.9)
    assert days[-1]["twr_cumulative_pct"] == pytest.approx(weeks[0]["twr_pct"])


def test_months_and_quarters_agree_with_the_days(db):
    account = _account(db)
    values = [10000 * (1.001**n) for n in range(130)]  # about six months
    _rows(db, account, values, flows={0: 10000}, start=date(2025, 1, 2))
    stats = PerformanceStatsService(db)
    series = stats.daily(account_ids=[account.id])

    def chained(grain):
        growth = 1.0
        for period in stats.periods(series, grain):
            growth *= 1 + period["twr_pct"]
        return growth - 1

    total = values[-1] / values[0] - 1
    for grain in ("day", "week", "month", "quarter", "year"):
        assert chained(grain) == pytest.approx(total, abs=1e-6)


def test_a_deposit_is_not_a_gain(db):
    account = _account(db)
    _rows(db, account, [1000, 1000, 6000, 6000], flows={0: 1000, 2: 5000})
    stats = PerformanceStatsService(db)

    (week,) = stats.periods(stats.daily(account_ids=[account.id]), "week")

    assert week["twr_pct"] == pytest.approx(0.0)
    assert week["net_flow"] == 6000.0
    assert week["gain"] == pytest.approx(0.0)
    assert week["mwr_pct"] == pytest.approx(0.0, abs=1e-6)


def test_drawdown_and_risk_statistics(db):
    account = _account(db)
    # Up to a peak of 1,200, down to 900 (-25%), back to 1,260.
    _rows(db, account, [1000, 1200, 1080, 900, 1260], flows={0: 1000})
    stats = PerformanceStatsService(db)

    figures = stats.statistics(stats.daily(account_ids=[account.id]))
    risk = figures["risk"]

    assert risk["max_drawdown"] == pytest.approx(-0.25)
    assert risk["max_drawdown_date"] == date(2025, 1, 9)
    assert risk["max_drawdown_start"] == date(2025, 1, 7)
    assert risk["max_drawdown_recovered"] == date(2025, 1, 10)
    assert figures["returns"]["inception"] == pytest.approx(0.26)
    # Daily returns 20%, -10%, -16.67%, 40% (the funding day returns nothing).
    returns = [0.0, 0.2, -0.1, 900 / 1080 - 1, 0.4]
    mean = sum(returns) / 5
    expected = (sum((r - mean) ** 2 for r in returns) / 4) ** 0.5 * 252**0.5
    assert risk["volatility"] == pytest.approx(expected)
    assert figures["ending_value"] == 1260.0
    assert figures["activity"]["inception"]["gain"] == pytest.approx(260.0)


def test_returns_over_a_year_are_annualised(db):
    account = _account(db)
    days = 2 * 261  # two years of weekdays
    values = [1000 * (1.21 ** (n / (days - 1))) for n in range(days)]
    _rows(db, account, values, flows={0: 1000}, start=date(2023, 1, 2))
    stats = PerformanceStatsService(db)

    figures = stats.statistics(stats.daily(account_ids=[account.id]))

    # 21% over two years is 10% a year.
    assert figures["returns"]["inception"] == pytest.approx(0.10, abs=0.002)
    assert figures["activity"]["inception"]["ending_value"] == pytest.approx(1210.0)


def test_a_client_is_its_accounts_added_together_not_averaged(db):
    first = _account(db, "First")
    second = _account(db, "Second")
    # 1,000 doubles; 9,000 stands still. Together: 10,000 -> 11,000.
    _rows(db, first, [1000, 2000], flows={0: 1000})
    _rows(db, second, [9000, 9000], flows={0: 9000})
    stats = PerformanceStatsService(db)

    series = stats.daily(account_ids=[first.id, second.id])
    (week,) = stats.periods(series, "week")

    assert week["twr_pct"] == pytest.approx(0.10)
    assert week["closing_value"] == 11000.0


# ---------------------------------------------------------------------------
# Reconstruction from trades and prices
# ---------------------------------------------------------------------------


def test_a_holding_is_valued_each_day_from_its_price_history(db):
    account = _account(db)
    sleeve = _sleeve(db, account)
    start = date(2025, 1, 6)
    _closes(db, "SPY", start, [1, 1, 1, 1])  # the market calendar
    _closes(db, "ABC", start, [100, 110, 99, 121])
    _trade(db, sleeve, start, "BUY", 10, 100)

    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 1, 9))

    rows = (
        db.query(DailyValuation)
        .filter(DailyValuation.sleeve_id == sleeve.id)
        .order_by(DailyValuation.as_of_date)
        .all()
    )
    assert [float(r.securities_value) for r in rows] == [1000.0, 1100.0, 990.0, 1210.0]
    assert float(rows[0].flow_in) == 1000.0
    assert [round(float(r.return_factor), 4) for r in rows[1:]] == [1.1, 0.9, 1.2222]
    assert {r.basis for r in rows} == {"reconstructed"}
    assert all(r.unpriced_value == 0 for r in rows)


def test_adjusted_prices_are_tied_to_what_was_actually_paid(db):
    # The history is on a later split-and-dividend basis: closes near 25 for a
    # share that traded at 100. Only its movement is used.
    account = _account(db)
    sleeve = _sleeve(db, account)
    start = date(2025, 1, 6)
    _closes(db, "SPY", start, [1, 1])
    _closes(db, "ABC", start, [25, 27.5])
    _trade(db, sleeve, start, "BUY", 10, 100)

    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 1, 7))

    values = [
        float(r.securities_value)
        for r in db.query(DailyValuation)
        .filter(DailyValuation.sleeve_id == sleeve.id)
        .order_by(DailyValuation.as_of_date)
    ]
    assert values == [1000.0, 1100.0]


def test_an_assignment_at_the_strike_does_not_set_the_price(db):
    # Puts assigned: 1,000 shares delivered at 109 on a day they closed at 66.
    account = _account(db)
    sleeve = _sleeve(db, account)
    start = date(2025, 10, 27)
    _closes(db, "SPY", start, [1, 1, 1, 1, 1, 1])
    _closes(db, "FISV", start, [120, 120, 70, 68, 66, 67])
    put = "FI251031P00109000"
    _trade(db, sleeve, date(2025, 10, 28), "SELL", 10, 55, symbol=put)
    _trade(db, sleeve, date(2025, 10, 31), "BUY", 10, 0, symbol=put)
    _trade(db, sleeve, date(2025, 10, 31), "BUY", 1000, 109, symbol="FISV")

    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 11, 3))

    rows = {
        r.as_of_date: r
        for r in db.query(DailyValuation).filter(DailyValuation.sleeve_id == sleeve.id)
    }
    # Worth what the market says on the day and after, not what was paid.
    assert float(rows[date(2025, 10, 31)].securities_value) == 66000.0
    assert float(rows[date(2025, 11, 3)].securities_value) == 67000.0


def test_a_security_with_no_history_is_carried_at_its_last_trade(db):
    account = _account(db)
    sleeve = _sleeve(db, account)
    start = date(2025, 1, 6)
    _closes(db, "SPY", start, [1, 1, 1])
    _trade(db, sleeve, start, "BUY", 5, 40, symbol="~DELISTED CORP")

    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 1, 8))

    rows = db.query(DailyValuation).filter(DailyValuation.sleeve_id == sleeve.id).all()
    assert {float(r.securities_value) for r in rows} == {200.0}
    assert {float(r.unpriced_value) for r in rows} == {200.0}


# ---------------------------------------------------------------------------
# Splits
# ---------------------------------------------------------------------------


def test_trades_before_a_split_are_read_in_todays_shares(db):
    account = _account(db)
    sleeve = _sleeve(db, account)
    _trade(db, sleeve, date(2024, 5, 31), "BUY", 4, 1000)
    _trade(db, sleeve, date(2024, 6, 21), "SELL", 40, 120)
    db.add(
        CorporateAction(
            symbol="ABC",
            effective_date=date(2024, 6, 10),
            action_type="SPLIT",
            ratio=D(10),
            source="brokerage",
        )
    )
    db.commit()

    views = adjusted_trades(db, db.query(Trade).order_by(Trade.trade_date).all())
    positions = PortfolioCalculationService(db).calculate_positions(sleeve.id)

    assert (views[0].quantity, views[0].price) == (D(40), D(100))
    # The cash the trade moved is unchanged.
    assert views[0].quantity * views[0].price == D(4000)
    # Sold in full: no phantom short, and the gain is 40 x (120 - 100).
    assert positions["open"] == []
    assert positions["unmatched_sells"] == 0
    assert positions["closed"][0]["realized_gain"] == D(800)
    # The stored trade is untouched.
    assert db.query(Trade).filter(Trade.action == "BUY").one().quantity == D(4)


def test_value_is_continuous_across_a_split(db):
    account = _account(db)
    sleeve = _sleeve(db, account)
    start = date(2024, 6, 6)
    _closes(db, "SPY", start, [1, 1, 1, 1])
    # Split-adjusted, as the source delivers: no jump on the split day.
    _closes(db, "ABC", start, [100, 101, 102, 103])
    _trade(db, sleeve, start, "BUY", 4, 1000)
    db.add(
        CorporateAction(
            symbol="ABC",
            effective_date=date(2024, 6, 10),
            action_type="SPLIT",
            ratio=D(10),
            source="brokerage",
        )
    )
    db.commit()

    PerformanceBuildService(db).rebuild_account(account.id, today=date(2024, 6, 11))

    values = [
        float(r.securities_value)
        for r in db.query(DailyValuation)
        .filter(DailyValuation.sleeve_id == sleeve.id)
        .order_by(DailyValuation.as_of_date)
    ]
    assert values == [4000.0, 4040.0, 4080.0, 4120.0]


# ---------------------------------------------------------------------------
# Daily capture
# ---------------------------------------------------------------------------


def _captured_account(db, client, client_id, sdk, cash=6000.0, total=None):
    ba = _cash_account(
        db,
        client,
        client_id,
        sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
        ],
        cash_now=cash,
    )
    sdk.total = total
    return ba


def test_capture_records_the_days_holdings_and_totals_as_observed(
    db, client, client_id, sdk
):
    ba = _captured_account(db, client, client_id, sdk, total=10400.0)
    sdk.positions = {
        "results": [
            {
                "instrument": {"symbol": "ABC", "raw_symbol": "ABC", "kind": "stock"},
                "units": "40",
                "price": "110",
                "cost_basis": "100",
            },
        ]
    }

    result = DailyCaptureService(db).capture(ba.id)

    day = last_market_day()
    assert result["as_of_date"] == day
    (holding,) = db.query(DailyHolding).all()
    assert (holding.symbol, holding.quantity, holding.price, holding.market_value) == (
        "ABC",
        D(40),
        D(110),
        D(4400),
    )
    assert holding.security_type == "STOCK"
    assert holding.sleeve_id == ba.default_sleeve_id
    row = (
        db.query(DailyValuation)
        .filter(
            DailyValuation.account_id == ba.account_id, DailyValuation.as_of_date == day
        )
        .one()
    )
    assert row.basis == "observed"
    assert (row.total_value, row.cash_value, row.securities_value) == (
        D("10400.00"),
        D("6000.00"),
        D("4400.00"),
    )
    # The brokerage's price for the day joins the price history.
    assert db.query(DailyPrice).filter(
        DailyPrice.source == "brokerage"
    ).one().close == D(110)


def test_a_captured_day_survives_a_rebuild_unchanged(db, client, client_id, sdk):
    ba = _captured_account(db, client, client_id, sdk, total=10400.0)
    DailyCaptureService(db).capture(ba.id)
    day = last_market_day()

    def observed():
        return (
            db.query(DailyValuation)
            .filter(
                DailyValuation.account_id == ba.account_id,
                DailyValuation.as_of_date == day,
            )
            .one()
        )

    before = observed().total_value
    PerformanceBuildService(db).rebuild_account(ba.account_id)
    PerformanceBuildService(db).rebuild_account(ba.account_id)

    assert observed().basis == "observed"
    assert observed().total_value == before == D("10400.00")
    # Every market day up to it has a row; the others are reconstructed.
    rows = (
        db.query(DailyValuation)
        .filter(DailyValuation.account_id == ba.account_id)
        .all()
    )
    assert sum(1 for r in rows if r.basis == "observed") == 1
    assert len({r.as_of_date for r in rows}) == len(rows)


def test_a_late_transaction_refines_the_flow_but_not_the_captured_value(
    db, client, client_id, sdk
):
    ba = _captured_account(db, client, client_id, sdk, cash=6000.0, total=10000.0)
    day = last_market_day()
    DailyCaptureService(db).capture(ba.id, as_of=day)

    # A deposit of 2,500 made that day reaches the feed only afterwards.
    sdk.activities["data"].append(_cash_row("CONTRIBUTION", 2500.0, day.isoformat()))
    sync_brokerage_account(db, ba.id, force=True)

    row = (
        db.query(DailyValuation)
        .filter(
            DailyValuation.account_id == ba.account_id, DailyValuation.as_of_date == day
        )
        .one()
    )
    assert row.basis == "observed"
    assert row.total_value == D("10000.00")
    assert row.flow_in == D("2500.00")


def test_a_holding_our_trades_have_not_seen_is_placed_by_its_type(
    db, client, client_id, sdk
):
    etfs = client.post("/api/v1/strategies/", json={"name": "ETFs"}).json()["id"]
    stocks = client.post("/api/v1/strategies/", json={"name": "Stocks"}).json()["id"]
    sdk.activities = {
        "data": [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
        ]
    }
    sdk.cash = 3000.0
    (connection,) = client.post(
        f"/api/v1/clients/{client_id}/connections/discover"
    ).json()
    ba_id = connection["brokerage_accounts"][0]["id"]
    mapped = client.patch(
        f"/api/v1/brokerage-accounts/{ba_id}",
        json={
            "status": "mapped",
            "strategy_id": stocks,
            "strategy_routes": {"ETF": etfs},
        },
    ).json()
    sync_brokerage_account(db, ba_id)
    # Bought since, and not yet in the transaction feed.
    sdk.positions = {
        "results": [
            {
                "instrument": {"symbol": "ABC", "raw_symbol": "ABC", "kind": "stock"},
                "units": "40",
                "price": "100",
            },
            {
                "instrument": {"symbol": "XYZ", "raw_symbol": "XYZ", "kind": "etf"},
                "units": "30",
                "price": "100",
            },
        ]
    }

    DailyCaptureService(db).capture(ba_id)

    placed = {h.symbol: h.sleeve_id for h in db.query(DailyHolding)}
    assert placed["ABC"] == mapped["default_sleeve_id"]
    assert placed["XYZ"] == mapped["sleeve_routes"]["ETF"]
    # The ETF sleeve's value appeared because money went into it, not as a gain.
    row = (
        db.query(DailyValuation)
        .filter(
            DailyValuation.sleeve_id == mapped["sleeve_routes"]["ETF"],
            DailyValuation.basis == "observed",
        )
        .one()
    )
    assert row.total_value == D("3000.00")
    assert row.flow_in == D("3000.00")
    assert row.is_provisional is True


def test_capture_is_due_until_the_latest_market_day_is_recorded(
    db, client, client_id, sdk
):
    ba = _captured_account(db, client, client_id, sdk, total=10000.0)
    service = DailyCaptureService(db)

    assert service.needs_capture() is True
    service.capture(ba.id)
    assert service.needs_capture() is False


# ---------------------------------------------------------------------------
# API and report
# ---------------------------------------------------------------------------


def test_period_and_statistics_endpoints(db, client):
    account = _account(db, "Api")
    _rows(db, account, [1000, 1100, 1100, 1045, 1065.9], flows={0: 1000})
    base = f"/api/v1/clients/{account.client_id}/accounts/{account.id}/performance"

    periods = client.get(f"{base}/periods?grain=day").json()
    statistics = client.get(f"{base}/statistics").json()
    client_view = client.get(
        f"/api/v1/clients/{account.client_id}/performance/periods?grain=week"
    ).json()

    assert periods["grain"] == "day" and len(periods["periods"]) == 5
    assert periods["periods"][1]["twr_pct"] == pytest.approx(0.10)
    assert periods["periods"][1]["basis"] == "reconstructed"
    assert statistics["ending_value"] == 1065.9
    assert statistics["returns"]["inception"] == pytest.approx(0.0659)
    assert statistics["risk"]["max_drawdown"] == pytest.approx(-0.05)
    assert client_view["periods"][0]["closing_value"] == 1065.9
    assert client.get(f"{base}/periods?grain=fortnight").status_code == 422
    assert client.get("/api/v1/clients/nope/performance/periods").status_code == 404


def test_report_renders_with_the_accounts_figures(db, client):
    account = _account(db, "Reported")
    account.name = "Brokerage Account — 12345678"
    db.commit()
    _rows(db, account, [10000, 10500, 10200, 11000], flows={0: 10000})
    base = f"/api/v1/clients/{account.client_id}/accounts/{account.id}/report"

    html = client.get(f"{base}?format=html")
    pdf = client.get(base)

    assert html.status_code == 200
    assert "Investment Performance Report" in html.text
    assert "$11,000" in html.text
    assert "10.00%" in html.text  # since inception
    # The full account number in the custodian's name is not printed.
    assert "12345678" not in html.text
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"


def test_report_says_so_when_there_is_no_record(db, client):
    account = _account(db, "Empty")
    resp = client.get(
        f"/api/v1/clients/{account.client_id}/accounts/{account.id}/report"
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# The summary follows the selected period
# ---------------------------------------------------------------------------


def _two_year_sleeve(db):
    """Bought in 2024; half sold in 2024, the rest in 2025; a second holding kept."""
    from app.services.performance_service import PerformanceService

    account = _account(db, "Windowed")
    sleeve = _sleeve(db, account)
    _closes(db, "SPY", date(2024, 1, 2), [1] * 520)  # market calendar to end-2025
    _closes(db, "ABC", date(2024, 1, 2), [100 + n * 0.1 for n in range(520)])
    _closes(db, "KEEP", date(2024, 1, 2), [50 + n * 0.05 for n in range(520)])
    _trade(db, sleeve, date(2024, 1, 2), "BUY", 20, 100)
    _trade(db, sleeve, date(2024, 1, 2), "BUY", 10, 50, symbol="KEEP")
    _trade(db, sleeve, date(2024, 6, 3), "SELL", 10, 120)
    _trade(db, sleeve, date(2025, 6, 2), "SELL", 10, 150)
    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 12, 30))
    return sleeve, PerformanceService(db)


def test_realised_gain_counts_only_lots_closed_in_the_period(db, no_live_prices):
    sleeve, service = _two_year_sleeve(db)

    first = service.performance([sleeve.id], date(2024, 1, 1), date(2024, 12, 31))[
        "summary"
    ]
    second = service.performance([sleeve.id], date(2025, 1, 1), date(2025, 12, 31))[
        "summary"
    ]
    whole = service.performance([sleeve.id])["summary"]

    assert (first["total_realized_gain"], first["closed_positions_count"]) == (200.0, 1)
    assert (second["total_realized_gain"], second["closed_positions_count"]) == (
        500.0,
        1,
    )
    assert (whole["total_realized_gain"], whole["closed_positions_count"]) == (700.0, 2)
    assert (first["trades_count"], second["trades_count"], whole["trades_count"]) == (
        3,
        1,
        4,
    )


def test_unrealised_gain_is_the_balance_on_the_periods_last_day(db, no_live_prices):
    sleeve, service = _two_year_sleeve(db)

    summary = service.performance([sleeve.id], date(2024, 1, 1), date(2024, 12, 31))[
        "summary"
    ]

    row = (
        db.query(DailyValuation)
        .filter(
            DailyValuation.sleeve_id == sleeve.id,
            DailyValuation.as_of_date <= date(2024, 12, 31),
        )
        .order_by(DailyValuation.as_of_date.desc())
        .first()
    )
    # Open at the end of 2024: 10 ABC at a cost of 100 and 10 KEEP at 50.
    assert summary["total_cost_basis"] == 1500.0
    assert summary["total_market_value"] == pytest.approx(float(row.securities_value))
    assert summary["total_unrealized_gain"] == pytest.approx(
        float(row.securities_value) - 1500.0
    )
    # Not what is open today, when ABC has been sold out entirely.
    today = service.performance([sleeve.id])["summary"]
    assert today["total_cost_basis"] == 500.0


def test_cash_in_a_past_period_is_what_was_held_then(
    db, client, client_id, sdk, no_live_prices
):
    from app.services.performance_service import PerformanceService

    ba = _cash_account(
        db,
        client,
        client_id,
        sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2025-01-06"),
            _cash_row("BUY", -4000.0, "2025-01-06", "ABC", 40, 100),
            _cash_row("CONTRIBUTION", 5000.0, "2026-02-02"),
        ],
        cash_now=11000.0,
    )

    past = PerformanceService(db).performance(
        [ba.default_sleeve_id],
        date(2025, 1, 1),
        date(2025, 12, 31),
        cash_account_ids=[ba.account_id],
    )["summary"]
    now = PerformanceService(db).performance(
        [ba.default_sleeve_id], cash_account_ids=[ba.account_id]
    )["summary"]

    # At the end of 2025 the second deposit had not arrived.
    assert past["cash_balance"] == 6000.0
    assert past["total_value"] == pytest.approx(
        past["total_market_value"] + past["cash_balance"]
    )
    assert now["cash_balance"] == 11000.0


# ---------------------------------------------------------------------------
# The realised basis: holdings at cost, unrealised gains left out
# ---------------------------------------------------------------------------


def _held_then_sold(db):
    """Bought at 100, rises to 150 while held, sold at 150 on the last day."""
    account = _account(db, "Realised")
    sleeve = _sleeve(db, account)
    start = date(2025, 1, 6)
    _closes(db, "SPY", start, [1] * 5)
    _closes(db, "ABC", start, [100, 120, 140, 150, 150])
    _trade(db, sleeve, start, "BUY", 10, 100)
    _trade(db, sleeve, date(2025, 1, 10), "SELL", 10, 150)
    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 1, 10))
    return account, sleeve


def test_cost_of_what_is_open_is_recorded_each_day(db):
    account, sleeve = _held_then_sold(db)

    rows = (
        db.query(DailyValuation)
        .filter(DailyValuation.sleeve_id == sleeve.id)
        .order_by(DailyValuation.as_of_date)
        .all()
    )
    assert [float(r.securities_value) for r in rows] == [1000, 1200, 1400, 1500, 0]
    # Cost does not move with the price; it goes when the position is closed.
    assert [float(r.cost_value) for r in rows] == [1000, 1000, 1000, 1000, 0]


def test_realised_basis_counts_the_gain_only_when_the_position_closes(db):
    account, sleeve = _held_then_sold(db)
    stats = PerformanceStatsService(db)

    market = stats.periods(stats.daily(sleeve_ids=[sleeve.id]), "day")
    realised = stats.periods(
        stats.daily(sleeve_ids=[sleeve.id], basis="realized"), "day"
    )

    # At market the gain builds day by day; realised, it lands on the sale.
    assert [round(d["twr_pct"], 4) for d in market[1:4]] == [0.2, 0.1667, 0.0714]
    assert [d["twr_pct"] for d in realised[1:4]] == [0.0, 0.0, 0.0]
    assert realised[-1]["gain"] == pytest.approx(500.0)
    assert [d["closing_value"] for d in realised] == [1000, 1000, 1000, 1000, 0]
    # Both bases agree once nothing is left unrealised.
    assert realised[-1]["twr_cumulative_pct"] == pytest.approx(
        market[-1]["twr_cumulative_pct"]
    )


def test_realised_basis_leaves_an_open_gain_out(db):
    account = _account(db, "StillOpen")
    sleeve = _sleeve(db, account)
    start = date(2025, 1, 6)
    _closes(db, "SPY", start, [1] * 3)
    _closes(db, "ABC", start, [100, 120, 150])
    _trade(db, sleeve, start, "BUY", 10, 100)
    PerformanceBuildService(db).rebuild_account(account.id, today=date(2025, 1, 8))
    stats = PerformanceStatsService(db)

    (market,) = stats.periods(stats.daily(sleeve_ids=[sleeve.id]), "week")
    (realised,) = stats.periods(
        stats.daily(sleeve_ids=[sleeve.id], basis="realized"), "week"
    )

    assert market["twr_pct"] == pytest.approx(0.5)
    assert realised["twr_pct"] == pytest.approx(0.0)
    assert realised["closing_value"] == 1000.0


def test_an_account_opening_on_existing_cash_does_not_gain_on_its_first_day(db):
    # The record starts with 5,000 already in the account; 1,000 more arrives.
    account = _account(db, "Opening")
    db.add(
        DailyValuation(
            account_id=account.id,
            as_of_date=date(2025, 1, 6),
            securities_value=D(0),
            cost_value=D(0),
            cash_value=D(6000),
            total_value=D(6000),
            flow_in=D(1000),
            flow_out=D(0),
            return_factor=D(1),
            basis="reconstructed",
        )
    )
    db.commit()
    stats = PerformanceStatsService(db)

    (day,) = stats.daily(account_ids=[account.id], basis="realized")

    assert day.factor == D(1)


def test_period_endpoints_take_a_basis(db, client):
    account, sleeve = _held_then_sold(db)
    base = (
        f"/api/v1/clients/{account.client_id}/accounts/{account.id}"
        f"/sleeves/{sleeve.id}/performance"
    )

    realised = client.get(f"{base}/periods?grain=day&basis=realized").json()
    monthly = client.get(f"{base}/monthly?basis=realized").json()
    series = client.get(f"{base}/returns-series?basis=realized").json()

    assert realised["basis"] == "realized"
    assert realised["periods"][2]["twr_pct"] == 0.0
    assert monthly["months"][0]["return_pct"] == 50.0
    assert series["series"][-1]["twr_cumul"] == pytest.approx(0.5)
    assert client.get(f"{base}/periods?basis=book").status_code == 422
