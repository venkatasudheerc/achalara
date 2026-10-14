import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { invitationsApi } from '@/api/endpoints/invitations'
import type { InvitationRequestCreate, InvitationStatus } from '@/api/types'

const listKey = ['admin', 'invitation-requests'] as const

export function useRequestInvitation() {
  return useMutation({ mutationFn: (body: InvitationRequestCreate) => invitationsApi.request(body) })
}

export function useConfirmInvitation() {
  return useMutation({ mutationFn: (token: string) => invitationsApi.confirm(token) })
}

export function useInvitationRequests() {
  return useQuery({ queryKey: listKey, queryFn: () => invitationsApi.list(), refetchInterval: 60_000 })
}

export function useSetInvitationStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: InvitationStatus }) => invitationsApi.setStatus(id, status),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: listKey })
      qc.invalidateQueries({ queryKey: ['admin', 'status'] })
    },
  })
}
