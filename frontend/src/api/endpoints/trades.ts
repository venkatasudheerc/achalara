import { apiClient } from '../client'
import type { TradeCreate, TradeResponse, ReassignRequest, ReassignResult } from '../types'

export const tradesApi = {
  create: (body: TradeCreate) =>
    apiClient.post<TradeResponse>('/api/v1/trades/', body).then((r) => r.data),

  reassign: (body: ReassignRequest) =>
    apiClient.post<ReassignResult>('/api/v1/trades/reassign', body).then((r) => r.data),
}
