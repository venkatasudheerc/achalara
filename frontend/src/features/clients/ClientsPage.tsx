import { useState, type FormEvent } from 'react'
import { flushSync } from 'react-dom'
import { Link, useNavigate } from 'react-router-dom'
import { useCreateClient, useClientsList } from '@/hooks/useClients'
import { useScope } from '@/context/ScopeContext'
import { useIsAdmin, useUsers } from '@/hooks/useAuth'
import type { ClientResponse } from '@/api/types'

type Mode = 'list' | 'create'

export function ClientsPage() {
  const navigate = useNavigate()
  const { setClient } = useScope()
  const createClient = useCreateClient()

  const { data: apiClients, isLoading } = useClientsList()
  const clients: ClientResponse[] = apiClients ?? []
  // The admin assigns clients to advisors; an advisor's list is only their own.
  const isAdmin = useIsAdmin()
  const { data: users } = useUsers(isAdmin)
  const advisors = (users ?? []).filter((u) => u.role === 'advisor')
  const advisorName = (id: string | null) => (id ? advisors.find((a) => a.id === id)?.name ?? 'An advisor' : null)

  const [mode, setMode] = useState<Mode>('list')
  const [name, setName] = useState('')
  const [createEmail, setCreateEmail] = useState('')
  const [advisorId, setAdvisorId] = useState('')
  const [error, setError] = useState('')

  const handleCreate = async (e: FormEvent) => {
    e.preventDefault()
    setError('')
    try {
      await createClient.mutateAsync({
        name: name.trim(),
        email: createEmail.trim().toLowerCase() || null,
        ...(isAdmin ? { advisor_id: advisorId || null } : {}),
      })
      setName('')
      setCreateEmail('')
      setAdvisorId('')
      setMode('list')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  const selectClient = (c: ClientResponse) => {
    flushSync(() => setClient(c.id, c.name))
    navigate('/app/performance')
  }

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="font-display text-2xl text-summit-ink">Clients</h1>
          <p className="text-stone text-sm mt-1">
            {isAdmin ? 'Every client of the firm.' : 'The clients assigned to you.'} Open one to manage its accounts, its login and its family.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => { setMode('create'); setError('') }}
            className={`px-3 py-1.5 text-sm rounded-btn border transition-colors ${
              mode === 'create'
                ? 'border-gold bg-gold text-on-gold'
                : 'border-stone/30 text-stone hover:border-gold hover:text-summit-ink'
            }`}
          >
            + New client
          </button>
        </div>
      </div>

      {/* Create form */}
      {mode === 'create' && (
        <form
          onSubmit={handleCreate}
          className="mb-6 border border-stone/20 rounded-card p-6 bg-mist/30"
        >
          <h2 className="font-medium text-summit-ink mb-1">Create a new client</h2>
          <p className="text-xs text-stone mb-4">
            The email is what the client will sign in with once you invite them. Leave it empty for a minor
            without one; you can invite them later with any address.
          </p>
          <div className={`grid grid-cols-1 gap-4 ${isAdmin ? 'sm:grid-cols-3' : 'sm:grid-cols-2'}`}>
            <div>
              <label className="text-xs text-stone block mb-1">Client name</label>
              <input
                required
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Acme Corp"
                className="w-full border border-stone/30 rounded-btn px-3 py-2 text-sm focus:outline-none focus:border-pine"
              />
            </div>
            <div>
              <label className="text-xs text-stone block mb-1">Email (optional)</label>
              <input
                type="email"
                value={createEmail}
                onChange={(e) => setCreateEmail(e.target.value)}
                placeholder="contact@acme.com"
                className="w-full border border-stone/30 rounded-btn px-3 py-2 text-sm focus:outline-none focus:border-pine"
              />
            </div>
            {isAdmin && (
              <div>
                <label htmlFor="new-client-advisor" className="text-xs text-stone block mb-1">Advisor</label>
                <select id="new-client-advisor" value={advisorId} onChange={(e) => setAdvisorId(e.target.value)}
                  className="w-full border border-stone/30 rounded-btn px-3 py-2 text-sm bg-surface focus:outline-none focus:border-pine">
                  <option value="">None (yours)</option>
                  {advisors.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
            )}
          </div>
          {error && <p className="text-loss text-xs mt-3">{error}</p>}
          <div className="flex items-center gap-3 mt-4">
            <button
              type="submit"
              disabled={createClient.isPending}
              className="px-4 py-2 bg-gold text-on-gold text-sm rounded-btn hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {createClient.isPending ? 'Creating…' : 'Create client'}
            </button>
            <button
              type="button"
              onClick={() => { setMode('list'); setError('') }}
              className="text-sm text-stone hover:text-summit-ink transition-colors"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* Loading state */}
      {isLoading && mode === 'list' && (
        <div className="divide-y divide-stone/10 border border-stone/20 rounded-card overflow-hidden animate-pulse">
          {[1, 2].map((i) => (
            <div key={i} className="flex items-center justify-between px-6 py-4">
              <div className="space-y-2">
                <div className="h-4 w-32 bg-stone/20 rounded" />
                <div className="h-3 w-48 bg-stone/10 rounded" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Client list */}
      {!isLoading && clients.length > 0 && mode === 'list' && (
        <div className="divide-y divide-stone/10 border border-stone/20 rounded-card overflow-hidden">
          {clients.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between px-6 py-4 hover:bg-mist/40 transition-colors"
            >
              <div>
                <p className="font-medium text-summit-ink">{c.name}</p>
                <p className="text-xs text-stone">
                  <span className="font-mono">{c.email ?? 'No email'}</span>
                  {isAdmin && <span> · {advisorName(c.advisor_id) ? `Advisor: ${advisorName(c.advisor_id)}` : 'No advisor'}</span>}
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => selectClient(c)}
                  className="px-3 py-1.5 text-xs border border-pine text-pine rounded-btn hover:bg-pine hover:text-on-dark transition-colors"
                >
                  View performance
                </button>
                <Link
                  to={`/app/clients/${c.id}`}
                  className="px-3 py-1.5 text-xs border border-stone/30 text-stone rounded-btn hover:border-summit-ink hover:text-summit-ink transition-colors"
                >
                  Manage
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty list with no form shown */}
      {!isLoading && clients.length === 0 && mode === 'list' && (
        <p className="text-center py-16 text-stone text-sm">
          No clients yet.{' '}
          <button onClick={() => setMode('create')} className="text-pine underline underline-offset-2">
            Create one
          </button>.
        </p>
      )}
    </div>
  )
}
