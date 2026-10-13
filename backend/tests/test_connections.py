"""Brokerage connections: discovery, mapping, sync, reconciliation, webhooks.

Offline. The real ``SnapTradeConnector`` runs against a stub SDK client that
replays the sanitized Vanguard fixtures, so these cover the whole path from a
SnapTrade payload to trades, cash activities and performance.
"""
import base64
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import settings
from app.connectors import registry
from app.connectors.snaptrade_connector import SnapTradeConnector
from app.models.brokerage_connection import (
    BrokerageAccount,
    BrokerageActivity,
    BrokerageConnection,
)
from app.models.cash_activity import CashActivity
from app.models.perf import DailyValuation
from app.services.performance_build_service import rebuild_for_sleeves
from app.models.position import Position
from app.models.sleeve import Sleeve
from app.models.strategy import Strategy
from app.models.sync_log import SyncLog
from app.models.trade import Trade
from app.services.cash_activity_service import CashActivityService
from app.services.connection_service import (
    ConnectionService,
    run_all_brokerage_syncs,
    sync_brokerage_account,
)
from app.services.mwr_calculation import MWRCalculationService
from app.services.portfolio_calculation import PortfolioCalculationService
from app.services.trade_reassignment import reassign_symbols

FIXTURES = Path(__file__).parent / "fixtures" / "snaptrade"
USER_ID = "achalara-test-user"
CONSUMER_KEY = "test-consumer-key"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text())


class _RateLimited(Exception):
    status = 429


