import { apiClient } from '../client'
import type { MarketDataStatusResponse, SystemStatusResponse, TickerChangeProposal } from '../types'

export const adminApi = {
  status: () => apiClient.get<SystemStatusResponse>('/api/v1/admin/status').then((r) => r.data),
  marketDataStatus: () =>
    apiClient.get<MarketDataStatusResponse>('/api/v1/admin/market-data/status').then((r) => r.data),
  /** Sends a test message through the alert channel. */
  tickerChanges: () =>
    apiClient.get<TickerChangeProposal[]>('/api/v1/admin/ticker-changes').then((r) => r.data),
  confirmTickerChange: (body: { old: string; new: string; on: string }) =>
    apiClient.post<{ accounts_rebuilt: number }>('/api/v1/admin/ticker-changes', body).then((r) => r.data),
  testAlert: () =>
    apiClient.post<{ sent: boolean }>('/api/v1/admin/status/test-alert').then((r) => r.data),
}
