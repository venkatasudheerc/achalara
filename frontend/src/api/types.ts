// Hand-typed from openapi.yaml — regenerate with `npm run gen:api` once backend is running

export type TradeAction = 'BUY' | 'SELL'

export type UserRole = 'advisor' | 'client'
export interface LoginRequest { email: string; password: string }
/** An account a client user may view; never carries a full account number */
export interface VisibleAccount {
  id: string
  /** The owner, which is not the viewer when `shared` */
  client_id: string
  name: string; number_last4: string | null; shared: boolean
}
export interface MeResponse {
  id: string; email: string; name: string; role: UserRole
  client_id: string | null
  /** Empty for an advisor, who sees every account */
  accounts: VisibleAccount[]
}
export interface UserResponse {
  id: string; email: string; name: string; role: UserRole
  client_id: string | null; is_active: boolean
  /** False until the person has accepted their invite */
  has_password: boolean
  last_login_at: string | null
}
export interface LinkResponse {
  /** Shown once; only a digest is stored */
  token: string
  /** Frontend route that accepts the link */
  path: string
  purpose: 'invite' | 'reset'; email: string; expires_at: string
}
export interface LinkPreview {
  purpose: 'invite' | 'reset'; email: string; name: string
  accounts: VisibleAccount[]
}
export interface AccountAccessResponse {
  client_id: string; account_id: string; account_name: string
  owner_client_id: string; owner_name: string
}
export interface ClientCreate { name: string; email: string }
export interface ClientResponse {
  id: string; name: string; email: string
  created_at: string; updated_at: string
}

export interface AccountCreate { name: string; description?: string; account_number?: string | null }
/** Which lots a sale closes first, as set at the brokerage */
export type CostBasisMethod = 'FIFO' | 'MIN_TAX'
export interface AccountResponse {
  id: string; client_id: string; name: string
  description: string; account_number: string | null
  cost_basis_method: CostBasisMethod
  /** True for an account another client owns that this client may view; client_id is always the owner */
  shared: boolean; owner_name: string | null
}

export interface SleeveCreate { strategy_id: string }
export interface SleeveResponse {
  id: string; account_id: string; strategy_id: string; strategy_name: string | null
}

export interface StrategyCreate { name: string; description?: string }
export interface StrategyResponse { id: string; name: string; description: string | null }

export interface TradeCreate {
  sleeve_id: string; trade_date: string; symbol: string
  action: TradeAction; quantity: number; price: number
  commission?: number; notes?: string
}
export interface TradeResponse extends TradeCreate { id: string; created_at: string }
export interface TradeSummary {
  id: string; sleeve_id: string; trade_date: string; symbol: string
  action: TradeAction; quantity: number; price: number
  commission: number; notes: string
  /** ETF, STOCK, ADR… as the source reported it; null for CSV/Sheets/manual trades */
  security_type?: string | null
}

export interface PerformanceSummary {
  mwr_pct: number | null; twr_pct: number | null; twr_note: string | null
  total_return_pct: number | null
  total_cost_basis: number; total_market_value: number; total_unrealized_gain: number
  /** Cash held now; set for whole-account views, where returns include cash */
  cash_balance?: number | null
  /** Whole-account value now; the last point of the value chart */
  total_value?: number | null
  /** Securities the brokerage holds that our trades don't show yet, at current prices */
  holdings_adjustment?: number | null
  total_invested: number; total_proceeds: number; total_realized_gain: number
  /** Dividends and interest received less fees and tax withheld */
  total_income?: number
  closed_positions_count: number; trades_count: number
}
export interface PerformanceChild {
  level: string; id: string; name: string | null; summary: PerformanceSummary
  /** Populated only when level=sleeve and parent is a strategy — use for drill-down links */
  account_id?: string | null
  client_id?: string | null
}
export interface TimeseriesPoint {
  date: string; value: number; cost_basis: number | null
  net_contributions?: number | null
  cash?: number | null
  /** Net money put in since the previous point (negative if taken out) */
  net_flow?: number
}
export interface LevelPerformance {
  level: string; id: string; name: string
  start_date: string | null; end_date: string | null
  summary: PerformanceSummary
  timeseries: TimeseriesPoint[]
  children: PerformanceChild[]
}