class _StubSDK:
    """A SnapTrade SDK client that replays canned payloads and records calls."""

    def __init__(self):
        self.activities = _fixture("vanguard_activities.json")
        self.positions = _fixture("vanguard_positions.json")
        self.initial_sync_completed = True
        self.synced_through = "2026-09-30"
        self.authorizations = [
            {"id": "auth-1", "brokerage": {"name": "Vanguard"}, "disabled": False}
        ]
        self.rate_limited = False
        self.cash = None
        self.total = None
        self.calls = []
        self.account_information = self
        self.connections = self
        self.authentication = self

    def _resp(self, body):
        return type("Resp", (), {"body": body})()

    def login_snap_trade_user(self, **kwargs):
        self.calls.append(("link", kwargs))
        return self._resp({"redirectURI": "https://app.snaptrade.com/portal/abc"})

    def list_brokerage_authorizations(self, **kwargs):
        return self._resp(self.authorizations)

    def delete_connection(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return self._resp({})

    def list_user_accounts(self, **kwargs):
        status = {
            "transactions": {
                "initial_sync_completed": self.initial_sync_completed,
                "last_successful_sync": self.synced_through,
            }
        }
        return self._resp(
            [
                {
                    "id": "acct-1",
                    "name": "Brokerage Account",
                    "number": "11112222",
                    "institution_name": "Vanguard",
                    "brokerage_authorization": "auth-1",
                    "sync_status": status,
                    "balance": (
                        {"total": {"amount": self.total, "currency": "USD"}}
                        if self.total is not None
                        else None
                    ),
                },
                {
                    "id": "acct-2",
                    "name": "Roth IRA",
                    "number": "33334444",
                    "institution_name": "Vanguard",
                    "brokerage_authorization": "auth-1",
                    "sync_status": status,
                },
            ]
        )

    def get_account_activities(self, **kwargs):
        self.calls.append(("activities", kwargs))
        if self.rate_limited:
            raise _RateLimited("429")
        return self._resp(self.activities)

    def get_all_account_positions(self, **kwargs):
        return self._resp(self.positions)

    def get_user_account_balance(self, **kwargs):
        if self.cash is None:
            return self._resp([])
        return self._resp([{"currency": {"code": "USD"}, "cash": self.cash}])


@pytest.fixture
def sdk(monkeypatch):
    """Route the registered SnapTrade connector through a stub SDK."""
    stub = _StubSDK()
    monkeypatch.setattr(settings, "snaptrade_user_id", USER_ID)
    monkeypatch.setattr(settings, "snaptrade_consumer_key", CONSUMER_KEY)
    original = registry.get_connector("snaptrade")
    registry.register("snaptrade", SnapTradeConnector(client=stub))
    yield stub
    registry.register("snaptrade", original)


@pytest.fixture
def client_id(client):
    resp = client.post(
        "/api/v1/clients/", json={"name": "Linked", "email": "linked@example.com"}
    )
    assert resp.status_code == 201
    return resp.json()["id"]


def _mapped_account(db, client_id, external_ref="acct-1") -> BrokerageAccount:
    """Discover the stub's accounts and map one into the hierarchy."""
    service = ConnectionService(db)
    service.discover(client_id)
    ba = (
        db.query(BrokerageAccount)
        .filter(BrokerageAccount.external_account_ref == external_ref)
        .one()
    )
    return service.map_account(ba.id)


def _allow_resync(db, ba):
    """Age the last sync past the 24-hour guard."""
    ba.last_synced_at = datetime.now(timezone.utc) - timedelta(hours=25)
    db.commit()


# ---------------------------------------------------------------------------
# Linking and discovery
# ---------------------------------------------------------------------------


def test_link_returns_a_short_lived_portal_url(client, client_id, sdk):
    resp = client.post(f"/api/v1/clients/{client_id}/connections/snaptrade/link")
    assert resp.status_code == 200
    body = resp.json()
    assert body["redirect_url"].startswith("https://")
    assert body["expires_in_seconds"] == 300
    # Read-only: trade scopes are never requested.
    assert sdk.calls[-1][1]["connection_type"] == "read"
    assert sdk.calls[-1][1]["user_id"] == USER_ID


def test_link_reports_when_snaptrade_is_not_configured(client, client_id, sdk, monkeypatch):
    monkeypatch.setattr(settings, "snaptrade_user_id", "")
    resp = client.post(f"/api/v1/clients/{client_id}/connections/snaptrade/link")
    assert resp.status_code == 503


def test_link_for_unknown_client_is_404(client, sdk):
    resp = client.post("/api/v1/clients/nope/connections/snaptrade/link")
    assert resp.status_code == 404


def test_discover_records_the_login_and_every_account_under_it(client, client_id, sdk):
    resp = client.post(f"/api/v1/clients/{client_id}/connections/discover")
    assert resp.status_code == 200
    (connection,) = resp.json()
    assert connection["institution"] == "Vanguard"
    assert connection["status"] == "active"
    accounts = connection["brokerage_accounts"]
    assert {a["name"] for a in accounts} == {"Brokerage Account", "Roth IRA"}
    assert all(a["status"] == "unmapped" for a in accounts)
    # Only the last four digits of the account number are kept.
    assert {a["number_last4"] for a in accounts} == {"2222", "4444"}


def test_discover_is_repeatable_and_keeps_mappings(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    ConnectionService(db).discover(client_id)

    assert db.query(BrokerageConnection).count() == 1
    assert db.query(BrokerageAccount).count() == 2
    db.refresh(ba)
    assert ba.status == "mapped"


def test_discover_marks_a_vanished_login_deleted(db, client, client_id, sdk):
    ConnectionService(db).discover(client_id)
    sdk.authorizations = []
    assert ConnectionService(db).discover(client_id) == []
    assert db.query(BrokerageConnection).one().status == "deleted"


def test_discover_flags_a_disabled_login_as_broken(db, client, client_id, sdk):
    sdk.authorizations[0]["disabled"] = True
    (connection,) = ConnectionService(db).discover(client_id)
    assert connection.status == "broken"


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------


def test_mapping_creates_account_and_a_fifo_unallocated_sleeve(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)

    assert ba.status == "mapped"
    sleeve = db.query(Sleeve).filter(Sleeve.id == ba.default_sleeve_id).one()
    assert sleeve.account_id == ba.account_id
    assert sleeve.accounting_method == "FIFO"
    assert sleeve.strategy.name == "Unallocated"
    assert sleeve.account.client_id == client_id
    assert sleeve.account.name == "Brokerage Account"


def test_mapping_two_accounts_shares_one_unallocated_strategy(db, client, client_id, sdk):
    _mapped_account(db, client_id, "acct-1")
    _mapped_account(db, client_id, "acct-2")
    assert db.query(Strategy).filter(Strategy.name == "Unallocated").count() == 1


def test_mapping_via_api_into_a_chosen_strategy(db, client, client_id, sdk):
    strategy_id = client.post("/api/v1/strategies/", json={"name": "Income"}).json()["id"]
    (connection,) = client.post(
        f"/api/v1/clients/{client_id}/connections/discover"
    ).json()
    ba_id = connection["brokerage_accounts"][0]["id"]

    resp = client.patch(
        f"/api/v1/brokerage-accounts/{ba_id}",
        json={"status": "mapped", "strategy_id": strategy_id},
    )
    assert resp.status_code == 200
    sleeve = db.query(Sleeve).filter(Sleeve.id == resp.json()["default_sleeve_id"]).one()
    assert sleeve.strategy_id == strategy_id


def test_an_agents_login_can_map_an_account_to_its_real_owner(db, client, client_id, sdk):
    owner_id = client.post(
        "/api/v1/clients/", json={"name": "Owner", "email": "owner@example.com"}
    ).json()["id"]
    (connection,) = client.post(
        f"/api/v1/clients/{client_id}/connections/discover"
    ).json()
    ba_id = connection["brokerage_accounts"][0]["id"]

    resp = client.patch(
        f"/api/v1/brokerage-accounts/{ba_id}",
        json={"status": "mapped", "client_id": owner_id},
    )

    assert resp.status_code == 200
    assert resp.json()["owner_client_id"] == owner_id
    sleeve = db.query(Sleeve).filter(Sleeve.id == resp.json()["default_sleeve_id"]).one()
    assert sleeve.account.client_id == owner_id
    # The login itself still belongs to the agent.
    assert db.query(BrokerageConnection).one().client_id == client_id
    # And it syncs like any other mapped account.
    assert sync_brokerage_account(db, ba_id)["imported"] == 8
    assert db.query(Trade).filter(Trade.sleeve_id == sleeve.id).count() == 8


def test_mapping_rejects_an_account_and_client_that_disagree(db, client, client_id, sdk):
    other_id = client.post(
        "/api/v1/clients/", json={"name": "Other", "email": "other@example.com"}
    ).json()["id"]
    first = _mapped_account(db, client_id, "acct-1")
    second = (
        db.query(BrokerageAccount)
        .filter(BrokerageAccount.external_account_ref == "acct-2")
        .one()
    )
    resp = client.patch(
        f"/api/v1/brokerage-accounts/{second.id}",
        json={"status": "mapped", "account_id": first.account_id, "client_id": other_id},
    )
    assert resp.status_code == 409
    resp = client.patch(
        f"/api/v1/brokerage-accounts/{second.id}",
        json={"status": "mapped", "client_id": "no-such-client"},
    )
    assert resp.status_code == 404


def test_mapping_refuses_a_sleeve_that_already_holds_trades(db, client, client_id, sdk):
    first = _mapped_account(db, client_id, "acct-1")
    sync_brokerage_account(db, first.id)
    sleeve = db.query(Sleeve).filter(Sleeve.id == first.default_sleeve_id).one()

    ConnectionService(db).discover(client_id)
    other = (
        db.query(BrokerageAccount)
        .filter(BrokerageAccount.external_account_ref == "acct-2")
        .one()
    )
    with pytest.raises(ValueError):
        ConnectionService(db).map_account(
            other.id, account_id=sleeve.account_id, strategy_id=sleeve.strategy_id
        )


def test_ignored_account_cannot_be_synced(db, client, client_id, sdk):
    (connection,) = client.post(
        f"/api/v1/clients/{client_id}/connections/discover"
    ).json()
    ba_id = connection["brokerage_accounts"][0]["id"]
    resp = client.patch(f"/api/v1/brokerage-accounts/{ba_id}", json={"status": "ignored"})
    assert resp.json()["status"] == "ignored"
    assert client.post(f"/api/v1/brokerage-accounts/{ba_id}/sync").status_code == 409


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def test_sync_ingests_trades_and_cash_and_reports_what_it_skipped(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    result = sync_brokerage_account(db, ba.id)

    assert result["status"] == "synced"
    assert result["imported"] == 8
    assert result["cash_imported"] == 1
    assert result["skipped_rows"] == {
        "sweep": 2,
        "corporate_action": 1,
    }
    assert result["transactions_synced_through"] == date(2026, 9, 30)

    trades = db.query(Trade).filter(Trade.sleeve_id == ba.default_sleeve_id).all()
    assert len(trades) == 8
    # The same-day round trip at one price keeps both legs.
    intc = sorted(t.action for t in trades if t.symbol == "INTC")
    assert intc == ["BUY", "SELL"]
    # Two identical fills are two trades.
    assert len([t for t in trades if t.symbol == "MU"]) == 2

    dividend = db.query(CashActivity).one()
    assert (dividend.type, dividend.symbol, dividend.amount) == (
        "DIVIDEND",
        "FRDM",
        Decimal("8.21"),
    )
    log = db.query(SyncLog).filter(SyncLog.import_type == "BROKERAGE").one()
    assert log.status == "SUCCESS" and log.rows_success == 8


def test_first_sync_pulls_full_history_and_later_ones_overlap_the_watermark(
    db, client, client_id, sdk
):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    first = [c for c in sdk.calls if c[0] == "activities"][-1][1]
    assert first["start_date"] is None

    _allow_resync(db, ba)
    sync_brokerage_account(db, ba.id)
    second = [c for c in sdk.calls if c[0] == "activities"][-1][1]
    assert second["start_date"] == date(2026, 9, 23)


def test_sync_within_24_hours_is_skipped_without_calling_the_source(
    db, client, client_id, sdk
):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    calls_before = len(sdk.calls)

    result = sync_brokerage_account(db, ba.id)

    assert result["status"] == "skipped"
    assert result["reason"] == "synced_recently"
    assert result["next_sync_allowed_at"] is not None
    assert len(sdk.calls) == calls_before


def test_resync_imports_nothing_new(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    _allow_resync(db, ba)

    result = sync_brokerage_account(db, ba.id)

    assert result["status"] == "synced"
    assert result["imported"] == 0
    assert result["duplicates"] == 8
    assert result["cash_imported"] == 0
    assert db.query(Trade).count() == 8
    assert db.query(CashActivity).count() == 1


def test_sync_waits_while_the_source_is_still_loading_history(db, client, client_id, sdk):
    sdk.initial_sync_completed = False
    ba = _mapped_account(db, client_id)

    result = sync_brokerage_account(db, ba.id)

    assert result["reason"] == "initial_sync_pending"
    assert not [c for c in sdk.calls if c[0] == "activities"]
    db.refresh(ba)
    # Not counted as a sync, so the next attempt is not held back 24 hours.
    assert ba.last_synced_at is None


def test_rate_limit_is_reported_not_retried(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sdk.rate_limited = True

    result = sync_brokerage_account(db, ba.id)

    assert result["reason"] == "rate_limited"
    assert len([c for c in sdk.calls if c[0] == "activities"]) == 1
    assert db.query(Trade).count() == 0


def test_sync_refuses_a_broken_connection(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    ba.connection.status = "broken"
    db.commit()
    resp = client.post(f"/api/v1/brokerage-accounts/{ba.id}/sync")
    assert resp.status_code == 409


def test_sync_route_returns_the_result(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    resp = client.post(f"/api/v1/brokerage-accounts/{ba.id}/sync")
    assert resp.status_code == 200
    assert resp.json()["imported"] == 8
    assert client.post("/api/v1/brokerage-accounts/nope/sync").status_code == 404


def test_scheduled_job_syncs_mapped_accounts_only(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    outcomes = run_all_brokerage_syncs(db)
    assert outcomes == {ba.id: "synced"}
    # The second account was discovered but never mapped.
    assert db.query(BrokerageAccount).count() == 2


# ---------------------------------------------------------------------------
# Splitting an account by security type, and loading from a start date
# ---------------------------------------------------------------------------


def _split_account(db, client, client_id, history_start=None):
    """Map acct-1 with ETFs routed to one strategy and the rest to another."""
    etfs = client.post("/api/v1/strategies/", json={"name": "ETFs"}).json()["id"]
    stocks = client.post("/api/v1/strategies/", json={"name": "Stocks"}).json()["id"]
    (connection,) = client.post(
        f"/api/v1/clients/{client_id}/connections/discover"
    ).json()
    ba_id = next(
        a["id"] for a in connection["brokerage_accounts"] if a["name"] == "Brokerage Account"
    )
    body = {"status": "mapped", "strategy_id": stocks, "strategy_routes": {"etf": etfs}}
    if history_start:
        body["history_start"] = history_start
    resp = client.patch(f"/api/v1/brokerage-accounts/{ba_id}", json=body)
    assert resp.status_code == 200, resp.text
    mapped = resp.json()
    return ba_id, mapped["sleeve_routes"]["ETF"], mapped["default_sleeve_id"]


def _symbols(db, sleeve_id):
    return sorted({t.symbol for t in db.query(Trade).filter(Trade.sleeve_id == sleeve_id)})


def test_mapping_with_routes_creates_one_fifo_sleeve_per_strategy(db, client, client_id, sdk):
    ba_id, etf_sleeve, stock_sleeve = _split_account(db, client, client_id)

    assert etf_sleeve != stock_sleeve
    sleeves = {s.id: s for s in db.query(Sleeve).all()}
    assert sleeves[etf_sleeve].strategy.name == "ETFs"
    assert sleeves[stock_sleeve].strategy.name == "Stocks"
    assert sleeves[etf_sleeve].account_id == sleeves[stock_sleeve].account_id
    assert {s.accounting_method for s in sleeves.values()} == {"FIFO"}


def test_sync_routes_trades_to_sleeves_by_security_type(db, client, client_id, sdk):
    ba_id, etf_sleeve, stock_sleeve = _split_account(db, client, client_id)

    result = sync_brokerage_account(db, ba_id)

    assert result["imported"] == 8
    # USO and VTI carry a type code; FRDM is recognised by its description.
    assert _symbols(db, etf_sleeve) == ["FRDM", "USO", "VTI"]
    # The last is a trade Vanguard sent with a name but no ticker.
    assert _symbols(db, stock_sleeve) == ["INTC", "MU", "~WALGREENS BOOTS ALLIANCEINC"]
    types = dict(db.query(Trade.symbol, Trade.security_type).distinct())
    assert types["USO"] == "ETF" and types["MU"] is None
    # The dividend follows the security it was paid on.
    assert db.query(CashActivity).one().sleeve_id == etf_sleeve
    assert result["security_type_sources"] == {"type": 3, "description": 1, "none": 4}


def test_a_symbol_stays_in_one_sleeve_even_when_rows_disagree_on_type(
    db, client, client_id, sdk
):
    # One INTC leg says common stock and the other says nothing; both must
    # land together or the round trip would be split across sleeves.
    ba_id, etf_sleeve, stock_sleeve = _split_account(db, client, client_id)
    for row in sdk.activities["data"]:
        if (row["symbol"] or {}).get("raw_symbol") == "INTC" and row["type"] == "SELL":
            row["symbol"]["type"] = {"code": "et"}

    sync_brokerage_account(db, ba_id)

    intc = {t.sleeve_id for t in db.query(Trade).filter(Trade.symbol == "INTC")}
    assert len(intc) == 1


def test_a_symbol_moved_by_hand_stays_moved_on_later_syncs(db, client, client_id, sdk):
    ba_id, etf_sleeve, stock_sleeve = _split_account(db, client, client_id)
    sync_brokerage_account(db, ba_id)
    reassign_symbols(db, etf_sleeve, stock_sleeve, ["USO"])
    # A new USO buy arrives on the next sync.
    extra = dict(sdk.activities["data"][0], id="new-uso", trade_date="2026-09-29T05:00:00Z")
    sdk.activities["data"].append(extra)
    ba = db.query(BrokerageAccount).filter(BrokerageAccount.id == ba_id).one()
    _allow_resync(db, ba)

    result = sync_brokerage_account(db, ba_id)

    assert result["imported"] == 1
    assert "USO" in _symbols(db, stock_sleeve)
    assert "USO" not in _symbols(db, etf_sleeve)


def test_resync_of_a_split_account_imports_nothing(db, client, client_id, sdk):
    ba_id, etf_sleeve, stock_sleeve = _split_account(db, client, client_id)
    sync_brokerage_account(db, ba_id)
    ba = db.query(BrokerageAccount).filter(BrokerageAccount.id == ba_id).one()
    _allow_resync(db, ba)

    result = sync_brokerage_account(db, ba_id)

    assert (result["imported"], result["duplicates"], result["cash_imported"]) == (0, 8, 0)
    assert db.query(Trade).count() == 8


def test_first_sync_starts_at_the_history_start_date(db, client, client_id, sdk):
    ba_id, _, _ = _split_account(db, client, client_id, history_start="2026-01-01")

    sync_brokerage_account(db, ba_id)

    call = [c for c in sdk.calls if c[0] == "activities"][-1][1]
    assert call["start_date"] == date(2026, 1, 1)
    listed = client.get(f"/api/v1/clients/{client_id}/connections").json()[0]
    account = next(a for a in listed["brokerage_accounts"] if a["id"] == ba_id)
    assert account["sync_start_date"] == "2026-01-01"


def test_trade_listing_shows_security_type(db, client, client_id, sdk):
    ba_id, etf_sleeve, _ = _split_account(db, client, client_id)
    sync_brokerage_account(db, ba_id)
    sleeve = db.query(Sleeve).filter(Sleeve.id == etf_sleeve).one()

    trades = client.get(
        f"/api/v1/clients/{client_id}/accounts/{sleeve.account_id}"
        f"/sleeves/{etf_sleeve}/trades"
    ).json()["trades"]

    assert {t["security_type"] for t in trades} == {"ETF"}


def test_sync_keeps_every_source_row_and_replaces_it_on_resync(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)

    rows = db.query(BrokerageActivity).filter(
        BrokerageActivity.brokerage_account_id == ba.id
    )
    assert rows.count() == len(sdk.activities["data"])
    split = rows.filter(BrokerageActivity.type == "SPLIT").one()
    assert split.outcome == "skipped:corporate_action"
    assert split.payload["symbol"]["raw_symbol"] == "NVDA"

    _allow_resync(db, ba)
    sync_brokerage_account(db, ba.id)
    assert rows.count() == len(sdk.activities["data"])


# ---------------------------------------------------------------------------
# Options, and re-reading stored rows
# ---------------------------------------------------------------------------


def _option_row(type_, units, price, amount, day, symbol="ABCD270115P00020000"):
    return {
        "id": f"opt-{type_}-{day}-{units}",
        "symbol": {"symbol": symbol, "raw_symbol": symbol, "description": "PUT ABCD CORP"},
        "option_symbol": None,
        "currency": {"code": "USD"},
        "type": type_,
        "description": "PUT ABCD CORP $20 EXP 01/15/27",
        "amount": amount,
        "price": price,
        "units": units,
        "fee": 0.0,
        "trade_date": f"{day}T05:00:00Z",
        "settlement_date": f"{day}T05:00:00Z",
    }


def test_a_written_option_that_expires_keeps_its_whole_premium(db, client, client_id, sdk):
    sdk.activities = {
        "data": [
            _option_row("SELL", -10, 2.0, 1990.0, "2026-03-02"),
            _option_row("EXPIRED", 10, 0.0, 0.0, "2026-04-17"),
        ]
    }
    ba = _mapped_account(db, client_id)

    result = sync_brokerage_account(db, ba.id)

    assert result["imported"] == 2
    positions = PortfolioCalculationService(db).calculate_positions(ba.default_sleeve_id)
    assert positions["open"] == []
    (closed,) = positions["closed"]
    # 10 contracts at 200 each, less the 10 commission; bought back for nothing.
    assert closed["realized_gain"] == Decimal("1990")
    assert {t.security_type for t in db.query(Trade)} == {"OPTION"}


def test_options_route_to_their_own_sleeve(db, client, client_id, sdk):
    options = client.post("/api/v1/strategies/", json={"name": "Options"}).json()["id"]
    stocks = client.post("/api/v1/strategies/", json={"name": "Stocks"}).json()["id"]
    sdk.activities["data"].append(_option_row("SELL", -10, 2.0, 1990.0, "2026-03-02"))
    (connection,) = client.post(
        f"/api/v1/clients/{client_id}/connections/discover"
    ).json()
    ba_id = connection["brokerage_accounts"][0]["id"]
    mapped = client.patch(
        f"/api/v1/brokerage-accounts/{ba_id}",
        json={"status": "mapped", "strategy_id": stocks, "strategy_routes": {"OPTION": options}},
    ).json()

    sync_brokerage_account(db, ba_id)

    assert _symbols(db, mapped["sleeve_routes"]["OPTION"]) == ["ABCD270115P00020000"]


def test_rederive_reads_stored_rows_again_without_calling_the_source(
    db, client, client_id, sdk
):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    # A row we hold but had not turned into a trade.
    record = (
        db.query(BrokerageActivity)
        .filter(BrokerageActivity.type == "SPLIT")
        .one()
    )
    record.payload = _option_row("SELL", -10, 2.0, 1990.0, "2026-03-02")
    record.type = "SELL"
    db.commit()
    calls_before = len(sdk.calls)

    result = ConnectionService(db).rederive(ba.id)

    assert len(sdk.calls) == calls_before
    assert (result["imported"], result["duplicates"]) == (1, 8)
    assert result["cash_imported"] == 0
    db.refresh(record)
    assert record.outcome == "trade"
    assert db.query(Trade).count() == 9
    # Running it again changes nothing.
    assert ConnectionService(db).rederive(ba.id)["imported"] == 0


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_reconciliation_lists_symbols_where_holdings_and_trades_disagree(
    db, client, client_id, sdk
):
    sdk.positions = {
        "results": [
            # Agrees with the two MU buys.
            {"instrument": {"symbol": "MU", "raw_symbol": "MU"}, "units": "20",
             "price": "95.00", "cost_basis": "90"},
            # Held at the brokerage, purchase not yet in the transaction feed.
            {"instrument": {"symbol": "CIBR", "raw_symbol": "CIBR"}, "units": "21.001",
             "price": "70.10"},
        ]
    }
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)

    resp = client.get(f"/api/v1/brokerage-accounts/{ba.id}/reconciliation")
    assert resp.status_code == 200
    report = resp.json()
    assert report["matched"] == 1
    drift = {d["symbol"]: d for d in report["drifted"]}
    assert drift["CIBR"]["awaiting_transactions"] is True
    assert drift["CIBR"]["derived_quantity"] == 0
    assert drift["USO"]["brokerage_quantity"] == 0
    assert drift["USO"]["difference"] == -10
    # The FRDM sell has no buy in the captured history, so it reads as a
    # short the brokerage does not hold.
    assert report["unmatched_sells"] == 1
    assert drift["FRDM"]["derived_quantity"] == -10
    assert report["skipped_rows"]["corporate_action"] == 1


def test_reconciliation_marks_positions_to_brokerage_prices(db, client, client_id, sdk):
    sdk.positions = {
        "results": [
            {"instrument": {"symbol": "MU", "raw_symbol": "MU"}, "units": "20",
             "price": "95.00", "cost_basis": "90"},
        ]
    }
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)

    position = (
        db.query(Position)
        .filter(Position.sleeve_id == ba.default_sleeve_id, Position.symbol == "MU")
        .one()
    )
    assert position.current_price == Decimal("95.00")
    assert position.market_value == Decimal("1900.00")
    assert position.unrealized_gain == Decimal("100.00")


# ---------------------------------------------------------------------------
# Splitting an account by strategy
# ---------------------------------------------------------------------------


def _second_sleeve(db, ba, name="Growth") -> Sleeve:
    strategy = Strategy(name=name)
    db.add(strategy)
    db.flush()
    sleeve = Sleeve(account_id=ba.account_id, strategy_id=strategy.id)
    db.add(sleeve)
    db.commit()
    return sleeve


def test_reassign_moves_a_symbols_whole_history(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    growth = _second_sleeve(db, ba)

    resp = client.post(
        "/api/v1/trades/reassign",
        json={
            "from_sleeve_id": ba.default_sleeve_id,
            "to_sleeve_id": growth.id,
            "symbols": ["mu", "FRDM"],
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "symbols": ["FRDM", "MU"],
        "trades_moved": 3,
        "cash_activities_moved": 1,
    }
    db.refresh(growth)
    # Lots keep matching the way they did in the sleeve they came from.
    assert growth.accounting_method == "FIFO"
    open_symbols = {
        p.symbol
        for p in db.query(Position).filter(
            Position.sleeve_id == growth.id, Position.status == "OPEN"
        )
    }
    assert open_symbols == {"MU", "FRDM"}
    assert db.query(CashActivity).one().sleeve_id == growth.id


def test_resync_after_reassign_does_not_bring_moved_trades_back(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    growth = _second_sleeve(db, ba)
    reassign_symbols(db, ba.default_sleeve_id, growth.id, ["MU", "FRDM"])
    _allow_resync(db, ba)

    result = sync_brokerage_account(db, ba.id)

    assert result["imported"] == 0
    assert result["cash_imported"] == 0
    assert db.query(Trade).count() == 8
    assert db.query(Trade).filter(Trade.sleeve_id == growth.id).count() == 3


def test_reassign_across_accounts_is_refused(db, client, client_id, sdk):
    first = _mapped_account(db, client_id, "acct-1")
    second = _mapped_account(db, client_id, "acct-2")
    resp = client.post(
        "/api/v1/trades/reassign",
        json={
            "from_sleeve_id": first.default_sleeve_id,
            "to_sleeve_id": second.default_sleeve_id,
            "symbols": ["MU"],
        },
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# FIFO lot accounting
# ---------------------------------------------------------------------------


def _fifo_sleeve(db, client, email="fifo@example.com") -> str:
    from tests.conftest import create_test_strategy

    _, _, sleeve_id = create_test_strategy(
        client, client_email=email, strategy_name=f"Strategy {email}"
    )
    db.query(Sleeve).filter(Sleeve.id == sleeve_id).update({"accounting_method": "FIFO"})
    db.commit()
    return sleeve_id


def _trade(db, sleeve_id, day, action, qty, price, commission="0"):
    db.add(
        Trade(
            sleeve_id=sleeve_id,
            trade_date=day,
            symbol="VTI",
            action=action,
            quantity=Decimal(qty),
            price=Decimal(price),
            commission=Decimal(commission),
        )
    )
    db.commit()


def test_fifo_partial_sell_consumes_the_oldest_lot_first(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "10")
    _trade(db, sleeve_id, date(2025, 2, 3), "BUY", "100", "20")
    _trade(db, sleeve_id, date(2025, 3, 3), "SELL", "150", "30")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    (open_pos,) = result["open"]
    assert open_pos["quantity"] == Decimal("50")
    assert open_pos["cost_basis"] == Decimal("1000")
    # One closed entry per lot the sell drew from.
    first, second = result["closed"]
    assert (first["matched_quantity"], first["entry_price"]) == (100.0, 10.0)
    assert first["realized_gain"] == Decimal("2000")
    assert (second["matched_quantity"], second["entry_price"]) == (50.0, 20.0)
    assert second["realized_gain"] == Decimal("500")
    assert result["unmatched_sells"] == 0


def test_fifo_handles_fractional_reinvested_lots(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "10", "100")
    _trade(db, sleeve_id, date(2025, 3, 31), "BUY", "0.632", "125")
    _trade(db, sleeve_id, date(2025, 6, 2), "SELL", "10.632", "130")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    assert result["open"] == []
    assert sum(p["matched_quantity"] for p in result["closed"]) == pytest.approx(10.632)


def test_fifo_sell_beyond_holdings_closes_the_long_and_opens_a_short(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "10", "100")
    _trade(db, sleeve_id, date(2025, 2, 3), "SELL", "25", "110")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    (short,) = result["open"]
    assert short["quantity"] == Decimal("-15")
    # A short's basis is the proceeds received, carried negative.
    assert short["cost_basis"] == Decimal("-1650")
    assert result["unmatched_sells"] == 1
    assert result["closed"][0]["matched_quantity"] == 10.0


def test_fifo_short_sale_is_closed_by_the_buy_that_covers_it(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 7, 29), "SELL", "1000", "11", commission="10")
    _trade(db, sleeve_id, date(2025, 8, 15), "BUY", "1000", "10", commission="10")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    # No phantom holding from the covering buy, and nothing left short.
    assert result["open"] == []
    assert result["unmatched_sells"] == 0
    (closed,) = result["closed"]
    assert closed["opened_at"] == date(2025, 7, 29)
    assert closed["closed_at"] == date(2025, 8, 15)
    # Sold at 11, bought back at 10, less both commissions.
    assert closed["realized_gain"] == Decimal("980")


def test_fifo_buy_covers_a_short_then_goes_long_with_the_rest(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "SELL", "40", "50")
    _trade(db, sleeve_id, date(2025, 1, 9), "BUY", "100", "45")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    (long_pos,) = result["open"]
    assert long_pos["quantity"] == Decimal("60")
    assert long_pos["cost_basis"] == Decimal("2700")
    assert result["closed"][0]["realized_gain"] == Decimal("200")


def test_a_short_position_is_valued_as_a_liability(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "SELL", "10", "50")

    valued = PortfolioCalculationService(db).calculate_account_value(
        sleeve_id, {"VTI": Decimal("40")}
    )

    assert valued["total_market_value"] == -400.0
    # Sold at 50, now 40: the short is up 100, a 20% gain on the 500 received.
    assert valued["total_unrealized_gain"] == 100.0
    assert valued["positions"][0]["unrealized_gain_pct"] == 20.0


def test_roll_up_positions_report_a_shorts_price_and_gain(db, client, monkeypatch):
    from app.models.position import Position
    from app.services import performance_service
    from app.services.performance_service import PerformanceService

    # Keep to the persisted price: no live market-data call from a test.
    monkeypatch.setattr(
        performance_service.WebullConnector, "is_configured", lambda self: False
    )

    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "SELL", "10", "50")
    PortfolioCalculationService(db).persist_all_positions(sleeve_id)
    db.query(Position).filter(Position.sleeve_id == sleeve_id).update(
        {"current_price": Decimal("40")}
    )
    db.commit()

    (short,) = PerformanceService(db).positions_payload([sleeve_id])["positions"]

    assert short["quantity"] == -10.0
    assert short["avg_cost"] == 50.0
    assert short["unrealized_gain"] == 100.0
    assert short["unrealized_gain_pct"] == 20.0


def test_round_trip_sleeves_still_ignore_a_partial_sell(db, client):
    from tests.conftest import create_test_strategy

    _, _, sleeve_id = create_test_strategy(client, client_email="rt@example.com")
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "10")
    _trade(db, sleeve_id, date(2025, 3, 3), "SELL", "60", "30")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    assert result["open"][0]["quantity"] == Decimal("100")
    assert result["closed"] == []


# ---------------------------------------------------------------------------
# Dividends and fees in performance
# ---------------------------------------------------------------------------


def _cash(db, sleeve_id, day, type_, amount, symbol="VTI"):
    db.add(
        CashActivity(
            sleeve_id=sleeve_id,
            activity_date=day,
            type=type_,
            symbol=symbol,
            amount=Decimal(amount),
            external_id=f"t:{day}:{type_}:{symbol}:{amount}",
        )
    )
    db.commit()


def _held_then_sold(db, client, email):
    sleeve_id = _fifo_sleeve(db, client, email)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "100")
    _trade(db, sleeve_id, date(2025, 12, 31), "SELL", "100", "110")
    return sleeve_id


def _mwr(db, sleeve_id):
    return MWRCalculationService(db).calculate_mwr(
        sleeve_id, date(2025, 1, 2), date(2025, 12, 31)
    )


def test_a_dividend_raises_mwr_and_a_fee_lowers_it(db, client):
    plain = _held_then_sold(db, client, "plain@example.com")
    with_dividend = _held_then_sold(db, client, "div@example.com")
    _cash(db, with_dividend, date(2025, 6, 30), "DIVIDEND", "200")
    with_fee = _held_then_sold(db, client, "fee@example.com")
    _cash(db, with_fee, date(2025, 6, 30), "FEE", "-200", symbol=None)

    assert _mwr(db, with_dividend) > _mwr(db, plain) > _mwr(db, with_fee)


def test_contributions_and_stray_income_leave_returns_unchanged(db, client):
    plain = _held_then_sold(db, client, "plain2@example.com")
    noisy = _held_then_sold(db, client, "noisy@example.com")
    _cash(db, noisy, date(2025, 6, 30), "CONTRIBUTION", "5000", symbol=None)
    _cash(db, noisy, date(2025, 6, 30), "WITHDRAWAL", "-900", symbol=None)
    # Interest on a settlement fund the sleeve never traded.
    _cash(db, noisy, date(2025, 6, 30), "INTEREST", "40", symbol="VMFXX")

    assert _mwr(db, noisy) == pytest.approx(_mwr(db, plain))
    assert CashActivityService(db).total_income([noisy]) == 0.0


def test_a_reinvested_dividend_nets_to_no_cash_flow(db, client):
    sleeve_id = _fifo_sleeve(db, client, "drip@example.com")
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "100")
    _cash(db, sleeve_id, date(2025, 6, 30), "DIVIDEND", "125")
    _trade(db, sleeve_id, date(2025, 6, 30), "BUY", "1", "125")

    flows = MWRCalculationService(db)._get_cash_flows(
        [sleeve_id], date(2025, 6, 1), date(2025, 7, 31)
    )
    assert flows == [(date(2025, 6, 30), Decimal("0"))]


def test_income_shows_in_summary_and_sleeve_listing(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    sleeve = db.query(Sleeve).filter(Sleeve.id == ba.default_sleeve_id).one()
    base = (
        f"/api/v1/clients/{client_id}/accounts/{sleeve.account_id}"
        f"/sleeves/{sleeve.id}"
    )

    (activity,) = client.get(f"{base}/cash-activities").json()
    assert activity["type"] == "DIVIDEND"
    assert activity["amount"] == 8.21
    assert activity["counts_toward_returns"] is True

    summary = client.get(f"{base}/performance").json()["summary"]
    assert summary["total_income"] == 8.21


# ---------------------------------------------------------------------------
# Time-weighted return
# ---------------------------------------------------------------------------


def _twr(db, sleeve_id, start, end, prices=None):
    from app.services.twr_calculation import TWRCalculationService

    return TWRCalculationService(db).calculate_twr(sleeve_id, start, end, prices)


def _sym_trade(db, sleeve_id, symbol, day, action, qty, price):
    db.add(
        Trade(
            sleeve_id=sleeve_id,
            trade_date=day,
            symbol=symbol,
            action=action,
            quantity=Decimal(qty),
            price=Decimal(price),
            commission=Decimal("0"),
        )
    )
    db.commit()


def test_twr_of_a_single_holding_is_its_price_change(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "100")
    _trade(db, sleeve_id, date(2025, 6, 30), "SELL", "100", "110")

    assert _twr(db, sleeve_id, date(2025, 1, 2), date(2025, 6, 30)) == pytest.approx(0.10)


def test_twr_does_not_compound_across_positions(db, client):
    # Ten holdings each up 10% make a portfolio up 10%, not 1.1 ** 10.
    sleeve_id = _fifo_sleeve(db, client)
    prices = {}
    for n in range(10):
        _sym_trade(db, sleeve_id, f"S{n}", date(2025, 1, 2), "BUY", "10", "100")
        prices[f"S{n}"] = Decimal("110")

    twr = _twr(db, sleeve_id, date(2025, 1, 2), date(2025, 1, 2), prices)

    assert twr == pytest.approx(0.10)


def test_twr_ignores_the_size_and_timing_of_new_money(db, client):
    # Up 10%, then ten times the money is added, then up 10% again.
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "10", "100")
    _trade(db, sleeve_id, date(2025, 3, 3), "BUY", "100", "110")

    twr = _twr(db, sleeve_id, date(2025, 1, 2), date(2025, 3, 3), {"VTI": Decimal("121")})

    assert twr == pytest.approx(1.1 * 1.1 - 1)


def test_twr_counts_a_dividend_as_return(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "100")
    _cash(db, sleeve_id, date(2025, 6, 30), "DIVIDEND", "500")

    twr = _twr(db, sleeve_id, date(2025, 1, 2), date(2025, 6, 30))

    assert twr == pytest.approx(0.05)


def test_twr_is_none_without_trades(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    assert _twr(db, sleeve_id, date(2025, 1, 1), date(2025, 12, 31)) is None


def _priced(db, sleeve_id, price):
    """Persist positions for a sleeve and give them a current price."""
    PortfolioCalculationService(db).persist_all_positions(sleeve_id)
    db.query(Position).filter(Position.sleeve_id == sleeve_id).update(
        {"current_price": Decimal(price)}
    )
    db.commit()
    # Where a daily record exists it is what performance reads, so bring it
    # up to the new price. (A sleeve with no rows is calculated from trades.)
    if db.query(DailyValuation).filter(DailyValuation.sleeve_id == sleeve_id).first():
        rebuild_for_sleeves(db, [sleeve_id])


def test_headline_weekly_and_monthly_returns_agree(db, client, monkeypatch):
    from app.services import performance_service
    from app.services.performance_service import PerformanceService
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    monkeypatch.setattr(
        performance_service.WebullConnector, "is_configured", lambda self: False
    )
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 6), "BUY", "100", "100")
    _trade(db, sleeve_id, date(2025, 2, 10), "BUY", "50", "110")
    _trade(db, sleeve_id, date(2025, 3, 17), "SELL", "60", "105")
    _cash(db, sleeve_id, date(2025, 3, 31), "DIVIDEND", "45")
    _priced(db, sleeve_id, "120")
    service = PerformanceService(db)

    headline = service.performance([sleeve_id])["summary"]
    weekly = WeeklySnapshotService(db).returns_series([sleeve_id])
    monthly = service.monthly_returns([sleeve_id])

    # The series closes on the headline figures...
    assert weekly[-1]["twr_cumul"] == pytest.approx(headline["twr_pct"], abs=1e-6)
    assert weekly[-1]["mwr_cumul"] == pytest.approx(headline["mwr_pct"], abs=1e-6)
    # ...and the months compound to the same time-weighted return.
    compounded = 1.0
    for month in monthly:
        compounded *= 1 + month["return_pct"] / 100
    assert compounded - 1 == pytest.approx(headline["twr_pct"], abs=1e-3)
    # The value chart ends on today's market value.
    series = service.performance([sleeve_id])["timeseries"]
    assert series[-1]["value"] == pytest.approx(headline["total_market_value"])
    # Earlier points are valued at what was known then, not at today's price.
    assert series[0]["value"] == pytest.approx(10000.0)


def test_weekly_series_for_several_sleeves_is_one_merged_portfolio(db, client, monkeypatch):
    from app.services import performance_service
    from app.services.performance_service import PerformanceService
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    monkeypatch.setattr(
        performance_service.WebullConnector, "is_configured", lambda self: False
    )
    first = _fifo_sleeve(db, client, "merge1@example.com")
    second = _fifo_sleeve(db, client, "merge2@example.com")
    _sym_trade(db, first, "AAA", date(2025, 1, 6), "BUY", "100", "10")
    _sym_trade(db, second, "BBB", date(2025, 1, 6), "BUY", "10", "900")
    _priced(db, first, "20")
    _priced(db, second, "900")

    headline = PerformanceService(db).performance([first, second])["summary"]
    weekly = WeeklySnapshotService(db).returns_series([first, second])

    # 1,000 doubled next to 9,000 unchanged is 10%, whatever the sleeves did alone.
    assert headline["twr_pct"] == pytest.approx(0.10)
    assert weekly[-1]["twr_cumul"] == pytest.approx(0.10)


def test_returns_are_not_quoted_when_no_money_was_ever_invested(db, client):
    # Options written for a premium and left to expire: a gain, but on no
    # capital, so neither return has a base to be a percentage of.
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 3, 3), "SELL", "10", "200")
    _trade(db, sleeve_id, date(2025, 4, 17), "BUY", "10", "50")

    assert _mwr(db, sleeve_id) is None
    assert _twr(db, sleeve_id, date(2025, 1, 2), date(2025, 12, 31)) is None


def test_mwr_values_open_holdings_at_market_when_prices_are_given(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "100", "100")
    _trade(db, sleeve_id, date(2026, 1, 2), "BUY", "1", "100")
    svc = MWRCalculationService(db)

    stale = svc.calculate_mwr(sleeve_id, date(2025, 1, 2), date(2026, 1, 2))
    marked = svc.calculate_mwr(
        sleeve_id, date(2025, 1, 2), date(2026, 1, 2), {"VTI": Decimal("120")}
    )

    assert stale == pytest.approx(0.0, abs=1e-6)
    assert marked == pytest.approx(0.20, abs=0.005)


# ---------------------------------------------------------------------------
# Cash: whole-account value and returns
# ---------------------------------------------------------------------------


def _cash_row(type_, amount, day, symbol=None, units=0, price=0):
    return {
        "id": f"cash-{type_}-{day}-{amount}",
        "symbol": (
            {"symbol": symbol, "raw_symbol": symbol, "type": {"code": "cs"}}
            if symbol
            else None
        ),
        "option_symbol": None,
        "currency": {"code": "USD"},
        "type": type_,
        "description": type_,
        "amount": amount,
        "price": price,
        "units": units,
        "fee": 0.0,
        "trade_date": f"{day}T05:00:00Z",
        "settlement_date": f"{day}T05:00:00Z",
    }


def _cash_account(db, client, client_id, sdk, rows, cash_now):
    """An account whose whole history is ``rows`` and whose cash is known."""
    from app.services import performance_service

    sdk.activities = {"data": rows}
    # The brokerage holds exactly what these trades add up to.
    held = {}
    for row in rows:
        symbol = (row["symbol"] or {}).get("raw_symbol")
        if row["type"] in ("BUY", "SELL") and symbol and len(symbol) < 10:
            units, price = held.get(symbol, (0, 0))
            held[symbol] = (units + row["units"], row["price"])
    sdk.positions = {
        "results": [
            {"instrument": {"symbol": sym, "raw_symbol": sym}, "units": str(units),
             "price": str(price), "cost_basis": str(price)}
            for sym, (units, price) in held.items()
            if units
        ]
    }
    sdk.cash = cash_now
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    return ba


@pytest.fixture
def no_live_prices(monkeypatch):
    from app.services import performance_service

    monkeypatch.setattr(
        performance_service.WebullConnector, "is_configured", lambda self: False
    )


def test_cash_on_a_past_date_is_worked_back_from_todays_balance(
    db, client, client_id, sdk
):
    from app.services.cash_ledger import CashLedger

    ba = _cash_account(
        db, client, client_id, sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-02-02", "ABC", 40, 100),
            _cash_row("DIVIDEND", 50.0, "2026-03-02", "ABC"),
            # Cash moving into the settlement fund is still cash.
            _cash_row("SWEEP IN", -6000.0, "2026-03-03", "VMFXX", 0, 1),
        ],
        cash_now=6050.0,
    )
    ledger = CashLedger.for_accounts(db, [ba.account_id])

    assert ledger.balance_on(date(2026, 1, 1)) == Decimal("0")
    assert ledger.balance_on(date(2026, 1, 5)) == Decimal("10000")
    assert ledger.balance_on(date(2026, 2, 2)) == Decimal("6000")
    assert ledger.balance_on(date(2026, 12, 31)) == Decimal("6050")
    # Only the deposit crossed the account boundary.
    assert ledger.external == {date(2026, 1, 5): Decimal("10000")}


def test_account_return_includes_idle_cash(db, client, client_id, sdk, no_live_prices):
    from app.services.performance_service import PerformanceService

    # 10,000 deposited, 4,000 of it put into a stock that then rises 25%.
    ba = _cash_account(
        db, client, client_id, sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
        ],
        cash_now=6000.0,
    )
    sleeve_id = ba.default_sleeve_id
    _priced(db, sleeve_id, "125")
    service = PerformanceService(db)

    account = service.performance([sleeve_id], cash_account_ids=[ba.account_id])
    sleeve = service.performance([sleeve_id])

    # The stock alone is up 25%; the account, with 6,000 idle, is up 10%.
    assert sleeve["summary"]["twr_pct"] == pytest.approx(0.25)
    assert sleeve["summary"]["cash_balance"] is None
    assert account["summary"]["twr_pct"] == pytest.approx(0.10)
    assert account["summary"]["mwr_pct"] == pytest.approx(0.10, abs=1e-3)
    assert account["summary"]["cash_balance"] == 6000.0
    # The chart is securities plus cash, ending on today's total.
    assert account["timeseries"][-1]["value"] == pytest.approx(11000.0)
    assert account["timeseries"][-1]["cash"] == pytest.approx(6000.0)


