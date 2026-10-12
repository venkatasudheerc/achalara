import { useState } from 'react'
import { useInviteClient, usePasswordReset, useUsers } from '@/hooks/useAuth'
import { formatDate } from '@/lib/formatters'
import type { LinkResponse } from '@/api/types'

/** Advisor's view of one client's login: its state, and the link to pass on. */
export function ClientLoginSection({ clientId }: { clientId: string }) {
  const { data: users, isLoading, isError } = useUsers()
  const invite = useInviteClient()
  const reset = usePasswordReset()
  const [link, setLink] = useState<LinkResponse | null>(null)
  const [copied, setCopied] = useState(false)

  const user = users?.find((u) => u.client_id === clientId)
  const pending = invite.isPending || reset.isPending
  const error = invite.error ?? reset.error

  const create = async () => {
    setCopied(false)
    try {
      setLink(user?.has_password ? await reset.mutateAsync(user.id) : await invite.mutateAsync(clientId))
    } catch {
      // Shown below from the mutation's error.
    }
  }

  const url = link ? `${window.location.origin}${link.path}` : ''
  const copy = async () => {
    await navigator.clipboard.writeText(url)
    setCopied(true)
  }

  let status = 'No login yet. Create an invite link and send it to the client.'
  if (user?.has_password) {
    status = user.last_login_at
      ? `Signs in as ${user.email}. Last signed in ${formatDate(user.last_login_at)}.`
      : `Signs in as ${user.email}. Has not signed in since setting a password.`
  } else if (user) {
    status = `Invited as ${user.email}; the client has not set a password yet.`
  }

  return (
    <section className="border border-stone/20 rounded-card p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-2">Client login</h2>
          <p className="text-sm text-summit-ink">
            {isLoading ? 'Loading…' : isError ? 'Could not load the login state.' : status}
          </p>
        </div>
        <button
          onClick={create}
          disabled={pending || isLoading}
          className="shrink-0 text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-paper transition-colors disabled:opacity-50"
        >
          {pending ? 'Creating…' : user?.has_password ? 'Create reset link' : user ? 'New invite link' : 'Create invite link'}
        </button>
      </div>
      {error && <p className="text-loss text-xs mt-3">{error.message}</p>}
      {link && (
        <div className="mt-4 p-4 bg-mist/40 rounded-btn space-y-2">
          <p className="text-xs text-stone">
            Send this link to {link.email}. It works once and expires {formatDate(link.expires_at)}. It is
            not shown again.
          </p>
          <div className="flex items-center gap-2">
            <input readOnly value={url} aria-label="One-time link" onFocus={(e) => e.target.select()}
              className="flex-1 min-w-0 border border-stone/30 rounded-btn px-2 py-1.5 text-xs font-mono bg-white" />
            <button onClick={copy} className="shrink-0 px-3 py-1.5 bg-pine text-paper text-xs rounded-btn hover:bg-pine-deep">
              {copied ? 'Copied' : 'Copy'}
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
