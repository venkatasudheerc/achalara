import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { clientsApi } from '@/api/endpoints/clients'
import type { ClientCreate, ClientUpdate, RelativeCreate } from '@/api/types'

export const clientKeys = {
  list: (skip?: number, limit?: number) => ['clients', 'list', skip, limit] as const,
  detail: (id: string) => ['clients', id] as const,
  performance: (id: string, start?: string, end?: string) =>
    ['clients', id, 'performance', start, end] as const,
  monthlyPerformance: (id: string) => ['clients', id, 'performance', 'monthly'] as const,
  returnsSeries: (id: string, start?: string, end?: string) =>
    ['clients', id, 'performance', 'returns-series', start, end] as const,
  positions: (id: string) => ['clients', id, 'positions'] as const,
  trades: (id: string, skip?: number, limit?: number) =>
    ['clients', id, 'trades', skip, limit] as const,
  relatives: (id: string) => ['clients', id, 'relatives'] as const,
}

export function useClientsList(skip = 0, limit = 100) {
  return useQuery({
    queryKey: clientKeys.list(skip, limit),
    queryFn: () => clientsApi.list({ skip, limit }),
  })
}

export function useClient(clientId: string) {
  return useQuery({
    queryKey: clientKeys.detail(clientId),
    queryFn: () => clientsApi.get(clientId),
    enabled: !!clientId,
  })
}

export function useClientPerformance(
  clientId: string,
  params?: { start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: clientKeys.performance(clientId, params?.start_date, params?.end_date),
    queryFn: () => clientsApi.getPerformance(clientId, params),
    enabled: !!clientId,
  })
}

export function useClientMonthlyPerformance(clientId: string) {
  return useQuery({
    queryKey: clientKeys.monthlyPerformance(clientId),
    queryFn: () => clientsApi.getMonthlyPerformance(clientId),
    enabled: !!clientId,
  })
}

export function useClientReturnsSeries(
  clientId: string,
  params?: { start_date?: string; end_date?: string }
) {
  return useQuery({
    queryKey: clientKeys.returnsSeries(clientId, params?.start_date, params?.end_date),
    queryFn: () => clientsApi.getReturnsSeries(clientId, params),
    enabled: !!clientId,
  })
}

export function useClientPositions(clientId: string) {
  return useQuery({
    queryKey: clientKeys.positions(clientId),
    queryFn: () => clientsApi.getPositions(clientId),
    enabled: !!clientId,
  })
}

export function useClientTrades(clientId: string, skip = 0, limit = 100) {
  return useQuery({
    queryKey: clientKeys.trades(clientId, skip, limit),
    queryFn: () => clientsApi.getTrades(clientId, { skip, limit }),
    enabled: !!clientId,
  })
}

export function useCreateClient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: ClientCreate) => clientsApi.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['clients'] }),
  })
}

export function useUpdateClient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ clientId, body }: { clientId: string; body: ClientUpdate }) => clientsApi.update(clientId, body),
    // The name also shows on the client list and, through the login, in the portal.
    onSuccess: () => qc.invalidateQueries(),
  })
}

/** The client's spouse and minors, with whether each has a login. */
export function useClientRelatives(clientId: string) {
  return useQuery({
    queryKey: clientKeys.relatives(clientId),
    queryFn: () => clientsApi.relatives(clientId),
    enabled: !!clientId,
  })
}

/**
 * Changes to who is whose spouse or minor. Each touches two clients and what
 * both may see, so every client query is fetched again afterwards.
 */
export function useFamilyChanges() {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: ['clients'] })
  return {
    setSpouse: useMutation({
      mutationFn: (v: { clientId: string; spouseId: string | null }) => clientsApi.setSpouse(v.clientId, v.spouseId),
      onSuccess: refresh,
    }),
    setGuardian: useMutation({
      mutationFn: (v: { clientId: string; guardianId: string | null }) => clientsApi.setGuardian(v.clientId, v.guardianId),
      onSuccess: refresh,
    }),
    addRelative: useMutation({
      mutationFn: (v: { clientId: string; body: RelativeCreate }) => clientsApi.addRelative(v.clientId, v.body),
      onSuccess: refresh,
    }),
  }
}
