import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  portalApi,
  type PerformanceFilters, type PortalScope, type PositionFilters, type RealizedFilters, type ActivityFilters,
} from '@/api/endpoints/portal'

/**
 * The client an advisor is previewing (`?as=<clientId>` on any portal URL),
 * or undefined for a client looking at their own portal.
 */
export function usePreviewClient(): string | undefined {
  const [params] = useSearchParams()
  return params.get('as') ?? undefined
}

export function usePortalAccounts() {
  const asClient = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'accounts', asClient],
    queryFn: () => portalApi.accounts(asClient),
    staleTime: 5 * 60_000,
  })
}

export function usePortalHome(filters: PortalScope) {
  const as_client = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'home', as_client, filters],
    queryFn: () => portalApi.home({ ...filters, as_client }),
    placeholderData: keepPreviousData,
    // Value and the day's change are live, so the page keeps itself current.
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}

export function usePortalOverview(filters: PortalScope) {
  const as_client = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'overview', as_client, filters],
    queryFn: () => portalApi.overview({ ...filters, as_client }),
    placeholderData: keepPreviousData,
  })
}

export function usePortalPositions(filters: PositionFilters) {
  const as_client = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'positions', as_client, filters],
    queryFn: () => portalApi.positions({ ...filters, as_client }),
    placeholderData: keepPreviousData,
    // Prices here are live, so the page keeps itself current while it is open.
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  })
}

export function usePortalActivity(filters: ActivityFilters) {
  const as_client = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'activity', as_client, filters],
    queryFn: () => portalApi.activity({ ...filters, as_client }),
    placeholderData: keepPreviousData,
  })
}

export function usePortalRealized(filters: RealizedFilters) {
  const as_client = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'realized', as_client, filters],
    queryFn: () => portalApi.realized({ ...filters, as_client }),
    placeholderData: keepPreviousData,
  })
}

export function usePortalPerformance(filters: PerformanceFilters, enabled = true) {
  const as_client = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'performance', as_client, filters],
    queryFn: () => portalApi.performance({ ...filters, as_client }),
    placeholderData: keepPreviousData,
    enabled,
  })
}
