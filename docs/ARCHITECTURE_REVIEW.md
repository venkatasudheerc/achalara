# Architecture review (2026-10-11)

## Context

A review of the project's architecture as of 2026-10-11. It is an assessment, not an
implementation plan. It is based on the code on branch `bridge/snaptrade-integration` (then 33
commits ahead of `main`), the dev database, and facts measured during the review. Each finding says what it is, the evidence,
why it matters, and what I would do. A suggested order of work is at the end.

Size for reference: backend ~12,000 lines of application code and ~6,000 of tests (278 passing);
frontend ~5,300 lines; 62 API operations; 13 tables across `public` and `perf`.

## What is sound and should be kept

1. **The domain hierarchy.** `Client → Account → Sleeve ← Strategy` is consistent across models,
   routes and the frontend's scope. Every roll-up resolves to a set of sleeves or accounts.
2. **The connector seam.** `connectors/base.py` + normalized types keep SnapTrade's SDK and
   payload shapes inside one module. Nothing upstream imports the vendor.
3. **One ingestion pipeline** (`ingestion_service.py`) with database-enforced idempotency
   (`UNIQUE(sleeve_id, external_id)`), used by CSV, Sheets and the brokerage.
4. **Raw source rows are kept** (`brokerage_activities`). This already paid for itself three
   times: options, ticker-less trades and cash history were all added without a new pull.
5. **`perf` schema with one stored grain.** Day-level rows, everything else derived; observed
   versus reconstructed is explicit on every row.
6. **The API contract is honest.** All 62 implemented operations are in `openapi.yaml` and vice
   versa (checked mechanically during this review).
7. **Migrations are exercised** up, down and up against a throwaway Postgres before touching the
   dev database.
8. **Documentation is unusually good** (`DATA_MODEL.md`, both `CLAUDE.md` files).

## Findings, most serious first

### 1. There is no authentication or authorization — blocker for any real client data
- **Evidence.** No route has an auth dependency. `POST /clients/login` checks one shared dev
  password and returns the client record; it issues no token and nothing checks one afterwards.
  Every endpoint, including `DELETE /connections/{id}`, `POST …/sync`, `POST /admin/*` and the
  PDF report, is open to anyone who can reach the port. A `client_id` in a path is never checked
  against a caller.
- **Why it matters.** The database now holds real brokerage data for real people (holdings,
  cash, account numbers), and the repository is public.
- **Do.** Add an advisor login (session or JWT) as a FastAPI dependency on every router; add an
  ownership check helper used by all `client_id` routes; gate `/admin` separately; make the report
  download an authenticated request. Decide early whether clients ever log in themselves, because
  that changes the authorization model from "advisor sees all" to per-client scoping.

### 2. The brokerage link is single-tenant by construction
- **Evidence.** One SnapTrade Personal key and one `SNAPTRADE_USER_ID` in settings.
  `ConnectionService.discover(client_id)` assigns *every* login on that key to whichever client
  ran discovery. Several people's accounts sit under one login owned by one of them.
- **Why it matters.** A second advisor client with their own brokerage login cannot be
  represented. Moving to SnapTrade's Commercial key means a per-client `userSecret` that is
  unrecoverable if lost, so it needs encrypted storage and a key-management decision.
- **Do.** Treat this as the gate between "tool for one household" and "product". Store
  `external_user_id` (already a column) per client, add the encrypted secret, and stop reading
  the user id from settings.

### 3. Two return engines coexist and can disagree
- **Evidence.** `PerformanceService.performance` reads `perf.daily_valuation` when rows exist
  (Modified Dietz, mid-day) and otherwise falls back to `TWRCalculationService.growth_at` /
  `MWRCalculationService` computed from trades (a different flow-timing rule, last-trade prices).
  `weekly_snapshot_service.py` and `monthly_returns` each carry both paths. Which numbers a
  client sees depends on whether a rebuild happened. Services also call each other's private
  methods to bridge the two (`stats._twr`, `stats._mwr`, `MWRCalculationService._solve_irr`).
