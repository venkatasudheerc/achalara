import { useState } from 'react'
import { useEmailLink } from '@/hooks/useAuth'
import { formatDate } from '@/lib/formatters'
import type { LinkResponse } from '@/api/types'

/**
 * A one-time sign-in link just made (an invite or a reset): the address to pass
 * on, a Copy button, and "Email it" when the app can send mail. `whose` names
 * the login in the confirmation ("this client's login", "Pat's login").
 * Sizes are explicit pixels so it reads the same in the workspace and the new app.
 */
export function OneTimeLink({ link, whose = "this login" }: { link: LinkResponse; whose?: string }) {
  const [copied, setCopied] = useState(false)
  const emailLink = useEmailLink()
  // What became of emailing the link: nothing yet, sent, or not accepted.
  const [emailed, setEmailed] = useState<'sent' | 'failed' | null>(null)
  const url = `${window.location.origin}${link.path}`

  const copy = async () => {
    await navigator.clipboard.writeText(url)
    setCopied(true)
  }

  // A link is a way in, so the address is put in front of the sender before it goes.
  const send = async () => {
    if (!window.confirm(`Email this link to ${link.email}?\n\nWhoever opens it can set the password for ${whose}.`)) return
    try {
      setEmailed((await emailLink.mutateAsync(link.token)).sent ? 'sent' : 'failed')
    } catch {
      setEmailed('failed')
    }
  }

  return (
    <div className="mt-[16px] p-[16px] bg-mist/40 rounded-[10px] flex flex-col gap-[8px]">
      <p className="text-[13px] text-stone">
        Send this link to {link.email}. It works once and expires {formatDate(link.expires_at)}. It is
        not shown again.
      </p>
      <div className="flex flex-wrap items-center gap-[8px]">
        <input readOnly value={url} aria-label="One-time link" onFocus={(e) => e.target.select()}
          className="flex-1 min-w-[200px] border border-stone/30 rounded-[8px] px-[8px] py-[6px] text-[12px] font-mono bg-surface text-summit-ink" />
        <button type="button" onClick={copy}
          className="shrink-0 px-[12px] py-[6px] bg-pine text-on-dark text-[12px] rounded-[8px] hover:bg-pine-deep">
          {copied ? 'Copied' : 'Copy'}
        </button>
        {link.can_email && (
          <button type="button" onClick={send} disabled={emailLink.isPending || emailed === 'sent'}
            className="shrink-0 px-[12px] py-[6px] border border-pine text-pine text-[12px] rounded-[8px] hover:bg-pine hover:text-on-dark transition-colors disabled:opacity-50">
            {emailLink.isPending ? 'Sending…' : emailed === 'sent' ? 'Emailed' : 'Email it'}
          </button>
        )}
      </div>
      {emailed === 'sent' && <p className="text-[12px] text-gain">Sent to {link.email}.</p>}
      {emailed === 'failed' && (
        <p className="text-[12px] text-loss">The email could not be sent. Copy the link and pass it on yourself.</p>
      )}
    </div>
  )
}
