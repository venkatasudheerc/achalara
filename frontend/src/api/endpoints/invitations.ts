import { apiClient } from '../client'
import type { InvitationRequest, InvitationRequestCreate, InvitationStatus } from '../types'

export const invitationsApi = {
  /** The public page's form. Answers the same way whatever became of the request. */
  request: (body: InvitationRequestCreate) =>
    apiClient
      .post<{ received: boolean; confirm_by_email: boolean }>('/api/v1/invitation-requests', body)
      .then((r) => r.data),

  /** Called from the page the emailed link opens, when the visitor presses Confirm. */
  confirm: (token: string) =>
    apiClient.post<{ confirmed: boolean }>('/api/v1/invitation-requests/confirm', { token }).then((r) => r.data),

  list: () =>
    apiClient.get<InvitationRequest[]>('/api/v1/admin/invitation-requests').then((r) => r.data),

  setStatus: (id: string, status: InvitationStatus) =>
    apiClient
      .patch<InvitationRequest>(`/api/v1/admin/invitation-requests/${id}`, { status })
      .then((r) => r.data),
}
