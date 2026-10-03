# Portfolio Management System — Roadmap

## Phase 0: Foundation Setup ✅ COMPLETE

- [x] Directory structure, Git repo, `.gitignore`
- [x] Docker Compose for PostgreSQL + Redis
- [x] SQLAlchemy ORM models (Client, Account, Sleeve, Strategy, Trade, Position, SyncLog)
- [x] Alembic migration framework
- [x] Pydantic v2 schemas
- [x] FastAPI app with CORS middleware

---

## Phase 1: Foundation Validation ✅ COMPLETE

- [x] PostgreSQL connection verified
- [x] Alembic migrations running (`alembic upgrade head`)
- [x] FastAPI server starts clean; `/health` and `/docs` respond
- [x] pytest suite passing (SQLite in-memory)

---

## Phase 2: Historical Data Import ✅ COMPLETE

- [x] CSV import pipeline with `VALIDATE`/`IMPORT` modes
- [x] Auto-routing by Account + Strategy columns (creates sleeves as needed)
- [x] Duplicate detection on `(date, symbol, qty, price)` per sleeve
- [x] SyncLog audit trail per import
- [x] `GET /api/v1/admin/sync-logs`

---

## Phase 3: Portfolio Calculations ✅ COMPLETE

- [x] Position tracking: quantity-matched round-trips, weighted-avg cost basis
- [x] Open positions with unrealized P&L (Webull price fetch)
- [x] Closed positions with realized gains
- [x] MWR (IRR solver) and TWR (geometric linking) at sleeve / account / client / strategy level
- [x] Monthly return breakdown endpoint

---

## Phase 4: Daily Sync Pipeline ✅ COMPLETE

- [x] Public Google Sheets sync via CSV export (no credentials needed)
- [x] Dedup on `google_sheet_row_id` (safe to re-run)
- [x] APScheduler daily sync job (configurable hour via `.env`)
- [x] SheetSyncConfig CRUD — register sheet → sleeve mappings
- [x] `POST /api/v1/admin/sync-daily` and scheduler both call shared `run_daily_sync()`

---

## Phase 5: Frontend Application

- [ ] Initialize React + TypeScript app (Vite)
- [ ] API client (Axios/Fetch with typed responses from `openapi.yaml`)
- [ ] Client dashboard — list clients, create client, client detail
- [ ] Account & sleeve management views
- [ ] Performance dashboard — MWR/TWR charts, date range selector, strategy comparison
- [ ] Positions table (open + closed) with P&L columns
- [ ] Trade history view + manual trade entry form
- [ ] Admin tools — CSV import form, sync logs viewer, sync-config management

**Deliverable:** Full-featured web application for portfolio management.

---

## Phase 6: Advanced Features (Ongoing)

- [ ] **Auth** — JWT login, role-based access control, API key management
- [ ] **Reporting** — PDF/Excel export, performance attribution, benchmark comparison, tax-lot tracking
- [ ] **Real-time** — WebSocket for live price updates and position changes
- [ ] **Data quality** — anomaly detection, account reconciliation, audit logging
- [ ] **Performance optimization** — Redis caching for computed metrics, materialized views

---

## Open Technical Items

- Rotate the Webull API secrets in `backend/.env` — they are live and should move to a secrets manager long-term.
- Decide symbol normalization: trades store `BATS:IGE`; Webull lookups strip to `IGE`. Optionally normalize on import.
- Tech debt: migrate Pydantic `class Config` → `model_config = ConfigDict(...)`.
- Replace Postgres-only `DISTINCT ON` in `twr_calculation.py` for portability.
- Exercise live Google Sheets sync end-to-end once a `SheetSyncConfig` is registered.

## Phase — Bridge (universal brokerage connectivity)

> Bridge brings trade/position data into Achalara from any source. Today that's CSV, Google
> Sheets, and Webull prices living in `app/services/`. This phase formalizes them behind one
> `BrokerageConnector` interface so any vendor (starting with SnapTrade) is a swappable adapter,
> and CSV/manual remain the permanent universal fallback.
>
> Strategy decided: **aggregator-first, not build-your-own** (per-broker integrations don't
> scale and "any broker in the world" can't be built solo). First adapter: **SnapTrade**
> (US-first, read + trade on one API, so it carries us from performance now to Grow later).
> Architecture guardrails live in `backend/app/connectors/CONNECTORS.md`.

### Pre-work (do first)

- [ ] **Rotate the exposed Webull secrets** and confirm no `.env` is in git history (repo is
      public). Blast radius only grows once SnapTrade keys + per-client tokens arrive.

### B1 — Formalize the interface ✅ COMPLETE

- [x] Add `app/connectors/` with `base.py` (`BrokerageConnector` + `ConnectorCapabilities`),
      `models.py` (normalized types), `registry.py`.
- [x] Add `fake_connector.py` for tests.
- [x] Write `app/connectors/CONNECTORS.md` (the "no vendor SDK escapes this layer" rule).

### B2 — Refactor existing sources behind the interface ✅ COMPLETE

- [x] `csv_connector.py` — existing CSV import, now producing `NormalizedTrade[]`.
- [x] `sheets_connector.py` — existing Google Sheets sync, same.
- [x] `webull_connector.py` — existing price fetch, normalized.
- [x] Extract the shared VALIDATE→IMPORT/dedup/route/persist path into
      `services/ingestion_service.py`; every source feeds it. Proves the abstraction against
      code we already trust.

### B3 — SnapTrade spike ~~(throwaway separate repo)~~ — SUPERSEDED

Original plan was a throwaway repo. Dropped after reading SnapTrade's live docs: the auth flow,
endpoints, `UniversalActivity` shape, daily-batch freshness model, rate limits and webhook events
are now documented in `app/connectors/SNAPTRADE_PLAN.md`, so the unknowns are narrow and
Vanguard-specific. B1/B2 also already derisked the abstraction, so the adapter is a contained
addition rather than a bet.

Replaced by: build the connector in this repo, exercise it against a real Vanguard account with a
throwaway script in the scratchpad, then sanitize those payloads into CI fixtures. Execution order
lives in `app/connectors/SNAPTRADE_BUILD_PLAN.md`.

### B4 — SnapTrade adapter (production, in main repo)

- [ ] `snaptrade_connector.py` implementing the interface: linking + read first.
- [ ] App-level keys in `.env`; per-client connection tokens **encrypted at rest in the DB**.
- [ ] Add link/callback/connection-management endpoints to root `openapi.yaml`.
- [ ] Recorded-fixture tests (no live network in CI).

### B5 — Real-time freshness

- [ ] Wire SnapTrade webhooks to trigger `ingestion_service.sync_connection`, so connected
      accounts stay current without manual refresh.

### B6 — Trading (deferred — enables Grow)

- [ ] Implement `place_order` on the SnapTrade adapter; flip `capabilities.can_trade`.
- [ ] Do not start until Grow is on the active roadmap.

### Definition of done (Bridge MVP = B1–B4)

A US client links a brokerage account via SnapTrade; transactions flow through the **same**
ingestion pipeline as CSV, dedup idempotently by `external_id`, and appear in performance
(MWR/TWR) with no manual upload — while CSV/Sheets remain available for any unsupported broker.
