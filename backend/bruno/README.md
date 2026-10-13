# PMS API — Bruno Collection

A full Bruno collection for the PMS backend. The folders are numbered so that
**"Run Collection"** executes a coherent happy-path flow and chains IDs automatically:

```
00 Auth      → sign in as an advisor              (session cookie kept for the run)
00 Health    → liveness
01 Clients   → create client                       (captures clientId)
02 Accounts  → create account                      (captures accountId)
03 Strategies→ create global strategy (strategyId), create sleeve (sleeveId),
               + sleeve performance/positions/trades
04 Trades    → add BUY/BUY/SELL trades into the sleeve  (captures tradeId)
05 Prices    → set + fetch market prices for the sleeve
06 Admin     → CSV import, sync logs, sync-config CRUD, sheet sync
```

A **Strategy** is a firm-wide definition; a **Sleeve** is that strategy run inside one
account. Trades, positions, prices and sync configs all hang off the **sleeve**.

## Run it

1. Start the stack: `cd backend && ./infra.sh up -d` (app on <http://localhost:8000>).
2. Open this folder (`backend/bruno`) in [Bruno](https://www.usebruno.com/).
3. Select your private environment (top-right) and set `advisorEmail` and
   `advisorPassword` in it. Use `environments/Local.private.bru`, which is git-ignored;
   `Local.bru` is committed and must keep those two blank.
4. Run **00 Auth / Login** first. Every route except Health, Root and sign-in needs a
   session; Bruno keeps the cookie Login returns and sends it on later requests.
5. Either run requests top-to-bottom, or use **Run Collection** for the whole flow
   (leave **00 Auth / Logout** out of it).

Or headless via the Bruno CLI:

```bash
npm install -g @usebruno/cli
cd backend/bruno
bru run --env Local.private
```

**Expected CLI result:** all requests pass except **06 Admin / Sync Daily (Sheets)**, which
returns `502` until you supply a real, accessible Google Sheet ID + credentials — it's
included for completeness. To run everything except that one:
`bru run --env Local.private --exclude "**/Sync Daily*"`.

## Calling the data sources directly

Two folders call a third party itself, not the Achalara backend, and need no Achalara
sign-in. Each signs its requests in a folder-level script and reads its keys from your
private environment:

- **07 SnapTrade (direct)**: accounts, balances, positions and activities as SnapTrade
  returns them.
- **07 Webull (direct)**: stock quotes and daily bars, plus the option quote, which answers
  403 until US options market data is enabled for the API keys. Set `webullAppKey` and
  `webullAppSecret` (from `backend/.env`).

## How chaining works

Each create request stores the returned `id` into a runtime variable via a
`vars:post-response` block (`clientId`, `accountId`, `strategyId`, `sleeveId`, `configId`).
Later requests reference them as `{{clientId}}`, etc. Re-running is safe — the client
email is randomized per run in a `script:pre-request` so you never hit
"Email already registered".

To send a request by itself against data that already exists, set `ClientId`, `AccountId`
and `sleeveId` in your private environment. `collection.bru` uses them whenever the
matching Create request has not been run. Sign-in does not supply them: an advisor is not
tied to a client, so `client_id` in the Login and Me responses is `null` for an advisor.

## Notes

- A `401` on any request means Login was not run in this session, or the session has
  expired (sessions last 7 days). Run **00 Auth / Login** again. There is no first
  advisor until one is created: `python -m app.cli create-advisor` (from `backend/`).

- `05 Prices / Fetch from Webull` will return `status: "partial"` with `fetched: 0`
  unless valid Webull credentials are configured in `.env` — that's expected; the
  request still returns 200.
- `06 Admin / Import Historical` runs in `mode=VALIDATE` (dry run) by default so it
  doesn't write trades. Change the `mode` query param to `IMPORT` to persist.
- `06 Admin / Sync Daily` needs a real Google Sheet ID + credentials; it's included
  for completeness and will error without them.
