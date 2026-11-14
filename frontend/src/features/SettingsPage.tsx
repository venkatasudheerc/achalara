import { useState, type FormEvent } from 'react'
import { useClientsList } from '@/hooks/useClients'
import { useInviteAdvisor, useUsers } from '@/hooks/useAuth'
import { formatDate } from '@/lib/formatters'
import { OneTimeLink } from '@/features/auth/OneTimeLink'
import type { LinkResponse, UserResponse } from '@/api/types'

const field = 'w-full border border-stone/30 rounded-btn px-3 py-2 text-sm bg-surface focus:outline-none focus:border-pine'

/** Whether an advisor has accepted their invite and signed in. */
function signInState(u: UserResponse): string {
  if (!u.is_active) return 'Turned off'
  if (!u.has_password) return 'Invited; has not set a password yet'
  return u.last_login_at ? `Last signed in ${formatDate(u.last_login_at)}` : 'Set a password; not signed in since'
}

/** The admin's list of advisors, and inviting a new one. */
function AdvisorsSection() {
  const { data: users, isLoading, isError, refetch } = useUsers()
  const { data: clients = [] } = useClientsList()
  const invite = useInviteAdvisor()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [link, setLink] = useState<LinkResponse | null>(null)

  const advisors = (users ?? []).filter((u) => u.role === 'advisor')
  const clientCount = (id: string) => clients.filter((c) => c.advisor_id === id).length

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setLink(null)
    try {
      setLink(await invite.mutateAsync({ name: name.trim(), email: email.trim().toLowerCase() }))
      setName(''); setEmail(''); setOpen(false)
    } catch {
      // Shown below from the mutation's error.
    }
  }

  return (
    <section className="border border-stone/20 rounded-card p-6">
      <div className="flex items-center justify-between gap-3 mb-2">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone">Advisors</h2>
        {!open && (
          <button onClick={() => { invite.reset(); setOpen(true) }}
            className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-on-dark transition-colors">
            + Invite an advisor
          </button>
        )}
      </div>
      <p className="text-sm text-stone mb-16">
        An advisor manages only the clients assigned to them: their accounts, logins and family. Assign a client
        on the client's page. System status, market data, imports, requests and strategies stay with you.
      </p>

      {open && (
        <form onSubmit={submit} className="mb-16 p-16 bg-mist/30 rounded-btn space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="advisor-name" className="text-xs text-stone block mb-1">Name</label>
              <input id="advisor-name" required autoFocus value={name} onChange={(e) => setName(e.target.value)} className={field} />
            </div>
            <div>
              <label htmlFor="advisor-email" className="text-xs text-stone block mb-1">Sign-in email</label>
              <input id="advisor-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
                className={`${field} font-mono`} />
            </div>
          </div>
          {invite.isError && <p className="text-loss text-xs">{invite.error.message}</p>}
          <div className="flex gap-2">
            <button type="submit" disabled={invite.isPending}
              className="px-3 py-1.5 bg-pine text-on-dark text-xs rounded-btn hover:bg-pine-deep disabled:opacity-50">
              {invite.isPending ? 'Creating…' : 'Create invite link'}
            </button>
            <button type="button" onClick={() => setOpen(false)} className="px-3 py-1.5 text-xs text-stone hover:text-summit-ink">
              Cancel
            </button>
          </div>
        </form>
      )}

      {link && <OneTimeLink link={link} whose="this advisor's login" />}

      {isLoading && <p className="text-stone text-sm">Loading…</p>}
      {isError && (
        <p className="text-loss text-sm">
          Could not load the advisors. <button onClick={() => refetch()} className="underline underline-offset-2">Try again</button>
        </p>
      )}
      {users && advisors.length === 0 && <p className="text-stone text-sm py-1">No advisors yet. Every client is yours.</p>}
      {advisors.length > 0 && (
        <ul className="divide-y divide-stone/10 mt-2">
          {advisors.map((a) => (
            <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-summit-ink">{a.name}</p>
                <p className="text-xs text-stone font-mono truncate">{a.email}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-summit-ink">{signInState(a)}</p>
                <p className="text-xs text-stone">
                  <span className="font-mono">{clientCount(a.id)}</span> {clientCount(a.id) === 1 ? 'client' : 'clients'}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/** Settings: the admin's alone (the route is guarded). */
export function SettingsPage() {
  const { data: clients = [], isLoading } = useClientsList()

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="font-display text-2xl text-summit-ink">Settings</h1>
        <p className="text-stone text-sm mt-1">Platform configuration.</p>
      </div>

      <AdvisorsSection />

      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">Clients</h2>
        {isLoading ? (
          <p className="text-stone text-sm">Loading…</p>
        ) : clients.length ? (
          <ul className="space-y-2">
            {clients.map((c) => (
              <li key={c.id} className="text-sm font-mono text-stone">
                <span className="text-summit-ink">{c.name}</span>{c.email ? ` — ${c.email}` : ''}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-stone text-sm">No clients found.</p>
        )}
      </section>

      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-2">Sign-in</h2>
        <p className="text-sm text-stone">
          The admin, advisors and clients sign in with an email and password. Invite an advisor above. Invite a
          client, or send a password-reset link, from that client's page.
        </p>
      </section>
    </div>
  )
}
