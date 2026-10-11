# CLAUDE.md — Backend

This file provides guidance to Claude Code when working in `backend/`.
Read the root `../CLAUDE.md` first for shared context (project overview, Sleeve model, monorepo layout) and `./connectors/CONNECTORS.md` for universal brokerage connector guidance.

## Tech Stack

- **Framework:** FastAPI 0.104 (sync `def` handlers run in the threadpool)
- **ORM:** SQLAlchemy 2.0 with sync `Session` (never `AsyncSession`)
- **Migrations:** Alembic
- **Database:** PostgreSQL 15 (Docker); SQLite in-memory for tests (built via `create_all`)
- **Validation:** Pydantic v2
- **Scheduler:** APScheduler 3 (`BackgroundScheduler`), started/stopped in the lifespan hook; Redis 7 is the optional jobstore
- **Testing:** pytest + httpx `TestClient`
- **Linting:** Black, Flake8

UUID (`String(36)`) primary keys on all models. Timestamps are tz-aware via `BaseModel`.

## Commands

Run from the repo root (`Achalara/`). The venv lives at `backend/venv/`.

```bash
# Start infra (Postgres + Redis)
cd backend && docker-compose up -d

# Run the server (from backend/, with venv active)
uvicorn app.main:app --reload --port 8000      # Swagger UI at /docs

# Tests (offline by default — never hits a third-party API)
backend/venv/bin/pytest backend/tests -v
backend/venv/bin/pytest backend/tests --cov=backend/app          # with coverage
backend/venv/bin/pytest backend/tests/test_sleeves.py -v         # single file
backend/venv/bin/pytest backend/tests/test_performance.py::test_name -v   # single test

# Live API tests — opt-in only, read-only, need real credentials in .env
export SNAPTRADE_TEST_USER_ID=<the userId you linked>
backend/venv/bin/pytest backend/tests/integration -m live -v -s

# Migrations (run from backend/)
alembic upgrade head
alembic revision --autogenerate -m "description"

# Format / lint (from backend/)
black app/
flake8 app/
```

`backend/infra.sh` wraps common docker/db operations.

## Architecture

Request flow: **route → service → ORM model**. Routes are registered in `app/main.py`:

| Prefix               | Router                                                  |
| -------------------- | ------------------------------------------------------- |
| `/api/v1/clients`    | `clients`, `accounts`, `sleeves` (nested under clients) |
| `/api/v1/strategies` | `strategies` (firm-wide definitions)                    |
| `/api/v1/trades`     | `trades`                                                |
| `/api/v1/admin`      | `admin` (import, sync-daily, sync-logs, sync-configs)   |
| `/api/v1`            | `connections` (brokerage link, discover, map, sync, reconcile, webhook) |
| `/api/v1`            | `performance` (periods by grain, statistics, account report)            |

**Performance roll-ups** (`services/performance_service.py`): a level resolves to a _set of sleeve ids_, then one calc runs over the **merged** trade stream — returns are NOT averaged from child returns. Account = all sleeves in the account; Client = all sleeves under the client's accounts; Strategy = all sleeves for that strategy. Each response is `{ level, id, name, summary, timeseries, children }`.

### Key files

