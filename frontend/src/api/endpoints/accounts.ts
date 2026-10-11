import { apiClient } from '../client'
import { PERIOD_BASIS } from './performance'
import type {
  AccountCreate, AccountResponse,
  LevelPerformance, MonthlyReturnsResponse, ReturnsSeriesResponse, AccountPositionsResponse,
} from '../types'

const base = (clientId: string) => `/api/v1/clients/${clientId}/accounts`

export const accountsApi = {
  create: (clientId: string, body: AccountCreate) =>
    apiClient.post<AccountResponse>(`${base(clientId)}`, body).then((r) => r.data),

  list: (clientId: string) =>
    apiClient.get<AccountResponse[]>(`${base(clientId)}`).then((r) => r.data),

  get: (clientId: string, accountId: string) =>
    apiClient.get<AccountResponse>(`${base(clientId)}/${accountId}`).then((r) => r.data),

  getPerformance: (
    clientId: string, accountId: string,
    params?: { start_date?: string; end_date?: string }
  ) =>
    apiClient
      .get<LevelPerformance>(`${base(clientId)}/${accountId}/performance`, { params })
      .then((r) => r.data),

  getMonthlyPerformance: (clientId: string, accountId: string) =>
    apiClient
      .get<MonthlyReturnsResponse>(`${base(clientId)}/${accountId}/performance/monthly`, { params: { basis: PERIOD_BASIS } })
      .then((r) => r.data),

  getReturnsSeries: (
    clientId: string, accountId: string,
    params?: { start_date?: string; end_date?: string }
  ) =>
    apiClient
      .get<ReturnsSeriesResponse>(
        `${base(clientId)}/${accountId}/performance/returns-series`,
        { params: { ...params, basis: PERIOD_BASIS } }
      )
      .then((r) => r.data),

  getPositions: (clientId: string, accountId: string) =>
    apiClient
      .get<AccountPositionsResponse>(`${base(clientId)}/${accountId}/positions`)
      .then((r) => r.data),
}
