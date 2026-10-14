import { useState, type ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { usePortalAccounts, usePortalHome } from '@/hooks/usePortal'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatDate, formatPercent, formatTime } from '@/lib/formatters'
import { accountLabel, signedCurrency, tone } from '@/features/portal/ui'
import { HomeChart } from '@/features/portal/HomeChart'
import { AllocationDonut } from '@/features/portal/AllocationDonut'
import type { PortalExpiringOption, PortalHomeHolding } from '@/api/types'

// At most this many accounts get a button each; beyond it they go in a list.
const ACCOUNT_BUTTONS = 3

function greeting(): string {
  const hour = new Date().getHours()
  return hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening'
}

/** "Oct 23": the year is the current one everywhere on this page. */
function shortDate(day: string): string {
  return formatDate(day).replace(/, \d{4}$/, '')
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`
}

function Panel({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <section className={`bg-surface border border-stone/25 rounded-[12px] p-[24px] md:p-[28px] ${className}`}>
      {children}
    </section>
  )
}

function Tile({ label, children, sub }: { label: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <div className="bg-surface border border-stone/25 rounded-[12px] px-[22px] py-[20px]">
      <div className="text-[16px] text-summit-ink/70">{label}</div>
      <div className="font-mono text-[28px] mt-[6px]">{children}</div>
      {sub && <div className="text-[15px] text-summit-ink/70 mt-[4px]">{sub}</div>}
    </div>
  )
}

function Note({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="py-[14px] border-t border-stone/20">
      <div className="font-semibold">{title}</div>
      <div className="text-[16px] text-summit-ink/70 mt-[3px]">{children}</div>
    </div>
  )
}

/** One side of the day's movers: the symbol, its move in percent and what that was in dollars. */
function Movers({ title, rows }: { title: string; rows: PortalHomeHolding[] }) {
  return (
    <div>
      <div className="text-[15px] font-medium text-summit-ink/70 pb-[6px]">{title}</div>
      {rows.length === 0 ? <p className="text-summit-ink/70 py-[12px] border-t border-stone/20">None today.</p> : rows.map((h) => (
        <div key={h.symbol} className="flex items-baseline justify-between gap-[12px] py-[12px] border-t border-stone/20">
          <span className="font-semibold">{h.symbol}</span>
          <span className={`font-mono text-right ${tone(h.day_change)}`}>
            {signedCurrency(h.day_change)}
            <span className="block text-[14px]">{formatPercent(h.day_change_pct, 1)}</span>
          </span>
        </div>
      ))}
    </div>
  )
}

function expiryLine(o: PortalExpiringOption): string {
  const what = `${o.underlying} ${formatCurrency(o.strike)} ${o.kind}, ${shortDate(o.expiry)}`
  if (o.above_strike_pct == null) return `${what}.`
  const gap = `${Math.abs(o.above_strike_pct * 100).toFixed(0)}%`
  return `${what}: shares are ${gap} ${o.above_strike_pct >= 0 ? 'above' : 'below'} the strike.`
}

export function PortalHomePage() {
  const { search } = useLocation()
  const { data: portal } = usePortalAccounts()
  const [accountId, setAccountId] = useState('')
  const { data, isLoading, isError, error, refetch } = usePortalHome({ account_id: accountId || undefined })

  if (isLoading) return <div className="grid gap-[20px] md:grid-cols-3"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load your accounts.'} onRetry={() => refetch()} />
  const accounts = portal?.accounts ?? []
  if (portal && accounts.length === 0) {
    return <EmptyState title="No accounts yet" message="Achalara has not set up any accounts for you to view yet." />
  }

  const firstName = (portal?.viewer.name ?? '').split(/\s+/)[0]
  const pick = 'h-[48px] px-[18px] rounded-btn border text-[16px] transition-colors'
  const notes = data.expiring_options.length > 0 || data.carried_losses > 0
    || data.turning_long_term.length > 0 || data.concentrated.length > 0

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-[16px]">
        <div>
          <h1 className="font-display font-medium text-[40px] leading-tight">{greeting()}{firstName && `, ${firstName}`}</h1>
          <p className="text-summit-ink/70 mt-[6px]">
            {data.live_prices_at ? `Market prices as of ${formatTime(data.live_prices_at)} today. ` : ''}
            {data.as_of ? `Holdings from your custodian, ${shortDate(data.as_of)}.` : ''}
          </p>
        </div>
        {accounts.length > 1 && (accounts.length <= ACCOUNT_BUTTONS ? (
          <div role="group" aria-label="Account" className="flex flex-wrap gap-[8px]">
            {[{ id: '', name: 'All accounts' }, ...accounts].map((a) => (
              <button key={a.id} type="button" aria-pressed={accountId === a.id} onClick={() => setAccountId(a.id)}
                className={`${pick} ${accountId === a.id
                  ? 'bg-pine-deep border-pine-deep text-on-dark dark:bg-pine dark:border-pine'
                  : 'bg-surface border-stone/50 hover:border-pine'}`}>
                {a.name}
              </button>
            ))}
          </div>
        ) : (
          <div>
            <label htmlFor="home-account" className="sr-only">Account</label>
            <select id="home-account" value={accountId} onChange={(e) => setAccountId(e.target.value)}
              className={`${pick} bg-surface border-stone/50 text-summit-ink w-[360px] max-w-full`}>
              <option value="">All accounts ({accounts.length})</option>
              {accounts.map((a) => <option key={a.id} value={a.id}>{accountLabel(a)}</option>)}
            </select>
          </div>
        ))}
      </div>

      <div className="grid gap-[20px] [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
        <section className="rounded-[12px] px-[30px] py-[28px] flex flex-col gap-[10px] bg-pine-deep text-on-dark dark:bg-surface dark:border dark:border-gold/70">
          <div className="text-[16px] text-on-dark/80">Total value</div>
          <div className="font-mono font-medium text-[44px] xl:text-[52px] leading-none tracking-tight">{formatCurrency(data.total_value)}</div>
          <div className="font-mono text-[20px] text-on-dark/90">
            {data.day_change == null ? 'Today’s change is not available' : (
              <>{signedCurrency(data.day_change)} ({formatPercent(data.day_change_pct)}) today</>
            )}
          </div>
        </section>

        <Panel className="flex flex-col gap-[10px]">
          <div className="text-[16px] text-summit-ink/70">This year{data.is_provisional ? '*' : ''}</div>
          <div className={`font-mono font-medium text-[44px] leading-none ${tone(data.ytd_twr_pct)}`}>{formatPercent(data.ytd_twr_pct)}</div>
          <div className="text-summit-ink/70">
            {data.benchmark_ytd_pct == null ? 'No comparison available' : (
              <>
                S&amp;P 500 <span className="font-mono text-summit-ink">{formatPercent(data.benchmark_ytd_pct)}</span>
                {data.excess_ytd_pct != null && (
                  <> · {data.excess_ytd_pct >= 0 ? 'ahead' : 'behind'} by{' '}
                    <span className={`font-mono ${tone(data.excess_ytd_pct)}`}>{Math.abs(data.excess_ytd_pct * 100).toFixed(2)} pts</span>
                  </>
                )}
              </>
            )}
          </div>
        </Panel>

        <Panel className="flex flex-col gap-[14px]">
          <div className="text-[16px] text-summit-ink/70">Asset allocation</div>
          <AllocationDonut allocation={data.allocation} />
        </Panel>
      </div>

      <div className="grid gap-[20px] [grid-template-columns:repeat(auto-fit,minmax(230px,1fr))]">
        <Tile label="Cash available">{data.cash_value == null ? '—' : formatCurrency(data.cash_value)}</Tile>
        <Tile label="Dividends and interest, this year">
          <span className={data.income_ytd ? tone(data.income_ytd) : ''}>{signedCurrency(data.income_ytd)}</span>
        </Tile>
        <Tile label="Realised gains, this year"
          sub={<>Short-term {signedCurrency(data.realized_short_ytd)} · long-term {signedCurrency(data.realized_long_ytd)}</>}>
          <span className={tone(data.realized_ytd)}>{signedCurrency(data.realized_ytd)}</span>
        </Tile>
        <Tile label="You added, this year">{data.added_ytd == null ? '—' : formatCurrency(data.added_ytd)}</Tile>
      </div>

      <HomeChart accountId={accountId || undefined} />

      <div className="grid gap-[20px] items-start [grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))]">
        <Panel>
          <h2 className="text-[20px] font-semibold">Today’s movers</h2>
          <p className="text-[15px] text-summit-ink/70 mt-[3px] mb-[14px]">The holdings that moved your total most today, in dollars.</p>
          {data.movers_up.length === 0 && data.movers_down.length === 0
            ? <p className="text-summit-ink/70 py-[10px]">No price moves to show yet today.</p>
            : (
              <div className="grid gap-[24px] sm:grid-cols-2">
                <Movers title="Gaining" rows={data.movers_up} />
                <Movers title="Losing" rows={data.movers_down} />
              </div>
            )}
          <Link to={{ pathname: '/portal/holdings', search }} className="inline-block mt-[14px] py-[10px] font-semibold text-pine underline underline-offset-2">
            See all {plural(data.holdings_count, 'holding', 'holdings')}
          </Link>
        </Panel>

        <Panel>
          <h2 className="text-[20px] font-semibold mb-[10px]">Portfolio Insights!</h2>
          {!notes && <p className="text-summit-ink/70 py-[10px]">Nothing needs your attention right now.</p>}
          {data.expiring_options.length > 0 && (
            <Note title={`${plural(data.expiring_options.length, 'option expires', 'options expire')} within 14 days`}>
              {data.expiring_options.slice(0, 3).map(expiryLine).join(' ')}
              {data.expiring_options.length > 3 && ` And ${data.expiring_options.length - 3} more.`}
            </Note>
          )}
          {data.carried_losses > 0 && (
            <Note title={`${formatCurrency(data.carried_losses)} of losses not yet counted for tax`}>
              Carried in shares you still hold after buying back within 30 days. They count when those shares are sold.
            </Note>
          )}
          {data.turning_long_term.length > 0 && (
            <Note title={`${plural(data.turning_long_term.length, 'holding becomes', 'holdings become')} long-term before year end`}>
              {data.turning_long_term.slice(0, 4).map((t) => `${t.symbol} on ${shortDate(t.date)}`).join(', ')}
              {data.turning_long_term.length > 4 ? `, and ${data.turning_long_term.length - 4} more.` : '.'}
            </Note>
          )}
          {data.concentrated.length > 0 && (
            <Note title={data.concentrated.length === 1 ? 'One holding is over 20% of your total' : `${data.concentrated.length} holdings are each over 20% of your total`}>
              {data.concentrated.map((h) => `${h.symbol} is ${((h.share ?? 0) * 100).toFixed(1)}%`).join(', ')} of everything you hold here.
            </Note>
          )}
        </Panel>
      </div>

      {data.is_provisional && (
        <p className="text-[15px] text-summit-ink/70 max-w-4xl">
          * Provisional. Transactions reach us from your custodian with a lag of 1–2 business days, so this year's
          return{data.record_through ? `, which runs through ${shortDate(data.record_through)},` : ''} may change slightly once they arrive.
        </p>
      )}
    </>
  )
}
