import { apiClient } from '../client'
import type { PlaidChoice, PlaidConfirmed, PlaidFound, PlaidLinkAvailability, PlaidLinkStart, PlaidRepaired } from '../types'

const base = '/api/v1/portal/links/plaid'
/** An advisor previewing a client links for them, as the client would. */
const params = (asClient?: string) => (asClient ? { as_client: asClient } : undefined)

export const plaidApi = {
  availability: (asClient?: string) =>
    apiClient.get<PlaidLinkAvailability>(base, { params: params(asClient) }).then((r) => r.data),
  start: (asClient?: string) =>
    apiClient.post<PlaidLinkStart>(`${base}/start`, null, { params: params(asClient) }).then((r) => r.data),
  finish: (publicToken: string, asClient?: string) =>
    apiClient.post<PlaidFound>(`${base}/finish`, { public_token: publicToken }, { params: params(asClient) }).then((r) => r.data),
  found: (connectionId: string, asClient?: string) =>
    apiClient.get<PlaidFound>(`${base}/${connectionId}`, { params: params(asClient) }).then((r) => r.data),
  /** Opens Plaid Link to sign in again to one of the viewer's logins (no new place used). */
  repair: (connectionId: string, asClient?: string) =>
    apiClient.post<PlaidLinkStart>(`${base}/${connectionId}/repair`, null, { params: params(asClient) }).then((r) => r.data),
  repaired: (connectionId: string, asClient?: string) =>
    apiClient.post<PlaidRepaired>(`${base}/${connectionId}/repaired`, null, { params: params(asClient) }).then((r) => r.data),
  confirm: (connectionId: string, choices: PlaidChoice[], asClient?: string) =>
    apiClient.post<PlaidConfirmed>(`${base}/${connectionId}/confirm`, { choices }, { params: params(asClient) }).then((r) => r.data),
}