def test_a_deposit_is_money_in_but_a_trade_is_not(db, client, client_id, sdk, no_live_prices):
    from app.services.performance_service import PerformanceService

    # Flat prices throughout: more money arriving must not look like a gain.
    ba = _cash_account(
        db, client, client_id, sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
            _cash_row("CONTRIBUTION", 50000.0, "2026-03-02"),
            _cash_row("BUY", -20000.0, "2026-03-02", "ABC", 200, 100),
        ],
        cash_now=36000.0,
    )
    _priced(db, ba.default_sleeve_id, "100")

    summary = PerformanceService(db).performance(
        [ba.default_sleeve_id], cash_account_ids=[ba.account_id]
    )["summary"]

    assert summary["twr_pct"] == pytest.approx(0.0, abs=1e-9)
    assert summary["mwr_pct"] == pytest.approx(0.0, abs=1e-6)


def test_chart_points_carry_the_money_put_in_so_a_benchmark_can_match_it(
    db, client, client_id, sdk, no_live_prices
):
    from app.services.performance_service import PerformanceService

    ba = _cash_account(
        db, client, client_id, sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
            # Deposited on a day with no trade: it shows at the next point.
            _cash_row("CONTRIBUTION", 5000.0, "2026-02-10"),
            _cash_row("BUY", -1000.0, "2026-03-02", "ABC", 10, 100),
            _cash_row("WITHDRAWAL", -2000.0, "2026-03-02"),
        ],
        cash_now=8000.0,
    )
    service = PerformanceService(db)
    sleeve_id = ba.default_sleeve_id

    account = service.performance([sleeve_id], cash_account_ids=[ba.account_id])
    sleeve = service.performance([sleeve_id])

    def moved(result):
        return [
            (str(p["date"]), p["net_flow"]) for p in result["timeseries"] if p["net_flow"]
        ]

    # For the account, only deposits and withdrawals are money in.
    assert moved(account) == [
        ("2026-01-05", 10000.0),
        ("2026-02-10", 5000.0),
        ("2026-03-02", -2000.0),
    ]
    assert account["timeseries"][-1]["net_contributions"] == 13000.0
    # For the sleeve alone, buying is.
    assert moved(sleeve) == [("2026-01-05", 4000.0), ("2026-03-02", 1000.0)]


