import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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

/** The client's own named groups of accounts. */
export function usePortalGroups() {
  const asClient = usePreviewClient()
  return useQuery({
    queryKey: ['portal', 'groups', asClient],
    queryFn: () => portalApi.groups(asClient),
    staleTime: 5 * 60_000,
  })
}

/** Create, rename, refill or delete a group; the list is fetched again after each. */
export function useGroupChanges() {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['portal', 'groups'] })
  return {
    create: useMutation({
      mutationFn: (v: { name: string; accountIds?: string[] }) => portalApi.createGroup(v.name, v.accountIds),
      onSuccess: refresh,
    }),
    rename: useMutation({
      mutationFn: (v: { id: string; name: string }) => portalApi.updateGroup(v.id, { name: v.name }),
      onSuccess: refresh,
    }),
    setAccounts: useMutation({
      mutationFn: (v: { id: string; accountIds: string[] }) => portalApi.setGroupAccounts(v.id, v.accountIds),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: string) => portalApi.deleteGroup(id), onSuccess: refresh }),
  }
}
