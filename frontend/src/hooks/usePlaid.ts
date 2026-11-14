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
