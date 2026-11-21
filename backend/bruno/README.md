# PMS API — Bruno Collection

A Bruno collection for the backend. The folders are numbered so that **"Run Collection"**
runs one coherent flow and chains the ids it needs:

```
00 Auth       → sign in as staff (admin or advisor); the session cookie is kept for the run
00 Health     → liveness
01 Clients    → create a client                         (stores clientId)
02 Accounts   → create an account                       (stores accountId)
03 Strategies → create a strategy and a sleeve          (strategyId, sleeveId), + reads
04 Trades     → add BUY/BUY/SELL trades into the sleeve
05 Prices     → set and fetch market prices for the sleeve
06 Admin      → rebuild performance, system status, ticker-change proposals
07 Benchmarks → a benchmark's own performance
07 Plaid (direct)  → Plaid's sandbox itself: a throwaway login, accounts, holdings, transactions
07 Webull (direct) → Webull's market data, signed in a folder script
08 Plaid Linking   → a client linking accounts through Plaid, through the backend
09 Performance     → periods, statistics and the PDF report
10 Portal (Plaid accounts) → what the client sees over the accounts 08 linked
99 Sign out        → Logout, last so it cannot end the run early
```

A **Strategy** is a firm-wide definition; a **Sleeve** is that strategy run inside one
account. Trades, positions and prices hang off the **sleeve**.

## Run it

1. Start the stack: `cd backend && docker-compose up -d`, then the server on
   <http://localhost:8000>.
2. Open this folder (`backend/bruno`) in [Bruno](https://www.usebruno.com/).
3. Select your private environment and fill it in. Use `environments/Local.private.bru`,
   which is git-ignored; `Local.bru` is committed and **must keep every key and password
   blank**:

   | Variable | What | Needed for |
   |---|---|---|
   | `advisorEmail`, `advisorPassword` | a staff login (`python -m app.cli create-admin`) | everything |
   | `plaidClientId`, `plaidSecret` | Plaid's **sandbox** secret (`PLAID_SECRET_SANDBOX`) | the Plaid folders |
   | `plaidBaseUrl` | `https://sandbox.plaid.com` | the Plaid folders |
   | `webullAppKey`, `webullAppSecret` | from `backend/.env` | 07 Webull (direct) |
   | `ClientId`, `AccountId`, `sleeveId` | ids that already exist | a single request on its own |

4. Run **00 Auth / Login** first: every route except Health, Root and sign-in needs a
   session, and Bruno keeps the cookie Login returns.
5. Run requests top to bottom, or **Run Collection** for the whole flow.

Or headless with the Bruno CLI:

```bash
cd backend/bruno
bru run --env Local.private
```

**Expected result:** every request passes, and a request that needs a key you have not set
is **skipped**, not failed (the Webull and Plaid folders). A run with no keys at all is green.

## Plaid

Two folders cover Plaid, and the first is the way to see what Plaid sends before the
backend reads it.

- **07 Plaid (direct)** calls Plaid's sandbox itself with the `user_good` login at First
  Platypus Bank (checking, savings, CD, credit card, money market, IRA, 401(k), loans). It
  makes its own throwaway login and removes it at the end. Look at the holdings' securities:
  a fund with a name and no `ticker_symbol` is how Plaid sends a target-date trust or a 529
  portfolio, and a settlement fund arrives as a ticker-less mutual fund.
- **08 Plaid Linking** is a client linking accounts: availability, start, a sandbox public
  token (what Plaid Link's window would hand back), finish, found, confirm, connections,
  accounts, refresh, discover (all logins, one login) and repair. Plaid Link's window is the
  one step Bruno cannot do. **10 Portal (Plaid accounts)** then reads positions, home,
  overview, activity, trades, realised gains, performance, insights, record gaps and the
  holdings check over the accounts that were added. The portal routes are the client's own;
  staff see a client's portal with `?as_client={{clientId}}`, which these requests carry.

**Never point these at production.**

- The direct folder refuses any `plaidBaseUrl` that is not the sandbox.
- 08 and 10 go through the backend, which must itself run with `PLAID_ENV=sandbox` and the
  sandbox secret. Finish and Confirm add real rows, so run them against a **database you can
  throw away**, not your development data. One way: a second database in the same Postgres
  container, `alembic upgrade head` (and `alembic -n md upgrade head`) against it, and the
  server on another port with `DATABASE_URL`, `PLAID_ENV=sandbox`, `PLAID_SECRET` and
  `SCHEDULER_ENABLED=false` set for that process only.
- What Bruno cannot reach: a login that needs signing in again. Its access key is stored
  encrypted and never returned, so "Reset Login" in the direct folder resets only the
  direct folder's own login. The repair routes (Repair Start, Repaired) are run against a
  healthy login; the broken-login path is covered by the backend's own tests.

## Calling Webull directly

**07 Webull (direct)** calls Webull itself, with no Achalara sign-in, and signs its requests
in a folder-level script. The option quote answers 403 until US options market data is
enabled for the API keys. Without `webullAppKey` and `webullAppSecret` the folder is skipped.

## How chaining works

Each create request stores the id it gets into a runtime variable in a
`vars:post-response` block (`clientId`, `accountId`, `strategyId`, `sleeveId`), and later
requests use `{{clientId}}` and so on. **Variable names are case sensitive:** the runtime
ones are lower case, and `ClientId`, `AccountId` and `sleeveId` in the environment are only
fallbacks `collection.bru` copies in when the matching Create request has not run. The Plaid
folders store `plaidConnectionId`, `plaidChoices`, `plaidInvestedAccountId` and
`plaidCashAccountId` the same way.

Re-running is safe: the client email is randomised per run in a `script:pre-request`.

To send a request by itself against data that already exists, set `ClientId`, `AccountId`
and `sleeveId` in your private environment. Sign-in does not supply them: an advisor is not
tied to a client, so `client_id` in the Login and Me responses is `null` for staff.

## Notes

- A `401` on any request means Login was not run in this session, or the session has
  expired (sessions last 7 days). There is no first admin until one is created:
  `python -m app.cli create-admin` (from `backend/`).
- `05 Prices / Fetch from Webull` answers `status: "partial"` with `fetched: 0` unless valid
  Webull credentials are configured in `.env`; that is expected, and the request still
  returns 200.
- The SnapTrade folders and the old "Brokerage Connections" folder are gone: SnapTrade is
  retired and those routes no longer exist.
