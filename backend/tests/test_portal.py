"""The client portal: one client's accounts read together, and nobody else's."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.account import Account
from app.models.client import Client
from app.models.perf import DailyHolding, DailyValuation
from app.models.position import Position
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.trade import Trade
from app.models.user import AccountAccess
from app.services.auth_service import AuthService
from tests.test_perf import _closes, _rows

PASSWORD = "a long passphrase 2026"
OPTION = "ABC270115P00050000"


def _trade(db, sleeve, day, action, qty, price, symbol, kind="STOCK"):
    db.add(
        Trade(
            sleeve_id=sleeve.id,
            trade_date=day,
            symbol=symbol,
            action=action,
            quantity=D(str(qty)),
            price=D(str(price)),
            commission=D(0),
            security_type=kind,
        )
    )


def _priced(db, sleeve, symbol, quantity, cost, price):
    db.add(
        Position(
            sleeve_id=sleeve.id,
            symbol=symbol,
            status="OPEN",
            quantity=D(str(quantity)),
            cost_basis=D(str(cost)),
            current_price=D(str(price)),
        )
    )


@pytest.fixture
def world(db):
    """Maya: a brokerage account run as Growth and Index, and an IRA run as
    Index. Ravi: a trust run as Growth, which nobody else may see by default."""
    maya = Client(name="Maya Rao", email="maya@example.com")
    ravi = Client(name="Ravi Rao", email="ravi@example.com")
    growth, index = Strategy(name="Growth"), Strategy(name="Index")
    db.add_all([maya, ravi, growth, index])
    db.flush()
    brokerage = Account(
        client_id=maya.id, name="Brokerage — 12345678", account_number="12345678"
    )
    ira = Account(client_id=maya.id, name="Rollover IRA", account_number="99990001")
    trust = Account(client_id=ravi.id, name="Family Trust", account_number="55551180")
    db.add_all([brokerage, ira, trust])
    db.flush()

    def sleeve(account, strategy):
        row = Sleeve(
            account_id=account.id, strategy_id=strategy.id, accounting_method="FIFO"
        )
        db.add(row)
        db.flush()
        return row

    s = {
        "brokerage_growth": sleeve(brokerage, growth),
        "brokerage_index": sleeve(brokerage, index),
        "ira_index": sleeve(ira, index),
        "trust_growth": sleeve(trust, growth),
    }
    # Brokerage / Growth: AAPL held; AMD bought and sold within a year (+200);
    # an option written and still open.
    _trade(db, s["brokerage_growth"], date(2025, 3, 3), "BUY", 10, 100, "AAPL")
    _trade(db, s["brokerage_growth"], date(2025, 11, 20), "BUY", 20, 50, "AMD")
    _trade(db, s["brokerage_growth"], date(2026, 8, 14), "SELL", 20, 60, "AMD")
    _trade(
        db, s["brokerage_growth"], date(2026, 9, 18), "SELL", 2, 300, OPTION, "OPTION"
    )
    # Brokerage / Index: VOO held; DIS held for more than a year, sold at a loss (-50).
    _trade(db, s["brokerage_index"], date(2024, 1, 9), "BUY", 5, 400, "VOO", "ETF")
    _trade(db, s["brokerage_index"], date(2024, 2, 1), "BUY", 10, 100, "DIS")
    _trade(db, s["brokerage_index"], date(2026, 1, 15), "SELL", 10, 95, "DIS")
    # IRA / Index, and Ravi's trust.
    _trade(db, s["ira_index"], date(2026, 10, 2), "BUY", 4, 250, "VTI", "ETF")
    _trade(db, s["trust_growth"], date(2026, 5, 6), "BUY", 3, 200, "JNJ")
    _priced(db, s["brokerage_growth"], "AAPL", 10, 1000, 150)
    _priced(db, s["brokerage_index"], "VOO", 5, 2000, 500)
    _priced(db, s["ira_index"], "VTI", 4, 1000, 260)
    _priced(db, s["trust_growth"], "JNJ", 3, 600, 190)
    db.commit()
    return {
        "maya": maya,
        "ravi": ravi,
        "growth": growth,
        "index": index,
        "brokerage": brokerage,
        "ira": ira,
        "trust": trust,
        **s,
    }


def _browser_for(db, client, role_email=None):
    """A browser signed in as ``client`` through a real invite."""
    service = AuthService(db)
    token, _ = service.invite_client(client.id)
    browser = TestClient(app)
    accepted = browser.post(
        f"/api/v1/auth/links/{token}/accept", json={"password": PASSWORD}
    )
    assert accepted.status_code == 200
    return browser


@pytest.fixture
def maya(anon_client, db, world):
    return _browser_for(db, world["maya"])


def _symbols(rows):
    return sorted(r["symbol"] for r in rows)


# -- whose portal ---------------------------------------------------------


def test_portal_needs_a_session(anon_client, world):
    for path in [
        "accounts",
        "overview",
        "positions",
        "trades",
        "realized",
        "performance",
    ]:
        assert anon_client.get(f"/api/v1/portal/{path}").status_code == 401, path


def test_accounts_lists_own_accounts_and_their_strategies(maya, world):
    body = maya.get("/api/v1/portal/accounts").json()

    assert body["viewer"] == {
        "client_id": world["maya"].id,
        "name": "Maya Rao",
        "preview": False,
    }
    assert [a["name"] for a in body["accounts"]] == ["Brokerage", "Rollover IRA"]
    brokerage = body["accounts"][0]
    assert brokerage["number_last4"] == "5678" and not brokerage["shared"]
    assert [s["strategy_name"] for s in brokerage["sleeves"]] == ["Growth", "Index"]
    assert "12345678" not in maya.get("/api/v1/portal/accounts").text


def test_a_client_cannot_name_another_client_or_reach_their_account(maya, world):
    # ``as_client`` is the advisor's; from a client it changes nothing.
    as_other = maya.get(
        "/api/v1/portal/positions", params={"as_client": world["ravi"].id}
    ).json()
    assert "JNJ" not in _symbols(as_other["positions"])

    others_account = maya.get(
        "/api/v1/portal/positions", params={"account_id": world["trust"].id}
    )
    assert others_account.status_code == 404


def test_a_shared_account_joins_the_view_marked_shared(maya, db, world):
    db.add(AccountAccess(client_id=world["maya"].id, account_id=world["trust"].id))
    db.commit()

    accounts = maya.get("/api/v1/portal/accounts").json()["accounts"]
    positions = maya.get("/api/v1/portal/positions").json()["positions"]

    assert [(a["name"], a["shared"]) for a in accounts][-1] == ("Family Trust", True)
    jnj = next(p for p in positions if p["symbol"] == "JNJ")
    assert jnj["shared"] and jnj["account_name"] == "Family Trust"


def test_an_advisor_previews_a_named_clients_portal(client, world):
    assert client.get("/api/v1/portal/accounts").status_code == 422
    assert (
        client.get("/api/v1/portal/accounts", params={"as_client": "nope"}).status_code
        == 404
    )

    body = client.get(
        "/api/v1/portal/accounts", params={"as_client": world["ravi"].id}
    ).json()

    assert body["viewer"]["preview"] is True
    assert [a["name"] for a in body["accounts"]] == ["Family Trust"]


# -- home -----------------------------------------------------------------


def test_home_values_holdings_at_live_prices_with_the_days_change(maya, monkeypatch):
    from app.services import live_quotes

    # (price, previous close): AAPL up 10 on the day, VOO flat, VTI unquoted.
    monkeypatch.setattr(
        live_quotes,
        "_fetch",
        lambda symbols: {"AAPL": (D("160"), D("150")), "VOO": (D("500"), D("500"))},
    )

    body = maya.get("/api/v1/portal/home").json()

    # Ten AAPL at 160, five VOO at 500, four VTI at the custodian's 260.
    assert body["total_value"] == 1600 + 2500 + 1040
    assert body["day_change"] == 100
    assert body["day_change_pct"] == pytest.approx(100 / (5140 - 100))
    top = {h["symbol"]: h for h in body["top_holdings"]}
    assert [h["symbol"] for h in body["top_holdings"]] == ["VOO", "AAPL", "VTI"]
    assert top["AAPL"]["day_change_pct"] == pytest.approx(10 / 150)
    assert top["VTI"]["day_change_pct"] is None
    assert top["VOO"]["share"] == pytest.approx(2500 / 5140)
    # Only AAPL has a live price to move by: ten shares up 10 each.
    assert [(h["symbol"], h["day_change"]) for h in body["movers_up"]] == [
        ("AAPL", 100)
    ]
    assert body["movers_down"] == []
    # Each is a fifth of the total or more, so each is pointed out.
    assert [h["symbol"] for h in body["concentrated"]] == ["VOO", "AAPL", "VTI"]
    assert {a["kind"]: a["value"] for a in body["allocation"]} == {
        "etf": 3540,
        "stock": 1600,
    }
    # This year's realised gains, split the way the realised page splits them.
    assert (body["realized_short_ytd"], body["realized_long_ytd"]) == (200, -50)
    assert body["holdings_count"] == 4


def test_home_is_limited_to_one_account_and_to_what_the_client_may_see(maya, world):
    one = maya.get("/api/v1/portal/home", params={"account_id": world["ira"].id})
    assert one.json()["total_value"] == 1040
    assert [h["symbol"] for h in one.json()["top_holdings"]] == ["VTI"]
    other = maya.get("/api/v1/portal/home", params={"account_id": world["trust"].id})
    assert other.status_code == 404


def test_option_symbols_are_read_apart():
    from app.services.portal_service import option_parts

    assert option_parts("ABC261023P00180000") == {
        "underlying": "ABC",
        "kind": "put",
        "strike": 180.0,
        "expiry": date(2026, 10, 23),
    }
    # A digit after the root (a corporate action) is not part of the shares' symbol.
    assert option_parts("XYZ1270115C00000500")["underlying"] == "XYZ"
    assert option_parts("ABC") is None


def test_options_expiring_within_two_weeks_say_how_far_the_shares_are(monkeypatch):
    from app.services import live_quotes
    from app.services.portal_service import PortalService

    monkeypatch.setattr(live_quotes, "_fetch", lambda symbols: {"ABC": D("190.80")})
    rows = [
        {"symbol": "ABC261023P00180000", "quantity": -2, "account_name": "Brokerage"},
        {"symbol": "ABC270115P00180000", "quantity": -1, "account_name": "Brokerage"},
        {"symbol": "ABC", "quantity": 10, "account_name": "Brokerage"},
    ]

    (soon,) = PortalService._expiring_options(rows, date(2026, 10, 12))

    assert (soon["days"], soon["written"], soon["contracts"]) == (11, True, 2)
    assert soon["above_strike_pct"] == pytest.approx(0.06)


def test_shares_passing_one_year_before_year_end_are_listed(db, world):
    from app.services.portal_service import PortalService

    # Maya's AAPL was bought on 3 Mar 2025 and her VTI on 2 Oct 2026.
    service = PortalService(db, world["maya"].id)
    refs = service._refs()

    assert service._turning_long_term(refs, date(2026, 2, 1)) == [
        {"symbol": "AAPL", "date": date(2026, 3, 4)}
    ]
    # Already long-term, or not until next year: nothing to say.
    assert service._turning_long_term(refs, date(2026, 10, 12)) == []


# -- positions ------------------------------------------------------------


def test_positions_are_listed_per_strategy_with_totals(maya):
    body = maya.get("/api/v1/portal/positions").json()
    rows = {p["symbol"]: p for p in body["positions"]}

    assert _symbols(body["positions"]) == sorted(["AAPL", "VOO", "VTI", OPTION])
    assert rows["AAPL"]["strategy_name"] == "Growth"
    assert rows["VOO"]["strategy_name"] == "Index"
    assert rows["VOO"]["account_name"] == "Brokerage"
    assert (
        rows["AAPL"]["market_value"] == 1500 and rows["AAPL"]["unrealized_gain"] == 500
    )
    assert rows["AAPL"]["unrealized_gain_pct"] == pytest.approx(0.5)
    # A written option: short, costed from the premium, with no price to value it.
    assert rows[OPTION]["is_short"] and rows[OPTION]["security_type"] == "option"
    assert rows[OPTION]["market_value"] is None
    # Two contracts written at $3.00 a share: $600 of premium.
    assert (rows[OPTION]["avg_cost"], rows[OPTION]["multiplier"]) == (3.0, 100)
    assert rows[OPTION]["cost_basis"] == -600 and rows["AAPL"]["multiplier"] == 1
    assert body["unpriced_count"] == 1
    assert body["total_market_value"] == 1500 + 2500 + 1040
    assert body["total_unrealized_gain"] == 500 + 500 + 40


def test_positions_show_the_markets_price_where_there_is_one(maya, monkeypatch):
    """Only the price is live: quantity and cost stay the custodian's."""
    from app.services import live_quotes

    asked = []

    def source(symbols):
        asked.append(sorted(symbols))
        return {"AAPL": D("160"), "VOO": D("510")}  # nothing for VTI

    monkeypatch.setattr(live_quotes, "_fetch", source)

    body = maya.get("/api/v1/portal/positions").json()
    rows = {p["symbol"]: p for p in body["positions"]}

    # Ten shares that cost 1,000, now at 160.
    assert (rows["AAPL"]["price"], rows["AAPL"]["price_source"]) == (160, "live")
    assert (rows["AAPL"]["market_value"], rows["AAPL"]["cost_basis"]) == (1600, 1000)
    assert rows["AAPL"]["unrealized_gain"] == 600
    assert rows["AAPL"]["unrealized_gain_pct"] == pytest.approx(0.6)
    # No quote: the custodian's price stands. An option is never asked for.
    assert (rows["VTI"]["price"], rows["VTI"]["price_source"]) == (260, "custodian")
    assert rows[OPTION]["price_source"] is None and OPTION not in asked[0]
    assert body["total_market_value"] == 1600 + 2550 + 1040
    assert body["live_prices_at"] is not None

    # A second look inside a minute does not ask the source again, and a symbol
    # it had no quote for is not asked about again either.
    maya.get("/api/v1/portal/positions")
    assert len(asked) == 1


