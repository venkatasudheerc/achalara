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
  const waiting = list.reduce((t, c) => t + (c.own ? (c.waiting_accounts ?? 0) : 0), 0)
  const base = headlineBase(list, needsYou)
  if (waiting === 0 || needsYou > 0) return base
  return `${base} ${waiting === 1 ? '1 account is' : `${waiting} accounts are`} waiting for your review.`
}

function headlineBase(list: PortalConnection[], needsYou: number): string {
  if (list.length === 0) return 'Nothing is linked yet. Connect an institution and its accounts update every day by themselves.'
  if (needsYou > 0) return `${needsYou === 1 ? 'One login needs' : `${needsYou} logins need`} you to sign in again.`
  const notSharing = list.filter((c) => c.state !== 'sharing').length
  if (notSharing > 0) return `${notSharing} of ${list.length} logins ${notSharing === 1 ? 'needs' : 'need'} a look.`
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

/** "Today", "Yesterday" or "Nov 14": a day short enough for a tile. */
function shortDay(instant: string): string {
  const day = new Date(instant)
  const now = new Date()
  if (day.toDateString() === now.toDateString()) return 'Today'
  const before = new Date(now); before.setDate(now.getDate() - 1)
  if (day.toDateString() === before.toDateString()) return 'Yesterday'
  return day.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

/** Four figures that say at a glance whether the data is coming in. */
function Summary({ list }: { list: PortalConnection[] }) {
  const accounts = new Map<string, PortalAccount>()
  for (const c of list) for (const a of c.accounts) accounts.set(a.id, a)
  const value = [...accounts.values()].reduce((t, a) => t + (a.value ?? 0), 0)
  const moments = list.map((c) => c.last_refreshed_at ?? c.status_checked_at).filter((m): m is string => !!m)
  const latest = moments.length ? moments.reduce((a, b) => (new Date(a) > new Date(b) ? a : b)) : null
  const look =
    list.filter((c) => c.state !== 'sharing').length +
    list.reduce((t, c) => t + (c.own ? (c.waiting_accounts ?? 0) : 0), 0) +
    [...accounts.values()].filter((a) => a.health?.state === 'incomplete').length
  const tiles = [
    { label: 'Logins', value: String(list.length), note: list.length === 1 ? 'institution' : 'institutions' },
    { label: 'Accounts', value: String(accounts.size), note: accounts.size ? `${formatCurrency(value)} in all` : 'none fed yet' },
    { label: 'Last refreshed', value: latest ? shortDay(latest) : 'Not yet', note: latest ? `${formatTime(latest)} · daily refresh` : 'by the daily refresh' },
    { label: 'Need a look', value: String(look), note: look === 0 ? 'all clear' : 'see the cards below', warn: look > 0 },
  ]
  return (
    <dl className="grid grid-cols-2 lg:grid-cols-4 gap-[12px]">
      {tiles.map((t) => (
        <div key={t.label} className="border border-line rounded-[16px] px-[16px] py-[14px] bg-surface flex flex-col gap-[2px] min-w-0">
          <dt className="text-[13px] text-stone">{t.label}</dt>
          <dd className={`font-display text-[22px] leading-tight truncate ${t.warn ? 'text-loss' : ''}`}>{t.value}</dd>
          <dd className="text-[13px] text-stone truncate">{t.note}</dd>
        </div>
      ))}
    </dl>
  )
}

function ConnectionCard({ connection, signIn, onReview }: {
  connection: PortalConnection
  signIn: ReturnType<typeof useSignInAgain>
  onReview: (r: Review) => void
}) {
  const state = stateText(connection)
  const refreshed = connection.last_refreshed_at ?? connection.status_checked_at
  return (
    <li className="border border-line rounded-[20px] p-[20px] flex flex-col gap-[14px] bg-surface">
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
        <span className={`inline-flex items-center gap-[6px] text-[13px] font-semibold px-[10px] py-[4px] rounded-full ${state.warn ? 'bg-loss/15 text-loss' : 'bg-accent-soft text-pine'}`}>
          <span aria-hidden className={`w-[8px] h-[8px] rounded-full ${state.warn ? 'bg-loss' : 'bg-gain'}`} />
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
                  <span className="text-[13px] text-stone flex flex-wrap items-center gap-x-[8px] gap-y-[2px]">
                    <span className={`inline-flex items-center gap-[5px] px-[8px] py-[1px] rounded-full text-[12px] font-medium ${kindOf(a.kind).bg} ${kindOf(a.kind).text}`}>
                      <span aria-hidden className={`w-[6px] h-[6px] rounded-full ${kindOf(a.kind).dot}`} />
                      {kindOf(a.kind).label}
                    </span>
                    {health && <span className={health.warn ? 'text-loss' : ''}>{health.text}</span>}
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
            {connection.waiting_accounts === 1 ? '1 account' : `${connection.waiting_accounts} accounts`} found. Review to add the new ones.
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
    <main className="w-full max-w-[1120px] mx-auto px-[20px] md:px-[32px] pt-[32px] pb-[72px] flex flex-col gap-[24px]">
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
          <div className="flex flex-wrap items-center justify-between gap-x-[24px] gap-y-[12px]">
            <p className="text-[17px] leading-relaxed">{headline(data.connections, data.needs_sign_in)}</p>
            <div className="flex flex-wrap items-center gap-[10px]">
              {hasOwn && (
                <button type="button" onClick={checkAll} disabled={discover.all.isPending}
                  className="h-[44px] px-[18px] rounded-[22px] bg-pine text-on-dark text-[14px] font-semibold disabled:opacity-60">
                  {discover.all.isPending ? 'Checking…' : 'Check for new accounts'}
                </button>
              )}
              <button type="button" onClick={() => setAdding(true)}
                className="h-[44px] px-[18px] rounded-[22px] border border-stone/40 text-[14px] font-semibold hover:bg-line">
                + Connect another institution
              </button>
            </div>
          </div>
          {hasOwn && (found || checkError) && (
            <div className="flex flex-col gap-[4px]">
              {found && !discover.all.isPending && (
                <p role="status" className="text-[14px] rounded-[12px] bg-accent-soft px-[14px] py-[10px]">
                  {found.new_accounts > 0
                    ? `${found.new_accounts} new account${found.new_accounts === 1 ? '' : 's'} found. Review ${found.new_accounts === 1 ? 'it' : 'them'} below.`
                    : 'No new accounts. Everything these logins share is already here.'}
                  {found.needs_sign_in > 0 && ` ${found.needs_sign_in === 1 ? 'One login needs' : `${found.needs_sign_in} logins need`} you to sign in again first.`}
                  {found.failed > 0 && ` ${found.failed === 1 ? 'One login' : `${found.failed} logins`} could not be checked; try again in a moment.`}
                </p>
              )}
              {checkError && <p role="alert" className="text-[14px] text-loss">{checkError}</p>}
            </div>
          )}
          {data.connections.length > 0 && <Summary list={data.connections} />}
          {data.connections.length > 0 && (
            <ul className="lg:columns-2 lg:gap-[16px] [&>li]:break-inside-avoid [&>li]:mb-[16px] flex flex-col gap-[16px] lg:block">
              {data.connections.map((c) => <ConnectionCard key={c.id} connection={c} signIn={signIn} onReview={setReviewing} />)}
            </ul>
          )}
          {signIn.error && <p role="alert" className="text-[14px] text-loss">{signIn.error}</p>}
        </>
      )}
      <AddAccountDialog open={adding} onClose={() => setAdding(false)} />
      <AddAccountDialog open={reviewing !== null} review={reviewing} onClose={() => setReviewing(null)} />
    </main>
  )
}
