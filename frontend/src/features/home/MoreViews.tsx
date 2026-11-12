import type { PortalAccount } from '@/api/types'
import { usePortalOverview, usePortalPositions, usePortalRealized } from '@/hooks/usePortal'
import { formatCurrency, formatDate, formatPercent } from '@/lib/formatters'
import { SkeletonCard } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { accountName, kindOf } from './selection'

const th = 'px-[14px] py-[10px] text-[13px] font-semibold text-stone text-left whitespace-nowrap'
const thNum = `${th} !text-right`
const td = 'px-[14px] py-[12px] text-[15px] border-t border-line'
const tdNum = `${td} text-right tabular-nums whitespace-nowrap`
const tone = (n: number | null | undefined) => (n == null ? '' : n < 0 ? 'text-loss' : 'text-gain')

/** Every account chosen: what it holds, its cash, this year's return, and where the figures come from. */
export function AccountsView({ accounts, accountIds }: { accounts: PortalAccount[]; accountIds?: string[] }) {
  const { data } = usePortalOverview({ account_ids: accountIds })
  const ytd = new Map((data?.accounts ?? []).map((a) => [a.id, a]))
  const total = accounts.reduce((t, a) => t + (a.value ?? 0), 0)
  return (
    <section className="flex flex-col gap-[14px]">
      <p className="text-[16px]">
        {accounts.length} {accounts.length === 1 ? 'account' : 'accounts'}, together <strong className="tabular-nums">{formatCurrency(total)}</strong>.
      </p>
      <div className="border border-line rounded-[18px] overflow-x-auto">
        <table className="w-full min-w-[760px]">
          <thead><tr>
            <th scope="col" className={th}>Account</th><th scope="col" className={th}>Owner</th><th scope="col" className={th}>Kind</th>
            <th scope="col" className={thNum}>Value</th><th scope="col" className={thNum}>Cash</th>
            <th scope="col" className={thNum}>This year</th><th scope="col" className={th}>Figures from</th>
          </tr></thead>
          <tbody>
            {accounts.map((a) => {
              const k = kindOf(a.kind)
              const year = ytd.get(a.id)
              return (
                <tr key={a.id}>
                  <td className={td}>
                    <span className="flex items-center gap-[10px]">
                      <span aria-hidden="true" className={`w-[10px] h-[10px] rounded-full shrink-0 ${k.dot}`} />
                      {accountName(a)}{a.number_last4 ? <span className="text-stone"> ··{a.number_last4}</span> : null}
                    </span>
                  </td>
                  <td className={td}>{a.owner_name}</td>
                  <td className={td}>{k.label}</td>
                  <td className={tdNum}>{a.value == null ? '—' : formatCurrency(a.value)}</td>
                  <td className={tdNum}>{a.cash == null ? '—' : formatCurrency(a.cash)}</td>
                  <td className={`${tdNum} ${tone(year?.twr_pct)}`}>{year?.twr_pct == null ? '—' : formatPercent(year.twr_pct)}</td>
                  <td className={`${td} text-[14px] text-stone`}>
                    {a.source ?? '—'}{a.as_of ? `, ${formatDate(a.as_of)}` : ''}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

/** Dividends and interest month by month over the past year. */
export function IncomeView({ accountIds }: { accountIds?: string[] }) {
  const start = new Date()
  start.setFullYear(start.getFullYear() - 1)
  const { data, isLoading, isError, error, refetch } = usePortalRealized({
    account_ids: accountIds, start_date: start.toISOString().slice(0, 10), grain: 'month',
  })
  if (isLoading) return <SkeletonCard />
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load income.'} onRetry={() => refetch()} />
  const months = data.periods.filter((p) => p.dividends || p.interest || p.margin_interest)
  const income = data.periods.reduce((t, p) => t + p.dividends + p.interest, 0)
  const borrowing = data.periods.reduce((t, p) => t + p.margin_interest, 0)
  if (!months.length) return <EmptyState title="No income in the past year" message="Dividends and interest will show here as they are paid." />
  const most = Math.max(...months.map((p) => p.dividends + p.interest), 1)
  return (
    <section className="flex flex-col gap-[18px]">
      <p className="text-[16px] leading-relaxed">
        <strong className="text-gain tabular-nums">{formatCurrency(income)}</strong> came in as dividends and interest over the past year
        {borrowing ? <>, and <strong className="text-loss tabular-nums">{formatCurrency(Math.abs(borrowing))}</strong> went out as interest on money borrowed</> : null}.
      </p>
      <div className="border border-line rounded-[18px] overflow-x-auto">
        <table className="w-full min-w-[620px]">
          <thead><tr>
            <th scope="col" className={th}>Month</th><th scope="col" className={`${th} w-[40%]`}><span className="sr-only">Bar</span></th>
            <th scope="col" className={thNum}>Dividends</th><th scope="col" className={thNum}>Interest</th><th scope="col" className={thNum}>Paid on borrowing</th>
          </tr></thead>
          <tbody>
            {months.map((p) => (
              <tr key={p.period_start}>
                <td className={td}>{new Date(`${p.period_start}T00:00:00`).toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}</td>
                <td className={td}>
                  <div aria-hidden="true" className="h-[10px] rounded-[5px] bg-gain" style={{ width: `${((p.dividends + p.interest) / most) * 100}%` }} />
                </td>
                <td className={tdNum}>{formatCurrency(p.dividends)}</td>
                <td className={tdNum}>{formatCurrency(p.interest)}</td>
                <td className={`${tdNum} ${p.margin_interest ? 'text-loss' : 'text-stone'}`}>{p.margin_interest ? formatCurrency(Math.abs(p.margin_interest)) : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[13px] text-stone">Fund capital-gain distributions are counted with dividends, as the custodian reports them.</p>
    </section>
  )
}

/** A share of the whole: no plus sign, which here would read as a gain. */
const share = (x: number) => `${x < 0 ? '−' : ''}${Math.abs(x * 100).toFixed(1)}%`

const TYPE_NAMES: Record<string, string> = { stock: 'Stocks', etf: 'ETFs', option: 'Options', other: 'Other' }

/** How the money is spread: by type of holding, the largest holdings, and how concentrated it is. */
export function AnalysisView({ accountIds }: { accountIds?: string[] }) {
  const { data, isLoading, isError, error, refetch } = usePortalPositions({ account_ids: accountIds })
  if (isLoading) return <SkeletonCard />
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load holdings.'} onRetry={() => refetch()} />

  const cash = data.account_balances.reduce((t, b) => t + (b.cash_value ?? 0), 0)
  const byType = new Map<string, number>()
  const bySymbol = new Map<string, number>()
  for (const p of data.positions) {
    const v = p.market_value ?? 0
    byType.set(p.security_type, (byType.get(p.security_type) ?? 0) + v)
    bySymbol.set(p.symbol, (bySymbol.get(p.symbol) ?? 0) + v)
  }
  if (data.options) byType.set('option', (byType.get('option') ?? 0) + data.options.market_value)
  const invested = [...byType.values()].reduce((t, v) => t + v, 0)
  const whole = invested + cash
  if (whole <= 0) return <EmptyState title="Nothing held" message="These accounts hold nothing to analyse yet." />

  const mix = [...byType].map(([type, value]) => ({ label: TYPE_NAMES[type] ?? type, value }))
  if (cash) mix.push({ label: 'Cash', value: cash })
  mix.sort((a, b) => b.value - a.value)
  const largest = [...bySymbol].sort((a, b) => b[1] - a[1]).slice(0, 10)
  const topShare = largest[0] ? largest[0][1] / whole : 0
  const fiveShare = largest.slice(0, 5).reduce((t, [, v]) => t + v, 0) / whole

  const Bars = ({ rows }: { rows: { label: string; value: number }[] }) => (
    <div className="flex flex-col gap-[10px]">
      {rows.map((r) => (
        <div key={r.label} className="grid grid-cols-[110px_1fr_70px] md:grid-cols-[140px_1fr_80px] items-center gap-[12px] text-[15px]">
          <span className="truncate">{r.label}</span>
          <div className="h-[12px] rounded-[6px] bg-line overflow-hidden">
            <div className={`h-full rounded-[6px] ${r.value < 0 ? 'bg-loss' : 'bg-pine'}`} style={{ width: `${Math.min(Math.abs(r.value) / whole, 1) * 100}%` }} />
          </div>
          <span className="text-right tabular-nums">{share(r.value / whole)}</span>
        </div>
      ))}
    </div>
  )

  return (
    <div className="grid lg:grid-cols-2 gap-[20px] items-start">
      <section aria-labelledby="mix" className="border border-line rounded-[20px] p-[22px] flex flex-col gap-[16px]">
        <h2 id="mix" className="font-display text-[20px]">What the money is in</h2>
        <Bars rows={mix} />
        <p className="text-[13px] text-stone">Holdings at today's prices; options at the custodian's last figure; cash as last reported{cash < 0 ? ' (negative: money borrowed)' : ''}.</p>
      </section>
      <section aria-labelledby="largest" className="border border-line rounded-[20px] p-[22px] flex flex-col gap-[16px]">
        <h2 id="largest" className="font-display text-[20px]">The largest holdings</h2>
        <p className="text-[15px] leading-relaxed">
          The largest is <strong className="tabular-nums">{share(topShare)}</strong> of the whole; the largest five together are{' '}
          <strong className="tabular-nums">{share(fiveShare)}</strong>.
        </p>
        <Bars rows={largest.map(([label, value]) => ({ label, value }))} />
      </section>
    </div>
  )
}
