import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sleevesApi } from '@/api/endpoints/sleeves'
import type { SleeveCreate, MarketPriceUpdate } from '@/api/types'

export const sleeveKeys = {
  list: (clientId: string, accountId: string) => ['sleeves', clientId, accountId] as const,
  detail: (clientId: string, accountId: string, sleeveId: string) =>
    ['sleeves', clientId, accountId, sleeveId] as const,
  performance: (clientId: string, accountId: string, sleeveId: string, start?: string, end?: string) =>
    ['sleeves', clientId, accountId, sleeveId, 'performance', start, end] as const,
  monthlyPerformance: (clientId: string, accountId: string, sleeveId: string) =>
    ['sleeves', clientId, accountId, sleeveId, 'performance', 'monthly'] as const,
  returnsSeries: (clientId: string, accountId: string, sleeveId: string, start?: string, end?: string) =>
    ['sleeves', clientId, accountId, sleeveId, 'performance', 'returns-series', start, end] as const,
  positions: (clientId: string, accountId: string, sleeveId: string) =>
    ['sleeves', clientId, accountId, sleeveId, 'positions'] as const,
  closedPositions: (clientId: string, accountId: string, sleeveId: string) =>
    ['sleeves', clientId, accountId, sleeveId, 'positions', 'closed'] as const,
  trades: (clientId: string, accountId: string, sleeveId: string, skip?: number) =>
    ['sleeves', clientId, accountId, sleeveId, 'trades', skip] as const,
  cashActivities: (clientId: string, accountId: string, sleeveId: string) =>
    ['sleeves', clientId, accountId, sleeveId, 'cash-activities'] as const,
}

export function useSleeves(clientId: string, accountId: string) {
  return useQuery({
    queryKey: sleeveKeys.list(clientId, accountId),
    queryFn: () => sleevesApi.list(clientId, accountId),
    enabled: !!clientId && !!accountId,
  })
}

export function useSleeve(clientId: string, accountId: string, sleeveId: string) {
  return useQuery({
    queryKey: sleeveKeys.detail(clientId, accountId, sleeveId),
    queryFn: () => sleevesApi.get(clientId, accountId, sleeveId),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleevePerformance(
  clientId: string, accountId: string, sleeveId: string,
  params?: { start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: sleeveKeys.performance(clientId, accountId, sleeveId, params?.start_date, params?.end_date),
    queryFn: () => sleevesApi.getPerformance(clientId, accountId, sleeveId, params),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleeveMonthlyPerformance(clientId: string, accountId: string, sleeveId: string) {
  return useQuery({
    queryKey: sleeveKeys.monthlyPerformance(clientId, accountId, sleeveId),
    queryFn: () => sleevesApi.getMonthlyPerformance(clientId, accountId, sleeveId),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleeveReturnsSeries(
  clientId: string, accountId: string, sleeveId: string,
  params?: { start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: sleeveKeys.returnsSeries(clientId, accountId, sleeveId, params?.start_date, params?.end_date),
    queryFn: () => sleevesApi.getReturnsSeries(clientId, accountId, sleeveId, params),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleevePositions(clientId: string, accountId: string, sleeveId: string) {
  return useQuery({
    queryKey: sleeveKeys.positions(clientId, accountId, sleeveId),
    queryFn: () => sleevesApi.getPositions(clientId, accountId, sleeveId),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleeveClosedPositions(clientId: string, accountId: string, sleeveId: string) {
  return useQuery({
    queryKey: sleeveKeys.closedPositions(clientId, accountId, sleeveId),
    queryFn: () => sleevesApi.getClosedPositions(clientId, accountId, sleeveId),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleeveTrades(
  clientId: string, accountId: string, sleeveId: string,
  skip = 0, limit = 100
) {
  return useQuery({
    queryKey: sleeveKeys.trades(clientId, accountId, sleeveId, skip),
    queryFn: () => sleevesApi.getTrades(clientId, accountId, sleeveId, { skip, limit }),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useSleeveCashActivities(clientId: string, accountId: string, sleeveId: string) {
  return useQuery({
    queryKey: sleeveKeys.cashActivities(clientId, accountId, sleeveId),
    queryFn: () => sleevesApi.getCashActivities(clientId, accountId, sleeveId),
    enabled: !!clientId && !!accountId && !!sleeveId,
  })
}

export function useCreateSleeve() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      clientId, accountId, body,
    }: { clientId: string; accountId: string; body: SleeveCreate }) =>
      sleevesApi.create(clientId, accountId, body),
    onSuccess: (_data, { clientId, accountId }) =>
      qc.invalidateQueries({ queryKey: sleeveKeys.list(clientId, accountId) }),
  })
}

export function useFetchMarketPrices() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      clientId, accountId, sleeveId,
    }: { clientId: string; accountId: string; sleeveId: string }) =>
      sleevesApi.fetchMarketPrices(clientId, accountId, sleeveId),
    onSuccess: (_data, { clientId, accountId, sleeveId }) =>
      qc.invalidateQueries({ queryKey: sleeveKeys.positions(clientId, accountId, sleeveId) }),
  })
}

export function useUpdateMarketPrices() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      clientId, accountId, sleeveId, body,
    }: { clientId: string; accountId: string; sleeveId: string; body: MarketPriceUpdate }) =>
      sleevesApi.updateMarketPrices(clientId, accountId, sleeveId, body),
    onSuccess: (_data, { clientId, accountId, sleeveId }) =>
      qc.invalidateQueries({ queryKey: sleeveKeys.positions(clientId, accountId, sleeveId) }),
  })
}