export interface MonthlyReturn {
  year: number; month: number; month_label: string
  start_value: number; end_value: number
  cash_in: number; cash_out: number; net_cash_flow: number
  realized_gain: number; return_pct: number | null
  /** Latest month only: also carries all unrealised gain on open positions */
  includes_unrealized?: boolean
}
export interface MonthlyReturnsResponse {
  months: MonthlyReturn[]
  cumulative_return_pct: number | null
}

export interface AggregatedPosition {
  symbol: string; quantity: number; cost_basis: number; avg_cost: number
  current_price: number | null; market_value: number | null
  unrealized_gain: number | null; unrealized_gain_pct: number | null
  trades_count: number
}
export interface ClientPositionsResponse {
  client_id: string; total_cost_basis: number; total_market_value: number
  total_unrealized_gain: number; positions_count: number
  positions: AggregatedPosition[]
}
export interface AccountPositionsResponse {
  account_id: string; total_cost_basis: number; total_market_value: number
  total_unrealized_gain: number; positions_count: number
  positions: AggregatedPosition[]
}

export interface PositionResponse {
  id: string; sleeve_id: string; symbol: string; quantity: number
  avg_cost: number; cost_basis: number; current_price: number | null
  market_value: number | null; unrealized_gain: number | null
  unrealized_gain_pct: number | null
}
export interface PortfolioSummary {
  total_cost_basis: number; total_market_value: number | null
  total_unrealized_gain: number | null
}
export interface PortfolioValueResponse {
  sleeve_id: string; summary: PortfolioSummary; positions: PositionResponse[]
}

export interface ClosedPosition {
  symbol: string; status: string
  matched_quantity: number | null; entry_price: number | null; exit_price: number | null
  realized_gain: number; realized_gain_pct: number
  opened_at: string | null; closed_at: string | null; trades_count: number
  /** As the brokerage reports the lot; null where the sleeve is not matched by lots */
  cost: number | null; proceeds: number | null
  disallowed_loss: number | null; reported_gain: number | null
  short_term_gain: number | null; long_term_gain: number | null
  term: 'short' | 'long' | 'mixed' | null
  adjustments: LotAdjustment[]
}
export interface ClosedPositionsResponse {
  sleeve_id: string; total_realized_gain: number
  total_reported_gain: number | null; total_disallowed_loss: number | null
  positions: ClosedPosition[]
}

export interface ClientTradesResponse {
  client_id: string; total: number; skip: number; limit: number; trades: TradeSummary[]
}
export interface SleeveTradesResponse {
  sleeve_id: string; total: number; trades: TradeSummary[]
}

export interface MarketPriceUpdate { prices: Record<string, number> }

export interface FetchMarketPricesResponse {
  status: string; updated: number; failed: string[]
}

export interface ImportSummary {
  total_rows: number; valid_trades: number; duplicates_found: number; errors: number
  accounts_created?: number; strategies_created?: number; sleeves_created?: number
}
export interface ImportResponse {
  status: string; mode: string; routing: string
  summary: ImportSummary; message: string
  validation_warnings?: string[]; sync_log_id?: string
}

export interface SyncDailyResponse { status: string; message: string; trades_added: number }

export interface SyncLog {
  id: string; source: string; status: string; message: string
  trades_added: number; created_at: string
}
export interface SyncLogsResponse { total: number; skip: number; limit: number; logs: SyncLog[] }

export interface SheetSyncConfig {
  id: string; sleeve_id: string; sheet_id: string; range_name: string; enabled: boolean
}
export interface SyncConfigCreate {
  sleeve_id: string; sheet_id: string; range_name: string; enabled?: boolean
}
export interface SyncConfigUpdate { enabled: boolean }

export interface WeeklyReturnPoint {
  date: string          // ISO date (Monday)
  twr_cumul: number | null
  mwr_cumul: number | null
  benchmark_cumul?: number | null
}
export interface ReturnsSeriesResponse {
  level: 'client' | 'account' | 'sleeve' | 'strategy'
  id: string
  series: WeeklyReturnPoint[]
}

export interface BenchmarkPoint { date: string; close: number }
export interface BenchmarkResponse {
  ticker: string
  timeseries: BenchmarkPoint[]
  warning: string | null
}

// ── Brokerage connections ──

