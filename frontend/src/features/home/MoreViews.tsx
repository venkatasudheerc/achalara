import type { PortalAccount } from '@/api/types'
import { usePortalOverview, usePortalPeople, usePortalPositions, usePortalRealized } from '@/hooks/usePortal'
import { formatCurrency, formatDate, formatPercent } from '@/lib/formatters'
import { SkeletonCard } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { accountName, kindOf, netWorth } from './selection'

const th = 'px-[14px] py-[10px] text-[13px] font-semibold text-stone text-left whitespace-nowrap'
const thNum = `${th} !text-right`
const td = 'px-[14px] py-[12px] text-[15px] border-t border-line'
const tdNum = `${td} text-right tabular-nums whitespace-nowrap`
const tone = (n: number | null | undefined) => (n == null ? '' : n < 0 ? 'text-loss' : 'text-gain')

/** The accounts as a table: what each holds, its cash, this year's return, and where the figures come from. */
function AccountsTable({ rows, ytd, seenBy }: {
  rows: PortalAccount[]
  ytd: Map<string, { twr_pct?: number | null }>
  seenBy: Map<string, string[]>
}) {
  return (
    <div className="border border-line rounded-[18px] overflow-x-auto">
      <table className="w-full min-w-[860px]">
        <thead><tr>
          <th scope="col" className={th}>Account</th><th scope="col" className={th}>Owner</th><th scope="col" className={th}>Kind</th>
          <th scope="col" className={thNum}>Value</th><th scope="col" className={thNum}>Cash</th>
          <th scope="col" className={thNum}>This year</th><th scope="col" className={th}>Figures from</th>
          <th scope="col" className={th}>Also seen by</th>
        </tr></thead>
        <tbody>
          {rows.map((a) => {
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
                <td className={td}>
                  {a.owners && a.owners.length > 1 ? a.owners.map((o) => o.name).join(' and ') : a.owner_name}
                  {a.held_for ? <span className="block text-[13px] text-stone">held for {a.held_for}</span> : null}
                </td>
                <td className={td}>{k.label}</td>
                <td className={tdNum}>{a.value == null ? '—' : formatCurrency(a.value)}</td>
                <td className={tdNum}>{a.cash == null || a.owed ? '—' : formatCurrency(a.cash)}</td>
                <td className={`${tdNum} ${tone(year?.twr_pct)}`}>{year?.twr_pct == null ? '—' : formatPercent(year.twr_pct)}</td>
                <td className={`${td} text-[14px] text-stone`}>
                  {a.source ?? '—'}{a.as_of ? `, ${formatDate(a.as_of)}` : ''}
                </td>
                <td className={`${td} text-[14px] ${seenBy.get(a.id)?.length ? 'text-summit-ink' : 'text-stone'}`}>
                  {a.shared ? '—' : seenBy.get(a.id)?.join(', ') || 'Nobody'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** A section's name with its total beside it. */
function SectionHead({ title, note }: { title: string; note: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-[12px]">
      <h2 className="font-display text-[20px]">{title}</h2>
      <span className="text-[14px] text-stone tabular-nums">{note}</span>
    </div>
  )
}

/**
 * Every account chosen, as assets and liabilities. A credit card is a liability and
 * is shown once, as a tile; other loans are rows. Where there is only one side, only
 * that side is shown, without headings.
 */
export function AccountsView({ accounts, accountIds }: { accounts: PortalAccount[]; accountIds?: string[] }) {
  const { data } = usePortalOverview({ account_ids: accountIds })
  const { data: people } = usePortalPeople()
  const seenBy = new Map((people?.your_accounts ?? []).map((a) => [a.id, a.seen_by]))
  const ytd = new Map((data?.accounts ?? []).map((a) => [a.id, a]))
  const worth = netWorth(accounts)
  const assets = accounts.filter((a) => !a.owed)
  const liabilities = accounts.filter((a) => a.owed)
  const cards = liabilities.filter((a) => a.card)
  const otherDebts = liabilities.filter((a) => !a.card)
  const limitTotal = cards.reduce((t, a) => t + (a.card?.credit_limit ?? 0), 0)
  const both = assets.length > 0 && liabilities.length > 0
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`
  return (
    <section className="flex flex-col gap-[18px]">
      <p className="text-[16px]">
        {both ? (
          <>
            Net worth of the accounts linked here <strong className="tabular-nums">{formatCurrency(worth.net)}</strong>:
            assets <span className="tabular-nums">{formatCurrency(worth.assets)}</span> less <span className="tabular-nums">{formatCurrency(worth.owed)}</span> owed.
          </>
        ) : assets.length === 0 ? (
          <>
            {cards.length > 0 && otherDebts.length === 0 ? plural(cards.length, 'credit card', 'credit cards') : plural(liabilities.length, 'liability', 'liabilities')}:{' '}
            <strong className="tabular-nums">{formatCurrency(worth.owed)}</strong> owed
            {limitTotal > 0 && <> of <span className="tabular-nums">{formatCurrency(limitTotal)}</span> in limits</>}.
          </>
        ) : (
          <>
            {plural(assets.length, 'account', 'accounts')}, together <strong className="tabular-nums">{formatCurrency(worth.assets)}</strong>.
          </>
        )}
      </p>

      {assets.length > 0 && (
        <div className="flex flex-col gap-[12px]">
          {both && <SectionHead title="Assets" note={`${plural(assets.length, 'account', 'accounts')} · ${formatCurrency(worth.assets)}`} />}
          <AccountsTable rows={assets} ytd={ytd} seenBy={seenBy} />
        </div>
      )}

      {liabilities.length > 0 && (
        <div className="flex flex-col gap-[12px]">
          {both && <SectionHead title="Liabilities" note={`${formatCurrency(worth.owed)} owed${limitTotal > 0 ? ` of ${formatCurrency(limitTotal)} in card limits` : ''}`} />}
          {cards.length > 0 && (
            <ul className="grid md:grid-cols-2 xl:grid-cols-3 gap-[14px] items-start">
              {[...cards].sort(byUrgency).map((a) => <CardTile key={a.id} account={a} />)}
            </ul>
          )}
          {otherDebts.length > 0 && <AccountsTable rows={otherDebts} ytd={ytd} seenBy={seenBy} />}
          {cards.length > 0 && (
            <p className="text-[13px] text-stone">
              Figures as each institution last reported them, refreshed daily. A dash means it does not send that figure.
            </p>
          )}
        </div>
      )}

      {accounts.some((a) => !a.shared) && (
        <p className="text-[13px] text-stone">
          Nobody sees an account until you share it. To change who sees one, choose it, or open Manage Access from the menu under your name.
        </p>
      )}
    </section>
  )
}

/** Whole days from today to a date, for "due in 5 days". */
function daysUntil(day: string): number {
  const start = new Date(); start.setHours(0, 0, 0, 0)
  return Math.round((new Date(`${day}T00:00:00`).getTime() - start.getTime()) / 86_400_000)
}

/** Overdue first, then the soonest payment due, then the most owed. */
function byUrgency(a: PortalAccount, b: PortalAccount): number {
  const owed = (x: PortalAccount) => Math.max(0, -(x.value ?? 0))
  const due = (x: PortalAccount) => x.card?.next_payment_due_date ?? '9999-12-31'
  return (
    Number(!!b.card?.is_overdue) - Number(!!a.card?.is_overdue) ||
    due(a).localeCompare(due(b)) ||
    owed(b) - owed(a)
  )
}

/** One credit card, lean: what is owed against the limit, then what is due, the cash limit and the last payment. */
function CardTile({ account }: { account: PortalAccount }) {
  const card = account.card
  if (!card) return null
  const owed = Math.max(0, -(account.value ?? 0))
  const limit = card.credit_limit
  const used = limit ? Math.min(owed / limit, 1) : null
  const due = card.next_payment_due_date
  const days = due ? daysUntil(due) : null
  const stale = daysUntil(card.as_of.slice(0, 10)) < -3
  const label = 'text-[13px] text-stone'
  return (
    <li className="border border-line rounded-[18px] p-[18px] bg-surface flex flex-col gap-[12px]">
      <div className="flex items-start justify-between gap-[12px]">
        <span className="min-w-0">
          <span className="font-semibold text-[16px]">
            {accountName(account)}{account.number_last4 ? <span className="text-stone font-normal"> ··{account.number_last4}</span> : null}
          </span>
          {account.shared && <span className="block text-[13px] text-stone">{account.owner_name.split(' ')[0]}’s</span>}
        </span>
        {card.is_overdue && <span className="text-[13px] font-semibold px-[10px] py-[2px] rounded-full bg-loss/15 text-loss shrink-0">Overdue</span>}
      </div>
      <div className="flex flex-col gap-[6px]">
        <div className="flex items-baseline justify-between gap-[12px]">
          <span className="font-display text-[22px] tabular-nums">{owed > 0 ? formatCurrency(owed) : 'No balance'}{owed > 0 && <span className="font-sans text-[14px] text-stone"> owed</span>}</span>
          <span className="text-[14px] text-stone tabular-nums">
            {owed > 0 && card.available_credit != null ? `${formatCurrency(card.available_credit)} available` : limit != null ? `${formatCurrency(limit)} limit` : ''}
          </span>
        </div>
        {used != null && owed > 0 && (
          <div className="h-[8px] rounded-[4px] bg-line overflow-hidden" role="img" aria-label={`${(used * 100).toFixed(0)} percent of the ${formatCurrency(limit)} limit used`}>
            <div className={`h-full rounded-[4px] ${used > 0.5 ? 'bg-loss' : 'bg-pine'}`} style={{ width: `${Math.max(used * 100, 2)}%` }} />
          </div>
        )}
        {limit != null && owed > 0 && used != null && <span className={label}>{(used * 100).toFixed(0)}% of {formatCurrency(limit)}</span>}
      </div>
      <dl className="grid grid-cols-3 gap-x-[12px] gap-y-[8px] text-[14px] border-t border-line pt-[12px]">
        <div className="min-w-0">
          <dt className={label}>Due</dt>
          <dd className={days != null && days <= 7 ? 'text-loss font-medium' : ''}>
            {due ? (days != null && days >= 0 && days <= 30 ? (days === 0 ? 'Today' : `In ${days} day${days === 1 ? '' : 's'}`) : formatDate(due)) : <span className="text-stone">Nothing</span>}
            {due && card.last_statement_balance != null && card.last_statement_balance > 0 && <span className="block text-[13px] text-stone tabular-nums">statement {formatCurrency(card.last_statement_balance)}</span>}
            {due && card.minimum_payment != null && <span className="block text-[13px] text-stone tabular-nums">min {formatCurrency(card.minimum_payment)}</span>}
          </dd>
        </div>
        <div className="min-w-0">
          <dt className={label}>Cash limit</dt>
          <dd className="tabular-nums">{card.cash_advance_limit == null ? '—' : formatCurrency(card.cash_advance_limit)}</dd>
        </div>
        <div className="min-w-0">
          <dt className={label}>Last paid</dt>
          <dd className="tabular-nums">
            {card.last_payment_amount == null ? '—' : formatCurrency(card.last_payment_amount)}
            {card.last_payment_date && <span className="block text-[13px] text-stone">{formatDate(card.last_payment_date)}</span>}
          </dd>
        </div>
      </dl>
      {stale && <p className="text-[13px] text-loss">Last reported {formatDate(card.as_of)}; it should refresh daily.</p>}
    </li>
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

/** The 11 GICS sectors, as market data names them. */
const SECTORS = [
  'Information Technology', 'Health Care', 'Financials', 'Consumer Discretionary', 'Communication Services',
  'Industrials', 'Consumer Staples', 'Energy', 'Utilities', 'Real Estate', 'Materials',
]

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
  // Where the stocks sit in the 11 sectors. Funds are one row (what they hold is not looked
  // through), options are the custodian's figure, and a stock with no sector is said so.
  const bySector = new Map<string, number>(SECTORS.map((name) => [name, 0]))
  let funds = 0
  let unclassified = 0
  let unclassifiedCount = 0
  for (const p of data.positions) {
    const v = p.market_value ?? 0
    if (p.sector_group === 'sector' && p.sector) bySector.set(p.sector, (bySector.get(p.sector) ?? 0) + v)
    else if (p.sector_group === 'fund') funds += v
    else if (p.sector_group === 'unclassified') { unclassified += v; unclassifiedCount += 1 }
  }
  const optionsValue = data.options?.market_value ?? 0
  const sectorRows = [...bySector].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
  const stocksInSectors = sectorRows.reduce((t, r) => t + r.value, 0)
  const sectorsHeld = sectorRows.filter((r) => r.value > 0).length
  const otherRows = [
    { label: 'Funds and ETFs', value: funds, muted: true },
    { label: 'Options', value: optionsValue, muted: true },
    { label: 'Cash', value: cash, muted: true },
    { label: 'Not classified', value: unclassified, muted: true },
  ].filter((r) => r.value !== 0)
  const topSector = sectorRows[0]

  const largest = [...bySymbol].sort((a, b) => b[1] - a[1]).slice(0, 10)
  const topShare = largest[0] ? largest[0][1] / whole : 0
  const fiveShare = largest.slice(0, 5).reduce((t, [, v]) => t + v, 0) / whole

  const Bars = ({ rows, wide }: { rows: { label: string; value: number; muted?: boolean }[]; wide?: boolean }) => (
    <div className="flex flex-col gap-[10px]">
      {rows.map((r) => (
        <div key={r.label} className={`grid ${wide ? 'grid-cols-[128px_1fr_58px] md:grid-cols-[196px_1fr_64px]' : 'grid-cols-[110px_1fr_70px] md:grid-cols-[140px_1fr_80px]'} items-center gap-[12px] text-[15px]`}>
          <span className={wide ? 'leading-tight' : 'truncate'}>{r.label}</span>
          <div className="h-[12px] rounded-[6px] bg-line overflow-hidden">
            <div className={`h-full rounded-[6px] ${r.value < 0 ? 'bg-loss' : r.muted ? 'bg-stone/40' : 'bg-pine'}`} style={{ width: `${Math.min(Math.abs(r.value) / whole, 1) * 100}%` }} />
          </div>
          <span className="text-right tabular-nums">{share(r.value / whole)}</span>
        </div>
      ))}
    </div>
  )

  return (
    <div className="grid lg:grid-cols-2 gap-[20px] items-start">
      <section aria-labelledby="sectors" className="border border-line rounded-[20px] p-[22px] flex flex-col gap-[16px]">
        <h2 id="sectors" className="font-display text-[20px]">What the stocks are in</h2>
        <p className="text-[15px] leading-relaxed">
          {stocksInSectors > 0 && topSector ? (
            <>
              <strong>{topSector.label}</strong> is the largest sector at{' '}
              <strong className="tabular-nums">{share(topSector.value / whole)}</strong> of the whole. Stocks with a sector
              are <strong className="tabular-nums">{share(stocksInSectors / whole)}</strong> of it, spread over {sectorsHeld} of
              the 11 sectors.
            </>
          ) : (
            'None of these holdings is a stock with a sector yet.'
          )}
        </p>
        <Bars rows={sectorRows} wide />
        {otherRows.length > 0 && (
          <div className="flex flex-col gap-[10px] border-t border-line pt-[14px]">
            <span className="text-[13px] text-stone">Not in a sector</span>
            <Bars rows={otherRows} wide />
          </div>
        )}
        <p className="text-[13px] text-stone leading-relaxed">
          The 11 sectors are the GICS sectors, from market data. A fund is one row: what it holds is not looked through.
          {unclassifiedCount > 0 && ` ${unclassifiedCount} holding${unclassifiedCount === 1 ? ' has' : 's have'} no sector on file yet.`}
        </p>
      </section>
      <div className="flex flex-col gap-[20px]">
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
    </div>
  )
}