- **Why it matters.** This is the highest-risk area for silent wrong numbers, and it roughly
  doubles the code that must be kept correct.
- **Do.** Make the daily record the only source: build rows for every account on every trade
  change (already wired), delete the from-trades fallback and `twr_calculation.py`'s walker,
  promote `_twr` / `_mwr` / `_solve_irr` to a public returns module, and rename
  `weekly_snapshot_service.py` (it no longer snapshots anything).

### 4. Valuation correctness rests on several heuristics that are not visible to a reader of the numbers
- **Evidence.** (a) Options have no price history; a liability shows only when traded, and the
  first observed day's step is now set aside as a "valuation adjustment", which can move a
  year-to-date return by several percentage points. (b) Past holdings are valued by anchoring adjusted Webull
  closes to trade prices, with a special case for option assignments. (c) Mergers are skipped;
  a position acquired for cash never closes. (d) `ROUND_TRIP` and `FIFO` sleeves use different
  lot matching, but `daily_valuation.cost_value` always uses FIFO. (e) The `realized` basis and
  `cost_value` were built and then left unused.
- **Why it matters.** Each is defensible alone; together they mean a reported return depends
  on rules a reviewer cannot see from the output. The seam adjustment in particular makes
  returns and total value tell different stories.
- **Do.** Decide the seam treatment deliberately (my recommendation stands: include it).
  **Decided 2026-10-11:** the step is counted as a return on the first recorded day; the
  separate adjustment is removed (see `backend/DATA_MODEL.md`).
  Add a reconciliation report per account that states, in dollars, how much of current value is
  unpriced, adjusted, or provisional. Either retire `ROUND_TRIP` for brokerage-era data or make
  cost consistent. Remove the unused realised basis or put it on a screen.

### 5. Long work runs inside web requests, and the scheduler lives in the web process
- **Evidence.** A full-history sync took 99 seconds inside the request thread. Every
  `POST /trades` triggers a full account rebuild (≈3 s for one account today). APScheduler starts
  in the FastAPI lifespan, so two workers means every job runs twice, and under `--reload` the
  catch-up capture check fires on every restart. Redis is in docker-compose and unused. There is
  no job lock and no record of job runs beyond logs.
- **Why it matters.** The daily capture is now the system's most valuable job: a missed day
  cannot be recaptured. It currently depends on a laptop dev server.
