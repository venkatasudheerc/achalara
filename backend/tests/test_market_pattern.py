# flake8: noqa: F811
"""The market-pattern tile: market data's record, the app's daily copy of it, and
the rule that sets it beside the cash the viewer holds. Every figure is invented."""
from datetime import date, datetime, timedelta, timezone

from app.models.market_pattern import MarketPatternCopy
from app.services import market_pattern_copy
from app.services.insights.service import InsightService
from tests.test_insights import TODAY, Stub, account
from tests.test_research_api import market  # fixture: 36 years of daily S&P 500 levels


# -- market data's record ---------------------------------------------------

def test_the_pattern_is_a_square_per_year_for_this_week_of_the_year_and_this_month(db, market):
    db.commit()
    from app.md import insights

    november = insights.market_pattern(db, today=date(2026, 11, 9))  # a Monday, ISO week 46
    assert november["week_key"] == [2026, 46] and november["month_key"] == [2026, 11]
    month, week = november["month"], november["week"]
    # The test index rises every day except in September: every November rose.
    assert len(month["years"]) == 20 and all(y["up"] for y in month["years"])
    assert month["years"][0]["year"] == month["first_year"] and month["years"][-1]["year"] == month["last_year"] == 2025
    assert month["best"] >= month["median"] >= month["worst"] > 0
    assert len(week["years"]) == 20 and all(y["up"] for y in week["years"])

    # And September has fallen every year: said as plainly.
    september = insights.market_pattern(db, today=date(2026, 9, 16))["month"]
    assert not any(y["up"] for y in september["years"]) and september["best"] < 0


# -- the app's copy ----------------------------------------------------------

def test_the_copy_is_stored_read_back_and_dropped_when_stale(db, market):
    db.commit()
    assert market_pattern_copy.latest(db) is None
    assert market_pattern_copy.refresh(db, today=date(2026, 11, 9)) is True
    row = db.get(MarketPatternCopy, "sp500")
    assert row.payload["month_key"] == [2026, 11] and row.payload["as_of"] == "2026-11-09"

    stored = row.refreshed_at if row.refreshed_at.tzinfo else row.refreshed_at.replace(tzinfo=timezone.utc)
    fresh = market_pattern_copy.latest(db, today=stored.date() + timedelta(days=2))
    assert fresh["name"] == "S&P 500"
    # Older than four days: the week and month it names may be over.
    assert market_pattern_copy.latest(db, today=stored.date() + timedelta(days=6)) is None


def test_with_no_levels_on_file_nothing_is_stored_and_the_old_copy_stays(db):
    assert market_pattern_copy.refresh(db) is False
    assert db.query(MarketPatternCopy).count() == 0
    db.add(MarketPatternCopy(key="sp500", payload={"kept": True}, refreshed_at=datetime.now(timezone.utc)))
    db.commit()
    assert market_pattern_copy.refresh(db) is False
    assert db.get(MarketPatternCopy, "sp500").payload == {"kept": True}


def test_the_job_is_listed_on_system_status(client):
    ids = [j["id"] for j in client.get("/api/v1/admin/status").json()["jobs"]]
    assert "market_pattern_copy" in ids


# -- the rule -----------------------------------------------------------------

def pattern(ups, grain_median=0.019, best=0.108, worst=-0.075):
    years = [{"year": 2006 + i, "up": up} for i, up in enumerate(ups)]
    return {"count": len(ups), "median": grain_median, "best": best, "worst": worst,
            "years": years, "first_year": 2006, "last_year": 2006 + len(ups) - 1}


def copy(week_ups, month_ups, week_key=None, month_key=None):
    return {
        "code": "SPX", "name": "S&P 500", "basis": "price", "as_of": "2026-11-15",
        "week_key": week_key or list(TODAY.isocalendar()[:2]),
        "month_key": month_key or [TODAY.year, TODAY.month],
        "week": pattern(week_ups), "month": pattern(month_ups),
    }


def tile(stub, payload):
    out = InsightService(stub, lambda ids: stub, today=TODAY, market=lambda: payload).respond()
    return next((f for f in out["insights"] if f["rule"] == "cash_and_market_pattern"), None)


HOLDINGS = [account("Chk", "checking", 12000), account("Brk", "taxable", 88000, cash=0)]
ELEVEN_OF_TWENTY = [True] * 11 + [False] * 9
FIFTEEN_OF_TWENTY = [True] * 15 + [False] * 5


def test_cash_over_a_tenth_is_set_beside_the_week_and_the_month_in_past_years():
    finding = tile(Stub(HOLDINGS), copy(ELEVEN_OF_TWENTY, FIFTEEN_OF_TWENTY))
    assert finding["title"] == "You hold 12% in cash. The S&P 500 rose in 15 of the last 20 Novembers."
    assert finding["wide"] and finding["action"] is None
    assert finding["link"]["view"] == "research"
    spans = finding["visual"]["spans"]
    assert [s["when"] for s in spans] == ["This week · 9 to 13 Nov", "This month · November"]
    assert spans[0]["said"] == "Up in 11 of the last 20 years" and spans[1]["said"] == "Up in 15 of the last 20 years"
    assert spans[1]["years"] == FIFTEEN_OF_TWENTY
    assert spans[1]["nums"] == "Typical month +1.9% · best +10.8% · worst −7.5%"
    assert "not what this year will do" in finding["detail"]
    assert finding["foot"] == "S&P 500, 2006 to 2025 · your cash as of 15 Nov"


def test_a_month_with_a_poor_record_is_said_as_plainly():
    finding = tile(Stub(HOLDINGS), copy([False] * 12 + [True] * 8, [False] * 11 + [True] * 9))
    assert "rose in 9 of the last 20 Novembers" in finding["title"]
    assert [s["said"] for s in finding["visual"]["spans"]] == ["Up in 8 of the last 20 years", "Up in 9 of the last 20 years"]


def test_it_waits_for_cash_over_a_tenth_a_fresh_copy_and_enough_years():
    payload = copy(ELEVEN_OF_TWENTY, FIFTEEN_OF_TWENTY)
    # Exactly a tenth is not over it.
    tenth = [account("Chk", "checking", 10000), account("Brk", "taxable", 90000, cash=0)]
    assert tile(Stub(tenth), payload) is None
    assert tile(Stub(HOLDINGS), None) is None  # no copy, or an old one
    # Fewer than ten years of a period is not a record: that stretch is left out.
    short = tile(Stub(HOLDINGS), copy([True] * 6, FIFTEEN_OF_TWENTY))
    assert [s["when"] for s in short["visual"]["spans"]] == ["This month · November"]
    assert tile(Stub(HOLDINGS), copy([True] * 6, [True] * 6)) is None


def test_a_copy_made_for_another_week_or_month_is_not_used():
    last_week = copy(ELEVEN_OF_TWENTY, FIFTEEN_OF_TWENTY, week_key=[2026, 45])
    assert [s["when"] for s in tile(Stub(HOLDINGS), last_week)["visual"]["spans"]] == ["This month · November"]
    assert tile(Stub(HOLDINGS), copy(ELEVEN_OF_TWENTY, FIFTEEN_OF_TWENTY, week_key=[2026, 45], month_key=[2026, 10])) is None


def test_an_incomplete_asset_holds_the_tile_back_like_the_cash_nudge():
    sick = account("Brk", "taxable", 88000, cash=0, health={"state": "incomplete", "reasons": ["x"], "download_from": None})
    assert tile(Stub([account("Chk", "checking", 12000), sick]), copy(ELEVEN_OF_TWENTY, FIFTEEN_OF_TWENTY)) is None
