import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { connectionsApi } from '@/api/endpoints/connections'
import type { BrokerageAccountUpdate } from '@/api/types'

export const connectionKeys = {
  list: (clientId: string) => ['connections', clientId] as const,
}

export function useConnections(clientId: string) {
  return useQuery({
    queryKey: connectionKeys.list(clientId),
    queryFn: () => connectionsApi.list(clientId),
    enabled: !!clientId,
  })
}

export function useStartLink() {
  return useMutation({
    mutationFn: ({ clientId, redirectUri }: { clientId: string; redirectUri: string }) =>
      connectionsApi.startLink(clientId, redirectUri),
  })
}

export function useDiscoverConnections() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (clientId: string) => connectionsApi.discover(clientId),
    onSuccess: (data, clientId) => qc.setQueryData(connectionKeys.list(clientId), data),
  })
}

export function useRemoveConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (connectionId: string) => connectionsApi.remove(connectionId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['connections'] }),
  })
}

export function useUpdateBrokerageAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: BrokerageAccountUpdate }) =>
      connectionsApi.updateAccount(id, body),
    // Mapping can create an account, a strategy and a sleeve.
    onSuccess: () => qc.invalidateQueries(),
  })
}

export function useSyncBrokerageAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (brokerageAccountId: string) => connectionsApi.syncAccount(brokerageAccountId),
    // New trades change positions and performance at every level.
    onSuccess: () => qc.invalidateQueries(),
  })
}