def test_account_views_with_cash_agree_with_each_other(
    db, client, client_id, sdk, no_live_prices
):
    from app.services.performance_service import PerformanceService
    from app.services.weekly_snapshot_service import WeeklySnapshotService

    ba = _cash_account(
        db, client, client_id, sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
            _cash_row("DIVIDEND", 80.0, "2026-02-16", "ABC"),
            _cash_row("SELL", 2200.0, "2026-03-02", "ABC", -20, 110),
            _cash_row("FEE", -15.0, "2026-03-31"),
        ],
        cash_now=8265.0,
    )
    sleeve_id = ba.default_sleeve_id
    _priced(db, sleeve_id, "120")
    service = PerformanceService(db)
    accounts = [ba.account_id]

    headline = service.performance([sleeve_id], cash_account_ids=accounts)["summary"]
    weekly = WeeklySnapshotService(db).returns_series(
        [sleeve_id], cash_account_ids=accounts
    )
    monthly = service.monthly_returns([sleeve_id], cash_account_ids=accounts)

    # 10,000 in; now 20 shares at 120 plus 8,265 cash.
    assert headline["twr_pct"] == pytest.approx(10665 / 10000 - 1)
    assert weekly[-1]["twr_cumul"] == pytest.approx(headline["twr_pct"], abs=1e-6)
    assert weekly[-1]["mwr_cumul"] == pytest.approx(headline["mwr_pct"], abs=1e-6)
    compounded = 1.0
    for month in monthly:
        compounded *= 1 + month["return_pct"] / 100
    assert compounded - 1 == pytest.approx(headline["twr_pct"], abs=1e-3)