def test_positions_fall_back_to_the_custodians_prices(maya, monkeypatch):
    from app.services import live_quotes

    def down(symbols):
        raise ConnectionError("source unreachable")

    monkeypatch.setattr(live_quotes, "_fetch", down)

    body = maya.get("/api/v1/portal/positions").json()

    assert body["live_prices_at"] is None
    assert {p["price_source"] for p in body["positions"]} == {"custodian", None}
    assert body["total_market_value"] == 1500 + 2500 + 1040
    # Asking for the custodian's prices does not consult the source at all.
    monkeypatch.setattr(live_quotes, "_fetch", lambda symbols: {"AAPL": D("999")})
    quiet = maya.get("/api/v1/portal/positions", params={"live": "false"}).json()
    assert quiet["total_market_value"] == 1500 + 2500 + 1040


def test_trades_are_totalled_for_each_account(maya, world):
    body = maya.get("/api/v1/portal/trades", params={"limit": 1}).json()

    # One row on this page, but every account with a trade is totalled.
    assert len(body["trades"]) == 1 and body["total"] == 8
    accounts = {a["account_name"]: a for a in body["accounts"]}
    assert set(accounts) == {"Brokerage", "Rollover IRA"}
    assert (accounts["Rollover IRA"]["total"], accounts["Rollover IRA"]["bought"]) == (
        1,
        1000,
    )
    assert accounts["Brokerage"]["total"] == 7
    assert sum(a["bought"] for a in body["accounts"]) == body["bought"]
    # A filter narrows the accounts too.
    sells = maya.get("/api/v1/portal/trades", params={"action": "sell"}).json()
    assert [a["account_name"] for a in sells["accounts"]] == ["Brokerage"]


