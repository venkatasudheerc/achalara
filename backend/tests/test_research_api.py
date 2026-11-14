"""Research for every signed-in user: what a client login may read, and the insights."""
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.md import insights
from app.md.models import (
    IndexDef,
    IndexLevelHist,
    IndexMember,
    IndexMemberHist,
    PriceAdjDaily,
    Security,
    SecurityClassification,
    SecuritySymbol,
)
from app.models.client import Client
from app.services.auth_service import AuthService

TODAY = date(2026, 11, 8)  # a Sunday: the week of 2-6 November has ended
STAMP = datetime(2026, 11, 8)
ADVISOR = ("research-advisor@example.com", "Correct-Horse-Battery-9")
CLIENT_PASSWORD = "Another-Long-Passphrase-7"


def _weekdays(first, last):
    day = first
    while day <= last:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def _security(db, symbol, kind="stock", sector="IT", member="SP500", nov_boost=0.0):
    security = Security(name=f"{symbol} Example Corp", kind=kind)
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    if member:
        db.add(IndexMember(index_code=member, security_id=security.id, since=TODAY))
        db.add(
            IndexMemberHist(
                index_code=member, security_id=security.id, valid_from=TODAY
            )
        )
    if sector:
        db.add(
            SecurityClassification(
                security_id=security.id, sector_code=sector, as_of=TODAY
            )
        )
    close = 100.0
    for day in _weekdays(date(2021, 12, 1), date(2026, 11, 6)):
        step = 0.0005 + (nov_boost if day.month == 11 else 0.0)
        close *= 1 + step
        db.add(
            PriceAdjDaily(
                security_id=security.id,
                price_date=day,
                adj_close=Decimal(str(round(close, 4))),
                fetched_at=STAMP,
            )
        )
    db.flush()
    return security


@pytest.fixture
def market(db):
    for code in ("SP500", "R2000"):
        db.add(IndexDef(code=code, name=code, owner="Example", method="fund_file"))
    db.flush()
    _security(db, "AAA", nov_boost=0.004)  # beats SPY every November
    _security(db, "BBB", sector="FIN")
    _security(db, "SPY", kind="etf", sector=None, member=None)
    _security(db, "IWM", kind="etf", sector=None, member=None)
    _security(db, "SML", sector="IT", member="R2000")
    level = 1000.0
    for day in _weekdays(date(1990, 1, 1), date(2026, 11, 6)):
        level *= 1.0003 if day.month != 9 else 0.9995
        db.add(
            IndexLevelHist(
                symbol="SPX",
                price_date=day,
                close=Decimal(str(round(level, 4))),
                source="test",
                fetched_at=STAMP,
            )
        )
    db.flush()


@pytest.fixture
def as_family_member(db, anon_client, monkeypatch):
    """A second browser, signed in as a client through a real invite."""
    from app.md import insights as module

    monkeypatch.setattr(module, "date", _FixedDate)
    AuthService(db).create_advisor(ADVISOR[0], "Ada Advisor", ADVISOR[1])
    member = Client(name="Example Family Member", email="member@example.com")
    db.add(member)
    db.commit()
    advisor = anon_client  # on the test database
    assert (
        advisor.post(
            "/api/v1/auth/login", json={"email": ADVISOR[0], "password": ADVISOR[1]}
        ).status_code
        == 200
    )
    link = advisor.post("/api/v1/auth/invites", json={"client_id": member.id}).json()
    browser = TestClient(app)
    assert (
        browser.post(
            f"/api/v1/auth/links/{link['token']}/accept",
            json={"password": CLIENT_PASSWORD},
        ).status_code
        == 200
    )
    return browser


class _FixedDate(date):
    @classmethod
    def today(cls):
        return TODAY


RESEARCH_PATHS = (
    "this-week",
    "this-month",
    "outlook?month=11",
    "calendar?symbol=SPX&start_year=2000&end_year=2025",
    "month-grid?symbol=AAA",
    "month-grid?symbol=SPX&start_year=2000&end_year=2009",
    "top-performers?month=11",
    "sectors?month=11&compare=R2000",
    "securities?q=aaa",
    "securities/AAA?month=11",
    "returns?symbols=AAA,SPX",
    "seasonality?subject=SPX",
    "movers?grain=week&universe=SP500",
    "tools",
)