export type ConnectionStatus = 'active' | 'broken' | 'deleted'
export type BrokerageAccountStatus = 'unmapped' | 'mapped' | 'ignored'

export interface LinkResponse { redirect_url: string; expires_in_seconds: number }

export interface ReconciliationDrift {
  symbol: string; brokerage_quantity: number; derived_quantity: number
  difference: number; awaiting_transactions: boolean
}
export interface Reconciliation {
  matched: number; drifted: ReconciliationDrift[]
  unmatched_sells: number; skipped_rows: Record<string, number>
}

export interface BrokerageAccount {
  id: string; connection_id: string; name: string; number_last4: string | null
  status: BrokerageAccountStatus
  account_id: string | null; default_sleeve_id: string | null
  /** Client who owns the mapped account; may differ from the connection's client */
  owner_client_id: string | null
  sleeve_routes: Record<string, string> | null
  sync_start_date: string | null
  initial_sync_completed: boolean
  transactions_synced_through: string | null
  last_synced_at: string | null; last_reconciled_at: string | null
  reconciliation: Reconciliation | null
}
export interface Connection {
  id: string; client_id: string; source: string; institution: string
  status: ConnectionStatus; brokerage_accounts: BrokerageAccount[]
}

export interface BrokerageAccountUpdate {
  status: 'mapped' | 'ignored'
  account_id?: string | null; strategy_id?: string | null
  /** Owner of the account when it is not the client whose login reaches it */
  client_id?: string | null
  /** Security type → strategy id; other types use strategy_id */
  strategy_routes?: Record<string, string> | null
  history_start?: string | null
}
export interface BrokerageSyncResult {
  status: 'synced' | 'skipped'
  reason: 'synced_recently' | 'initial_sync_pending' | 'rate_limited' | null
  imported: number; duplicates: number; cash_imported: number
  skipped_rows: Record<string, number>
  next_sync_allowed_at: string | null
  transactions_synced_through: string | null
}

export type CashActivityType =
  | 'DIVIDEND' | 'INTEREST' | 'FEE' | 'WITHHOLDING'
  | 'CONTRIBUTION' | 'WITHDRAWAL' | 'TRANSFER' | 'OTHER'
export interface CashActivity {
  id: string; sleeve_id: string; activity_date: string; type: CashActivityType
  symbol: string | null; amount: number; notes: string | null
  counts_toward_returns: boolean
}

export interface ReassignRequest { from_sleeve_id: string; to_sleeve_id: string; symbols: string[] }
export interface ReassignResult { symbols: string[]; trades_moved: number; cash_activities_moved: number }

// ── Performance periods (read from the daily valuation record) ──

export type PeriodGrain = 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface PeriodPerformance {
  period_start: string; period_end: string
  opening_value: number; closing_value: number; cash_value: number | null
  /** Money put in less money taken out during the period */
  net_flow: number
  /** closing − opening − net_flow */
  gain: number
  /** Decimal fractions (0.05 = 5%); null when no capital was at work */
  twr_pct: number | null; mwr_pct: number | null
  twr_cumulative_pct: number | null; twr_ytd_pct: number | null
  benchmark_return_pct: number | null; excess_return_pct: number | null
  unpriced_pct: number
  /** Captured from the brokerage on the day, rebuilt from trades and prices, or both */
  basis: 'observed' | 'reconstructed' | 'mixed'
  is_provisional: boolean
}
export interface PeriodsResponse {
  level: string; id: string; name: string | null
  grain: PeriodGrain; benchmark: string | null
  /** market: holdings at each day's prices. realized: at cost, unrealised gains left out */
  basis: 'market' | 'realized'
  periods: PeriodPerformance[]
}

// ── Client portal ─────────────────────────────────────────────────────────
// All percentages in the portal are decimal fractions (0.05 = 5%).

export type SecurityGroup = 'stock' | 'etf' | 'option' | 'other'

export interface PortalSleeve { sleeve_id: string; strategy_id: string; strategy_name: string }
export interface PortalAccount extends VisibleAccount { sleeves: PortalSleeve[] }
export interface PortalAccountsResponse {
  /** `preview` is true when an advisor is looking at this client's portal */
  viewer: { client_id: string; name: string; preview: boolean }
  accounts: PortalAccount[]
}