def test_position_filters(maya, world):
    def symbols(**params):
        return _symbols(
            maya.get("/api/v1/portal/positions", params=params).json()["positions"]
        )

    assert symbols(account_id=world["ira"].id) == ["VTI"]
    assert symbols(strategy_id=world["index"].id) == ["VOO", "VTI"]
    assert symbols(account_id=world["brokerage"].id, strategy_id=world["index"].id) == [
        "VOO"
    ]
    assert symbols(type="etf") == ["VOO", "VTI"]
    assert symbols(type="option") == [OPTION]
    assert symbols(q="aap") == ["AAPL"]


def test_recorded_holdings_take_over_from_the_trade_history(maya, db, world):
    """Once the custodian's holdings are on record they are the list: its
    quantity, value and cost. Where it gave no cost, the trades supply one."""
    for symbol, quantity, value, cost in [
        ("AAPL", 12, 1920, None),  # no cost from the custodian; trades say $100
        ("BACK", 5, 600, 110),  # bought back; the purchase is not in the feed yet
        ("NEW", 7, 700, None),  # nothing known about what was paid
    ]:
        db.add(
            DailyHolding(
                account_id=world["brokerage"].id,
                sleeve_id=world["brokerage_growth"].id,
                as_of_date=date(2026, 10, 9),
                symbol=symbol,
                quantity=D(quantity),
                price=D(value) / D(quantity),
                market_value=D(value),
                avg_cost=D(cost) if cost is not None else None,
            )
        )
    db.commit()

    body = maya.get(
        "/api/v1/portal/positions", params={"account_id": world["brokerage"].id}
    ).json()
    rows = {p["symbol"]: p for p in body["positions"]}

    # VOO is in the trades but the custodian does not hold it: not listed.
    assert _symbols(body["positions"]) == sorted(["AAPL", "BACK", "NEW", OPTION])
    assert rows["AAPL"]["quantity"] == 12 and rows["AAPL"]["market_value"] == 1920
    assert rows["AAPL"]["cost_basis"] == 1200  # $100 a share from the trades
    assert rows["BACK"]["cost_basis"] == 550 and rows["BACK"]["unrealized_gain"] == 50
    assert rows["NEW"]["cost_basis"] is None and rows["NEW"]["unrealized_gain"] is None
    assert body["total_market_value"] == 3220
    assert body["total_unrealized_gain"] == 770  # only where a cost is known


