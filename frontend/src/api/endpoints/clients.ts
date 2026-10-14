import { apiClient } from '../client'
import { PERIOD_BASIS } from './performance'
import type {
  ClientCreate, ClientResponse, ClientUpdate,
  LevelPerformance, MonthlyReturnsResponse, ReturnsSeriesResponse,
  ClientPositionsResponse, ClientTradesResponse,
} from '../types'

const base = '/api/v1/clients'

export const clientsApi = {
  list: (params?: { skip?: number; limit?: number }) =>
    apiClient.get<ClientResponse[]>(`${base}/`, { params }).then((r) => r.data),

  create: (body: ClientCreate) =>
    apiClient.post<ClientResponse>(`${base}/`, body).then((r) => r.data),

  get: (clientId: string) =>
    apiClient.get<ClientResponse>(`${base}/${clientId}`).then((r) => r.data),

  update: (clientId: string, body: ClientUpdate) =>
    apiClient.patch<ClientResponse>(`${base}/${clientId}`, body).then((r) => r.data),

  getPerformance: (clientId: string, params?: { start_date?: string; end_date?: string }) =>
    apiClient
      .get<LevelPerformance>(`${base}/${clientId}/performance`, { params })
      .then((r) => r.data),

  getMonthlyPerformance: (clientId: string) =>
    apiClient
      .get<MonthlyReturnsResponse>(`${base}/${clientId}/performance/monthly`, { params: { basis: PERIOD_BASIS } })
      .then((r) => r.data),

  getReturnsSeries: (clientId: string, params?: { start_date?: string; end_date?: string }) =>
    apiClient
      .get<ReturnsSeriesResponse>(`${base}/${clientId}/performance/returns-series`, { params: { ...params, basis: PERIOD_BASIS } })
      .then((r) => r.data),

  getPositions: (clientId: string) =>
    apiClient
      .get<ClientPositionsResponse>(`${base}/${clientId}/positions`)
      .then((r) => r.data),

  getTrades: (clientId: string, params?: { skip?: number; limit?: number }) =>
    apiClient
      .get<ClientTradesResponse>(`${base}/${clientId}/trades`, { params })
      .then((r) => r.data),
}
