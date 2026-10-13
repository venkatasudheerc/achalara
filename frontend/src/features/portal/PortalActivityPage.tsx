import { useState } from 'react'
import { usePortalActivity, usePreviewClient } from '@/hooks/usePortal'
import { portalApi, type ActivityFilters, type ActivityShow } from '@/api/endpoints/portal'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatDate, formatNumber, formatSharePrice, securityLabel } from '@/lib/formatters'
import {
  AccountStrategyFields, ExportLink, Field, PageHeader, Pills, Quantity, Select, TextInput,
  TYPE_OPTIONS, daysAgo, signedCurrency, tone, useAccountStrategyFilter, useDebounced,
} from '@/features/portal/ui'
import type { ActivityRow, SecurityGroup } from '@/api/types'

const PAGE = 50
const THIS_YEAR = new Date().getFullYear()
const PERIODS = [
  { value: '30d', label: '30 days' }, { value: '90d', label: '90 days' }, { value: 'ytd', label: 'This year' },
  { value: 'last', label: String(THIS_YEAR - 1) }, { value: 'all', label: 'All time' },
] as const
type Period = (typeof PERIODS)[number]['value']

function span(period: Period): { from: string; to: string } {
  if (period === '30d') return { from: daysAgo(30), to: '' }
  if (period === '90d') return { from: daysAgo(90), to: '' }
  if (period === 'ytd') return { from: `${THIS_YEAR}-01-01`, to: '' }
  if (period === 'last') return { from: `${THIS_YEAR - 1}-01-01`, to: `${THIS_YEAR - 1}-12-31` }
  return { from: '', to: '' }
}

const ACTIONS = [{ value: 'all', label: 'All' }, { value: 'buy', label: 'Buy' }, { value: 'sell', label: 'Sell' }] as const

const SHOW = [
  { value: 'all', label: 'All' }, { value: 'trades', label: 'Trades' },
  { value: 'money', label: 'Deposits and withdrawals' }, { value: 'income', label: 'Dividends and interest' },
  { value: 'charges', label: 'Fees and margin interest' },
] as const satisfies readonly { value: ActivityShow; label: string }[]

/** What a row was, in a word or two, coloured by the direction the money went. */
function What({ row }: { row: ActivityRow }) {
  const colour = row.event ? 'bg-gold/25 text-summit-ink'
    : row.kind === 'trade' ? (row.action === 'BUY' ? 'bg-mist text-pine-deep' : 'bg-loss/15 text-loss')
    : row.amount >= 0 ? 'bg-gain/15 text-gain' : 'bg-loss/15 text-loss'
  return <span className={`inline-block px-[10px] py-[3px] rounded-full text-[14px] font-semibold whitespace-nowrap ${colour}`}>{row.label}</span>
}