def test_options_are_valued_together_at_the_custodians_figure(maya, db, world):
    """The custodian prices no single option, but its account total values
    them: securities less the holdings it lists."""
    brokerage = world["brokerage"]
    db.add(
        DailyHolding(
            account_id=brokerage.id,
            sleeve_id=world["brokerage_growth"].id,
            as_of_date=date(2026, 10, 9),
            symbol="AAPL",
            quantity=D(10),
            price=D(150),
            market_value=D(1500),
            avg_cost=D(100),
        )
    )
    db.add(
        DailyValuation(
            account_id=brokerage.id,
            as_of_date=date(2026, 10, 9),
            securities_value=D(700),  # 1500 of AAPL, so the option is held at -800
            cash_value=D(0),
            total_value=D(700),
            basis="observed",
        )
    )
    db.commit()
    params = {"account_id": brokerage.id}

    body = maya.get("/api/v1/portal/positions", params=params).json()

    # Written for 2 x $300 = $600 of premium; now a liability of $800.
    assert body["options"] == {
        "count": 1,
        "market_value": -800,
        "cost_basis": -600,
        "unrealized_gain": -200,
    }
    assert body["total_market_value"] == 700
    assert body["total_unrealized_gain"] == 500 - 200
    # Not attributed when the options are searched for one at a time.
    searched = maya.get(
        "/api/v1/portal/positions", params={**params, "q": "ABC27"}
    ).json()
    assert searched["options"] is None and searched["unpriced_count"] == 1


