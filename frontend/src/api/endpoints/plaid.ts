import { apiClient } from '../client'
import type { PlaidChoice, PlaidConfirmed, PlaidDiscovered, PlaidFound, PlaidLinkAvailability, PlaidLinkStart, PlaidRefreshed, PlaidRepaired } from '../types'

const base = '/api/v1/portal/links/plaid'
/** An advisor previewing a client links for them, as the client would. */
const params = (asClient?: string) => (asClient ? { as_client: asClient } : undefined)

export const plaidApi = {
  refreshMine: (asClient?: string) =>
    apiClient.post<PlaidRefreshed>(`${base}/refresh`, null, { params: params(asClient) }).then((r) => r.data),
  availability: (asClient?: string) =>
    apiClient.get<PlaidLinkAvailability>(base, { params: params(asClient) }).then((r) => r.data),
  start: (asClient?: string) =>
    apiClient.post<PlaidLinkStart>(`${base}/start`, null, { params: params(asClient) }).then((r) => r.data),
  finish: (publicToken: string, asClient?: string) =>
    apiClient.post<PlaidFound>(`${base}/finish`, { public_token: publicToken }, { params: params(asClient) }).then((r) => r.data),
  found: (connectionId: string, asClient?: string) =>
    apiClient.get<PlaidFound>(`${base}/${connectionId}`, { params: params(asClient) }).then((r) => r.data),
  /** Opens Plaid Link to sign in again to one of the viewer's logins (no new place used). */
  repair: (connectionId: string, asClient?: string, selectAccounts = false) =>
    apiClient
      .post<PlaidLinkStart>(`${base}/${connectionId}/repair`, null, {
        params: { ...params(asClient), ...(selectAccounts ? { select_accounts: true } : {}) },
      })
      .then((r) => r.data),
  /** Each of the viewer's own logins checked for accounts not seen before. */
  discoverMine: (asClient?: string) =>
    apiClient.post<PlaidDiscovered>(`${base}/discover`, null, { params: params(asClient) }).then((r) => r.data),
  /** One login checked, answering with its accounts and what is proposed for each. */
  discover: (connectionId: string, asClient?: string) =>
    apiClient.post<PlaidFound>(`${base}/${connectionId}/discover`, null, { params: params(asClient) }).then((r) => r.data),
  repaired: (connectionId: string, asClient?: string) =>
    apiClient.post<PlaidRepaired>(`${base}/${connectionId}/repaired`, null, { params: params(asClient) }).then((r) => r.data),
  confirm: (connectionId: string, choices: PlaidChoice[], asClient?: string) =>
    apiClient.post<PlaidConfirmed>(`${base}/${connectionId}/confirm`, { choices }, { params: params(asClient) }).then((r) => r.data),
}