def test_a_family_member_reads_every_research_route(as_family_member, market):
    for path in RESEARCH_PATHS:
        response = as_family_member.get(f"/api/v1/research/{path}")
        assert response.status_code == 200, (path, response.text[:200])


def test_a_family_member_cannot_reach_the_operations_pages(as_family_member):
    for path in ("/api/v1/admin/market-data/status", "/api/v1/admin/status"):
        assert as_family_member.get(path).status_code == 403, path


def test_research_is_not_open_to_the_public(anon_client):
    for path in ("this-week", "tools", "securities/AAA"):
        assert anon_client.get(f"/api/v1/research/{path}").status_code == 401


def test_the_tool_list_describes_every_function(as_family_member):
    tools = as_family_member.get("/api/v1/research/tools").json()
    names = {t["name"] for t in tools}
    assert names == {t.name for t in insights.TOOLS}
    for tool in tools:
        assert tool["description"]
        assert tool["parameters"]["type"] == "object"
        assert tool["parameters"]["additionalProperties"] is False


def test_this_week_reports_the_week_that_ended(db, market):
    week = insights.this_week(db, TODAY)
    assert week["period"] == "2026-W45" and week["end"] == date(2026, 11, 6)
    assert {r["symbol"] for r in week["indices"]} == {"SPX"}
    assert any("dividends" in n for n in week["notes"])
    assert week["running"] is False


def test_this_week_is_the_week_so_far_while_it_is_running(db, market):
    """On a weekday the week has not ended; it is shown to the latest close, not
    the week before."""
    week = insights.this_week(db, date(2026, 11, 5))  # a Thursday
    assert week["period"] == "2026-W45" and week["running"] is True
    assert week["start"] == date(2026, 11, 2)
    assert any("so far" in n for n in week["notes"])


def test_top_performers_compare_with_the_index_fund_and_say_what_luck_gives(db, market):
    out = insights.top_performers(db, 11, "SP500", today=TODAY)
    assert out["benchmark"]["symbol"] == "SPY"
    assert [r["symbol"] for r in out["rows"]] == ["AAA"]
    row = out["rows"][0]
    assert (
        row["sector"] == "Information Technology" and row["name"] == "AAA Example Corp"
    )
    assert out["eligible"] == 2 and out["expected_by_luck"] == pytest.approx(
        2 * 0.5**4
    )
    # The luck estimate is a figure for the advisor's screen, not a note every reader sees.
    assert not any("chance" in n for n in out["notes"])
    small = insights.top_performers(db, 11, "R2000", today=TODAY)
    assert small["benchmark"]["symbol"] == "IWM"
    with pytest.raises(ValueError):
        insights.top_performers(db, 13, today=TODAY)


def test_the_sector_scorecard_puts_two_indices_side_by_side(db, market):
    out = insights.sector_scorecard(db, 11, "SP500", "R2000", TODAY)
    rows = {r["sector_code"]: r["results"] for r in out["sectors"]}
    assert rows["IT"]["SP500"]["beat_share"] == 1.0  # AAA, every November
    assert "R2000" in rows["IT"]
    assert rows["FIN"]["SP500"]["observations"] == 4
    assert rows["FIN"]["SP500"]["stocks"] == 1
    it = rows["IT"]["SP500"]
    assert it["median_return"] > it["median_excess"] > 0  # SPY also rose each November
    # Ordered by lead over the benchmark, highest first.
    leads = [r["results"]["SP500"]["median_excess"] for r in out["sectors"]]
    assert leads == sorted(leads, reverse=True)
    assert any("up to 4 so far" in n for n in out["notes"])


def test_a_calendar_grid_says_how_thin_its_cells_are(db, market):
    stock = insights.calendar_grid(db, "AAA", today=TODAY)
    assert any("not a seasonal pattern" in n for n in stock["notes"])
    index = insights.calendar_grid(db, "SPX", 1991, 2025, "median", TODAY)
    assert index["years"]["first"] == 1991 and index["stat"] == "median"
    assert not any("not a seasonal pattern" in n for n in index["notes"])
    assert all(c["days"] >= 1 for c in index["cells"])


