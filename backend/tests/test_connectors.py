"""Tests for the Bridge connector layer (B1/B2).

Exercises the normalized types, the fake connector, capability-based branching,
and the shared ingestion pipeline — all with zero network calls.
"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from tests.conftest import create_test_strategy

from app.connectors.csv_connector import CSVConnector
from app.connectors.fake_connector import FakeConnector
from app.connectors.models import (
    NormalizedPosition,
    NormalizedTrade,
    NotSupported,
    OrderRequest,
    RawAccount,
    TradeAction,
)
from app.connectors.registry import available_sources, get_connector
from app.services.ingestion_service import IngestionService
from app.models.trade import Trade


def _trade(symbol="AAPL", qty="10", price="100", action=TradeAction.BUY, source="fake"):
    return NormalizedTrade(
        external_id=f"{source}:{symbol}:{qty}:{price}",
        symbol=symbol,
        action=action,
        quantity=Decimal(qty),
        price=Decimal(price),
        executed_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        source=source,
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_resolves_known_sources():
    assert get_connector("csv") is not None
    assert get_connector("sheets") is not None
    assert get_connector("fake") is not None
    assert {"csv", "sheets", "fake"}.issubset(set(available_sources()))


def test_registry_unknown_source_raises():
    with pytest.raises(KeyError):
        get_connector("nope")


# ---------------------------------------------------------------------------
# Capabilities — callers branch on these, never on the class
# ---------------------------------------------------------------------------


def test_capabilities_are_honest():
    assert CSVConnector.capabilities.can_read_transactions is True
    assert CSVConnector.capabilities.can_trade is False
    assert CSVConnector.capabilities.data_freshness == "manual"


# ---------------------------------------------------------------------------
# Fake connector — deterministic, no network
# ---------------------------------------------------------------------------


def test_fake_connector_round_trips_seeded_data():
    conn = FakeConnector(
        accounts=[RawAccount(external_ref="acct-1", name="Brokerage")],
        positions=[
            NormalizedPosition(
                symbol="AAPL", quantity=Decimal("5"), avg_cost=Decimal("90")
            )
        ],
        transactions=[_trade()],
    )

    assert conn.fetch_accounts("c1")[0].external_ref == "acct-1"
    assert conn.fetch_positions("c1", "acct-1")[0].symbol == "AAPL"

    txns = conn.fetch_transactions("c1", "acct-1")
    assert len(txns) == 1
    assert txns[0].action is TradeAction.BUY

    # Deterministic: repeated calls return equal data.
    assert conn.fetch_transactions("c1", "acct-1") == txns


def test_fake_connector_transaction_date_filter():
    conn = FakeConnector(transactions=[_trade()])
    after = datetime(2024, 6, 1, tzinfo=timezone.utc)
    assert conn.fetch_transactions("c1", "a", since=after) == []


def test_fake_connector_place_order_when_enabled():
    conn = FakeConnector()
    result = conn.place_order(
        "c1",
        "a",
        OrderRequest(symbol="AAPL", action=TradeAction.BUY, quantity=Decimal("1")),
    )
    assert result.status == "FILLED"


# ---------------------------------------------------------------------------
# CSV connector — non-linkable methods guard the contract
# ---------------------------------------------------------------------------


def test_csv_connector_not_linkable():
    conn = CSVConnector()
    with pytest.raises(NotSupported):
        conn.initiate_link("c1", "https://cb")
    with pytest.raises(NotSupported):
        conn.fetch_transactions("c1", "a")
    assert conn.list_connections("c1") == []


def test_csv_connector_parses_to_normalized_trades():
    csv_bytes = (
        b"Date,Symbol,Action,Quantity,Price,Commission,Strategy,Account,Notes\n"
        b"2024-03-01,AAPL,BUY,10,100,0,Growth,ACC1,\n"
    )
    trades, errors, rows = CSVConnector().parse_transactions(csv_bytes)
    assert rows == 1
    assert errors == []
    assert len(trades) == 1
    t = trades[0]
    assert t.symbol == "AAPL"
    assert t.action is TradeAction.BUY
    assert t.strategy == "Growth"
    assert t.account == "ACC1"
    assert t.source == "csv"
    # external_id is stable for the same (date, symbol, qty, price)
    trades2, _, _ = CSVConnector().parse_transactions(csv_bytes)
    assert trades2[0].external_id == t.external_id


# ---------------------------------------------------------------------------
# Ingestion pipeline — one path, idempotent dedup
# ---------------------------------------------------------------------------


def test_ingest_to_sleeve_dedups_idempotently(client, db):
    _c, _a, sleeve_id = create_test_strategy(client, client_email="ingest@example.com")
    ingestion = IngestionService(db)

    first = ingestion.ingest_to_sleeve([_trade()], sleeve_id)
    assert first["success"] is True
    assert first["imported"] == 1
    assert db.query(Trade).filter(Trade.sleeve_id == sleeve_id).count() == 1

    # Re-ingesting the same trade collapses to a duplicate — no new row.
    second = ingestion.ingest_to_sleeve([_trade()], sleeve_id)
    assert second["imported"] == 0
    assert second["duplicates"] == 1
    assert db.query(Trade).filter(Trade.sleeve_id == sleeve_id).count() == 1


def test_ingest_to_sleeve_validate_mode_persists_nothing(client, db):
    _c, _a, sleeve_id = create_test_strategy(client, client_email="val@example.com")
    result = IngestionService(db).ingest_to_sleeve(
        [_trade()], sleeve_id, mode="VALIDATE"
    )
    assert result["success"] is True
    assert result["imported"] == 1
    assert result["sync_log_id"] is None
    assert db.query(Trade).filter(Trade.sleeve_id == sleeve_id).count() == 0
