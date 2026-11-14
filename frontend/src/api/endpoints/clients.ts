import { apiClient } from '../client'
import { PERIOD_BASIS } from './performance'
import type {
  ClientCreate, ClientResponse, ClientUpdate, Relative, RelativeCreate,
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

  /** Makes the two each other's spouse; null ends it. */
  setSpouse: (clientId: string, spouseId: string | null) =>
    apiClient.put<ClientResponse>(`${base}/${clientId}/spouse`, { spouse_id: spouseId }).then((r) => r.data),

  /** Marks the client a minor in the guardian's care; null, not a minor. */
  setGuardian: (clientId: string, guardianId: string | null) =>
    apiClient.put<ClientResponse>(`${base}/${clientId}/guardian`, { guardian_id: guardianId }).then((r) => r.data),

  /** The client's spouse first, then minors (theirs and their spouse's). */
  relatives: (clientId: string) =>
    apiClient.get<Relative[]>(`${base}/${clientId}/relatives`).then((r) => r.data),

  /** A new client who is this client's spouse or minor, with the same advisor. */
  addRelative: (clientId: string, body: RelativeCreate) =>
    apiClient.post<ClientResponse>(`${base}/${clientId}/relatives`, body).then((r) => r.data),

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