def test_todays_total_rests_on_the_brokerages_current_holdings(
    db, client, client_id, sdk, no_live_prices
):
    from app.services.performance_service import PerformanceService

    # 10,000 in, 4,000 of it in ABC. The brokerage has since bought 3,000 of
    # XYZ: its cash already shows that, but the trade has not reached us.
    ba = _cash_account(
        db, client, client_id, sdk,
        [
            _cash_row("CONTRIBUTION", 10000.0, "2026-01-05"),
            _cash_row("BUY", -4000.0, "2026-01-05", "ABC", 40, 100),
        ],
        cash_now=3000.0,
    )
    sdk.positions = {
        "results": [
            {"instrument": {"symbol": "ABC", "raw_symbol": "ABC"}, "units": "40",
             "price": "100", "cost_basis": "100"},
            {"instrument": {"symbol": "XYZ", "raw_symbol": "XYZ"}, "units": "30",
             "price": "100"},
        ]
    }
    report = ConnectionService(db).reconcile(ba.id)
    assert report["holdings_adjustment"] == 3000.0
    rebuild_for_sleeves(db, [ba.default_sleeve_id])

    result = PerformanceService(db).performance(
        [ba.default_sleeve_id], cash_account_ids=[ba.account_id]
    )

    # Without the correction the account would look 30% down today, or, with
    # it applied only to today, 43% up on an understated past.
    summary = result["summary"]
    assert summary["cash_balance"] == 3000.0
    assert summary["holdings_adjustment"] == 3000.0
    assert summary["twr_pct"] == pytest.approx(0.0, abs=1e-9)
    assert summary["mwr_pct"] == pytest.approx(0.0, abs=1e-6)
    assert {round(p["value"], 2) for p in result["timeseries"]} == {10000.0}