def test_positions_csv(maya):
    response = maya.get(
        "/api/v1/portal/positions", params={"format": "csv", "q": "AAPL"}
    )

    assert response.headers["content-type"].startswith("text/csv")
    assert "positions.csv" in response.headers["content-disposition"]
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("Symbol,Account,Strategy,Type,Quantity")
    assert lines[1].startswith("AAPL,Brokerage,Growth,stock,10.0")


# -- trades ---------------------------------------------------------------


def test_trades_newest_first_with_totals_for_everything_matched(maya):
    body = maya.get("/api/v1/portal/trades", params={"limit": 2}).json()

    assert body["total"] == 8 and len(body["trades"]) == 2
    assert body["trades"][0]["symbol"] == "VTI"
    assert body["trades"][0]["strategy_name"] == "Index"
    assert body["trades"][0]["amount"] == 1000
    # Totals cover all eight trades, not the page.
    assert body["bought"] == 1000 + 1000 + 2000 + 1000 + 1000
    assert body["sold"] == 1200 + 600 + 950
    assert body["net_invested"] == body["bought"] - body["sold"]


def test_an_option_trade_is_priced_per_share_and_counted_in_contracts(maya):
    """Stored per contract ($300); quoted, and shown, per share ($3.00)."""
    body = maya.get("/api/v1/portal/trades", params={"type": "option"}).json()

    (option,) = body["trades"]
    assert (option["quantity"], option["multiplier"], option["price"]) == (2, 100, 3.0)
    assert option["amount"] == 600  # 2 contracts x 100 shares x $3.00
    shares = maya.get("/api/v1/portal/trades", params={"q": "AAPL"}).json()["trades"][0]
    assert (shares["multiplier"], shares["price"]) == (1, 100)


def test_trade_filters(maya, world):
    def symbols(**params):
        return _symbols(
            maya.get("/api/v1/portal/trades", params=params).json()["trades"]
        )

    assert symbols(start_date="2026-01-01", end_date="2026-08-31") == ["AMD", "DIS"]
    assert symbols(action="sell") == sorted(["AMD", "DIS", OPTION])
    assert symbols(account_id=world["ira"].id) == ["VTI"]
    assert symbols(strategy_id=world["growth"].id) == sorted(
        ["AAPL", "AMD", "AMD", OPTION]
    )
    assert symbols(type="etf") == ["VOO", "VTI"]
    assert symbols(q="vo") == ["VOO"]
    assert symbols(skip=7) == ["VOO"]  # the oldest


def test_trades_csv_carries_every_match_not_one_page(maya):
    response = maya.get("/api/v1/portal/trades", params={"format": "csv", "limit": 1})

    lines = response.text.strip().splitlines()
    assert lines[0].startswith("Date,Symbol,Action")
    assert len(lines) == 1 + 8


# -- realised gains -------------------------------------------------------


def test_realised_gains_split_by_holding_period(maya):
    body = maya.get("/api/v1/portal/realized").json()
    rows = {p["symbol"]: p for p in body["positions"]}

    assert _symbols(body["positions"]) == ["AMD", "DIS"]
    assert rows["AMD"]["term"] == "short" and rows["AMD"]["realized_gain"] == 200
    assert rows["AMD"]["realized_gain_pct"] == pytest.approx(0.2)
    assert rows["AMD"]["strategy_name"] == "Growth"
    assert rows["DIS"]["term"] == "long" and rows["DIS"]["realized_gain"] == -50
    assert rows["DIS"]["days_held"] == (date(2026, 1, 15) - date(2024, 2, 1)).days
    assert body["net_realized"] == 150
    assert (body["short_term"], body["long_term"]) == (200, -50)
    assert (body["gains"], body["losses"]) == (200, -50)
    assert body["positions"][0]["symbol"] == "AMD"  # closed most recently
    # Cost and proceeds are stated in full, as a brokerage's list states them.
    assert (rows["AMD"]["cost"], rows["AMD"]["proceeds"]) == (1000, 1200)
    assert body["proceeds"] - body["cost"] == body["net_realized"]
    assert body["disallowed_loss"] == 0