/** Where a row sits: its account, and the strategy it is held under */
export interface RowPlace {
  account_id: string; account_name: string; shared: boolean
  sleeve_id: string; strategy_id: string; strategy_name: string
}

export interface PortalPosition extends RowPlace {
  symbol: string; security_type: SecurityGroup; quantity: number
  /** Per share; null when the cost is not known */
  avg_cost: number | null; cost_basis: number | null
  /** Shares per unit of quantity: 100 for an option contract, else 1 */
  multiplier: number
  /** null when there is no price (options) */
  price: number | null; market_value: number | null
  /** live = the market's current price; custodian = its last reported price, kept where there is no live quote */
  price_source: 'live' | 'custodian' | null
  /** Since the previous close, when the price is live */
  day_change?: number | null; day_change_pct?: number | null
  unrealized_gain: number | null; unrealized_gain_pct: number | null
  is_short: boolean
}
export interface PortalPositionsResponse {
  /** The custodian's holdings: quantity and cost */
  as_of: string | null; count: number
  /** When the live prices shown were fetched; null when none are live */
  live_prices_at: string | null
  /** Listed without a price of their own */
  unpriced_count: number
  /** The custodian's combined value for the unpriced options; counted in the totals when present */
  options: { count: number; market_value: number; cost_basis: number; unrealized_gain: number } | null
  total_market_value: number; total_cost_basis: number
  total_unrealized_gain: number; total_unrealized_gain_pct: number | null
  /** Cash (negative when borrowed) and the custodian's combined options value by account, as last reported */
  account_balances: { account_id: string; as_of: string; cash_value: number | null; options_value: number | null; options_cost: number | null }[]
  positions: PortalPosition[]
}

export interface PortalTrade extends RowPlace {
  id: string; trade_date: string; symbol: string; action: TradeAction
  /** Set when the row is an option ending without a trade */
  event: 'assigned' | 'expired' | null
  security_type: SecurityGroup; quantity: number
  /** Per share, also for an option; `multiplier` is shares per unit of quantity (100 for a contract) */
  price: number; multiplier: number
  amount: number; commission: number
}
export interface PortalTradesResponse {
  total: number; skip: number; limit: number
  /** Totals for everything the filters match, not just the page */
  bought: number; sold: number; net_invested: number
  /** Each account with a matching trade and its totals, whatever page `trades` is on */
  accounts: { account_id: string; account_name: string; shared: boolean; total: number; bought: number; sold: number }[]
  trades: PortalTrade[]
}

export type ActivityKind =
  | 'trade' | 'deposit' | 'withdrawal' | 'transfer' | 'dividend' | 'interest'
  | 'margin_interest' | 'fee' | 'withholding' | 'other'
/** One thing that happened: a trade, or cash that moved */
export interface ActivityRow extends RowPlace {
  id: string; date: string; kind: ActivityKind
  /** The row in a word or two: Bought, Deposit, Transfer in */
  label: string
  /** The custodian's description, tidied; null on a trade */
  detail: string | null
  symbol: string | null
  /** The trade fields are null on a cash row */
  action: TradeAction | null; event: 'assigned' | 'expired' | null
  security_type: SecurityGroup | null; quantity: number | null
  price: number | null; multiplier: number | null
  /** A trade's value, unsigned. A cash row's amount, signed: money arriving is positive */
  amount: number
}
export interface ActivityFigures {
  total: number; trades: number; bought: number; sold: number
  /** Deposits and transfers in; withdrawals and transfers out (positive) */
  money_in: number; money_out: number
  /** Dividends and interest; margin interest, fees and tax withheld (positive) */
  income: number; charges: number
}
export interface PortalActivityResponse extends ActivityFigures {
  skip: number; limit: number; net_invested: number
  /** Each account with a matching row and its totals, whatever page `rows` is on */
  accounts: (ActivityFigures & { account_id: string; account_name: string; shared: boolean })[]
  rows: ActivityRow[]
}