def test_full_history_sync_reloads_from_the_first_day_and_adds_only_what_is_new(
    db, client, client_id, sdk
):
    ba_id, _, _ = _split_account(db, client, client_id, history_start="2026-01-01")
    sync_brokerage_account(db, ba_id)
    older = dict(
        sdk.activities["data"][0], id="older-uso", trade_date="2024-05-06T05:00:00Z"
    )
    sdk.activities["data"].append(older)

    result = sync_brokerage_account(db, ba_id, force=True, full_history=True)

    call = [c for c in sdk.calls if c[0] == "activities"][-1][1]
    assert call["start_date"] is None
    assert (result["imported"], result["duplicates"]) == (1, 8)
    ba = db.query(BrokerageAccount).filter(BrokerageAccount.id == ba_id).one()
    assert ba.sync_start_date is None


def test_options_are_repriced_to_what_the_brokerages_total_implies(
    db, client, client_id, sdk, no_live_prices
):
    from app.services.performance_service import PerformanceService

    # 10,000 in; 10 puts written for 2,000. They last traded at 200 a contract
    # but the brokerage's total says they now cost 500 each to buy back.
    put = _option_row("SELL", -10, 2.0, 2000.0, "2026-01-05")
    ba = _cash_account(
        db, client, client_id, sdk,
        [_cash_row("CONTRIBUTION", 10000.0, "2026-01-05"), put],
        cash_now=12000.0,
    )
    sdk.total = 7000.0
    from app.services.daily_capture_service import DailyCaptureService

    DailyCaptureService(db).capture(ba.id)

    # Implied option value 7,000 - 12,000 = -5,000, against -2,000 on our books.
    db.refresh(ba)
    assert ba.reconciliation["valuation_adjustment"] == -3000.0
    result = PerformanceService(db).performance(
        [ba.default_sleeve_id], cash_account_ids=[ba.account_id]
    )
    summary = result["summary"]
    # Today's total is the brokerage's, and the 3,000 lost shows as return.
    assert summary["total_value"] == pytest.approx(7000.0)
    assert summary["twr_pct"] == pytest.approx(-0.30)
    assert result["timeseries"][-1]["value"] == pytest.approx(7000.0)


