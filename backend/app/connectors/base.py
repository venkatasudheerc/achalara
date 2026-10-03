"""The connector interface: ``BrokerageConnector`` + ``ConnectorCapabilities``.

Callers depend on this Protocol and on the normalized types in ``models`` —
never on a concrete connector class. To ask "can this be traded?", read
``connector.capabilities.can_trade``; never ``isinstance(c, SomeConnector)``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Protocol, runtime_checkable

from app.connectors.models import (
    Connection,
    ConnectionResult,
    ConnectionStatus,
    LinkSession,
    NormalizedPosition,
    NormalizedTrade,
    OrderRequest,
    OrderResult,
    RawAccount,
)


@dataclass(frozen=True)
class ConnectorCapabilities:
    """Honest, machine-readable declaration of what a source can do.

    Callers branch on these flags, never on the concrete class. A connector
    must not advertise a capability it cannot honor.
    """

    can_read_positions: bool
    can_read_transactions: bool
    can_trade: bool
    supports_realtime: bool
    supports_historical_backfill: bool
    requires_manual_refresh: bool
    data_freshness: str  # "realtime" | "daily" | "manual"


@runtime_checkable
class BrokerageConnector(Protocol):
    """The contract every source adapts to.

    Reading methods are available now. Linking methods exist for aggregators
    (SnapTrade) and are stubbed (raising ``NotSupported``) by non-linkable
    sources such as CSV/manual, which declare it via ``capabilities``. Trading
    exists in the contract from day one but stays dormant behind
    ``capabilities.can_trade`` until Grow.
    """

    capabilities: ConnectorCapabilities

    # lifecycle / linking ---------------------------------------------------
    def initiate_link(self, client_id: str, redirect_uri: str) -> LinkSession:
        ...

    def complete_link(self, callback_payload: dict) -> ConnectionResult:
        ...

    def list_connections(self, client_id: str) -> List[Connection]:
        ...

    def refresh_connection(self, connection_id: str) -> ConnectionStatus:
        ...

    def remove_connection(self, connection_id: str) -> None:
        ...

    # reading (available now) ----------------------------------------------
    def fetch_accounts(self, connection_id: str) -> List[RawAccount]:
        ...

    def fetch_positions(
        self, connection_id: str, account_ref: str
    ) -> List[NormalizedPosition]:
        ...

    def fetch_transactions(
        self,
        connection_id: str,
        account_ref: str,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
    ) -> List[NormalizedTrade]:
        ...

    # trading (later — guard with capabilities.can_trade) -------------------
    def place_order(
        self, connection_id: str, account_ref: str, order: OrderRequest
    ) -> OrderResult:
        ...
