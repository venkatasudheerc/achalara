import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useAcceptLink, useLinkPreview } from '@/hooks/useAuth'
import { homeFor } from '@/features/auth/RequireAuth'
import { AuthFrame, authLabel, authSubmit } from '@/features/auth/AuthFrame'
import { PasswordInput } from '@/features/auth/PasswordInput'

const MIN_LENGTH = 12

/** Sets a password from an invite (`/invite/:token`) or a reset link (`/reset/:token`). */
export function AcceptLinkPage() {
  const { token = '' } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { data: link, isLoading, isError } = useLinkPreview(token)
  const accept = useAcceptLink(token)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')

  if (isLoading) {
    return <div className="min-h-screen bg-paper flex items-center justify-center text-stone text-sm">Checking your link…</div>
  }
  if (isError || !link) {
    return (
      <div className="min-h-screen bg-paper flex items-center justify-center px-6">
        <div className="max-w-sm text-center space-y-3">
          <h1 className="font-display text-2xl text-summit-ink">This link is no longer valid</h1>
          <p className="text-sm text-stone">Links work once and expire. Ask your Achalara contact for a new one.</p>
          <Link to="/login" className="text-sm text-pine underline underline-offset-2">Go to sign in</Link>
        </div>
      </div>
    )
  }

  const isInvite = link.purpose === 'invite'
  const namePart = link.email.split('@')[0].toLowerCase()
  const rules = [
    { label: `At least ${MIN_LENGTH} characters`, ok: password.length >= MIN_LENGTH },
    { label: 'A letter and a number', ok: /[A-Za-z]/.test(password) && /\d/.test(password) },
    { label: 'Not your email address', ok: password.length > 0 && !password.toLowerCase().includes(namePart) },
  ]
  const matches = password === confirm
  const ready = rules.every((r) => r.ok) && matches

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!ready) return
    try {
      const user = await accept.mutateAsync(password)
      navigate(homeFor(user.role), { replace: true })
    } catch {
      // Shown below from accept.error.
    }
  }

  return (
    <AuthFrame
      footnote={isInvite ? 'This link works once and expires in 7 days' : 'This link works once and expires in 24 hours'}
      aside={
        <>
          <h1 className="font-display font-light text-[44px] leading-tight">
            {isInvite ? `Welcome, ${link.name.split(' ')[0]}.` : 'Choose a new password.'}
          </h1>
          <p className="text-[17px] leading-relaxed text-on-dark/80">
            {isInvite
              ? 'Your Achalara contact has invited you to view your accounts. Choose a password to finish setting up.'
              : 'Setting a new password signs you out everywhere else.'}
          </p>
          {link.accounts.length > 0 && (
            <div className="border border-on-dark/20 rounded-card p-5 space-y-3">
              <p className="font-mono text-xs uppercase tracking-widest text-on-dark/70">You will be able to see</p>
              {link.accounts.map((a) => (
                <div key={a.id} className="flex justify-between gap-16 text-[15px]">
                  <span>{a.name}{a.number_last4 && <span className="font-mono"> ••{a.number_last4}</span>}</span>
                  <span className={a.shared ? 'text-gold' : 'text-on-dark/70'}>{a.shared ? 'Shared with you' : 'Yours'}</span>
                </div>
              ))}
            </div>
          )}
        </>
      }
    >
      <form onSubmit={submit} className="space-y-6">
        <div className="space-y-2">
          <h2 className="font-display text-[32px]">{isInvite ? 'Set your password' : 'Reset your password'}</h2>
          <p className="text-[15px] text-stone">You sign in with <span className="font-mono text-summit-ink">{link.email}</span>.</p>
        </div>
        {accept.isError && (
          <div role="alert" className="px-3.5 py-3 rounded-btn bg-loss/10 text-loss text-sm leading-snug">
            {accept.error.message}
          </div>
        )}
        <div>
          <label htmlFor="new-password" className={authLabel}>New password</label>
          <PasswordInput id="new-password" required autoFocus autoComplete="new-password"
            value={password} onChange={(e) => setPassword(e.target.value)} />
          <ul className="mt-2 space-y-1 text-[13px]">
            {rules.map((r) => (
              <li key={r.label} className={r.ok ? 'text-gain' : 'text-stone'}>
                <span aria-hidden className="font-mono mr-2">{r.ok ? '✓' : '·'}</span>{r.label}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <label htmlFor="confirm-password" className={authLabel}>Confirm password</label>
          <PasswordInput id="confirm-password" required autoComplete="new-password"
            value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {confirm && !matches && <p className="mt-2 text-[13px] text-loss">The two passwords differ.</p>}
        </div>
        <button type="submit" disabled={!ready || accept.isPending} className={authSubmit}>
          {accept.isPending ? 'Saving…' : isInvite ? 'Create account and continue' : 'Save password and sign in'}
        </button>
      </form>
    </AuthFrame>
  )
}