def test_account_without_reported_cash_stays_securities_only(
    db, client, client_id, sdk, no_live_prices
):
    from app.services.performance_service import PerformanceService

    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)

    summary = PerformanceService(db).performance(
        [ba.default_sleeve_id], cash_account_ids=[ba.account_id]
    )["summary"]

    assert summary["cash_balance"] is None


# ---------------------------------------------------------------------------
# Removing a connection
# ---------------------------------------------------------------------------


def test_delete_revokes_at_the_source_and_keeps_history(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    connection_id = ba.connection_id

    assert client.delete(f"/api/v1/connections/{connection_id}").status_code == 204

    assert ("delete", {"authorization_id": "auth-1", "user_id": USER_ID}) in sdk.calls
    assert client.get(f"/api/v1/clients/{client_id}/connections").json() == []
    assert db.query(Trade).count() == 8
    assert client.delete(f"/api/v1/connections/{connection_id}").status_code == 404


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


def _signed(event: dict):
    body = json.dumps(event).encode()
    digest = hmac.new(CONSUMER_KEY.encode(), body, hashlib.sha256).digest()
    return body, {"Signature": base64.b64encode(digest).decode()}


def test_webhook_with_a_bad_signature_is_rejected_before_anything_runs(
    db, client, client_id, sdk
):
    ba = _mapped_account(db, client_id)
    body, _ = _signed({"eventType": "ACCOUNT_TRANSACTIONS_UPDATED", "accountId": "acct-1"})

    for headers in ({}, {"Signature": "bm90LXRoZS1zaWduYXR1cmU="}):
        resp = client.post("/api/v1/webhooks/snaptrade", content=body, headers=headers)
        assert resp.status_code == 401

    assert db.query(Trade).count() == 0
    db.refresh(ba)
    assert ba.last_synced_at is None


def test_webhook_signature_covers_the_exact_bytes_sent(db, client, client_id, sdk):
    _, headers = _signed({"eventType": "CONNECTION_BROKEN"})
    resp = client.post(
        "/api/v1/webhooks/snaptrade",
        content=b'{"eventType": "CONNECTION_DELETED"}',
        headers=headers,
    )
    assert resp.status_code == 401


def test_transactions_webhook_syncs_and_a_replay_adds_nothing(db, client, client_id, sdk):
    _mapped_account(db, client_id)
    body, headers = _signed(
        {"eventType": "ACCOUNT_TRANSACTIONS_UPDATED", "accountId": "acct-1"}
    )

    first = client.post("/api/v1/webhooks/snaptrade", content=body, headers=headers)
    assert first.json() == {"status": "synced"}
    assert db.query(Trade).count() == 8

    replay = client.post("/api/v1/webhooks/snaptrade", content=body, headers=headers)
    assert replay.status_code == 200
    assert db.query(Trade).count() == 8
    assert db.query(CashActivity).count() == 1


def test_broken_connection_webhook_flags_the_login(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    body, headers = _signed(
        {"eventType": "CONNECTION_BROKEN", "brokerageAuthorizationId": "auth-1"}
    )
    resp = client.post("/api/v1/webhooks/snaptrade", content=body, headers=headers)
    assert resp.json() == {"status": "status_updated"}
    db.refresh(ba.connection)
    assert ba.connection.status == "broken"


def test_webhook_for_an_unknown_account_is_acknowledged_and_ignored(
    db, client, client_id, sdk
):
    body, headers = _signed(
        {"eventType": "ACCOUNT_TRANSACTIONS_UPDATED", "accountId": "someone-else"}
    )
    resp = client.post("/api/v1/webhooks/snaptrade", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}
