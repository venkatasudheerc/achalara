// Hand-typed from openapi.yaml — regenerate with `npm run gen:api` once backend is running

export type TradeAction = 'BUY' | 'SELL'

export interface ClientLogin { email: string; password: string }
export interface ClientCreate { name: string; email: string }
export interface ClientResponse {
  id: string; name: string; email: string
  created_at: string; updated_at: string
}

export interface AccountCreate { name: string; description?: string; account_number?: string | null }
export interface AccountResponse {
  id: string; client_id: string; name: string
  description: string; account_number: string | null
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
}

export interface PerformanceSummary {
  mwr_pct: number | null; twr_pct: number | null; twr_note: string | null
  total_return_pct: number | null
  total_cost_basis: number; total_market_value: number; total_unrealized_gain: number
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
export interface TimeseriesPoint { date: string; value: number; cost_basis: number }
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
}
export interface ClosedPositionsResponse {
  sleeve_id: string; total_realized_gain: number; positions: ClosedPosition[]
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
