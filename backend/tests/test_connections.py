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
from app.models.brokerage_connection import BrokerageAccount, BrokerageConnection
from app.models.cash_activity import CashActivity
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
    assert result["imported"] == 7
    assert result["cash_imported"] == 1
    assert result["skipped_rows"] == {
        "sweep": 2,
        "incomplete": 1,
        "corporate_action": 1,
    }
    assert result["transactions_synced_through"] == date(2026, 9, 30)

    trades = db.query(Trade).filter(Trade.sleeve_id == ba.default_sleeve_id).all()
    assert len(trades) == 7
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
    assert log.status == "SUCCESS" and log.rows_success == 7


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
    assert result["duplicates"] == 7
    assert result["cash_imported"] == 0
    assert db.query(Trade).count() == 7
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
    assert resp.json()["imported"] == 7
    assert client.post("/api/v1/brokerage-accounts/nope/sync").status_code == 404


def test_scheduled_job_syncs_mapped_accounts_only(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    outcomes = run_all_brokerage_syncs(db)
    assert outcomes == {ba.id: "synced"}
    # The second account was discovered but never mapped.
    assert db.query(BrokerageAccount).count() == 2


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
    # The FRDM sell has no buy in the captured history.
    assert report["unmatched_sells"] == 1
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
    assert open_symbols == {"MU"}
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
    assert db.query(Trade).count() == 7
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


def test_fifo_counts_a_sell_with_nothing_to_sell(db, client):
    sleeve_id = _fifo_sleeve(db, client)
    _trade(db, sleeve_id, date(2025, 1, 2), "BUY", "10", "100")
    _trade(db, sleeve_id, date(2025, 2, 3), "SELL", "25", "110")

    result = PortfolioCalculationService(db).calculate_positions(sleeve_id)

    assert result["open"] == []
    assert result["unmatched_sells"] == 1
    assert result["closed"][0]["matched_quantity"] == 10.0


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
# Removing a connection
# ---------------------------------------------------------------------------


def test_delete_revokes_at_the_source_and_keeps_history(db, client, client_id, sdk):
    ba = _mapped_account(db, client_id)
    sync_brokerage_account(db, ba.id)
    connection_id = ba.connection_id

    assert client.delete(f"/api/v1/connections/{connection_id}").status_code == 204

    assert ("delete", {"authorization_id": "auth-1", "user_id": USER_ID}) in sdk.calls
    assert client.get(f"/api/v1/clients/{client_id}/connections").json() == []
    assert db.query(Trade).count() == 7
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
    assert db.query(Trade).count() == 7

    replay = client.post("/api/v1/webhooks/snaptrade", content=body, headers=headers)
    assert replay.status_code == 200
    assert db.query(Trade).count() == 7
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
