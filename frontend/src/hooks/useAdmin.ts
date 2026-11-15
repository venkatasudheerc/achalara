import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '@/api/endpoints/admin'

/** The system status, read again every half minute while the page is open. */
export function useSystemStatus() {
  return useQuery({
    queryKey: ['admin', 'status'] as const,
    queryFn: () => adminApi.status(),
    refetchInterval: 30_000,
  })
}

/** The state of the md schema, read again every minute while the page is open. */
export function useMarketDataStatus() {
  return useQuery({
    queryKey: ['admin', 'market-data', 'status'] as const,
    queryFn: () => adminApi.marketDataStatus(),
    refetchInterval: 60_000,
  })
}

/** Likely ticker changes from the accounts' own records, for an admin to confirm. */
export function useTickerChanges() {
  return useQuery({ queryKey: ['admin', 'ticker-changes'] as const, queryFn: () => adminApi.tickerChanges() })
}

/** Confirm one: old trades are read under the new ticker and the accounts rebuilt. */
export function useConfirmTickerChange() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: adminApi.confirmTickerChange,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin'] })
      qc.invalidateQueries({ queryKey: ['portal'] })
    },
  })
}

export function useSendTestAlert() {
  return useMutation({ mutationFn: () => adminApi.testAlert() })
}