/** One account's activity, fetched when the account is opened and paged within it. */
function AccountActivity({ filters, accountId }: { filters: ActivityFilters; accountId: string }) {
  const [page, setPage] = useState(0)
  const { data, isLoading, isError, error, refetch } = usePortalActivity({
    ...filters, account_id: accountId, skip: page * PAGE, limit: PAGE,
  })
  if (isLoading) return <div className="p-[22px]"><SkeletonCard /></div>
  if (isError || !data) {
    return <div className="p-[22px]"><ErrorState message={error?.message ?? 'Could not load this activity.'} onRetry={() => refetch()} /></div>
  }

  const head = 'px-[14px] py-[14px] text-[15px] font-medium text-summit-ink/70 whitespace-nowrap'
  const cell = 'px-[14px] py-[14px] align-top'
  const num = `${cell} text-right font-mono whitespace-nowrap`
  const from = data.total === 0 ? 0 : data.skip + 1
  const to = data.skip + data.rows.length

  return (
    <div className="border-t border-stone/20">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[940px] border-collapse text-[17px]">
          <thead>
            <tr>
              <th scope="col" className={`${head} text-left pl-[22px]`}>Date</th>
              <th scope="col" className={`${head} text-left`}>Activity</th>
              <th scope="col" className={`${head} text-left`}>Strategy</th>
              <th scope="col" className={`${head} text-right`}>Quantity</th>
              <th scope="col" className={`${head} text-right`}>Price</th>
              <th scope="col" className={`${head} text-right pr-[22px]`}>Amount</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const trade = r.kind === 'trade'
              return (
                <tr key={`${r.kind}:${r.id}`} className="border-t border-stone/20">
                  <td className={`${cell} pl-[22px] font-mono whitespace-nowrap`}>{formatDate(r.date)}</td>
                  <td className={cell}>
                    <What row={r} />
                    {r.symbol && <span className="font-semibold ml-[8px]">{securityLabel(r.symbol)}</span>}
                    {r.detail && <span className="ml-[8px] text-[15px] text-summit-ink/70">{r.detail}</span>}
                  </td>
                  <td className={`${cell} text-summit-ink/80`}>{trade ? r.strategy_name : '—'}</td>
                  <td className={num}>{trade && r.quantity != null ? <Quantity value={r.quantity} multiplier={r.multiplier ?? 1} /> : '—'}</td>
                  <td className={num}>{!trade || r.event || r.price == null ? '—' : formatSharePrice(r.price, (r.multiplier ?? 1) > 1)}</td>
                  {/* A trade shows its value; cash shows which way it went. */}
                  <td className={`${num} pr-[22px] ${trade ? '' : tone(r.amount)}`}>
                    {trade ? (r.event ? '—' : formatCurrency(r.amount)) : signedCurrency(r.amount)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {data.total > PAGE && (
        <div className="px-[22px] py-[12px] border-t border-stone/20 flex flex-wrap items-center justify-between gap-[12px] text-summit-ink/70">
          <span>Showing {from}–{to} of {formatNumber(data.total, 0)}</span>
          <div className="flex gap-[8px]">
            <button type="button" disabled={page === 0} onClick={() => setPage(page - 1)}
              className="h-[48px] px-[18px] border border-stone/50 rounded-btn bg-surface text-summit-ink disabled:opacity-50">Previous</button>
            <button type="button" disabled={to >= data.total} onClick={() => setPage(page + 1)}
              className="h-[48px] px-[18px] border border-stone/50 rounded-btn bg-surface text-summit-ink disabled:opacity-50">Next</button>
          </div>
        </div>
      )}
    </div>
  )
}

export function PortalActivityPage() {
  const as_client = usePreviewClient()
  const filter = useAccountStrategyFilter()
  // A preset fills the two dates; editing a date leaves no preset selected.
  const [period, setPeriod] = useState<Period | null>('ytd')
  const [dates, setDates] = useState(span('ytd'))
  const [show, setShow] = useState<ActivityShow>('all')
  const [action, setAction] = useState<(typeof ACTIONS)[number]['value']>('all')
  const [type, setType] = useState('')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set())
  const q = useDebounced(search)

  // Buy or sell, and the security type, describe a trade: they are offered only where trades are shown.
  const tradesShown = show === 'all' || show === 'trades'
  const filters: ActivityFilters = {
    ...filter.scope,
    start_date: dates.from || undefined, end_date: dates.to || undefined,
    show: show === 'all' ? undefined : show,
    action: !tradesShown || action === 'all' ? undefined : action,
    type: tradesShown ? ((type || undefined) as SecurityGroup | undefined) : undefined,
    q: q || undefined,
  }
  // The totals and the list of accounts; each account's rows are fetched when it is opened.
  const { data, isLoading, isError, error, refetch } = usePortalActivity({ ...filters, limit: 1 })

  const pickPeriod = (p: Period) => { setPeriod(p); setDates(span(p)) }
  const setDate = (key: 'from' | 'to') => (v: string) => { setPeriod(null); setDates({ ...dates, [key]: v }) }
  const clear = () => {
    filter.setAccountId(''); filter.setStrategyId('')
    setShow('all'); setAction('all'); setType(''); setSearch(''); pickPeriod('ytd')
  }
  const toggle = (id: string) => {
    const next = new Set(open)
    if (next.has(id)) next.delete(id); else next.add(id)
    setOpen(next)
  }

  if (isLoading) return <div className="grid gap-[20px] md:grid-cols-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load your activity.'} onRetry={() => refetch()} />

  const tile = 'bg-surface border border-stone/25 rounded-[12px] px-[22px] py-[20px]'
  const everything = data.accounts.map((a) => a.account_id)
  const allOpen = everything.length > 1 && everything.every((id) => open.has(id))

  return (
    <>
      <PageHeader title="Activity"
        sub="Trades, and the money that moved in and out: deposits, withdrawals, dividends, interest and charges."
        action={<ExportLink href={portalApi.csvUrl('activity', { ...filters, as_client })} />} />

      <div className="bg-surface border border-stone/25 rounded-[12px] p-[20px] flex flex-wrap gap-[16px] items-end">
        <Field label="Period"><Pills label="Period" options={PERIODS} value={period} onChange={pickPeriod} /></Field>
        <Field label="From" htmlFor="trades-from"><TextInput id="trades-from" type="date" value={dates.from} onChange={setDate('from')} /></Field>
        <Field label="To" htmlFor="trades-to"><TextInput id="trades-to" type="date" value={dates.to} onChange={setDate('to')} /></Field>
        <AccountStrategyFields idPrefix="trades" filter={filter} />
        <Field label="Show" htmlFor="activity-show">
          <Select id="activity-show" value={show} onChange={(v) => setShow(v as ActivityShow)} minWidth={230}>
            {SHOW.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
        </Field>
        {tradesShown && (
          <>
            <Field label="Action"><Pills label="Action" options={ACTIONS} value={action} onChange={setAction} /></Field>
            <Field label="Type" htmlFor="trades-type">
              <Select id="trades-type" value={type} onChange={setType} minWidth={140}>
                {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </Select>
            </Field>
          </>
        )}
        <Field label="Symbol" htmlFor="trades-search" grow>
          <TextInput id="trades-search" value={search} onChange={setSearch} placeholder="e.g. NVDA" />
        </Field>
        <button type="button" onClick={clear} className="h-[48px] px-[8px] text-[16px] text-pine underline underline-offset-2">Clear filters</button>
      </div>

      {/* Two lines of four: what was traded, then the money that moved. */}
      {([
        ['Trade summary', [
          ['Trades', formatNumber(data.trades, 0), `of ${formatNumber(data.total, 0)} items`],
          ['Bought', formatCurrency(data.bought), ''], ['Sold', formatCurrency(data.sold), ''],
          ['Net invested', formatCurrency(data.net_invested), 'Bought less sold'],
        ]],
        ['Money movement summary', [
          ['Money in', formatCurrency(data.money_in), 'Deposits and transfers in'],
          ['Money out', formatCurrency(data.money_out), 'Withdrawals and transfers out'],
          ['Dividends and interest', formatCurrency(data.income), ''],
          ['Fees and margin interest', formatCurrency(data.charges), ''],
        ]],
      ] as const).map(([heading, tiles]) => (
        <section key={heading} aria-label={heading}>
          <h2 className="text-[18px] font-semibold mb-[10px]">{heading}</h2>
          <div className="grid gap-[20px] grid-cols-2 lg:grid-cols-4">
            {tiles.map(([label, value, note]) => (
              <div key={label} className={tile}>
                <div className="text-[16px] text-summit-ink/70">{label}</div>
                <div className="font-mono text-[26px] mt-[6px]">{value}</div>
                {note && <div className="text-[14px] text-summit-ink/70 mt-[4px]">{note}</div>}
              </div>
            ))}
          </div>
        </section>
      ))}

      {data.accounts.length > 1 && (
        <div className="flex justify-end">
          <button type="button" onClick={() => setOpen(allOpen ? new Set() : new Set(everything))}
            className="h-[48px] px-[18px] rounded-btn border border-stone/50 bg-surface text-[16px] hover:border-pine transition-colors">
            {allOpen ? 'Collapse all' : 'Expand all'}
          </button>
        </div>
      )}

      {data.accounts.length === 0 && (
        <div className="bg-surface border border-stone/25 rounded-[12px] py-[40px] px-[20px] text-center text-summit-ink/70">
          Nothing matches these filters.
        </div>
      )}
      {data.accounts.map((account) => {
        const expanded = data.accounts.length === 1 || open.has(account.account_id)
        return (
          <section key={account.account_id} className="bg-surface border border-stone/25 rounded-[12px] overflow-hidden">
            <button type="button" aria-expanded={expanded} onClick={() => toggle(account.account_id)}
              className="w-full text-left px-[22px] py-[18px] flex flex-wrap lg:flex-nowrap items-center justify-between gap-[14px] hover:bg-mist/40 transition-colors">
              <span className="flex items-center gap-[12px] min-w-0">
                <svg aria-hidden width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}>
                  <path d="M9 6l6 6-6 6" />
                </svg>
                <span>
                  <span className="block text-[19px] font-semibold">{account.account_name}</span>
                  <span className="block text-[15px] text-summit-ink/70">
                    {formatNumber(account.total, 0)} {account.total === 1 ? 'item' : 'items'} · {formatNumber(account.trades, 0)} {account.trades === 1 ? 'trade' : 'trades'}{account.shared && ' · shared'}
                  </span>
                </span>
              </span>
              <span className="shrink-0 flex flex-wrap justify-end gap-x-[28px] gap-y-[4px] font-mono text-right">
                <span><span className="block font-sans text-[14px] text-summit-ink/70">Bought</span><span className="text-[19px]">{formatCurrency(account.bought)}</span></span>
                <span><span className="block font-sans text-[14px] text-summit-ink/70">Sold</span><span className="text-[19px]">{formatCurrency(account.sold)}</span></span>
                <span><span className="block font-sans text-[14px] text-summit-ink/70">Money in</span><span className="text-[19px]">{formatCurrency(account.money_in)}</span></span>
                <span><span className="block font-sans text-[14px] text-summit-ink/70">Money out</span><span className="text-[19px]">{formatCurrency(account.money_out)}</span></span>
              </span>
            </button>
            {/* Keyed by the filters, so a change starts the account again at its first page. */}
            {expanded && <AccountActivity key={JSON.stringify(filters)} filters={filters} accountId={account.account_id} />}
          </section>
        )
      })}

      <p className="text-[15px] text-summit-ink/70">
        Recent activity can take 1–2 business days to arrive from your custodian. Your custodian’s own moves between
        the cash and margin sides of an account are left out.
      </p>
    </>
  )
}
