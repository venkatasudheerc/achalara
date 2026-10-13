import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { adminApi } from '@/api/endpoints/admin'
import type { SyncConfigCreate, SyncConfigUpdate } from '@/api/types'

export const adminKeys = {
  syncLogs: (clientId: string, skip?: number) => ['admin', 'sync-logs', clientId, skip] as const,
  syncConfigs: (clientId?: string) => ['admin', 'sync-configs', clientId] as const,
}

/** The system status, read again every half minute while the page is open. */
export function useSystemStatus() {
  return useQuery({
    queryKey: ['admin', 'status'] as const,
    queryFn: () => adminApi.status(),
    refetchInterval: 30_000,
  })
}

export function useSyncLogs(clientId: string, skip = 0, limit = 50) {
  return useQuery({
    queryKey: adminKeys.syncLogs(clientId, skip),
    queryFn: () => adminApi.getSyncLogs({ client_id: clientId, skip, limit }),
    enabled: !!clientId,
  })
}

export function useSyncConfigs(clientId?: string) {
  return useQuery({
    queryKey: adminKeys.syncConfigs(clientId),
    queryFn: () => adminApi.listSyncConfigs(clientId ? { client_id: clientId } : undefined),
  })
}

export function useImportHistorical() {
  return useMutation({
    mutationFn: ({
      params,
      file,
    }: {
      params: { client_id: string; sleeve_id?: string; mode: 'VALIDATE' | 'IMPORT' }
      file: File
    }) => adminApi.importHistorical(params, file),
  })
}

export function useSyncDaily() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (params: {
      client_id: string; sleeve_id: string; sheet_id: string; range_name?: string
    }) => adminApi.syncDaily(params),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'sync-logs'] }),
  })
}

export function useCreateSyncConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: SyncConfigCreate) => adminApi.createSyncConfig(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'sync-configs'] }),
  })
}

export function useUpdateSyncConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ configId, body }: { configId: string; body: SyncConfigUpdate }) =>
      adminApi.updateSyncConfig(configId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'sync-configs'] }),
  })
}

export function useDeleteSyncConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (configId: string) => adminApi.deleteSyncConfig(configId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin', 'sync-configs'] }),
  })
}
