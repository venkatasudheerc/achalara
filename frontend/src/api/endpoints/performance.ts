import { apiClient } from '../client'
import type { PeriodGrain, PeriodsResponse } from '../types'

/**
 * How the period widgets (returns chart, monthly grid, period table) value
 * holdings: at each day's closing prices, like the headline. The API can also
 * read the same record at cost ('realized'), leaving unrealised gains out.
 */
export const PERIOD_BASIS: 'market' | 'realized' = 'market'

/** Which entity a performance view is of; mirrors ScopeContext. */
export interface PerformanceTarget {
  level: 'client' | 'account' | 'sleeve' | 'strategy'
  clientId?: string | null
  accountId?: string | null
  sleeveId?: string | null
  strategyId?: string | null
}

function basePath(target: PerformanceTarget): string {
  if (target.level === 'strategy') return `/api/v1/strategies/${target.strategyId}`
  const client = `/api/v1/clients/${target.clientId}`
  if (target.level === 'client') return client
  const account = `${client}/accounts/${target.accountId}`
  if (target.level === 'account') return account
  return `${account}/sleeves/${target.sleeveId}`
}

export const performanceApi = {
  getPeriods: (
    target: PerformanceTarget,
    params: { grain: PeriodGrain; benchmark?: string; start_date?: string; end_date?: string },
  ) =>
    apiClient
      .get<PeriodsResponse>(`${basePath(target)}/performance/periods`, {
        params: { ...params, basis: PERIOD_BASIS },
      })
      .then((r) => r.data),

  /** Where the account's PDF report is served; opened directly by the browser. */
  reportUrl: (clientId: string, accountId: string) =>
    `${apiClient.defaults.baseURL}/api/v1/clients/${clientId}/accounts/${accountId}/report`,
}