- **Do.** Move sync, capture, price backfill and rebuild to a worker (the Redis already
  provisioned is enough with RQ or APScheduler's Redis jobstore plus a lock). Return 202 with a
  job id from sync endpoints. Record every job run in a table (start, end, outcome, counts) so a
  missed capture is visible. Then host it.

### 6. Layering has eroded in the route and service layers
- **Evidence.** Routes contain 55 inline `db.query` calls and 9 inline Pydantic schemas, against
  the project's own "routes are thin" rule. 23 of 60 operations have no `response_model`, so the
  contract is enforced only by hand. `connection_service.py` is 962 lines covering linking,
  mapping, sync, reconciliation and webhooks; `snaptrade_connector.py` is 1,094. There are 46
  `except Exception` handlers, several of which log and continue.
- **Do.** Split `connection_service` into link/mapping, sync, and reconciliation. Move route
  queries into services. Add `response_model` everywhere and generate the frontend types from
  the spec (below). Narrow the broad handlers to the failures actually expected.

### 7. Database: missing indexes, derived data stored as if primary, and floats in money paths
- **Evidence.** `trades` has no index on `sleeve_id` or `trade_date`; `positions` none on
  `sleeve_id`; `cash_activities` none on `sleeve_id`; `brokerage_activities` none on
  `activity_date`; `daily_holding.sleeve_id` none. Fine at 7,000 trades, not at 8 accounts × years.
  `positions` is derived from trades yet also carries `current_price`, which is wiped whenever
  positions are re-persisted. Statistics convert `Decimal` to `float` for chaining and IRR.
  Rebuild deletes and re-inserts an account's entire history on every sync.
  `accounts.name` stores the full brokerage account number (masked only when printed).
- **Do.** Add the indexes in one migration. Move current prices to `perf.daily_price` and make
  `positions` either a pure cache or a view. Make rebuilds incremental from the earliest changed
  date (the design already allows it). Strip account numbers at ingestion.

### 8. Frontend: the typed contract is hand-maintained, and there is no safety net
- **Evidence.** `src/api/types.ts` is 280 hand-written lines duplicating `openapi.yaml`, while
  `npm run gen:api` exists and is not used. No tests. `npm run lint` fails because eslint is not
  installed. Several mutations call `qc.invalidateQueries()` with no key, refetching everything.
  Page components run 350–450 lines. The performance page loads a 927-point series per view and
  recomputes the benchmark in the browser. The report download is a bare link.
- **Do.** Generate types from the spec and delete the hand-written file. Install eslint and add
  a small set of component tests around the performance page before its redesign. Scope query
  invalidation. Move the benchmark-with-deposits calculation to the server (the periods endpoint
  already returns benchmark returns).

### 9. Delivery and operations
- **Evidence.** No CI. No Dockerfile or deployment for the app. 33 commits (the whole brokerage
  and performance system) sit unpushed on one local branch; `main` predates all of it. Database
  backups exist only as dumps in a session's temp folder. Three dependencies are unpinned and
  PDF rendering needs a system library installed by hand. Tests run on SQLite while production
  is Postgres with a second schema, JSON columns and `FILTER` aggregates.
- **Do.** Push the branch and open a PR now (bus risk). Add CI running pytest, `npm run build`
  and the openapi-versus-routes check used in this review. Run the suite against Postgres in CI.
  Add a Dockerfile, scheduled `pg_dump`, and pin the three packages.
- **Status.** The branch is pushed with a pull request open; CI (`.github/workflows/ci.yml`) runs
  the tests, the contract test, the migrations on Postgres and the frontend build; the packages
  are pinned. Still open: running the suite itself on Postgres, a Dockerfile, scheduled backups.

### 10. A modelling tension worth a decision
Sleeves were defined as "a strategy as run in an account". The current data uses them as asset
classes (ETFs, Stocks, Options, Other), assigned automatically by security type. Both are
legitimate, but they are different ideas: strategy roll-ups across clients now mean "all ETFs",
cash belongs to no sleeve so children never sum to the account, and three of four sleeves cannot
show a time-weighted return. Decide whether sleeves are *strategies* (assigned by intent) or
*asset classes* (assigned by type), and if you need both, add asset class as an attribute of a
holding instead of overloading the sleeve.

## Suggested order

| Order | Work | Why first |
|---|---|---|
| 1 | Push the branch, open a PR, add CI | Protects three weeks of work; cheap |
| 2 | Authentication and authorization | Real personal financial data is exposed |
| 3 | Single return engine; settle the seam treatment | Removes the main source of wrong numbers |
| 4 | Worker + job log, then host the backend | Daily capture cannot be recovered when missed |
| 5 | Indexes, incremental rebuild, positions cleanup | Needed before more accounts are loaded |
| 6 | Generated frontend types, lint, tests | Do before the planned performance-page redesign |
| 7 | Multi-tenant SnapTrade (Commercial key) | Only when a second advisor client is real |
| 8 | Split oversized services; thin the routes | Ongoing, alongside the above |

## How to verify this review

- Routes versus spec: load `app.main.app`, compare `(path, method)` pairs with `openapi.yaml`.
- Auth: `grep -rn "Depends(" backend/app/api/routes` shows only `get_db`.
- Indexes: `select tablename, indexname from pg_indexes where schemaname in ('public','perf')`.
- Fallback path: `PerformanceService.performance` → `_from_daily_rows` returning `None`.
- Scheduler: `backend/app/services/scheduler.py`, started from `app/main.py` lifespan.
