import { apiClient } from '../client'
import type {
  ImportResponse, SyncDailyResponse,
  SyncLogsResponse, SheetSyncConfig, SyncConfigCreate, SyncConfigUpdate, SystemStatusResponse,
} from '../types'

export const adminApi = {
  status: () => apiClient.get<SystemStatusResponse>('/api/v1/admin/status').then((r) => r.data),
  /** Sends a test message through the alert channel. */
  testAlert: () =>
    apiClient.post<{ sent: boolean }>('/api/v1/admin/status/test-alert').then((r) => r.data),
  /** Asks the source now whether each brokerage link still shares data; returns the status afresh. */
  checkLinks: () =>
    apiClient.post<SystemStatusResponse>('/api/v1/admin/status/check-links').then((r) => r.data),

  importHistorical: (
    params: { client_id: string; sleeve_id?: string; mode: 'VALIDATE' | 'IMPORT' },
    file: File
  ) => {
    const form = new FormData()
    form.append('file', file)
    return apiClient
      .post<ImportResponse>('/api/v1/admin/import-historical', form, {
        params,
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },

  syncDaily: (params: {
    client_id: string; sleeve_id: string; sheet_id: string; range_name?: string
  }) =>
    apiClient
      .post<SyncDailyResponse>('/api/v1/admin/sync-daily', null, { params })
      .then((r) => r.data),

  getSyncLogs: (params: { client_id: string; skip?: number; limit?: number }) =>
    apiClient
      .get<SyncLogsResponse>('/api/v1/admin/sync-logs', { params })
      .then((r) => r.data),

  createSyncConfig: (body: SyncConfigCreate) =>
    apiClient
      .post<SheetSyncConfig>('/api/v1/admin/sync-configs', body)
      .then((r) => r.data),

  listSyncConfigs: (params?: { client_id?: string }) =>
    apiClient
      .get<SheetSyncConfig[]>('/api/v1/admin/sync-configs', { params })
      .then((r) => r.data),

  updateSyncConfig: (configId: string, body: SyncConfigUpdate) =>
    apiClient
      .patch<SheetSyncConfig>(`/api/v1/admin/sync-configs/${configId}`, body)
      .then((r) => r.data),

  deleteSyncConfig: (configId: string) =>
    apiClient.delete(`/api/v1/admin/sync-configs/${configId}`),
}
