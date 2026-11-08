import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { researchApi } from '@/api/endpoints/research'

// Market data changes once a night, so answers are kept for ten minutes.
const FRESH = 10 * 60_000

export function useResearchWeek() {
  return useQuery({ queryKey: ['research', 'week'], queryFn: researchApi.thisWeek, staleTime: FRESH })
}

export function useResearchMonth() {
  return useQuery({ queryKey: ['research', 'month'], queryFn: researchApi.thisMonth, staleTime: FRESH })
}

export function useResearchOutlook(month?: number) {
  return useQuery({ queryKey: ['research', 'outlook', month], queryFn: () => researchApi.outlook(month), staleTime: FRESH })
}

export function useCalendarGrid(params: { symbol: string; start_year?: number; end_year?: number; stat: 'mean' | 'median' }) {
  return useQuery({
    queryKey: ['research', 'calendar', params], queryFn: () => researchApi.calendar(params),
    staleTime: FRESH, placeholderData: keepPreviousData, enabled: params.symbol.length > 0,
  })
}

export function useTopPerformers(params: { month: number; universe: string }) {
  return useQuery({ queryKey: ['research', 'top', params], queryFn: () => researchApi.topPerformers(params), staleTime: FRESH, placeholderData: keepPreviousData })
}

export function useSectorScorecard(params: { month: number; universe: string; compare?: string }) {
  return useQuery({ queryKey: ['research', 'sectors', params], queryFn: () => researchApi.sectors(params), staleTime: FRESH, placeholderData: keepPreviousData })
}

export function useSecuritySearch(q: string) {
  return useQuery({ queryKey: ['research', 'search', q], queryFn: () => researchApi.search(q), staleTime: FRESH, enabled: q.trim().length > 0 })
}

export function useSecurityProfile(symbol: string | null, month?: number) {
  return useQuery({
    queryKey: ['research', 'profile', symbol, month], queryFn: () => researchApi.profile(symbol as string, month),
    staleTime: FRESH, enabled: Boolean(symbol),
  })
}
