"""Connector registry — name -> connector instance for runtime source selection.

Callers resolve a source by its registered name and depend only on the
``BrokerageConnector`` interface. New connectors register here (see the checklist
in CONNECTORS.md). The Webull connector is *not* registered by default because
constructing it reads API credentials; obtain it explicitly when needed.
"""
from __future__ import annotations

from typing import Dict

from app.connectors.base import BrokerageConnector
from app.connectors.csv_connector import CSVConnector
from app.connectors.fake_connector import FakeConnector
from app.connectors.sheets_connector import SheetsConnector

_REGISTRY: Dict[str, BrokerageConnector] = {}


def register(name: str, connector: BrokerageConnector) -> None:
    """Register (or replace) a connector under ``name`` (case-insensitive)."""
    _REGISTRY[name.lower()] = connector


def get_connector(name: str) -> BrokerageConnector:
    """Return the connector registered under ``name``.

    Raises ``KeyError`` if no source is registered with that name.
    """
    key = name.lower()
    if key not in _REGISTRY:
        raise KeyError(f"No connector registered for source '{name}'")
    return _REGISTRY[key]


def available_sources() -> list[str]:
    """List the registered source names."""
    return sorted(_REGISTRY)


# Default registrations. Stateless connectors are safe as singletons.
register("csv", CSVConnector())
register("sheets", SheetsConnector())
register("fake", FakeConnector())