def test_realised_gains_by_period_and_by_account_with_income_kept_apart(
    db, maya, world
):
    from app.models.cash_activity import CashActivity

    for day, kind, amount, sleeve in [
        (date(2026, 1, 20), "DIVIDEND", 30, "brokerage_index"),
        (date(2026, 8, 3), "INTEREST", 5, "brokerage_growth"),
        (date(2026, 8, 5), "FEE", -9, "brokerage_growth"),  # not income
        (date(2026, 8, 28), "MARGIN_INTEREST", -12, "brokerage_growth"),
    ]:
        db.add(
            CashActivity(
                sleeve_id=world[sleeve].id,
                activity_date=day,
                type=kind,
                amount=D(amount),
                external_id=f"test:{kind}:{day}",
            )
        )
    db.commit()

    body = maya.get("/api/v1/portal/realized").json()

    # Income is beside the gains, never inside them.
    assert body["net_realized"] == 150
    assert (body["dividends"], body["interest"]) == (30, 5)
    # Interest paid on borrowed money is its own line, not netted into either.
    assert body["margin_interest"] == -12
    months = {p["period_start"]: p for p in body["periods"]}
    assert list(months) == ["2026-08-01", "2026-01-01"]  # newest first
    august, january = months["2026-08-01"], months["2026-01-01"]
    assert (august["short_term"], august["long_term"], august["interest"]) == (
        200,
        0,
        5,
    )
    assert (january["long_term"], january["dividends"]) == (-50, 30)
    assert (august["margin_interest"], january["margin_interest"]) == (-12, 0)
    assert january["period_end"] == "2026-01-31"

    quarters = maya.get("/api/v1/portal/realized", params={"grain": "quarter"}).json()
    assert [(p["period_start"], p["period_end"]) for p in quarters["periods"]] == [
        ("2026-07-01", "2026-09-30"),
        ("2026-01-01", "2026-03-31"),
    ]

    (account,) = body["accounts"]  # the IRA had nothing closed and no income
    assert (account["account_name"], account["realized"]) == ("Brokerage", 150)
    assert (account["short_term"], account["long_term"]) == (200, -50)
    by_strategy = {s["strategy_name"]: s for s in account["sleeves"]}
    assert (by_strategy["Growth"]["realized"], by_strategy["Growth"]["interest"]) == (
        200,
        5,
    )
    assert (by_strategy["Index"]["realized"], by_strategy["Index"]["dividends"]) == (
        -50,
        30,
    )

    # Income follows the dates; a term filter leaves it alone.
    later = maya.get("/api/v1/portal/realized", params={"start_date": "2026-06-01"})
    assert (later.json()["dividends"], later.json()["interest"]) == (0, 5)
    backwards = {"start_date": "2026-06-01", "end_date": "2026-01-01"}
    assert maya.get("/api/v1/portal/realized", params=backwards).status_code == 400


def test_realised_filters(maya, world):
    def symbols(**params):
        return _symbols(
            maya.get("/api/v1/portal/realized", params=params).json()["positions"]
        )

    assert symbols(term="long") == ["DIS"]
    assert symbols(result="loss") == ["DIS"]
    assert symbols(result="gain") == ["AMD"]
    assert symbols(start_date="2026-06-01") == ["AMD"]
    assert symbols(end_date="2026-06-01") == ["DIS"]
    assert symbols(strategy_id=world["index"].id) == ["DIS"]
    assert symbols(account_id=world["ira"].id) == []
    assert symbols(q="am") == ["AMD"]


# -- performance and home -------------------------------------------------


def test_performance_for_a_window_with_benchmark(maya, db, world):
    _rows(db, world["brokerage"], [1000, 1010, 1020.1, 1020.1], start=date(2026, 9, 1))
    _rows(db, world["ira"], [1000, 1000, 1000, 1000], start=date(2026, 9, 1))
    _closes(db, "SPY", date(2026, 8, 31), [100, 100, 100.5, 101, 101])

    body = maya.get(
        "/api/v1/portal/performance",
        params={"start_date": "2026-09-02", "benchmark": "SPY"},
    ).json()
    summary = body["summary"]

    # Both accounts together: 2000 after the first day, 2020.10 at the end.
    assert body["includes_cash"] and body["benchmark"] == "SPY"
    assert (summary["opening_value"], summary["closing_value"]) == (2000, 2020.1)
    assert summary["gain"] == pytest.approx(20.1) and summary["net_flow"] == 0
    assert summary["twr_pct"] == pytest.approx(0.01005)
    assert summary["mwr_pct"] == pytest.approx(0.01005, abs=1e-5)
    assert summary["benchmark_return_pct"] == pytest.approx(0.01)
    assert summary["excess_return_pct"] == pytest.approx(0.00005)
    # Every line starts at zero the day before the window and ends on the summary.
    assert body["series"][0] == {
        "date": "2026-09-01",
        "twr": 0.0,
        "mwr": 0.0,
        "benchmark": 0.0,
        "value": 2000.0,
    }
    assert body["series"][-1]["value"] == pytest.approx(2020.1)
    assert body["series"][-1]["twr"] == pytest.approx(0.01005)
    assert body["series"][-1]["benchmark"] == pytest.approx(0.01)
    assert [(m["year"], m["month"]) for m in body["months"]] == [(2026, 9)]
    assert body["periods"][0]["closing_value"] == 2020.1


