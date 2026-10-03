"""Deterministic, no-network connector for tests.

Implements the full ``BrokerageConnector`` surface with in-memory data so the
ingestion pipeline and performance code can be exercised with zero network
calls. Seed it with normalized trades/positions/accounts; everything it returns
is stable and repeatable.
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from app.connectors.base import ConnectorCapabilities
from app.connectors.models import (
    Connection,
    ConnectionResult,
    ConnectionStatus,
    LinkSession,
    NormalizedPosition,
    NormalizedTrade,
    NotSupported,
    OrderRequest,
    OrderResult,
    RawAccount,
)

SOURCE = "fake"


class FakeConnector:
    """In-memory connector with deterministic, seeded data."""

    capabilities = ConnectorCapabilities(
        can_read_positions=True,
        can_read_transactions=True,
        can_trade=True,
        supports_realtime=False,
        supports_historical_backfill=True,
        requires_manual_refresh=False,
        data_freshness="manual",
    )

    def __init__(
        self,
        accounts: Optional[List[RawAccount]] = None,
        positions: Optional[List[NormalizedPosition]] = None,
        transactions: Optional[List[NormalizedTrade]] = None,
    ):
        self._accounts = list(accounts or [])
        self._positions = list(positions or [])
        self._transactions = list(transactions or [])
        self._connections: Dict[str, Connection] = {}
        self._order_seq = 0

    # --- linking lifecycle -------------------------------------------------

    def initiate_link(self, client_id: str, redirect_uri: str) -> LinkSession:
        return LinkSession(
            redirect_url=f"{redirect_uri}?client={client_id}",
            session_ref=f"fake-session-{client_id}",
        )

    def complete_link(self, callback_payload: dict) -> ConnectionResult:
        connection_id = callback_payload.get("connection_id", "fake-connection")
        self._connections[connection_id] = Connection(
            connection_id=connection_id, institution="Fake Brokerage"
        )
        return ConnectionResult(
            connection_id=connection_id, institution="Fake Brokerage"
        )

    def list_connections(self, client_id: str) -> List[Connection]:
        return list(self._connections.values())

    def refresh_connection(self, connection_id: str) -> ConnectionStatus:
        return ConnectionStatus(connection_id=connection_id, status="active")

    def remove_connection(self, connection_id: str) -> None:
        self._connections.pop(connection_id, None)

    # --- reading -----------------------------------------------------------

    def fetch_accounts(self, connection_id: str) -> List[RawAccount]:
        return list(self._accounts)

    def fetch_positions(
        self, connection_id: str, account_ref: str
    ) -> List[NormalizedPosition]:
        return list(self._positions)

    def fetch_transactions(
        self,
        connection_id: str,
        account_ref: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[NormalizedTrade]:
        out = self._transactions
        if since is not None:
            out = [t for t in out if t.executed_at >= since]
        if until is not None:
            out = [t for t in out if t.executed_at <= until]
        return list(out)

    # --- trading -----------------------------------------------------------

    def place_order(
        self, connection_id: str, account_ref: str, order: OrderRequest
    ) -> OrderResult:
        if not self.capabilities.can_trade:
            raise NotSupported("Trading not enabled")
        self._order_seq += 1
        return OrderResult(order_ref=f"fake-order-{self._order_seq}", status="FILLED")
