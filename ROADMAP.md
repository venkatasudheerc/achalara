# Achalara — Roadmap

What is built, what comes next, and what is deliberately deferred. Detailed rules live in the
`CLAUDE.md` files; this page is the overview.

## Built

- **Hierarchy and trades.** Clients, accounts, firm-wide strategies and sleeves. Trades from CSV,
  public Google Sheets and brokerages, with duplicate detection on every path.
- **Brokerage connections (Bridge).** One connector interface (`app/connectors/`) with SnapTrade
  as the first adapter: linking, discovery, mapping, a daily sync at 8 AM US Eastern and a signed
  webhook. Splits, mergers and assigned or expired options are read from the brokerage's rows.
  A symbol's history can be moved between sleeves of one account.
- **Performance.** Money- and time-weighted returns at sleeve, account, client and strategy
  level, from a daily record (`perf` schema) of observed and rebuilt days. Periods by day, week,
  month and quarter, risk figures, benchmarks, and the account PDF report.
- **Realised gains.** Lot matching by FIFO or MinTax, following the brokerage's reading: wash
  sales, the 60/40 split and year-end mark of index options.
- **Sign-in.** Advisor and client roles, invite and reset links (emailed when mail is set up),
  shared accounts, and a public invitation form.
- **The new app (`/home`), where a client lands.** The first part of the 2026-11 redesign, built on
  the data already held: an account list grouped by person, by kind of account or by the client's
  own groups, and tabs that show any view for what is chosen (Dashboard, Accounts, Holdings at live
  prices, Transactions, Performance, Cost basis, Income, Analysis); Research (Market patterns);
  light, dark or the device's own setting. It replaced the old client portal, whose addresses
  redirect to it. The advisor workspace (`/app`) is unchanged and reached from it as "Manage".
- **Operations.** Deployment to one server (`deploy/`), backups, System status with alerts.
- **Market data (`md` schema).** Securities, daily index membership (S&P 500, Russell
  1000/2000/3000), identifiers, sectors and industries, in its own worker and migration history.
  A data model that can hold any market; every feed is American. A Market data page shows its state.

## Next

- **The household.** Households above clients, accounts of every kind (bank, card, loan,
  property) with balances entered by hand, then linked through Plaid; money in and out; nudges.
  Plan and Tax, shown as "coming soon" in the new app, follow.
- Deploy market data so its daily collection starts; then sectors on the Holdings page, daily
  prices for index members and chosen funds, and fundamentals.
- Register the SnapTrade webhook on the public host and confirm a real delivery.

## Deferred

- **Portfolio, Risk and Grow** screens show "coming soon" and have no backend.
- **Trading** through SnapTrade (`place_order`) waits until Grow is on the active roadmap.
- **Markets outside the US**: the model is ready; which markets and sources is decided later.

## Technical debt

- Pydantic `class Config` in the schemas should become `model_config = ConfigDict(...)`.
- Trade tables load a capped page and sort it in the browser: the sleeve Trades tab shows the 1,000
  most recent trades and the client page the 100 most recent, so a larger sleeve is shown
  incompletely. Needs server-side sort and paging on the trades endpoints and in `DataTable`.