def test_the_benchmark_can_be_chosen_from_the_list_offered(maya, db, world):
    from app.models.index_bar import IndexBar

    _rows(db, world["brokerage"], [1000, 1010, 1020.1, 1020.1], start=date(2026, 9, 1))
    _closes(db, "SPY", date(2026, 8, 31), [100, 100, 100.5, 101, 101])
    for offset, level in enumerate([5000, 5000, 5050, 5100, 5150]):
        db.add(
            IndexBar(
                symbol="SPX",
                bar_date=date(2026, 8, 31) + timedelta(days=offset),
                close=level,
                source="a-file",
            )
        )
    db.commit()
    params = {"start_date": "2026-09-02", "benchmark": "spx"}

    body = maya.get("/api/v1/portal/performance", params=params).json()

    # The index's own levels, not the fund's closes: 5000 to 5150.
    assert body["benchmark"] == "SPX"
    assert body["summary"]["benchmark_return_pct"] == pytest.approx(0.03)
    assert body["series"][-1]["benchmark"] == pytest.approx(0.03)
    offered = {b["code"]: b for b in body["benchmarks"]}
    assert offered["SPX"] == {
        "code": "SPX",
        "name": "S&P 500 index",
        "includes_dividends": False,
    }
    assert offered["SPY"]["includes_dividends"] is True

    # With none chosen, the S&P 500 index is the one compared with.
    default = maya.get(
        "/api/v1/portal/performance", params={"start_date": "2026-09-02"}
    ).json()
    assert default["benchmark"] == "SPX"
    assert default["summary"]["benchmark_return_pct"] == pytest.approx(0.03)

    unknown = maya.get("/api/v1/portal/performance", params={"benchmark": "FTSE"})
    assert unknown.status_code == 422


def test_an_index_benchmark_is_served_to_the_chart_from_what_is_on_file(client, db):
    from app.models.index_bar import IndexBar

    for day, level in ((date(2026, 9, 1), 5000), (date(2026, 9, 2), 5050)):
        db.add(IndexBar(symbol="NDX", bar_date=day, close=level, source="a-file"))
    db.commit()

    body = client.get(
        "/api/v1/benchmarks/ndx/performance", params={"start_date": "2026-09-02"}
    ).json()

    assert body == {
        "ticker": "NDX",
        "timeseries": [{"date": "2026-09-02", "close": 5050.0}],
        "warning": None,
    }


def test_a_benchmark_that_starts_inside_the_window_is_measured_from_there(
    maya, db, world
):
    _rows(
        db,
        world["brokerage"],
        [1000, 1010, 1020, 1030],
        flows={0: 1000},
        start=date(2026, 9, 1),
    )
    _closes(db, "SPY", date(2026, 9, 2), [100, 102, 104])  # nothing before the window

    summary = maya.get(
        "/api/v1/portal/performance", params={"benchmark": "SPY"}
    ).json()["summary"]

    assert summary["benchmark_from"] == "2026-09-02"
    assert summary["benchmark_return_pct"] == pytest.approx(0.04)


def test_one_strategy_shows_no_money_weighted_return(maya, db, world):
    _rows(db, world["brokerage"], [1000, 1005], flows={0: 1000}, start=date(2026, 9, 1))

    whole = maya.get("/api/v1/portal/performance").json()
    one = maya.get(
        "/api/v1/portal/performance", params={"strategy_id": world["growth"].id}
    ).json()

    assert whole["summary"]["mwr_pct"] is not None
    # No daily rows for the sleeve in this test: nothing to show, and no cash.
    assert one["includes_cash"] is False and one["summary"] is None


def test_performance_rejects_a_backwards_window_and_an_unknown_grain(maya):
    backwards = maya.get(
        "/api/v1/portal/performance",
        params={"start_date": "2026-09-02", "end_date": "2026-09-01"},
    )

    assert backwards.status_code == 400
    assert (
        maya.get(
            "/api/v1/portal/performance", params={"grain": "fortnight"}
        ).status_code
        == 422
    )


def test_overview_adds_the_accounts_and_lists_their_strategies(maya, db, world):
    _rows(db, world["brokerage"], [1000, 1100], flows={0: 1000}, start=date(2026, 9, 1))
    _rows(db, world["ira"], [500, 500], flows={0: 500}, start=date(2026, 9, 1))

    body = maya.get("/api/v1/portal/overview").json()
    accounts = {a["name"]: a for a in body["accounts"]}

    assert body["as_of"] == "2026-09-02"
    assert body["total_value"] == 1600
    assert body["ytd_gain"] == 100  # the 1500 deposited is not a gain
    assert body["ytd_realized"] == 150  # AMD +200, DIS -50, both closed in 2026
    assert accounts["Brokerage"]["value"] == 1100
    assert [s["strategy_name"] for s in accounts["Brokerage"]["sleeves"]] == [
        "Growth",
        "Index",
    ]
    assert accounts["Rollover IRA"]["value"] == 500
    assert body["timeseries"][-1] == {"date": "2026-09-02", "value": 1600}
    assert body["recent"][0]["symbol"] == "VTI" and body["recent"][0]["kind"] == "BUY"

    one = maya.get(
        "/api/v1/portal/overview", params={"account_id": world["ira"].id}
    ).json()
    assert one["total_value"] == 500 and [a["name"] for a in one["accounts"]] == [
        "Rollover IRA"
    ]


