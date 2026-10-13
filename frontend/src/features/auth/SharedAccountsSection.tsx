import { useState } from 'react'
import { useAccountAccess, useGrantAccess, useRevokeAccess } from '@/hooks/useAuth'
import { useClientsList } from '@/hooks/useClients'
import { useAccounts } from '@/hooks/useAccounts'

/**
 * Advisor's control over which accounts of *other* clients this client may
 * view (read-only), for example someone acting as agent on a relative's account.
 */
export function SharedAccountsSection({ clientId }: { clientId: string }) {
  const { data: grants, isLoading, isError } = useAccountAccess(clientId)
  const { data: clients } = useClientsList()
  const grant = useGrantAccess(clientId)
  const revoke = useRevokeAccess(clientId)
  const [ownerId, setOwnerId] = useState('')
  const [accountId, setAccountId] = useState('')
  const { data: ownerAccounts } = useAccounts(ownerId)

  const others = (clients ?? []).filter((c) => c.id !== clientId)
  const shared = new Set((grants ?? []).map((g) => g.account_id))
  const choices = (ownerAccounts ?? []).filter((a) => !shared.has(a.id))
  const error = grant.error ?? revoke.error

  const share = async () => {
    try {
      await grant.mutateAsync(accountId)
      setAccountId('')
    } catch {
      // Shown below from the mutation's error.
    }
  }

  const select = 'border border-stone/30 rounded-btn px-2 py-1.5 text-sm bg-surface focus:outline-none focus:border-pine'

  return (
    <section className="border border-stone/20 rounded-card p-6">
      <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-2">Accounts shared with this client</h2>
      <p className="text-sm text-stone mb-16">
        Accounts owned by other clients that this client may view in their portal. Viewing only; the owner still sees
        the account as their own.
      </p>

      {isLoading && <p className="text-sm text-stone">Loading…</p>}
      {isError && <p className="text-sm text-loss">Could not load shared accounts.</p>}
      {grants && grants.length === 0 && <p className="text-sm text-stone py-1">None shared.</p>}
      {grants && grants.length > 0 && (
        <ul className="divide-y divide-stone/10 mb-2">
          {grants.map((g) => (
            <li key={g.account_id} className="flex items-center justify-between py-3">
              <div>
                <p className="text-sm font-medium text-summit-ink">{g.account_name}</p>
                <p className="text-xs text-stone">Owned by {g.owner_name}</p>
              </div>
              <button onClick={() => revoke.mutate(g.account_id)} disabled={revoke.isPending}
                className="text-xs border border-stone/30 text-stone rounded-btn px-3 py-1.5 hover:border-loss hover:text-loss transition-colors disabled:opacity-50">
                Stop sharing
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-end gap-3 mt-16 p-16 bg-mist/30 rounded-btn">
        <div>
          <label htmlFor="share-owner" className="text-xs text-stone block mb-1">Owner</label>
          <select id="share-owner" value={ownerId} className={select}
            onChange={(e) => { setOwnerId(e.target.value); setAccountId('') }}>
            <option value="">Choose a client…</option>
            {others.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor="share-account" className="text-xs text-stone block mb-1">Account</label>
          <select id="share-account" value={accountId} disabled={!ownerId} className={`${select} disabled:opacity-50`}
            onChange={(e) => setAccountId(e.target.value)}>
            <option value="">{ownerId && choices.length === 0 ? 'No accounts left to share' : 'Choose an account…'}</option>
            {choices.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </div>
        <button onClick={share} disabled={!accountId || grant.isPending}
          className="px-3 py-1.5 bg-pine text-on-dark text-xs rounded-btn hover:bg-pine-deep disabled:opacity-50">
          {grant.isPending ? 'Sharing…' : 'Share account'}
        </button>
      </div>
      {error && <p className="text-loss text-xs mt-3">{error.message}</p>}
    </section>
  )
}
