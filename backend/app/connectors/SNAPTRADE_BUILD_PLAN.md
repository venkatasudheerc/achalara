# SnapTrade — Build Plan (main repo, no separate spike)

Companion to `SNAPTRADE_PLAN.md` (which holds the API research and design decisions).
This file is the **execution order**: what gets built, in what sequence, and how each step is
verified before the next one starts.

Decision made: build directly in this repo. B1/B2 already derisked the abstraction, so a
SnapTrade adapter is a contained addition, not a bet. The spike's *learning* still happens —
via a throwaway script in the scratchpad — but the code we write is code we keep.

---

## Step 0 — Housekeeping (before any SnapTrade code)

**0a. Commit the B1/B2 work.** It's currently 10 uncommitted files (connectors package,
`ingestion_service.py`, route refactors, `test_connectors.py`) with 116 tests passing. SnapTrade
builds directly on this. Committing first means a clean diff and a safe rollback point.

**0b. Rotate the exposed Webull secrets.** `ROADMAP.md` flags this as a pre-work blocker, and it
gets worse once SnapTrade keys land: this repo is public. Confirm no `.env` is in git history.
→ *This is yours to do; I can help verify git history is clean.*

**0c. Get SnapTrade Personal API keys.** From the SnapTrade dashboard: `clientId` + `consumerKey`.
Personal flow (not Commercial) for now — your own Vanguard login, no per-user `userSecret` to
store. Nothing in steps 2+ runs without these.
→ *Yours. Put them in `backend/.env`, never in chat.*

**Verify:** `git log` shows the B1/B2 commit; `backend/.env` has the two SnapTrade keys;
`pytest backend/tests` still green.

---

## Step 1 — Dependencies + config

- Add to `backend/requirements.txt`: `snaptrade-python-sdk`, and `cryptography` (for Fernet
  token encryption — not currently a dependency).
- Extend `app/config.py` `Settings` with `snaptrade_client_id`, `snaptrade_consumer_key`,
  `connection_encryption_key` (all defaulting to `""`, matching the existing `webull_app_key`
  pattern).
- Update `backend/.env.example`.

**Verify:** `python -c "from app.config import settings; print(bool(settings.snaptrade_client_id))"`
prints `True`. No secrets committed.

---

## Step 2 — `snaptrade_connector.py` (read-only)

The core deliverable. Implements the existing `BrokerageConnector` Protocol — **no interface
changes needed**, B1 already has `LinkSession` / `ConnectionResult` / `Connection` /
`ConnectionStatus` in `models.py`.

Scope for this step:
- `is_configured()` — credential check, mirroring `WebullConnector`
- `initiate_link(client_id, redirect_uri)` → `LinkSession` (portal URL; note the **5-minute
  expiry** in the returned session)
- `fetch_accounts(connection_id)` → `list[RawAccount]` — your several Vanguard accounts
- `fetch_positions(connection_id, account_ref)` → `list[NormalizedPosition]`
- `fetch_transactions(connection_id, account_ref, since, until)` → `list[NormalizedTrade]`,
  handling pagination (`offset`/`limit`, max 1000) and reverse-chronological ordering
- `place_order(...)` → `raise NotSupported` (B6 only)
- `capabilities`: `can_trade=False`, `supports_realtime=False`, `data_freshness="daily"`

Mapping rules (from `SNAPTRADE_PLAN.md` §3), all sealed in this module:
- only `type in (BUY, SELL)` becomes a `NormalizedTrade`; other activity types are skipped
- `abs(units)` for quantity; action derived from `type`, **never** from the sign of `units`
- `fee` → `commission`
- null `trade_date` → skip with a logged validation error
- `external_id` = `snaptrade:{account_id}:{trade_date}:{symbol}:{units}:{price}` — deterministic,
  **not** SnapTrade's `id` (which "may change if reprocessed")
- raw payload retained in `NormalizedTrade.raw` for audit

**Verify:** unit tests with hand-written fake payloads (no network) covering BUY/SELL mapping,
negative units, null `trade_date`, non-trade types skipped, pagination, and `external_id`
stability. `pytest backend/tests/test_connectors.py` green.

---

## Step 3 — Throwaway script + link your Vanguard account

A script in the **scratchpad** (not `app/`, not committed) that:
1. calls `initiate_link()` and prints the portal URL
2. **you** open it, pick Vanguard, log in + MFA → that's the part I can't do
3. calls `fetch_accounts()` and dumps raw JSON
4. calls `fetch_transactions()` per account and dumps raw JSON

**This is where the spike's learning happens.** Open questions to answer against real data:
- Does Vanguard return non-null `trade_date` and clean `BUY`/`SELL` types?
- What does the `symbol` object look like — does its ticker match our stored `BATS:IGE` format?
- **Can two distinct fills collide on `(date, symbol, units, price)`?** If yes, `external_id`
  needs `external_reference_id` mixed in.
- How far back does history go?
- With several accounts under one login, how do per-account rate limits actually behave?

