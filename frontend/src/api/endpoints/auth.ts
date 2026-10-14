import { apiClient } from '../client'
import type {
  EmailLinkResponse,
  AccountAccessResponse, LinkPreview, LinkResponse, LoginRequest, MeResponse, UserResponse,
} from '../types'

const base = '/api/v1/auth'

export const authApi = {
  me: () => apiClient.get<MeResponse>(`${base}/me`).then((r) => r.data),

  login: (body: LoginRequest) =>
    apiClient.post<MeResponse>(`${base}/login`, body).then((r) => r.data),

  logout: () => apiClient.post<void>(`${base}/logout`).then((r) => r.data),

  users: () => apiClient.get<UserResponse[]>(`${base}/users`).then((r) => r.data),

  /** `email` is the address the client will sign in with; the client's own when omitted. */
  invite: (clientId: string, email?: string) =>
    apiClient.post<LinkResponse>(`${base}/invites`, { client_id: clientId, email }).then((r) => r.data),

  /** Changes a client's sign-in email and returns a link (reset, or a fresh invite) to send them. */
  changeEmail: (userId: string, email: string) =>
    apiClient.patch<LinkResponse>(`${base}/users/${userId}/email`, { email }).then((r) => r.data),

  passwordReset: (userId: string) =>
    apiClient.post<LinkResponse>(`${base}/users/${userId}/password-reset`).then((r) => r.data),

  /** Emails an unused link to the sign-in address it was made for. */
  emailLink: (token: string) =>
    apiClient.post<EmailLinkResponse>(`${base}/link-emails`, { token }).then((r) => r.data),

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
