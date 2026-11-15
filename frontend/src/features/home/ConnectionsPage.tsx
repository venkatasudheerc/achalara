import { useState } from 'react'
import type { PortalAccount, PortalConnection } from '@/api/types'
import { usePortalConnections } from '@/hooks/usePortal'
import { usePlaidDiscover, usePlaidRepair } from '@/hooks/usePlaid'
import { loadPlaid } from '@/lib/plaid'
import { formatCurrency, formatDate, formatTime } from '@/lib/formatters'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { AddAccountDialog, type Review } from './AddAccountDialog'
import { accountName, kindOf } from './selection'

const first = (name: string | null) => (name ?? 'Its owner').split(' ')[0]

/** "today, 6:30 AM EST" or "Nov 12, 2026, 6:30 AM EST": when a login last brought figures in. */
function when(instant: string): string {
  const day = new Date(instant).toDateString() === new Date().toDateString() ? 'today' : formatDate(instant)
  return `${day}, ${formatTime(instant)}`
}

/** The one sentence the page opens with. */
function headline(list: PortalConnection[], needsYou: number): string {
  if (list.length === 0) return 'Nothing is linked yet. Connect an institution and its accounts update every day by themselves.'
  if (needsYou > 0) return `${needsYou === 1 ? 'One login needs' : `${needsYou} logins need`} you to sign in again.`
  const waiting = list.filter((c) => c.state !== 'sharing').length
  if (waiting > 0) return `${waiting} of ${list.length} logins ${waiting === 1 ? 'needs' : 'need'} a look.`
  return list.length === 1 ? 'Your one login is up to date.' : `All ${list.length} logins are up to date.`
}

function stateText(c: PortalConnection): { text: string; warn: boolean } {
  switch (c.state) {
    case 'sharing': return { text: 'Sharing', warn: false }
    case 'needs_sign_in': return { text: c.own ? 'Needs you to sign in again' : `Needs ${first(c.owner_name)} to sign in again`, warn: true }
    case 'consent_ending': return { text: `Consent ends on ${formatDate(c.consent_expires_at)}`, warn: true }
    default: return { text: 'Stopped', warn: true }
  }
}

function healthText(a: PortalAccount): { text: string; warn: boolean } | null {
  const h = a.health
  if (!h) return null
  if (h.state === 'complete') return { text: 'Record complete', warn: false }
  if (h.state === 'provisional') return { text: 'Settling: recent transactions still posting', warn: false }
  return { text: `Incomplete${h.download_from ? ` · download from ${formatDate(h.download_from)}` : ''}`, warn: true }
}