def test_finding_and_profiling_a_security(db, market):
    found = insights.find_security(db, "example corp")
    assert {r["symbol"] for r in found["results"]} >= {"AAA", "BBB"}
    assert insights.find_security(db, "aaa")["results"][0]["symbol"] == "AAA"
    profile = insights.security_profile(db, "AAA", 11, TODAY)
    assert (
        profile["indices"] == ["SP500"]
        and profile["sector"] == "Information Technology"
    )
    assert len(profile["last_12_months"]) == 12
    assert profile["month_by_trading_day"]["buckets"]
    path = profile["month_path"]
    assert [d["day"] for d in path["typical"]] == list(range(1, 31))
    assert path["years"] == 4 and path["typical"][-1]["mean"] > 0  # Novembers 2022-2025
    current = path["current"]
    assert current["year"] == 2026 and current["through"] == date(2026, 11, 6)
    assert [d["day"] for d in current["days"]] == list(range(1, 7))
    assert insights.security_profile(db, "AAA", 10, TODAY)["month_path"]["current"] is None
    assert profile["sector_month_of_year"]["survivorship"] is True


def test_a_month_grid_runs_year_by_year_with_each_months_record(db, market):
    grid = insights.month_grid(db, "AAA", today=TODAY)
    # December 2021 is the first month on file and has no close before it.
    assert [r["year"] for r in grid["rows"]] == [2026, 2025, 2024, 2023, 2022]
    latest, whole = grid["rows"][0], grid["rows"][1]
    assert latest["running_month"] == 11 and latest["complete"] is False
    assert len(latest["months"]) == 11 and whole["complete"] is True
    growth = 1.0
    for value in whole["months"].values():
        growth *= 1 + value
    assert whole["ret"] == pytest.approx(growth - 1)
    november = grid["summary"]["11"]
    assert november["count"] == 4  # the running November is left out
    assert november["share_up"] == 1.0 and november["share_down"] == 0.0
    assert november["abs_best"] == pytest.approx(november["best"])
    assert grid["best"]["month"] == 11 and grid["year_summary"]["count"] == 4
    assert any("five years" in n for n in grid["notes"])


def test_a_month_grid_takes_a_span_of_years(db, market):
    grid = insights.month_grid(db, "SPX", 2000, 2009, TODAY)
    assert grid["years"] == {"first": 2000, "last": 2009, "count": 10}
    assert grid["available"]["first"] == 1990 and grid["basis"] == "price"
    assert grid["summary"]["9"]["share_down"] == 1.0  # every September fell
    assert all(r["complete"] for r in grid["rows"])
    with pytest.raises(ValueError):
        insights.month_grid(db, "SPX", 2010, 2000, TODAY)
    with pytest.raises(ValueError):
        insights.month_grid(db, "AAA", 2010, 2012, TODAY)


def test_search_puts_a_word_match_and_a_large_company_first(db, market):
    from app.md.models import Security, SecuritySymbol

    for symbol, name in (("PNX", "Pineapple Example Holdings"), ("APX", "Apple Example Inc")):
        security = Security(name=name, kind="stock")
        db.add(security)
        db.flush()
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    db.flush()
    found = [r["symbol"] for r in insights.find_security(db, "apple")["results"]]
    assert found[:2] == ["APX", "PNX"]  # a word starting "apple" before "pineapple"
    # Same kind of match: the S&P 500 member (AAA, BBB) before the rest.
    # Tickers starting with the text come before names, shortest ticker first.
    for symbol, name in (("APXL", "Long Ticker Example"), ("ZZZ", "Apx Partners Example")):
        security = Security(name=name, kind="stock")
        db.add(security)
        db.flush()
        db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    db.flush()
    found = [r["symbol"] for r in insights.find_security(db, "apx")["results"]]
    assert found[:3] == ["APX", "APXL", "ZZZ"]
    names = [r["symbol"] for r in insights.find_security(db, "example corp")["results"]]
    assert names.index("AAA") < names.index("SML") and names.index("BBB") < names.index("SML")


