import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { authApi } from '@/api/endpoints/auth'
import type { LoginRequest } from '@/api/types'

export const authKeys = {
  me: () => ['auth', 'me'] as const,
  users: () => ['auth', 'users'] as const,
  link: (token: string) => ['auth', 'link', token] as const,
  access: (clientId: string) => ['auth', 'access', clientId] as const,
}

/** The signed-in user. An error here means nobody is signed in. */
export function useMe() {
  return useQuery({
    queryKey: authKeys.me(),
    queryFn: () => authApi.me(),
    retry: false,
    staleTime: 5 * 60_000,
  })
}

export function useLogin() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: LoginRequest) => authApi.login(body),
    onSuccess: (me) => {
      // Nothing fetched for a previous user may be shown to this one.
      qc.clear()
      qc.setQueryData(authKeys.me(), me)
    },
  })
}

export function useLogout() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSettled: () => qc.clear(),
  })
}

export function useUsers() {
  return useQuery({ queryKey: authKeys.users(), queryFn: () => authApi.users() })
}

export function useInviteClient() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (clientId: string) => authApi.invite(clientId),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.users() }),
  })
}

export function usePasswordReset() {
  return useMutation({ mutationFn: (userId: string) => authApi.passwordReset(userId) })
}

export function useLinkPreview(token: string) {
  return useQuery({
    queryKey: authKeys.link(token),
    queryFn: () => authApi.previewLink(token),
    enabled: !!token,
    retry: false,
  })
}

export function useAcceptLink(token: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (password: string) => authApi.acceptLink(token, password),
    onSuccess: (me) => {
      qc.clear()
      qc.setQueryData(authKeys.me(), me)
    },
  })
}

export function useAccountAccess(clientId: string) {
  return useQuery({
    queryKey: authKeys.access(clientId),
    queryFn: () => authApi.accountAccess(clientId),
    enabled: !!clientId,
  })
}

export function useGrantAccess(clientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (accountId: string) => authApi.grantAccess(clientId, accountId),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.access(clientId) }),
  })
}

export function useRevokeAccess(clientId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (accountId: string) => authApi.revokeAccess(clientId, accountId),
    onSuccess: () => qc.invalidateQueries({ queryKey: authKeys.access(clientId) }),
  })
}