| File                                    | Purpose                                                                                 |
| --------------------------------------- | --------------------------------------------------------------------------------------- |
| `app/main.py`                           | App startup, router registration, lifespan (scheduler start/stop)                       |
| `app/config.py`                         | `Settings` reads `.env` (`database_url`, `redis_url`, `scheduler_enabled`, Webull keys) |
| `app/db/database.py`                    | Sync engine, `SessionLocal`, `get_db()` dependency                                      |
| `app/services/performance_service.py`   | Resolves sleeve sets and dispatches MWR/TWR calc                                        |
| `app/services/mwr_calculation.py`       | IRR solver (Money Weighted Return)                                                      |
| `app/services/twr_calculation.py`       | Geometric linking (Time Weighted Return)                                                |
| `app/services/portfolio_calculation.py` | Position tracking, weighted-avg cost basis, `persist_positions`                         |
| `app/services/trade_ingestion.py`       | Row validation + **duplicate detection** (intentional — do not skip)                    |
| `app/services/trade_import.py`          | CSV import pipeline (`import_type` param; `VALIDATE`/`IMPORT` modes)                    |
| `app/services/google_sheets_sync.py`    | Fetches public sheets via CSV export (no credentials)                                   |
| `app/services/daily_sync.py`            | Reusable sheet→DB sync (`run_daily_sync`, `run_all_enabled_syncs`)                      |
| `app/services/connection_service.py`    | Brokerage link/discover/map/reconcile + `sync_brokerage_account` (the one sync path)    |
| `app/models/perf.py`                    | The `perf` schema: daily valuation, holdings, prices, corporate actions                  |
| `app/services/performance_build_service.py` | Rebuilds reconstructed daily rows from trades, prices and cash; `dietz_factor`       |
| `app/services/daily_capture_service.py` | Captures the brokerage's holdings, cash and total as observed daily rows                 |
| `app/services/performance_stats_service.py` | Periods, account activity, drawdowns, risk — all read from daily rows                |
| `app/services/price_history_service.py` | Daily closes from Webull for held securities and benchmarks                             |
| `app/services/corporate_actions.py`     | Splits; `adjusted_trades` restates trades in today's shares on read                     |
| `app/services/report_service.py`        | The account performance report (HTML template → PDF)                                    |
| `app/services/cash_ledger.py`           | Cash balance on any date, worked back from the brokerage's reported balance             |
| `app/services/cash_activity_service.py` | Dividends/fees persistence + `income_flows` (which cash counts as returns)              |
| `app/services/trade_reassignment.py`    | Move a symbol's history between sleeves of one account                                  |
| `app/connectors/snaptrade_connector.py` | SnapTrade adapter: trades, cash activities, skipped-row tally                           |
| `app/services/scheduler.py`             | APScheduler lifecycle (`start_scheduler`, `stop_scheduler`)                             |
| `app/services/market_price.py`          | Position price updates / persistence                                                    |
| `app/services/webull_market_data.py`    | Webull API client                                                                       |
| `app/models/sleeve.py`                  | The account × strategy join that owns trades/positions/sync configs                     |
| `app/models/sync_log.py`                | Standalone import/sync audit trail (no FK to the hierarchy)                             |
| `tests/conftest.py`                     | Shared fixtures (DB session, `TestClient`)                                              |

## Coding Conventions

- **Routes are thin** — delegate all logic to a service; no business logic in handlers.
- **One service per domain.** Reuse existing services rather than duplicating logic.
- **Sync everywhere.** Plain `def` handlers + `Session`. Never add `async def` handlers that do blocking DB calls, and never mix in `AsyncSession`.
- **Pydantic schemas** live in `api/schemas/`; ORM models stay in `models/`.
- **Config via `.env`** through `config.py` — no hardcoded secrets/connection strings/API keys.
- **Schema changes go through Alembic** (`alembic revision --autogenerate`) — never edit tables directly.
- **Update `../openapi.yaml`** whenever an endpoint is added or its contract changes.

## Offline vs Live Tests

`pytest.ini` sets `addopts = -m "not live"`, so **the default run and CI never reach a
third-party API**. Tests that do are marked `@pytest.mark.live`, live in `tests/integration/`,
and additionally skip themselves unless real credentials are present — so they cannot run by
accident on a machine that lacks them.

- **Offline (default):** stub clients and recorded payloads. Deterministic, no network, no
  rate limit spent. Every mapping rule and dedup behavior is covered here.
- **Live (`-m live`):** answers only what offline tests cannot — what a real brokerage actually
  returns. Treated as exploratory, not regression cover: third-party payloads change outside
  our control, so asserting exact values there would make the suite flaky.

Live tests must stay **read-only**. Respect SnapTrade's limits (>=24h between transaction calls
per account, <=4 background holdings calls per user per day) — never loop them.

## Dedup Rules (don't bypass)

