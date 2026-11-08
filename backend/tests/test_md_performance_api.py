"""The market-data performance endpoints: advisors only, and refusals as HTTP answers."""
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.md import read as md_read
from app.md.models import IndexDef, IndexMember, PriceAdjDaily, Security, SecuritySymbol

STAMP = datetime(2026, 11, 8)


def _security(db, symbol, step):
    security = Security(name=symbol, kind="stock")
    db.add(security)
    db.flush()
    db.add(SecuritySymbol(security_id=security.id, symbol=symbol))
    if not db.get(IndexDef, "XYZ"):
        db.add(
            IndexDef(code="XYZ", name="Example", owner="Example", method="fund_file")
        )
        db.flush()
    db.add(
        IndexMember(index_code="XYZ", security_id=security.id, since=date(2026, 1, 2))
    )
    day, close = date(2024, 1, 2), 100.0
    while day < date(2026, 11, 7):
        if day.weekday() < 5:
            db.add(
                PriceAdjDaily(
                    security_id=security.id,
                    price_date=day,
                    adj_close=Decimal(str(round(close, 4))),
                    fetched_at=STAMP,
                )
            )
            close *= 1 + step
        day += timedelta(days=1)
    db.flush()


def test_returns(client, db):
    _security(db, "AAA", 0.001)
    _security(db, "BBB", 0.0)
    body = client.get(
        "/api/v1/research/returns",
        params={"symbols": "AAA,NOPE", "grain": "month", "benchmark": "BBB"},
    ).json()
    assert body["unknown"] == ["NOPE"] and body["benchmark"]["basis"] == "total"
    period = body["series"][0]["periods"][0]
    assert period["ret"] > 0 and period["excess"] == period["ret"]


def test_seasonality_and_the_month_it_needs(client, db):
    _security(db, "AAA", 0.001)
    ok = client.get(
        "/api/v1/research/seasonality",
        params={"subject": "AAA", "by": "trading_day", "month": 11},
    )
    assert (
        ok.status_code == 200 and ok.json()["buckets"][0]["bucket"] == "trading day 1"
    )
    assert ok.json()["month_to_date"]
    missing = client.get(
        "/api/v1/research/seasonality",
        params={"subject": "AAA", "by": "trading_day"},
    )
    assert missing.status_code == 422
    unknown = client.get("/api/v1/research/seasonality", params={"subject": "NOPE"})
    assert unknown.status_code == 404


def test_consistent_months_and_movers(client, db):
    _security(db, "AAA", 0.002)
    _security(db, "BBB", 0.0)
    body = client.get(
        "/api/v1/research/consistent-months",
        params={"month": 6, "benchmark": "BBB", "min_years": 2, "universe": "XYZ"},
    ).json()
    assert [r["symbol"] for r in body["rows"]] == ["AAA"]
    assert body["expected_by_luck"] > 0
    movers = client.get(
        "/api/v1/research/movers", params={"grain": "month", "universe": "XYZ"}
    ).json()
    assert movers["best"][0]["symbol"] == "AAA" and movers["count"] == 2


def test_a_separate_database_that_is_down_is_a_503(client, monkeypatch):
    def down(**kwargs):
        raise md_read.MdUnavailable("OperationalError")

    monkeypatch.setattr(md_read, "market_returns", down)
    response = client.get("/api/v1/research/returns", params={"symbols": "AAA"})
    assert response.status_code == 503


def test_not_open_to_the_public(anon_client):
    for path in ("returns?symbols=SPY", "seasonality?subject=SPY", "movers"):
        assert anon_client.get(f"/api/v1/research/{path}").status_code == 401