def test_an_option_that_ended_without_a_trade_says_how(maya, db, world):
    """Assigned or expired, from the brokerage's own label: never 'bought at $0'."""
    put = "XYZ261016P00010000"
    growth = world["brokerage_growth"]
    for day, action, price, notes in [
        (date(2026, 9, 1), "SELL", 50, None),
        (date(2026, 10, 1), "BUY", 0, "Assignment: PUT XYZ $10"),
    ]:
        db.add(
            Trade(
                sleeve_id=growth.id,
                trade_date=day,
                symbol=put,
                action=action,
                quantity=D(1),
                price=D(price),
                commission=D(0),
                security_type="OPTION",
                notes=notes,
            )
        )
    _trade(db, growth, date(2026, 10, 1), "BUY", 100, 10, "XYZ")
    db.commit()

    trades = maya.get("/api/v1/portal/trades", params={"q": "XYZ26"}).json()["trades"]
    lots = maya.get("/api/v1/portal/realized", params={"q": "XYZ26"}).json()

    assert [t["event"] for t in trades] == ["assigned", None]
    (lot,) = lots["positions"]
    assert (lot["event"], lot["realized_gain"]) == ("assigned", 0)
    assert lots["net_realized"] == 0  # the $50 premium is in the shares' cost
    shares = maya.get("/api/v1/portal/positions", params={"q": "XYZ"}).json()
    assert shares["positions"][0]["symbol"] == "XYZ"


def test_activity_lists_trades_and_money_movements_together(db, maya, world):
    from app.models.cash_activity import CashActivity

    _trade(db, world["brokerage_growth"], date(2026, 3, 2), "BUY", 10, 50, "ABC")
    _trade(db, world["brokerage_growth"], date(2026, 3, 9), "SELL", 4, 60, "ABC")
    for day, kind, amount, symbol, notes in [
        (
            date(2026, 3, 1),
            "CONTRIBUTION",
            1000,
            None,
            "ACH DIRECT WITHDRAWAL TRACE # 90000000001",
        ),
        (date(2026, 3, 3), "TRANSFER", -200, None, "TRF FDS TO TYPE 1"),
        (date(2026, 3, 3), "TRANSFER", 200, None, "TRF FDS FRM TYPE 2"),
        (date(2026, 3, 4), "TRANSFER", -150, None, "JRL TO 90000002-1"),
        (date(2026, 3, 5), "DIVIDEND", 12, "ABC", "ABC CORP"),
        (date(2026, 3, 6), "MARGIN_INTEREST", -7, None, "INT 03/01-03/05"),
        (date(2026, 3, 9), "WITHDRAWAL", -300, None, "To SOME BANK xxxxxxxx90001"),
    ]:
        db.add(
            CashActivity(
                sleeve_id=world["brokerage_growth"].id,
                activity_date=day,
                type=kind,
                symbol=symbol,
                amount=D(amount),
                notes=notes,
                external_id=f"activity:{kind}:{day}:{amount}",
            )
        )
    db.commit()

    # The fixture has trades of its own on other dates; March holds only these.
    march = {"start_date": "2026-03-01", "end_date": "2026-03-31"}
    body = maya.get("/api/v1/portal/activity", params=march).json()

    # The two rows of the custodian's own bookkeeping are left out.
    assert [(r["date"], r["label"]) for r in body["rows"]] == [
        ("2026-03-09", "Sold"),
        ("2026-03-09", "Withdrawal"),
        ("2026-03-06", "Margin interest"),
        ("2026-03-05", "Dividend"),
        ("2026-03-04", "Transfer out"),
        ("2026-03-02", "Bought"),
        ("2026-03-01", "Deposit"),
    ]
    assert (body["total"], body["trades"]) == (7, 2)
    assert (body["bought"], body["sold"]) == (500, 240)
    assert (body["money_in"], body["money_out"]) == (1000, 450)
    assert (body["income"], body["charges"]) == (12, 7)
    assert [a["account_id"] for a in body["accounts"]] == [world["brokerage"].id]

    # Described in plain words, with no trace or account number carried over.
    details = {r["label"]: r["detail"] for r in body["rows"]}
    assert details["Deposit"] == "Bank transfer (ACH)"
    assert details["Transfer out"] == "To another account at your custodian"
    assert details["Withdrawal"] == "To SOME BANK"
    withdrawal = body["rows"][1]
    assert (withdrawal["amount"], withdrawal["quantity"]) == (-300, None)

    def labels(**params):
        rows = maya.get("/api/v1/portal/activity", params={**march, **params}).json()[
            "rows"
        ]
        return [r["label"] for r in rows]

    assert labels(show="money") == ["Withdrawal", "Transfer out", "Deposit"]
    assert labels(show="income") == ["Dividend"]
    assert labels(show="charges") == ["Margin interest"]
    assert labels(show="trades") == ["Sold", "Bought"]
    # An action can only describe a trade; a symbol also finds its dividend.
    assert labels(action="buy") == ["Bought"]
    assert labels(q="ABC") == ["Sold", "Dividend", "Bought"]
    assert labels(skip=5, limit=5) == ["Bought", "Deposit"]

    csv_text = maya.get(
        "/api/v1/portal/activity", params={**march, "format": "csv"}
    ).text
    assert csv_text.splitlines()[0].startswith("Date,Activity,Symbol,Detail")
    assert "90000000001" not in csv_text
