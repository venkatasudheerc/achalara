import { apiClient } from '../client'
import type { InvitationRequest, InvitationRequestCreate, InvitationStatus } from '../types'

export const invitationsApi = {
  /** The public page's form. Answers the same way whatever became of the request. */
  request: (body: InvitationRequestCreate) =>
    apiClient.post<{ received: boolean }>('/api/v1/invitation-requests', body).then((r) => r.data),

  list: () =>
    apiClient.get<InvitationRequest[]>('/api/v1/admin/invitation-requests').then((r) => r.data),

  setStatus: (id: string, status: InvitationStatus) =>
    apiClient
      .patch<InvitationRequest>(`/api/v1/admin/invitation-requests/${id}`, { status })
      .then((r) => r.data),
}
