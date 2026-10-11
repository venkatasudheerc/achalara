import { apiClient } from '../client'
import { PERIOD_BASIS } from './performance'
import type {
  StrategyCreate, StrategyResponse,
  LevelPerformance, MonthlyReturnsResponse, ReturnsSeriesResponse,
} from '../types'

const base = '/api/v1/strategies'

export const strategiesApi = {
  create: (body: StrategyCreate) =>
    apiClient.post<StrategyResponse>(`${base}/`, body).then((r) => r.data),

  list: () =>
    apiClient.get<StrategyResponse[]>(`${base}/`).then((r) => r.data),

  get: (strategyId: string) =>
    apiClient.get<StrategyResponse>(`${base}/${strategyId}`).then((r) => r.data),

  getPerformance: (strategyId: string, params?: { start_date?: string; end_date?: string }) =>
    apiClient
      .get<LevelPerformance>(`${base}/${strategyId}/performance`, { params })
      .then((r) => r.data),

  getMonthlyPerformance: (strategyId: string) =>
    apiClient
      .get<MonthlyReturnsResponse>(`${base}/${strategyId}/performance/monthly`, { params: { basis: PERIOD_BASIS } })
      .then((r) => r.data),

  getReturnsSeries: (strategyId: string, params?: { start_date?: string; end_date?: string }) =>
    apiClient
      .get<ReturnsSeriesResponse>(`${base}/${strategyId}/performance/returns-series`, { params: { ...params, basis: PERIOD_BASIS } })
      .then((r) => r.data),
}