/** The portal's home page. Value and the day's change are at live prices; the year's figures run through `record_through` */
export interface PortalHomeHolding {
  symbol: string; value: number
  /** Today's move in dollars, and as a fraction */
  day_change: number | null; day_change_pct: number | null; share: number | null
}
export interface PortalExpiringOption {
  symbol: string; account_name: string; underlying: string; kind: 'put' | 'call'
  strike: number; expiry: string; days: number; contracts: number; written: boolean
  underlying_price: number | null
  /** Positive when the shares are above the strike; null with no live price */
  above_strike_pct: number | null
}
export interface PortalHomeResponse {
  as_of: string | null; live_prices_at: string | null; record_through: string | null
  is_provisional: boolean
  total_value: number; day_change: number | null; day_change_pct: number | null
  ytd_twr_pct: number | null; benchmark: string
  benchmark_ytd_pct: number | null; excess_ytd_pct: number | null
  /** Over the whole record, which starts on `first_date`; the fall is a negative fraction */
  first_date: string | null; since_start_twr_pct: number | null; max_drawdown_pct: number | null
  allocation: { kind: SecurityGroup | 'cash'; value: number; share: number | null }[]
  cash_value: number | null
  /** Dividends and interest */
  income_ytd: number
  realized_ytd: number; realized_short_ytd: number; realized_long_ytd: number
  /** Deposits less withdrawals */
  added_ytd: number | null
  holdings_count: number
  top_holdings: PortalHomeHolding[]
  /** The holdings that moved the total most today, in dollars; up to three each */
  movers_up: PortalHomeHolding[]; movers_down: PortalHomeHolding[]
  expiring_options: PortalExpiringOption[]
  /** Wash-sale losses in the cost of shares still held */
  carried_losses: number
  turning_long_term: { symbol: string; date: string }[]
  concentrated: PortalHomeHolding[]
}

export interface PortalClosedLot extends RowPlace {
  symbol: string; security_type: SecurityGroup
  /** An assigned option shows no gain: its premium is carried by the shares that changed hands */
  event: 'assigned' | 'expired' | 'marked' | null
  opened_at: string | null; closed_at: string; days_held: number | null
  /** short = held a year or less; mixed = an index option, 60% long-term and 40% short-term */
  term: 'short' | 'long' | 'mixed'
  quantity: number | null
  /** Shares per unit of quantity: 100 for an option contract */
  multiplier: number
  /** Per share */
  entry_price: number | null; exit_price: number | null
  /** As the custodian reports the lot; cost includes any earlier wash-sale loss carried into it */
  cost: number; proceeds: number
  /** The part of this lot's loss a wash sale carried into the shares that replaced it */
  disallowed_loss: number
  short_term_gain: number; long_term_gain: number
  /** Proceeds less cost, plus the disallowed loss */
  realized_gain: number; realized_gain_pct: number | null
  adjustments: LotAdjustment[]
}
export type LotAdjustment = 'wash' | 'mark' | 'unmarked' | 'index_option' | 'written_option'
/** Capital gains and the income received over one slice; `realized` is short plus long term, income is never in it */
export interface PortalGainFigures {
  count: number; short_term: number; long_term: number; realized: number
  disallowed_loss: number; dividends: number; interest: number
  /** Interest paid on money borrowed; negative */
  margin_interest: number
}
export interface PortalGainPeriod extends PortalGainFigures { period_start: string; period_end: string }
export interface PortalGainSleeve extends PortalGainFigures { sleeve_id: string; strategy_id: string; strategy_name: string }
export interface PortalGainAccount extends PortalGainFigures {
  account_id: string; account_name: string; shared: boolean; sleeves: PortalGainSleeve[]
}
export interface PortalRealizedResponse {
  count: number; net_realized: number; short_term: number; long_term: number
  gains: number; losses: number; years: number[]
  cost: number; proceeds: number; disallowed_loss: number
  /** Received over the same dates; follows the dates, account and strategy only, and is not part of net_realized */
  dividends: number; interest: number
  /** Interest paid on money borrowed over the same dates; negative */
  margin_interest: number
  /** By month or quarter, newest first */
  periods: PortalGainPeriod[]
  accounts: PortalGainAccount[]
  positions: PortalClosedLot[]
}