**Verify:** raw payloads on disk; the four questions above answered; connector mapping corrected
if real data contradicts the assumptions.

---

## Step 4 — Sanitized fixtures + offline tests

- Create `backend/tests/fixtures/` (doesn't exist yet).
- Sanitize the Step 3 payloads: scrub account numbers, real balances, identifying details —
  keep the *shape* and the edge cases.
- Rewrite Step 2's tests against these real-shaped fixtures.
- **No live network in CI** — same discipline as `test_benchmarks.py` patching the Webull service.

**Verify:** `pytest backend/tests` green with zero network calls. Fixtures contain no real
account numbers or holdings.

---

## Step 5 — Persistence

- Model `app/models/brokerage_connection.py` per `SNAPTRADE_PLAN.md` §4, including
  `transactions_synced_through` (the watermark from SnapTrade's `sync_status`, which is
  authoritative — not our own clock).
- Nullable `brokerage_connection_id` + `external_account_ref` on `accounts`, so an `Account` can
  be backed by a live connection instead of being CSV-only.
- Alembic migration (`alembic revision --autogenerate`).
- Fernet encrypt/decrypt for the secret column, used **only** inside the connector module.
- Update `backend/DATA_MODEL.md`.

**Verify:** `alembic upgrade head` clean on Postgres; `alembic downgrade -1` also clean;
tests still green (SQLite `create_all` picks up the new model).

---

## Step 6 — Service + routes

- `app/services/connection_service.py` — link, list, remove, and **one shared sync function**
  (`backend/CLAUDE.md`: "sync logic must stay shared" — the webhook handler and the manual
  `/sync` route must both call it, never inline it).
- Thin routes per `SNAPTRADE_PLAN.md` §4: link, list, delete, sync.
- Account-mapping endpoint: with several Vanguard accounts arriving at once, choosing which
  SnapTrade `accountId` maps to which Achalara `Account` — and which to ignore — is real work,
  not an afterthought.
- Update root `openapi.yaml`.

**Verify:** `TestClient` tests for each route; `openapi.yaml` matches the implemented routes;
trades from a fixture flow end-to-end into a sleeve and show up in MWR/TWR.

---

## Step 7 — Webhooks

Pulled forward from B5, because transactions are daily-batch anyway: webhooks are the natural
trigger, and a polling loop would be throwaway work.

- `POST /api/v1/webhooks/snaptrade`
- **HMAC SHA256 verification of the raw body, keyed with `consumerKey`**, before the payload is
  trusted at all. Treat an unverified body as attacker-controlled.
- Handle: `CONNECTION_ADDED`, `ACCOUNT_TRANSACTIONS_INITIAL_UPDATE`,
  `ACCOUNT_TRANSACTIONS_UPDATED`, `ACCOUNT_HOLDINGS_UPDATED`, `CONNECTION_BROKEN`,
  `CONNECTION_DELETED`, `NEW_ACCOUNT_AVAILABLE`.
- Must return 200/201/202/204 or SnapTrade retries with exponential backoff.
- Calls the same shared sync function from Step 6.

**Verify:** tests for valid signature, **invalid signature rejected**, and each event type;
a replayed webhook is idempotent (no duplicate trades).

---

## Step 8 — Frontend

Per `frontend/CLAUDE.md`: `src/api/endpoints/connections.ts` + `useConnections` hook,
"Link brokerage" action on the client detail page, account-mapping UI, and a repair prompt when
status is `broken` (**required by SnapTrade's launch checklist**).

**Verify:** link flow works in the browser against your real Vanguard account; `npm run build`
clean; skeleton/error/empty states present per the repo's "done" definition.

---

## Step 9 — Launch checklist

SnapTrade requires before production: 429 handling, connection-repair flow with user
notification, user-visible connection list + delete, compliance policy read. Rate limits to
respect: holdings ≤4 background calls/user/day; transactions ≥24h between calls per account.

---

## Open decisions (don't block Steps 0–4)

1. **Personal → Commercial migration.** Personal is right now (your own Vanguard login, multiple
   accounts inside it is normal and supported). Multi-client production needs Commercial, which
   means storing per-client `userSecret` encrypted and **unrecoverable if lost**. Step 5's schema
   accommodates both; the switch is a config + registration change.
2. **Real-time vs Daily plan.** Transactions are day-delayed on both, so Real-time only buys
   fresher *holdings*. Daily is likely sufficient and cheaper.
3. **Non-trade activity** (dividends, fees, contributions) is dropped in Step 2. Dividends do
   affect real returns — a known accuracy gap, worth a follow-up, not a blocker.

---

## Suggested stopping points

- **After Step 2:** a tested connector with no credentials needed. Pure code progress.
- **After Step 4:** the integration is *proven* against your real Vanguard data, with offline
  tests. This is the highest-value checkpoint — everything after is plumbing.
- **After Step 6:** usable via the API.
- **After Step 8:** usable in the product.

I'd suggest reviewing at Step 2 and again at Step 4.
