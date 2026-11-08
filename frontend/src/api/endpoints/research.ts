import { apiClient } from '../client'
import type {
  RsCalendar, RsMonth, RsOutlook, RsProfile, RsSearch, RsSectors, RsTopPerformers, RsWeek,
} from '../types'

/** Market insights: read-only, the same for every signed-in user. */
export const researchApi = {
  thisWeek: () => apiClient.get<RsWeek>('/api/v1/research/this-week').then((r) => r.data),
  thisMonth: () => apiClient.get<RsMonth>('/api/v1/research/this-month').then((r) => r.data),
  outlook: (month?: number) =>
    apiClient.get<RsOutlook>('/api/v1/research/outlook', { params: { month } }).then((r) => r.data),
  calendar: (params: { symbol: string; start_year?: number; end_year?: number; stat: 'mean' | 'median' }) =>
    apiClient.get<RsCalendar>('/api/v1/research/calendar', { params }).then((r) => r.data),
  topPerformers: (params: { month: number; universe: string }) =>
    apiClient.get<RsTopPerformers>('/api/v1/research/top-performers', { params: { ...params, limit: 50 } }).then((r) => r.data),
  sectors: (params: { month: number; universe: string; compare?: string }) =>
    apiClient.get<RsSectors>('/api/v1/research/sectors', { params }).then((r) => r.data),
  search: (q: string) =>
    apiClient.get<RsSearch>('/api/v1/research/securities', { params: { q, limit: 8 } }).then((r) => r.data),
  profile: (symbol: string, month?: number) =>
    apiClient.get<RsProfile>(`/api/v1/research/securities/${encodeURIComponent(symbol)}`, { params: { month } }).then((r) => r.data),
}
