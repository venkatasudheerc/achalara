import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { plaidApi } from '@/api/endpoints/plaid'
import type { PlaidChoice } from '@/api/types'
import { usePreviewClient } from '@/hooks/usePortal'

/** Whether linking with Plaid is offered here, and how many logins are left. */
export function usePlaidAvailability() {
  const asClient = usePreviewClient()
  return useQuery({ queryKey: ['plaid', 'availability', asClient], queryFn: () => plaidApi.availability(asClient), staleTime: 60_000 })
}

/** Start a link, finish it, and confirm what each account is. After confirming,
 * every view of the client's accounts is fetched again. */
export function usePlaidLink() {
  const qc = useQueryClient()
  const asClient = usePreviewClient()
  return {
    start: useMutation({ mutationFn: () => plaidApi.start(asClient) }),
    finish: useMutation({ mutationFn: (publicToken: string) => plaidApi.finish(publicToken, asClient) }),
    confirm: useMutation({
      mutationFn: (v: { connectionId: string; choices: PlaidChoice[] }) => plaidApi.confirm(v.connectionId, v.choices, asClient),
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: ['portal'] })
        qc.invalidateQueries({ queryKey: ['plaid'] })
      },
    }),
  }
}

/** Bring the viewer's own linked accounts up to date now; every view is then
 * fetched again. */
export function usePlaidRefresh() {
  const qc = useQueryClient()
  const asClient = usePreviewClient()
  return useMutation({
    mutationFn: () => plaidApi.refreshMine(asClient),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['portal'] }),
  })
}

/** Check logins for accounts not seen before: all the viewer's own at once, or
 * one with what is proposed for each of its accounts. The connections list is
 * fetched again, since it says how many accounts wait. */
export function usePlaidDiscover() {
  const qc = useQueryClient()
  const asClient = usePreviewClient()
  const refetch = () => qc.invalidateQueries({ queryKey: ['portal'] })
  return {
    all: useMutation({ mutationFn: () => plaidApi.discoverMine(asClient), onSuccess: refetch }),
    one: useMutation({ mutationFn: (connectionId: string) => plaidApi.discover(connectionId, asClient), onSuccess: refetch }),
    /** A token for Plaid Link in update mode where the client may share more accounts. */
    select: useMutation({ mutationFn: (connectionId: string) => plaidApi.repair(connectionId, asClient, true) }),
  }
}

/** Sign in again to a login Plaid has stopped reading. Afterwards every view of
 * the accounts is fetched again, since the login was brought up to date. */
export function usePlaidRepair() {
  const qc = useQueryClient()
  const asClient = usePreviewClient()
  return {
    start: useMutation({ mutationFn: (loginId: string) => plaidApi.repair(loginId, asClient) }),
    done: useMutation({
      mutationFn: (loginId: string) => plaidApi.repaired(loginId, asClient),
      onSuccess: () => qc.invalidateQueries({ queryKey: ['portal'] }),
    }),
  }
}
