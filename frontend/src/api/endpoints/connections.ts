import { apiClient } from '../client'
import type {
  Connection, LinkResponse, BrokerageAccount, BrokerageAccountUpdate, BrokerageSyncResult,
} from '../types'

export const connectionsApi = {
  startLink: (clientId: string, redirectUri: string) =>
    apiClient
      .post<LinkResponse>(`/api/v1/clients/${clientId}/connections/snaptrade/link`, {
        redirect_uri: redirectUri,
      })
      .then((r) => r.data),

  discover: (clientId: string) =>
    apiClient
      .post<Connection[]>(`/api/v1/clients/${clientId}/connections/discover`)
      .then((r) => r.data),

  list: (clientId: string) =>
    apiClient.get<Connection[]>(`/api/v1/clients/${clientId}/connections`).then((r) => r.data),

  remove: (connectionId: string) =>
    apiClient.delete(`/api/v1/connections/${connectionId}`).then(() => undefined),

  updateAccount: (brokerageAccountId: string, body: BrokerageAccountUpdate) =>
    apiClient
      .patch<BrokerageAccount>(`/api/v1/brokerage-accounts/${brokerageAccountId}`, body)
      .then((r) => r.data),

  syncAccount: (brokerageAccountId: string) =>
    apiClient
      .post<BrokerageSyncResult>(`/api/v1/brokerage-accounts/${brokerageAccountId}/sync`)
      .then((r) => r.data),
}
