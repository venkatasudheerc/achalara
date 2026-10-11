import { apiClient } from '../client'
import { PERIOD_BASIS } from './performance'
import type {
  SleeveCreate, SleeveResponse,
  LevelPerformance, MonthlyReturnsResponse, ReturnsSeriesResponse,
  PortfolioValueResponse, ClosedPositionsResponse,
  SleeveTradesResponse, MarketPriceUpdate, FetchMarketPricesResponse, CashActivity,
} from '../types'

const base = (clientId: string, accountId: string) =>
  `/api/v1/clients/${clientId}/accounts/${accountId}/sleeves`

export const sleevesApi = {
  getCashActivities: (clientId: string, accountId: string, sleeveId: string) =>
    apiClient
      .get<CashActivity[]>(`${base(clientId, accountId)}/${sleeveId}/cash-activities`)
      .then((r) => r.data),

  create: (clientId: string, accountId: string, body: SleeveCreate) =>
    apiClient
      .post<SleeveResponse>(`${base(clientId, accountId)}`, body)
      .then((r) => r.data),

  list: (clientId: string, accountId: string) =>
    apiClient.get<SleeveResponse[]>(`${base(clientId, accountId)}`).then((r) => r.data),

  get: (clientId: string, accountId: string, sleeveId: string) =>
    apiClient
      .get<SleeveResponse>(`${base(clientId, accountId)}/${sleeveId}`)
      .then((r) => r.data),

  getPerformance: (
    clientId: string, accountId: string, sleeveId: string,
    params?: { start_date?: string; end_date?: string }
  ) =>
    apiClient
      .get<LevelPerformance>(
        `${base(clientId, accountId)}/${sleeveId}/performance`,
        { params }
      )
      .then((r) => r.data),

  getMonthlyPerformance: (clientId: string, accountId: string, sleeveId: string) =>
    apiClient
      .get<MonthlyReturnsResponse>(
        `${base(clientId, accountId)}/${sleeveId}/performance/monthly`, { params: { basis: PERIOD_BASIS } }
      )
      .then((r) => r.data),

  getReturnsSeries: (
    clientId: string, accountId: string, sleeveId: string,
    params?: { start_date?: string; end_date?: string }
  ) =>
    apiClient
      .get<ReturnsSeriesResponse>(
        `${base(clientId, accountId)}/${sleeveId}/performance/returns-series`,
        { params: { ...params, basis: PERIOD_BASIS } }
      )
      .then((r) => r.data),

  getPositions: (clientId: string, accountId: string, sleeveId: string) =>
    apiClient
      .get<PortfolioValueResponse>(`${base(clientId, accountId)}/${sleeveId}/positions`)
      .then((r) => r.data),

  getClosedPositions: (clientId: string, accountId: string, sleeveId: string) =>
    apiClient
      .get<ClosedPositionsResponse>(
        `${base(clientId, accountId)}/${sleeveId}/positions/closed`
      )
      .then((r) => r.data),

  getTrades: (
    clientId: string, accountId: string, sleeveId: string,
    params?: { skip?: number; limit?: number }
  ) =>
    apiClient
      .get<SleeveTradesResponse>(
        `${base(clientId, accountId)}/${sleeveId}/trades`,
        { params }
      )
      .then((r) => r.data),

  updateMarketPrices: (
    clientId: string, accountId: string, sleeveId: string, body: MarketPriceUpdate
  ) =>
    apiClient
      .post<{ status: string; updated: number }>(
        `${base(clientId, accountId)}/${sleeveId}/market-prices`,
        body
      )
      .then((r) => r.data),

  fetchMarketPrices: (clientId: string, accountId: string, sleeveId: string) =>
    apiClient
      .post<FetchMarketPricesResponse>(
        `${base(clientId, accountId)}/${sleeveId}/fetch-market-prices`
      )
      .then((r) => r.data),
}
