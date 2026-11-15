import { useState } from 'react'
import { usePlaidRepair } from '@/hooks/usePlaid'
import { loadPlaid } from '@/lib/plaid'

/**
 * Plaid Link in update mode for one of the viewer's own logins that stopped
 * sharing: no new place on the plan is used and its history carries on.
 */
export function useSignInAgain() {
  const repair = usePlaidRepair()
  const [working, setWorking] = useState<string | null>(null)
  const [error, setError] = useState('')

  const signIn = async (loginId: string) => {
    setError(''); setWorking(loginId)
    try {
      const [{ link_token }, Plaid] = await Promise.all([repair.start.mutateAsync(loginId), loadPlaid()])
      const handler = Plaid.create({
        token: link_token,
        onSuccess: () => {
          repair.done.mutate(loginId, {
            onSuccess: (r) => {
              if (r.status !== 'active') setError('The institution still asks to sign in. Try again in a moment.')
              setWorking(null)
            },
            onError: (e) => { setError(e.message); setWorking(null) },
          })
          handler.destroy()
        },
        onExit: (err) => {
          if (err) setError(err.display_message || err.error_message || 'Signing in did not finish.')
          setWorking(null)
          handler.destroy()
        },
      })
      handler.open()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start signing in.')
      setWorking(null)
    }
  }
  return { signIn, working, error }
}
