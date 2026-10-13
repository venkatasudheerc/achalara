import { useEffect, useState } from 'react'
import { useChangeSignInEmail, useInviteClient, usePasswordReset, useUsers } from '@/hooks/useAuth'
import { formatDate } from '@/lib/formatters'
import type { LinkResponse } from '@/api/types'

/**
 * Advisor's view of one client's login: its state, the email it signs in
 * with (the advisor's to set and to change), and the link to pass on.
 */
export function ClientLoginSection({ clientId, clientEmail }: { clientId: string; clientEmail: string }) {
  const { data: users, isLoading, isError } = useUsers()
  const invite = useInviteClient()
  const reset = usePasswordReset()
  const changeEmail = useChangeSignInEmail()
  const [link, setLink] = useState<LinkResponse | null>(null)
  const [copied, setCopied] = useState(false)

  const user = users?.find((u) => u.client_id === clientId)
  const current = user?.email ?? clientEmail
  const [email, setEmail] = useState(current)
  // Follow the login once it loads or its address changes on the server.
  useEffect(() => setEmail(current), [current])

  const typed = email.trim().toLowerCase()
  const changed = typed !== current.toLowerCase()
  const valid = /^\S+@\S+\.\S+$/.test(typed)
  const pending = invite.isPending || reset.isPending || changeEmail.isPending
  const error = invite.error ?? reset.error ?? changeEmail.error

  const run = async (make: () => Promise<LinkResponse>) => {
    setCopied(false)
    invite.reset(); reset.reset(); changeEmail.reset()
    try {
      setLink(await make())
    } catch {
      // Shown below from the mutation's error.
    }
  }
  // Before a login exists the address travels with the invite; afterwards a
  // different address is a change of sign-in email, which returns its own link.
  const submit = () => {
    if (!user) return run(() => invite.mutateAsync({ clientId, email: typed }))
    if (changed) return run(() => changeEmail.mutateAsync({ userId: user.id, email: typed }))
    return run(() => (user.has_password ? reset.mutateAsync(user.id) : invite.mutateAsync({ clientId })))
  }

  const url = link ? `${window.location.origin}${link.path}` : ''
  const copy = async () => {
    await navigator.clipboard.writeText(url)
    setCopied(true)
  }

  let status = 'No login yet. Create an invite link and send it to the client.'
  if (user?.has_password) {
    status = user.last_login_at ? `Last signed in ${formatDate(user.last_login_at)}.` : 'Has not signed in since setting a password.'
  } else if (user) {
    status = 'Invited; the client has not set a password yet.'
  }

  let action = 'Create invite link'
  if (user && changed) action = 'Change email and create link'
  else if (user?.has_password) action = 'Create reset link'
  else if (user) action = 'New invite link'

  return (
    <section className="border border-stone/20 rounded-card p-6">
      <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-2">Client login</h2>
      <p className="text-sm text-summit-ink">
        {isLoading ? 'Loading…' : isError ? 'Could not load the login state.' : status}
      </p>

      <div className="flex flex-wrap items-end gap-3 mt-16">
        <div className="flex-1 min-w-[240px]">
          <label htmlFor="sign-in-email" className="text-xs text-stone block mb-1">Sign-in email</label>
          <input id="sign-in-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)}
            className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm font-mono bg-surface focus:outline-none focus:border-pine" />
        </div>
        <button onClick={submit} disabled={pending || isLoading || !valid}
          className="shrink-0 text-xs border border-pine text-pine px-3 py-2 rounded-btn hover:bg-pine hover:text-on-dark transition-colors disabled:opacity-50">
          {pending ? 'Working…' : action}
        </button>
      </div>
      <p className="text-xs text-stone mt-2">
        {user && changed
          ? 'The current address will stop working and the client will be signed out. Their password is kept; the link lets them choose a new one.'
          : 'This is the address the client signs in with. Use a different one if it already belongs to another login; you can change it later.'}
      </p>
      {error && <p className="text-loss text-xs mt-3">{error.message}</p>}

      {link && (
        <div className="mt-16 p-16 bg-mist/40 rounded-btn space-y-2">
          <p className="text-xs text-stone">
            Send this link to {link.email}. It works once and expires {formatDate(link.expires_at)}. It is
            not shown again.
          </p>
          <div className="flex items-center gap-2">
            <input readOnly value={url} aria-label="One-time link" onFocus={(e) => e.target.select()}
              className="flex-1 min-w-0 border border-stone/30 rounded-btn px-2 py-1.5 text-xs font-mono bg-surface" />
            <button onClick={copy} className="shrink-0 px-3 py-1.5 bg-pine text-on-dark text-xs rounded-btn hover:bg-pine-deep">
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