export interface MonthFigure { year: number; month: number; twr_pct: number | null }
export interface PortalSummary {
  start: string; end: string
  opening_value: number; closing_value: number; cash_value: number | null
  net_flow: number; gain: number
  twr_pct: number | null
  /** null for a single strategy: deposits are made to the account */
  mwr_pct: number | null
  benchmark_return_pct: number | null; excess_return_pct: number | null
  /** Set when the benchmark's price history starts after the window: its return runs from this date */
  benchmark_from: string | null
  is_provisional: boolean
  best_month: MonthFigure | null; worst_month: MonthFigure | null
  months_up: number; months_total: number
}
/** `value` is what it was worth that day; the others are cumulative returns from the start of the window */
export interface CumulativePoint { date: string; twr: number | null; mwr: number | null; benchmark: number | null; value: number | null }
export interface PortalMonth extends MonthFigure { is_provisional: boolean }
export interface PortalYear { year: number; twr_pct: number | null; is_provisional: boolean }
export interface PortalPeriod {
  period_start: string; period_end: string
  opening_value: number; closing_value: number; net_flow: number; gain: number
  twr_pct: number | null; twr_ytd_pct: number | null
  benchmark_return_pct: number | null; excess_return_pct: number | null
  is_provisional: boolean
}
export type PortalGrain = 'day' | 'week' | 'month' | 'quarter'
/** A fund includes its dividends; an index level leaves them out */
export interface BenchmarkChoice { code: string; name: string; includes_dividends: boolean }
export interface PortalPerformanceResponse {
  first_date: string | null; as_of: string | null
  includes_cash: boolean; benchmark: string; grain: string
  /** What the return may be compared with; `benchmark` is the code of the one in use */
  benchmarks: BenchmarkChoice[]
  summary: PortalSummary | null
  series: CumulativePoint[]; months: PortalMonth[]; years: PortalYear[]; periods: PortalPeriod[]
}

export interface OverviewSleeve extends PortalSleeve { value: number | null; twr_pct: number | null; gain: number | null }
export interface OverviewAccount extends VisibleAccount {
  value: number | null; cash: number | null
  /** Year to date */
  twr_pct: number | null; gain: number | null
  sleeves: OverviewSleeve[]
}
export interface ActivityItem {
  date: string
  /** BUY | SELL | DIVIDEND | INTEREST | FEE | WITHHOLDING */
  kind: string
  symbol: string | null; quantity: number | null; amount: number; account_name: string
}
export interface PortalOverviewResponse {
  as_of: string | null; includes_cash: boolean
  total_value: number | null; cash_value: number | null
  ytd_twr_pct: number | null; ytd_gain: number | null; ytd_realized: number
  is_provisional: boolean
  accounts: OverviewAccount[]
  timeseries: { date: string; value: number }[]
  recent: ActivityItem[]
}

/** The advisor's system status page */
export interface StatusJob {
  id: string; label: string; next_run_at: string | null
  /** The last run since the app started; null until the job has run once */
  last_started_at: string | null; last_finished_at: string | null
  last_ok: boolean | null; last_error: string | null
}
export interface StatusBrokerageAccount {
  id: string; name: string; number_last4: string | null; owner: string | null
  status: string; connection_status: string
  last_synced_at: string | null; next_sync_allowed_at: string | null
  transactions_synced_through: string | null
  /** The latest day with the brokerage's own holdings and total on record */
  captured_through: string | null
  holdings_differ: number | null; skipped_rows: number
}
/** One brokerage login, and whether the source is still sharing it */
export interface StatusBrokerageLink {
  id: string; institution: string; source: string; status: string
  /** When the source was last asked; since when it stopped sharing, if it has */
  checked_at: string | null; disabled_at: string | null
  /** The client whose page the link is managed from */
  client_id: string; client: string | null
  accounts: number
}
export interface SystemStatusResponse {
  generated_at: string
  /** What needs a person to look, in plain words; empty when all is well */
  attention: string[]
  app: { environment: string; started_at: string; scheduler_enabled: boolean }
  database: { ok: boolean; size_bytes: number | null; migration: string | null }
  disk: { total_bytes: number; free_bytes: number }
  jobs: StatusJob[]
  brokerage_links: StatusBrokerageLink[]
  brokerage_accounts: StatusBrokerageAccount[]
  capture: { market_day: string; accounts: number; missing: string[] }
  data: {
    clients: number; accounts: number; trades: number; latest_trade_date: string | null
    priced_symbols: number; latest_price_date: string | null
    indices: { symbol: string; latest_date: string | null; days: number }[]
  }
  backup: { known: boolean; at: string | null; file: string | null; size_bytes: number | null }
  recent_log: { at: string; level: string; source: string; message: string }[]
}