/** Sign in to a login again (Plaid Link in update mode); the history carries on. */
function useSignInAgain() {
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

function ConnectionCard({ connection, signIn, onReview }: {
  connection: PortalConnection
  signIn: ReturnType<typeof useSignInAgain>
  onReview: (r: Review) => void
}) {
  const state = stateText(connection)
  const refreshed = connection.last_refreshed_at ?? connection.status_checked_at
  return (
    <li className="border border-line rounded-[18px] p-[18px] flex flex-col gap-[14px]">
      <div className="flex flex-wrap items-start justify-between gap-[12px]">
        <div className="flex flex-col gap-[2px] min-w-0">
          <h2 className="font-display text-[19px]">{connection.institution ?? 'An institution'}</h2>
          {!connection.own && (
            <span className="text-[14px] text-stone">
              {first(connection.owner_name)}’s login · {first(connection.owner_name)} signs in to it
            </span>
          )}
          <span className="text-[14px] text-stone">
            {refreshed ? `Last refreshed ${when(refreshed)}` : 'Not refreshed yet'}
          </span>
        </div>
        <span className={`text-[13px] font-semibold px-[10px] py-[4px] rounded-full ${state.warn ? 'bg-loss/15 text-loss' : 'bg-accent-soft text-pine'}`}>
          {state.text}
        </span>
      </div>

      {connection.accounts.length === 0 ? (
        <p className="text-[14px] text-stone">It feeds no accounts here.</p>
      ) : (
        <ul className="flex flex-col divide-y divide-line border-t border-line">
          {connection.accounts.map((a) => {
            const health = healthText(a)
            return (
              <li key={a.id} className="pt-[10px] pb-[10px] flex flex-wrap items-baseline justify-between gap-x-[16px] gap-y-[2px]">
                <span className="flex flex-col min-w-0">
                  <span className="text-[15px] font-medium">
                    {accountName(a)}{a.number_last4 ? <span className="text-stone font-normal"> ··{a.number_last4}</span> : null}
                  </span>
                  <span className="text-[13px] text-stone">
                    {kindOf(a.kind).label}
                    {health && <> · <span className={health.warn ? 'text-loss' : ''}>{health.text}</span></>}
                  </span>
                </span>
                <span className="font-mono tabular-nums text-[15px]">{a.value == null ? '—' : formatCurrency(a.value)}</span>
              </li>
            )
          })}
        </ul>
      )}

      {connection.own && (connection.waiting_accounts ?? 0) > 0 && (
        <div className="flex flex-wrap items-center gap-[12px] rounded-[14px] bg-accent-soft px-[14px] py-[12px]">
          <span className="text-[14px] font-medium flex-1 min-w-[180px]">
            {connection.waiting_accounts === 1 ? '1 new account is' : `${connection.waiting_accounts} new accounts are`} waiting for you to add it.
          </span>
          <button type="button" onClick={() => onReview({ connectionId: connection.id, institution: connection.institution ?? '' })}
            className="h-[44px] px-[18px] rounded-[22px] bg-pine text-on-dark text-[14px] font-semibold">
            Review
          </button>
        </div>
      )}

      {connection.own && connection.state === 'needs_sign_in' && (
        <div className="flex flex-wrap items-center gap-[12px]">
          <button type="button" onClick={() => signIn.signIn(connection.id)} disabled={signIn.working !== null}
            className="h-[44px] px-[18px] rounded-[22px] bg-pine text-on-dark text-[14px] font-semibold disabled:opacity-60">
            {signIn.working === connection.id ? 'Signing in…' : 'Sign in again'}
          </button>
          <span className="text-[14px] text-stone">Figures stay as they were last updated until then.</span>
        </div>
      )}
    </li>
  )
}

/**
 * Where your data comes from: every institution login that feeds the accounts in
 * view, how fresh it is, and the accounts it feeds with how far each record can
 * be trusted. Read-only, except signing in again to one's own login and
 * connecting another institution. A staff preview sees exactly what the client does.
 */
export function ConnectionsPage() {
  const { data, isLoading, isError, refetch } = usePortalConnections()
  const signIn = useSignInAgain()
  const discover = usePlaidDiscover()
  const [adding, setAdding] = useState(false)
  const [reviewing, setReviewing] = useState<Review | null>(null)
  const [checkError, setCheckError] = useState('')
  const hasOwn = (data?.connections ?? []).some((c) => c.own)
  const checkAll = () => { setCheckError(''); discover.all.mutate(undefined, { onError: (e) => setCheckError(e.message) }) }
  const found = discover.all.data

  return (
    <main className="w-full max-w-[720px] mx-auto px-[20px] md:px-[24px] pt-[32px] pb-[72px] flex flex-col gap-[24px]">
      <h1 className="font-display text-[32px] md:text-[36px] leading-tight">Where your data comes from</h1>
      {isLoading ? (
        <div className="flex flex-col gap-[14px]">
          <Skeleton className="h-[24px] w-[60%] rounded-[8px]" />
          <Skeleton className="h-[160px] rounded-[18px]" />
        </div>
      ) : isError || !data ? (
        <ErrorState message="Could not load where your figures come from." onRetry={() => refetch()} />
      ) : (
        <>
          <p className="text-[17px] leading-relaxed">{headline(data.connections, data.needs_sign_in)}</p>
          {data.connections.length > 0 && (
            <ul className="flex flex-col gap-[14px]">
              {data.connections.map((c) => <ConnectionCard key={c.id} connection={c} signIn={signIn} onReview={setReviewing} />)}
            </ul>
          )}
          {hasOwn && (
            <div className="flex flex-col gap-[8px]">
              <div className="flex flex-wrap items-center gap-[12px]">
                <button type="button" onClick={checkAll} disabled={discover.all.isPending}
                  className="h-[44px] px-[18px] rounded-[22px] bg-pine text-on-dark text-[14px] font-semibold disabled:opacity-60">
                  {discover.all.isPending ? 'Checking…' : 'Check for new accounts'}
                </button>
                <span className="text-[14px] text-stone">Opened an account at one of these? This finds it. Nothing changes until you add it.</span>
              </div>
              {found && !discover.all.isPending && (
                <p role="status" className="text-[14px]">
                  {found.new_accounts > 0
                    ? `${found.new_accounts} new account${found.new_accounts === 1 ? '' : 's'} found. Review ${found.new_accounts === 1 ? 'it' : 'them'} above.`
                    : 'No new accounts. Everything these logins share is already here.'}
                  {found.needs_sign_in > 0 && ` ${found.needs_sign_in === 1 ? 'One login needs' : `${found.needs_sign_in} logins need`} you to sign in again first.`}
                  {found.failed > 0 && ` ${found.failed === 1 ? 'One login' : `${found.failed} logins`} could not be checked; try again in a moment.`}
                </p>
              )}
              {checkError && <p role="alert" className="text-[14px] text-loss">{checkError}</p>}
            </div>
          )}
          {signIn.error && <p role="alert" className="text-[14px] text-loss">{signIn.error}</p>}
          <div>
            <button type="button" onClick={() => setAdding(true)}
              className="h-[44px] px-[18px] rounded-[22px] border border-stone/40 text-[14px] font-semibold hover:bg-line">
              + Connect another institution
            </button>
          </div>
        </>
      )}
      <AddAccountDialog open={adding} onClose={() => setAdding(false)} />
      <AddAccountDialog open={reviewing !== null} review={reviewing} onClose={() => setReviewing(null)} />
    </main>
  )
}
