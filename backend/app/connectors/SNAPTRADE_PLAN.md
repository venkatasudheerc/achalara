# SnapTrade Integration Plan (Bridge B3–B4)

Target: link a real **Vanguard** account and have its transactions flow through the existing
`IngestionService` pipeline into performance (MWR/TWR), with no manual CSV upload.

Grounded in SnapTrade's live docs (fetched 2026-10-03), not assumptions. Where the real API
differs from what our `BrokerageConnector` interface assumed, that's called out explicitly.

---

## 1. What the real SnapTrade API actually looks like

### Credentials: two different models

| Model | Credentials | Per-user registration |
|---|---|---|
| **Personal** | `clientId` + `consumerKey` only | None. Must **not** register users or store `userSecret`. |
| **Commercial** | `clientId` + `consumerKey`, plus per-user `userId` + `userSecret` | Required for each end user. |

**Decision point:** connecting *your own* Vanguard account to validate the integration is the
**Personal** flow — no user registration, no `userSecret` to store. Multi-client advisory use
(the actual product) is **Commercial**. The spike should use Personal; production uses Commercial.

### The linking flow (actual call sequence)

1. `POST /api/v1/snapTrade/registerUser` — body `{ userId }` (any string stable + unique to the
   user; we'd use our `Client.id` UUID). Returns `{ userId, userSecret }`.
   **`userSecret` cannot be retrieved later** — if lost, the user must re-register.
   *(Commercial only; skipped entirely in the Personal flow.)*
2. `POST` **Generate Connection Portal URL** (`loginSnapTradeUser`) — body includes `userId`,
   `userSecret`, and `connectionType: "read"` (vs `"trade-if-available"`). Optional
   `customRedirect` = where to send the user after they finish.
   Returns a `redirectURI` to SnapTrade's hosted Connection Portal. **The URL expires in 5 minutes.**
3. User opens that URL, picks Vanguard, does login + MFA, authorizes. Credentials go only to
   SnapTrade — never to us.
4. No callback exchange step. Once the portal flow completes, the connection and its accounts are
   simply *available* via the API. `customRedirect` just returns the user to our UI; the
   authoritative signal is the `CONNECTION_ADDED` webhook or polling `List user accounts`.

### Reading data

| Purpose | Endpoint |
|---|---|
| List connected accounts | `List user accounts` → each has an `accountId` (UUID) + `sync_status` |
| Positions | `List all account positions` (needs `accountId`) |
| Balances | `List account balances` |
| **Transactions** | `GET /accounts/{accountId}/activities` (`getAccountActivities`) |
| Connections (for repair/delete UI) | `listBrokerageAuthorizations` |

### `getAccountActivities` — the endpoint that feeds our trades

Query params: `startDate`, `endDate` (inclusive, date), `offset` (default 0), `limit`
(default **and max 1000**), `type` (comma-separated filter: `BUY,SELL,DIVIDEND,CONTRIBUTION,…`).
Response is paginated with `{ offset, limit, total }`; results in **reverse chronological** order
by `trade_date`.

Each `UniversalActivity`:

| Field | Type | Notes |
|---|---|---|
| `id` | UUID string | **Not stable** — "may change if reprocessed" ⚠️ see §3 |
| `symbol` | object \| null | null for non-security activity |
| `option_symbol` | object \| null | options only |
| `type` | string | `BUY`, `SELL`, `DIVIDEND`, `FEE`, `TRANSFER`, … |
| `units` | number | **Negative for SELL**, positive for BUY |
| `price` | number | per-share |
| `amount` | number \| null | signed: negative for BUY, positive for SELL |
| `fee` | number | → our `commission` |
| `currency` | object \| null | |
| `trade_date` | datetime \| null | granularity varies by brokerage; **can be null** |
| `settlement_date` | datetime | |
| `description` | string | |
| `external_reference_id` | string \| null | brokerage ref, groups related txns |

---

## 2. Data freshness — this changes our design

This is the biggest correction to earlier assumptions:

- **Transactions are cached, refreshed once per day, and delayed by one day. Intraday
  transactions are not available.** So there is no "live" trade feed to build against.
- Two plans: **Real-time** (holdings refreshed on request) vs **Daily** (holdings once/day).
- `sync_status` on each account reports the last successful sync *and the last date for which
  transactions are fully processed* — this, not our own clock, is the correct watermark.
- Rate limits are strict: Holdings **≤ 4 background calls per user per day**; the transactions
  endpoint wants **≥ 24h between calls per account**. Must handle `429` gracefully.
- Manual refresh exists (`Refresh connection`) on Daily plans and **may cost extra per call**.

**Implication:** our `ConnectorCapabilities` for SnapTrade should be honest about this —
`supports_realtime=False`, `data_freshness="daily"`. Polling on a user action ("Refresh now"
button) is the wrong default; webhooks + the daily scheduler are the right ones.

### Webhooks (worth doing in B4, not deferring to B5)

Configured in the SnapTrade Dashboard (webhook listener URL). Verify with the `Signature`
header: **HMAC SHA256 of the raw request body, keyed with our `consumerKey`**. Must respond
200/201/202/204 or SnapTrade retries with exponential backoff.

Events we care about:

| Event | Use |
|---|---|
| `CONNECTION_ADDED` | Link completed → discover accounts, create mapping |
| `ACCOUNT_TRANSACTIONS_INITIAL_UPDATE` | First historical backfill is ready → ingest |
| `ACCOUNT_TRANSACTIONS_UPDATED` | New transactions (daily) → incremental ingest |
| `ACCOUNT_HOLDINGS_UPDATED` | Positions/balances refreshed |
| `CONNECTION_BROKEN` | Must surface a re-connect prompt (required to launch) |
| `CONNECTION_DELETED` | User removed it → mark our row disconnected |
| `NEW_ACCOUNT_AVAILABLE` | New account under an existing connection |

Because transactions are daily-batch anyway, `ACCOUNT_TRANSACTIONS_UPDATED` **is** the natural
sync trigger. Building webhooks in B4 is less work than building a polling loop we'd then throw
away — I'd pull this forward from B5.

---

## 3. Dedup: the one real design problem

Our `IngestionService` dedups on a `(date, symbol, qty, price)` tuple
(`_trade_dedup_key`), and `NormalizedTrade.external_id` is documented as the idempotent key.

SnapTrade's activity `id` is explicitly **"may change if reprocessed"** — so it is *not* safe as
a dedup key. Using it would double-import a reprocessed trade.

**Proposed `external_id`:** derive a deterministic hash from immutable trade economics rather
than trusting SnapTrade's id:

```
snaptrade:{account_id}:{trade_date}:{symbol}:{units}:{price}
```

This matches how `csv_external_id()` already works, so behavior is consistent across sources, and
it survives reprocessing. Keep SnapTrade's `id` and `external_reference_id` in
`NormalizedTrade.raw` for audit.

**Open question for the spike:** does Vanguard-via-SnapTrade ever emit two genuinely distinct
fills with identical `(date, symbol, units, price)`? If yes, this key collapses them and we need
`external_reference_id` in the key. Must verify against real data — this is exactly what B3 is for.

### Other mapping decisions

- `units` is **negative for SELL** → take `abs(units)` for our `quantity`, and derive
  `action` from `type`, not from the sign.
- Only `type in (BUY, SELL)` becomes a `Trade`. `DIVIDEND`/`FEE`/`CONTRIBUTION`/`WITHDRAWAL`
  have no home in our `Trade` model today — **drop them in B4** and note the gap. (Dividends
  genuinely affect returns; that's a follow-up, not a blocker.)
- `trade_date` can be null → skip those rows with a logged validation error, rather than guessing
  from `settlement_date`.
- Symbol normalization: our trades store `BATS:IGE`-style prefixed tickers; SnapTrade returns a
  bare ticker. Resolve it in the connector. This intersects the existing open roadmap item about
  symbol normalization.

### Symbol shapes — resolved from the SDK's generated models

Confirmed by reading `snaptrade_client/model/*.pyi` (generated from SnapTrade's OpenAPI spec, so
authoritative). **Activities and positions nest symbols differently:**

| Context | Path to the ticker |
|---|---|
| Activity | `activity.symbol` → `SymbolNullable` → `.raw_symbol` / `.symbol` (flat strings) |
| Position | `position.symbol` → `PositionSymbol` → `.symbol` → `UniversalSymbol` → `.raw_symbol` / `.symbol` |

`raw_symbol` is the brokerage's own ticker; `symbol` may be SnapTrade's normalized form — prefer
`raw_symbol`. On `SymbolNullable` both are optional, so a fallback is needed.

`AccountUniversalActivity` field names are also confirmed exactly as designed above
(`units`, `price`, `amount`, `fee`, `trade_date` nullable, `currency`, `type`, `description`,
`external_reference_id`, `fx_rate`, `institution`, `option_symbol`, `currency_universal_symbol`).

`Position` additionally exposes `fractional_units` and `tax_lots` — relevant for Vanguard mutual
funds, and `tax_lots` is a potential input to the roadmap's tax-lot tracking item.

### Verified against a real Vanguard capture (2026-10-09, 8 accounts, ~12k activities)

- **History depth:** 2020-01 to 2023-10 depending on the account (`sync_status.transactions.first_transaction_date`).
  An account mid initial sync (`initial_sync_completed: false`) returns no activity at all while
  its holdings are already populated.
- **Types Vanguard emits:** `BUY`, `SELL`, `REI`, `DIVIDEND`, `INTEREST`, `INCOME`, `FEE`,
  `WITHHOLDING`, `CONTRIBUTION`, `DEPOSIT`, `WITHDRAWAL`, `WIRE OUT`, `SWEEP IN`/`SWEEP OUT`,
  `TRANSFER (INCOMING)`/`(OUTGOING)`, `SPLIT`, `CORP ACTION (MERGER)`, `CORP ACTION (CASH IN LIEU)`,
  `ASSIGNMENT`, `EXPIRED`, `INTEREST CHARGE`.
- **`REI` with units > 0 is a share purchase** (symbol + per-share price) → mapped as BUY.
  `REI` with 0 units is a Cash Plus sweep reinvestment → cash, skipped.
- **`trade_date` is date-only** (`05:00Z`, i.e. midnight US/Eastern).
- **~3% of BUY/SELL rows have a null `symbol`** (mostly delisted/acquired names; ticker only in
  `description`) → skipped with a warning.
- **Dedup collisions are real:** same-day buy+sell round trips at one price (key now includes
  action), and identical repeated fills with distinct ids (now get an occurrence suffix).
  `external_reference_id` is always null, so it cannot disambiguate.
- **Options appear** as OCC symbols (`BULL270115P00020000`) with per-share price and contract
  units; there is no ×100 multiplier applied. Open question.
- **Positions** live shape is `instrument` + per-unit `cost_basis`; `cost_basis` is missing for
  lots newer than the last transaction sync. Holdings reconcile to summed trades except for those
  lots (transactions lag holdings by several days).

---

## 4. Code changes

### New: `backend/app/connectors/snaptrade_connector.py`

Implements the existing `BrokerageConnector` Protocol — **no interface changes needed.** The
Protocol already has `initiate_link` / `complete_link` / `list_connections` /
`refresh_connection` / `remove_connection` / `fetch_accounts` / `fetch_positions` /
`fetch_transactions` / `place_order`, and the normalized types in `models.py` already include
`LinkSession`, `ConnectionResult`, `Connection`, `ConnectionStatus`. B1 anticipated this well.

```python
capabilities = ConnectorCapabilities(
    can_read_positions=True,
    can_read_transactions=True,
    can_trade=False,               # B6 only
    supports_realtime=False,       # transactions are daily + 1-day delayed
    supports_historical_backfill=True,
    requires_manual_refresh=False, # webhook-driven
    data_freshness="daily",
)
```

Two notes on fit:
- `complete_link(callback_payload)` has no real counterpart (there's no code exchange). Implement
  it as resolving/persisting the connection after the portal completes, or raise `NotSupported`
  and let the webhook handler own it. **Lean: webhook owns it**, keep `complete_link` as the
  thin "portal returned, go discover accounts" path.
- The SDK (`snaptrade-python-sdk` on PyPI) and `userSecret` handling stay sealed in this module,
  per the `CONNECTORS.md` one rule.

### New: DB table `brokerage_connections` (Alembic migration)

| Column | Type | Notes |
|---|---|---|
| `id` | `String(36)` | UUID |
| `client_id` | `String(36)` FK → `clients.id` | |
| `source` | `String` | `"snaptrade"` — generic for future aggregators |
| `external_user_id` | `String` | what we sent as SnapTrade `userId` |
| `external_connection_id` | `String` | SnapTrade connection/authorization id |
| `institution` | `String` | `"Vanguard"` |
| `status` | `String` | `active` / `broken` / `deleted` |
| `last_synced_at` | `DateTime(tz=True)` | |
| `transactions_synced_through` | `Date` | from `sync_status`; the real watermark for `startDate` |
| timestamps | | via `BaseModel` |

Plus on `accounts`: nullable `brokerage_connection_id` + `external_account_ref`, so an
`Account` can be backed by a live connection instead of being CSV-only.

**No secret column, and no encryption key — deliberately.** The Personal flow issues no
`userSecret`, so there is nothing to store. Adding key management before it protects anything
would introduce this design's only irreversible failure mode (lose the key → every client
re-links) for no benefit.

The Commercial flow changes that. When it is adopted, `user_secret_encrypted` (`Text`) and its
key arrive as one change: encrypt/decrypt only inside the connector module, and give
non-production environments their own throwaway key rather than skipping encryption there — a
crypto path that runs only in production fails first against real client secrets.

### New routes (thin; delegate to a `connections` service) + `openapi.yaml`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/clients/{client_id}/connections/snaptrade/link` | register (if needed) + portal URL. Note 5-min expiry in the response. |
| `GET` | `/api/v1/clients/{client_id}/connections` | list connections (any source) |
| `DELETE` | `/api/v1/connections/{connection_id}` | revoke + delete — **required by SnapTrade's launch checklist** |
| `POST` | `/api/v1/connections/{connection_id}/sync` | manual ingest; respects the ≥24h-per-account guidance |
| `POST` | `/api/v1/webhooks/snaptrade` | HMAC-verified event handler (see §2) |

Frontend (per `frontend/CLAUDE.md`): `src/api/endpoints/connections.ts` + `useConnections` hook,
"Link brokerage" action on the client detail page opening the portal URL, and a connection-repair
prompt when status is `broken`.

### Sync path — reuses B2 entirely

```
webhook ACCOUNT_TRANSACTIONS_UPDATED
  → verify HMAC
  → resolve brokerage_connections row
  → connector.fetch_transactions(account_ref, since=transactions_synced_through)
  → IngestionService.ingest_to_sleeve(trades, sleeve_id)   # dedups, persists, refreshes positions
  → update transactions_synced_through from sync_status
```

No new ingestion logic. Per `backend/CLAUDE.md`'s "sync logic must stay shared," the webhook
handler and the manual `/sync` route both call one shared function — same discipline as
`run_daily_sync()`.

---

## 5. Build order

**Pre-work (blocker):** rotate the exposed Webull secrets and confirm no `.env` is in git history.
`ROADMAP.md` already flags this — blast radius grows once SnapTrade keys and per-client secrets land.

**Step 1 — account + keys.** SnapTrade dashboard → Personal API key (`clientId`, `consumerKey`)
for the spike. Decide Personal vs Commercial for production (Commercial, for multi-client).

**Step 2 — B3 spike** (separate throwaway repo `achalara-bridge-spike`, per roadmap):
1. Personal-flow portal URL → link **your real Vanguard account**.
2. `List user accounts` → inspect `accountId`, `sync_status` shape.
3. `getAccountActivities` → **save real payloads as JSON fixtures.**
4. Answer the open questions: Does Vanguard return clean `BUY`/`SELL` with non-null `trade_date`?
   What does the `symbol` object look like, and does its ticker match our stored format?
   **Can two distinct fills share `(date, symbol, units, price)`?** (§3)
   How far back does history go?
5. Output = knowledge + fixtures. Delete the repo.

**Step 3 — B4 production** (this repo): Alembic migration → `snaptrade_connector.py` →
connections service + routes → webhook handler → `openapi.yaml` → frontend link/repair UI.
Tests use the spike's recorded fixtures; **no live network in CI** (mirrors how
`test_benchmarks.py` patches the Webull service).

**Step 4 — QA.** Link your Vanguard account end-to-end in the real app; confirm trades land in the
right sleeve and MWR/TWR reflect them. Compare against a CSV export of the same account as ground
truth — that's a dedup and correctness check our existing pipeline makes easy.

**Step 5 — launch checklist** (SnapTrade requires): 429 handling, connection-repair flow with user
notification, user-visible connection view + delete, compliance policy read.

**Deferred:** B6 trading — do not request trade scopes; `connectionType: "read"` only until Grow
is actually on the roadmap.

---

## 6. Decisions needed before coding

1. **Personal vs Commercial** for production. Commercial is the real answer for a multi-client
   advisory product, but it is what forces secret storage: a per-client `userSecret`, encrypted,
   unrecoverable if the key is lost. Personal (current choice) issues none, which is why no
   encryption key exists yet. Adopting Commercial means adding the column, the key, and a
   per-environment key policy together.
2. **Real-time vs Daily plan.** Daily is sufficient for performance tracking and cheaper;
   transactions are day-delayed on both, so Real-time only buys fresher *holdings*.
3. **Non-trade activity** (dividends, fees, contributions). Dropped in B4 — but dividends do
   affect real returns, so this is a known accuracy gap worth a follow-up.
4. **Webhooks in B4 vs B5.** Recommend pulling into B4: given daily batching, webhooks are the
   natural trigger and avoid building a throwaway polling loop.

## Sources

- https://docs.snaptrade.com/docs/getting-started
- https://docs.snaptrade.com/docs/launch-guide.md
- https://docs.snaptrade.com/docs/syncing
- https://docs.snaptrade.com/docs/webhooks
- https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getAccountActivities
- https://docs.snaptrade.com/reference/Authentication/Authentication_loginSnapTradeUser
- https://pypi.org/project/snaptrade-python-sdk/