def test_the_vix_says_its_change_is_not_a_return(db, market):
    from app.md import levels

    assert levels.LEVELS["VIX"] == "^VIX"
    level = 20.0
    for day in _weekdays(date(2015, 1, 1), date(2026, 11, 6)):
        level = level * (1.01 if day.day < 15 else 0.99)
        db.add(IndexLevelHist(symbol="VIX", price_date=day, close=Decimal(str(round(level, 4))), source="test", fetched_at=STAMP))
    db.flush()
    grid = insights.month_grid(db, "VIX", today=TODAY)
    assert grid["kind"] == "index" and any("not a return" in n for n in grid["notes"])
    assert any("not a return" in n for n in insights.calendar_grid(db, "VIX", today=TODAY)["notes"])
    assert not any("not a return" in n for n in insights.month_grid(db, "SPX", today=TODAY)["notes"])


def test_the_index_registry_lists_us_and_indian_levels():
    from app.md import levels

    codes = [i.code for i in levels.INDEX_LEVELS_INFO]
    assert len(codes) == len(set(codes)) and all(len(c) <= 12 for c in codes)
    assert {c: levels.LEVELS[c] for c in ("SPX", "NDX", "DJI", "RUI", "RUT", "RUA", "VIX")} == {
        "SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "RUI": "^RUI", "RUT": "^RUT", "RUA": "^RUA", "VIX": "^VIX"
    }
    assert levels.LEVELS["CNX500"] == "^CRSLDX"  # Yahoo serves Nifty 500 under this symbol
    india = [i for i in levels.INDEX_LEVELS_INFO if i.country == "IN"]
    assert len(india) == 21 and {i.currency for i in india} == {"INR"}
    assert {i.code for i in levels.INDEX_LEVELS_INFO if i.volatility} == {"VIX", "INDIAVIX"}


def _level(db, code, start=date(2015, 1, 1)):
    value = 1000.0
    for day in _weekdays(start, date(2026, 11, 6)):
        value *= 1.0004
        db.add(IndexLevelHist(symbol=code, price_date=day, close=Decimal(str(round(value, 4))), source="test", fetched_at=STAMP))
    db.flush()


def test_an_indian_index_says_its_level_is_in_rupees(db, market):
    _level(db, "NSEI")
    _level(db, "INDIAVIX")
    grid = insights.month_grid(db, "^NSEI", today=TODAY)
    assert grid["symbol"] == "NSEI" and grid["kind"] == "index"
    assert any("Indian rupees" in n for n in grid["notes"])
    assert any("Indian rupees" in n for n in insights.calendar_grid(db, "NSEI", today=TODAY)["notes"])
    assert any("Indian rupees" in n for n in insights.security_profile(db, "^NSEI", 11, TODAY)["notes"])
    vix = insights.month_grid(db, "INDIAVIX", today=TODAY)["notes"]
    assert any("the Nifty 50" in n and "not a return" in n for n in vix)
    assert not any("rupees" in n for n in insights.month_grid(db, "SPX", today=TODAY)["notes"])


def test_a_caret_always_means_the_index_even_when_a_stock_shares_the_code(db, market):
    _level(db, "NSEI")
    _security(db, "NSEI", member=None)  # a stock that happens to trade under the code
    assert insights.month_grid(db, "NSEI", today=TODAY)["kind"] == "security"
    assert insights.month_grid(db, "^NSEI", today=TODAY)["kind"] == "index"
    from app.md.status_report import _indices

    attention = []
    _indices(db, TODAY, attention)
    assert any("NSEI" in line and "^" in line for line in attention)


def test_a_family_member_reads_the_list_of_indices(as_family_member, market, db):
    _level(db, "NSEI")
    db.commit()
    body = as_family_member.get("/api/v1/research/indices").json()
    by_code = {i["code"]: i for i in body["indices"]}
    assert by_code["NSEI"]["display"] == "^NSEI" and by_code["NSEI"]["currency"] == "INR"
    assert by_code["NSEI"]["group"] == "India: broad market" and by_code["NSEI"]["first_day"]
    assert by_code["SPX"]["group"] == "Indices (US)" and by_code["INDIAVIX"]["volatility"]