- **Sheet-sourced trades** dedup on `trades.google_sheet_row_id` (unique; NULL for CSV trades).
- **CSV imports** dedup on `(date, symbol, qty, price)` per sleeve in the import pipeline.
- Re-running a sync is safe — duplicates are skipped. The dedup in `trade_ingestion.py` is intentional.

## Sync Logic Must Stay Shared

The `admin/sync-daily` route and the scheduler job both call `run_daily_sync()` from `daily_sync.py`. Do not inline sync logic in routes or duplicate it in the scheduler.

## Performance: the `perf` schema

Performance over time lives in the Postgres schema `perf` (`app/models/perf.py`); new
performance tables go there, with `__table_args__ = (..., {"schema": "perf"})`. Read
`DATA_MODEL.md` § "The `perf` schema" before touching it. The rules that must hold:

- **The day is the only stored grain.** Do not add tables or columns for weeks, months,
  quarters, or client/strategy roll-ups. Derive them in `PerformanceStatsService` from
  `perf.daily_valuation`. Returns are chained through time and summed-then-computed across
  members, never averaged.
- **Observed days are fact.** `DailyCaptureService` records the brokerage's holdings, cash and
  total for the day (`basis = "observed"`). Nothing may overwrite an observed value; a rebuild
  refreshes only its flows, return and `is_provisional`.
- **Reconstructed days are disposable.** `PerformanceBuildService.rebuild_account` replaces
  them wholesale. After anything that changes trades, call
  `performance_build_service.rebuild_for_sleeves`.
- **Read trades through `corporate_actions.adjusted_trades`** in any calculation of positions,
  value or returns, so splits are applied. Never mutate a stored trade for a split.
- **Webull closes are adjusted** (splits and dividends). Never multiply a past adjusted close by
  a share count directly; value through the build service's trade-price anchoring.
- **One daily-return formula per basis:** `dietz_factor` at market, `realized_factor` at cost
  (both in `performance_build_service.py`). The realised basis is a way of *reading* the same
  rows (`daily_valuation.cost_value` in place of `securities_value`), never a second table.
- Existing performance endpoints read from the daily record when it exists and fall back to
  `TWRCalculationService.growth_at` / `MWRCalculationService.calculate_mwr` (from trades) when it
  does not. Keep both paths returning the same response shape.
- Account and client views include cash where a `CashLedger` exists; sleeve and strategy views
  are securities-only.
- No return is quoted when no money was ever invested (written options, shorts): `None`, not 0.

## Brokerage Sync Rules

- `sync_brokerage_account()` in `connection_service.py` is the only brokerage sync path. The
  `/brokerage-accounts/{id}/sync` route, the scheduler job and the webhook handler all call it.
- At most one transactions pull per account per 24h. The guard lives in the service; only a
  source-initiated webhook passes `force=True`. Never loop or retry on a 429.
- Brokerage sleeves use `accounting_method = "FIFO"`. Do not ingest brokerage trades into a
  `ROUND_TRIP` sleeve, and keep one trade source per sleeve.
- Sync dedups across **all sleeves of the account** (`dedup_sleeve_ids`), because symbols can
  be reassigned to other strategy sleeves after ingestion.
- Rows the connector cannot represent (splits, mergers) are skipped **and counted**
  — never dropped silently. Every fetched row, skipped or not, is stored verbatim in
  `brokerage_activities`; use `ConnectionService.rederive` to re-read them before spending
  another pull.
- A synced trade goes to the sleeve already holding its symbol, else the sleeve routed for its
  `security_type` (`brokerage_accounts.sleeve_routes`), else `default_sleeve_id`. Do not place
  one symbol in two sleeves of an account.

## What "Done" Looks Like

- Route returns real data, not a placeholder or empty list
- A corresponding test exists and passes (`backend/venv/bin/pytest backend/tests`)
- Edge cases handled in the service layer (empty results, zero positions, etc.)
- No TODO/FIXME comments remain
- Any schema change has an Alembic migration, `DATA_MODEL.md` is updated, and `../openapi.yaml` is updated
