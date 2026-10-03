# Bridge — Connector Layer Conventions

> Scope: `backend/app/connectors/`. This is **Bridge** — the layer that brings trade and
> position data into Achalara from any source (CSV, Google Sheets, Webull, SnapTrade, and
> future brokers). Read this before adding or changing anything in this package.

---

## The one rule

**Nothing outside `app/connectors/` may import a vendor SDK or know a vendor's name.**
Every source speaks the project's **normalized types** (`connectors/models.py`). Services,
routes, and the ingestion pipeline depend only on the `BrokerageConnector` interface and
those normalized types — never on `snaptrade`, `plaid`, `webull`, `gspread`, or a CSV shape.

This is what makes any single vendor a replaceable detail. If it's violated, the abstraction
is worthless and you're locked in. Treat a vendor import leaking upward as a build-breaking bug.

---

## Why this layer exists

- "Connect any brokerage in the world" is bought, not built — but the **vendor must stay
  swappable**. We design our own interface and adapt vendors to it, not the reverse.
- Our differentiator is the performance/insight layer (Lens), not the plumbing. Connectors
  are commodities; our normalized model and analytics are the product.
- CSV/Sheets/manual must remain first-class **forever** — they are the universal fallback for
  any broker no aggregator covers.

---

## Structure

```
backend/app/connectors/
├── base.py            # BrokerageConnector protocol + ConnectorCapabilities
├── models.py          # NormalizedTrade, NormalizedPosition, RawAccount, enums
├── registry.py        # name -> connector instance; runtime source selection
├── csv_connector.py        # existing CSV import, refactored behind the interface
├── sheets_connector.py     # existing Google Sheets sync, behind the interface
├── webull_connector.py     # existing Webull price fetch, normalized
├── snaptrade_connector.py  # aggregator adapter (added after the spike)
└── fake_connector.py       # deterministic, no network — for tests
```

The shared ingestion pipeline lives **outside** this package, in
`app/services/ingestion_service.py`. Connectors *produce* normalized trades; the service
*validates, dedups, routes, and persists* them — the same VALIDATE→IMPORT path every source
reuses. Do not duplicate that pipeline per source.

---

## The interface (authoritative shape — keep in sync with `base.py`)

```python
class BrokerageConnector(Protocol):
    capabilities: ConnectorCapabilities

    # lifecycle / linking
    def initiate_link(self, client_id: str, redirect_uri: str) -> LinkSession: ...
    def complete_link(self, callback_payload: dict) -> ConnectionResult: ...
    def list_connections(self, client_id: str) -> list[Connection]: ...
    def refresh_connection(self, connection_id: str) -> ConnectionStatus: ...
    def remove_connection(self, connection_id: str) -> None: ...

    # reading (available now)
    def fetch_accounts(self, connection_id: str) -> list[RawAccount]: ...
    def fetch_positions(self, connection_id: str, account_ref: str) -> list[NormalizedPosition]: ...
    def fetch_transactions(self, connection_id: str, account_ref: str,
                           since=None, until=None) -> list[NormalizedTrade]: ...

    # trading (later — guard with capabilities.can_trade; raise NotSupported otherwise)
    def place_order(self, connection_id: str, account_ref: str, order: OrderRequest) -> OrderResult: ...
```

Sources that don't link (CSV, manual) implement the lifecycle methods as no-ops/stubs and
declare it via capabilities. Trading exists in the contract from day one but stays dormant
behind `capabilities.can_trade` until Grow.

### Capabilities, not isinstance

Callers branch on advertised capabilities, never on the concrete class:

```python
@dataclass(frozen=True)
class ConnectorCapabilities:
    can_read_positions: bool
    can_read_transactions: bool
    can_trade: bool
    supports_realtime: bool
    supports_historical_backfill: bool
    requires_manual_refresh: bool
    data_freshness: str   # "realtime" | "daily" | "manual"
```

No `if isinstance(c, SnapTradeConnector)` anywhere. If you need to know "can this be traded?",
ask `connector.capabilities.can_trade`.

---

## Normalized types — the only vocabulary that crosses the boundary

Mirror the persisted model (client → account → strategy/sleeve → trades). Every adapter
translates the vendor payload *into* these; the original payload is retained in `raw` for
audit/debug only and must never be read by upstream code.

- `NormalizedTrade`: `external_id`, `symbol`, `action`, `quantity`, `price`, `currency`,
  `executed_at`, `commission`, `source`, `raw`.
- `NormalizedPosition`: `symbol`, `quantity`, `avg_cost`, `currency`, `market_price?`, `as_of?`.
- `RawAccount`: `external_ref`, `name`, `account_number?`, `institution`.

**`external_id` is the dedup key.** Every trade from every source carries a stable source id so
ingestion is idempotent — the same trade arriving via SnapTrade sync and a later CSV re-upload
must collapse to one. Never bypass dedup (repo-wide rule; doubly true here).

---

## Secrets & per-client tokens (read before adding SnapTrade)

- **App-level keys** (SnapTrade client id/secret, Webull keys): `.env` only, never committed,
  never logged. `.env.example` lists names with empty values.
- **Per-client connection tokens / OAuth secrets**: **encrypted at rest in the DB**, never in
  `.env`, never in logs, never in API responses. Treat them like passwords.
- Symbol normalization: trades may store exchange-prefixed tickers (`BATS:IGE`) while vendor
  price lookups want the bare symbol (`IGE`). Normalize at the connector boundary so upstream
  sees one consistent symbol convention.

---

## Adding a new connector — checklist

1. Implement `BrokerageConnector` in `connectors/<name>_connector.py`; declare honest
   `capabilities`.
2. Map vendor payloads to normalized types; stash the original in `raw`. No vendor type escapes.
3. Register it in `registry.py`.
4. Add a `Fake`-style or recorded-fixture test — no live network in the test suite.
5. If it adds endpoints (link/callback/connection mgmt), add them to root `openapi.yaml`.
6. Keep app-level keys in `.env`; per-client tokens encrypted in the DB.
7. Run `black` + `flake8` per repo conventions; keep routes thin, logic in services.

---

## Testing

`fake_connector.py` implements the Protocol with deterministic in-memory data so ingestion and
performance can be tested with zero network calls. For real adapters, use recorded fixtures
(sanitized real payloads), never live credentials in CI.
