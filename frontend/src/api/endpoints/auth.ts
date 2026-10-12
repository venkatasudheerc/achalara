import { apiClient } from '../client'
import type {
  AccountAccessResponse, LinkPreview, LinkResponse, LoginRequest, MeResponse, UserResponse,
} from '../types'

const base = '/api/v1/auth'

export const authApi = {
  me: () => apiClient.get<MeResponse>(`${base}/me`).then((r) => r.data),

  login: (body: LoginRequest) =>
    apiClient.post<MeResponse>(`${base}/login`, body).then((r) => r.data),

  logout: () => apiClient.post<void>(`${base}/logout`).then((r) => r.data),

  users: () => apiClient.get<UserResponse[]>(`${base}/users`).then((r) => r.data),

  invite: (clientId: string) =>
    apiClient.post<LinkResponse>(`${base}/invites`, { client_id: clientId }).then((r) => r.data),

  passwordReset: (userId: string) =>
    apiClient.post<LinkResponse>(`${base}/users/${userId}/password-reset`).then((r) => r.data),

  previewLink: (token: string) =>
    apiClient.get<LinkPreview>(`${base}/links/${token}`).then((r) => r.data),

  acceptLink: (token: string, password: string) =>
    apiClient.post<MeResponse>(`${base}/links/${token}/accept`, { password }).then((r) => r.data),

  accountAccess: (clientId: string) =>
    apiClient
      .get<AccountAccessResponse[]>(`/api/v1/clients/${clientId}/account-access`)
      .then((r) => r.data),

  grantAccess: (clientId: string, accountId: string) =>
    apiClient
      .post<AccountAccessResponse>(`/api/v1/clients/${clientId}/account-access`, { account_id: accountId })
      .then((r) => r.data),

  revokeAccess: (clientId: string, accountId: string) =>
    apiClient
      .delete<void>(`/api/v1/clients/${clientId}/account-access/${accountId}`)
      .then((r) => r.data),
}
