import { useContext, useMemo, useState, type ReactNode } from 'react'
import { usePortalAccounts, usePortalHome, usePortalPositions } from '@/hooks/usePortal'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { SkeletonCard } from '@/components/Skeleton'
import { ShortBadge } from '@/components/ShortBadge'
import { formatCurrency, formatDate, formatNumber, formatPercent, formatSharePrice, formatTime, securityLabel } from '@/lib/formatters'
import {
  AccountStrategyFields, Field, HomeSelection, Pills, TextInput, TYPE_LABEL, signedCurrency, tone, useAccountStrategyFilter, useAccountName, useDebounced,
} from '@/features/portal/ui'
import type { PortalHomeResponse, PortalPosition, SecurityGroup } from '@/api/types'
import { INVESTED } from '@/features/home/selection'
import { displayName } from '@/features/research/ui'

const TYPES = [
  { value: '', label: 'All' }, { value: 'stock', label: 'Stocks' }, { value: 'etf', label: 'ETFs' },
  { value: 'option', label: 'Options' }, { value: 'other', label: 'Other' },
] as const

interface Group {
  id: string
  name: string
  rows: PortalPosition[]
  value: number
  dayChange: number | null
  gain: number | null
  unpriced: number
}
interface AccountGroup extends Group {
  last4: string | null; shared: boolean; strategies: Group[]
  /** The custodian's own figures, added to the priced holdings for the account's total */
  cash: number | null; optionsValue: number | null; optionsGain: number | null; balancesAsOf: string | null
  /** The open contracts the trade history names, shown under the account's Options line
   * (the custodian values them only as a group, so none has a value of its own) */
  contracts: PortalPosition[]
}

/** Totals of the rows that have a value; options without a price are counted, not valued. */
function summarise(id: string, name: string, rows: PortalPosition[]): Group {
  const priced = rows.filter((r) => r.market_value != null)
  const moved = rows.filter((r) => r.day_change != null)
  const costed = priced.filter((r) => r.unrealized_gain != null)
  return {
    id, name, rows,
    value: priced.reduce((sum, r) => sum + (r.market_value ?? 0), 0),
    dayChange: moved.length ? moved.reduce((sum, r) => sum + (r.day_change ?? 0), 0) : null,
    gain: costed.length ? costed.reduce((sum, r) => sum + (r.unrealized_gain ?? 0), 0) : null,
    unpriced: rows.length - priced.length,
  }
}

function shortDate(day: string): string {
  return formatDate(day).replace(/, \d{4}$/, '')
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg aria-hidden width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 transition-transform ${open ? 'rotate-90' : ''}`}>
      <path d="M9 6l6 6-6 6" />
    </svg>
  )
}

/** The figures on the right of an account or strategy tile. */
function Figures({ group, large }: { group: Group; large?: boolean }) {
  return (
    <div className="max-w-full flex flex-wrap items-baseline justify-end gap-x-[20px] sm:gap-x-[28px] gap-y-[4px] font-mono text-right">
      <div>
        <div className="font-sans text-[14px] text-summit-ink/70">Value</div>
        <div className={large ? 'text-[26px]' : 'text-[20px]'}>{formatCurrency(group.value)}</div>
      </div>
      <div>
        <div className="font-sans text-[14px] text-summit-ink/70">Today</div>
        <div className={`${large ? 'text-[20px]' : 'text-[18px]'} ${tone(group.dayChange)}`}>{signedCurrency(group.dayChange)}</div>
      </div>
      <div>
        <div className="font-sans text-[14px] text-summit-ink/70">Unrealised</div>
        <div className={`${large ? 'text-[20px]' : 'text-[18px]'} ${tone(group.gain)}`}>{signedCurrency(group.gain)}</div>
      </div>
    </div>
  )
}

function HoldingsTable({ rows }: { rows: PortalPosition[] }) {
  const cell = 'px-[14px] py-[13px] align-top'
  const num = `${cell} text-right font-mono whitespace-nowrap`
  const head = 'px-[14px] py-[10px] text-[14px] font-medium text-summit-ink/70 whitespace-nowrap'
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[860px] border-collapse text-[16px]">
        <thead>
          <tr>
            <th scope="col" className={`${head} text-left`}>Holding</th>
            <th scope="col" className={`${head} text-right`}>Quantity</th>
            <th scope="col" className={`${head} text-right`}>Avg cost</th>
            <th scope="col" className={`${head} text-right`}>Price</th>
            <th scope="col" className={`${head} text-right`}>Today</th>
            <th scope="col" className={`${head} text-right`}>Value</th>
            <th scope="col" className={`${head} text-right`}>Unrealised gain</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.sleeve_id}:${r.symbol}`} className="border-t border-stone/20">
              <td className={cell}>
                <span className="font-semibold">{securityLabel(r.symbol)}</span><ShortBadge quantity={r.quantity} />
                <div className="text-[14px] text-summit-ink/70">
                  {/* The name says more than the type, which the strategy and the filter already give. */}
                  {r.name ? displayName(r.name) : TYPE_LABEL[r.security_type]}{r.price_source === 'custodian' && ' · custodian’s price'}
                </div>
              </td>
              <td className={num}>
                {formatNumber(r.quantity, Number.isInteger(r.quantity) ? 0 : 4)}
                {r.multiplier > 1 && <div className="font-sans text-[14px] text-summit-ink/70">contracts × {r.multiplier}</div>}
              </td>
              <td className={num}>{formatSharePrice(r.avg_cost, r.multiplier > 1)}</td>
              <td className={num}>{formatCurrency(r.price)}</td>
              <td className={`${num} ${tone(r.day_change_pct)}`}>{formatPercent(r.day_change_pct, 1)}</td>
              <td className={num}>{formatCurrency(r.market_value)}</td>
              <td className={`${num} ${tone(r.unrealized_gain)}`}>
                {signedCurrency(r.unrealized_gain)}
                <div className="text-[14px]">{formatPercent(r.unrealized_gain_pct)}</div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** The open option contracts the history names: what they are and how many, never a price each. */
function ContractsTable({ rows }: { rows: PortalPosition[] }) {
  const cell = 'px-[14px] py-[13px] align-top'
  const num = `${cell} text-right font-mono whitespace-nowrap`
  const head = 'px-[14px] py-[10px] text-[14px] font-medium text-summit-ink/70 whitespace-nowrap'
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-[16px]">
        <thead>
          <tr>
            <th scope="col" className={`${head} text-left`}>Contract</th>
            <th scope="col" className={`${head} text-right`}>Quantity</th>
            <th scope="col" className={`${head} text-right`}>Premium per share</th>
            <th scope="col" className={`${head} text-right`}>Value</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.sleeve_id}:${r.symbol}`} className="border-t border-stone/20">
              <td className={cell}>
                <span className="font-semibold">{securityLabel(r.symbol)}</span><ShortBadge quantity={r.quantity} />
                <div className="text-[14px] text-summit-ink/70">{r.strategy_name}</div>
              </td>
              <td className={num}>
                {formatNumber(r.quantity, Number.isInteger(r.quantity) ? 0 : 4)}
                {r.multiplier > 1 && <div className="font-sans text-[14px] text-summit-ink/70">contracts × {r.multiplier}</div>}
              </td>
              <td className={num}>{formatSharePrice(r.avg_cost, true)}</td>
              <td className={`${cell} text-right text-[14px] text-summit-ink/70`}>Priced by the custodian as a group</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RailRow({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex justify-between gap-[12px]"><span>{label}</span><span className="font-mono text-right">{children}</span></div>
}

/** The whole portfolio in brief, beside the accounts. */
function Rail({ home }: { home: PortalHomeResponse }) {
  const coming = [
    ...home.expiring_options.map((o) => ({
      day: o.expiry, text: `${o.underlying} ${formatCurrency(o.strike)} ${o.kind} expires`,
    })),
    ...home.turning_long_term.map((t) => ({ day: t.date, text: `${t.symbol} becomes long-term` })),
  ].sort((a, b) => a.day.localeCompare(b.day)).slice(0, 5)
  const rule = 'border-t border-stone/30 pt-[22px] flex flex-col gap-[12px]'
  return (
    <aside aria-label="Portfolio summary"
      className="bg-mist rounded-[12px] px-[28px] py-[30px] flex flex-col gap-[24px] xl:sticky xl:top-[24px]">
      <div>
        <h2 className="font-display text-[24px] font-medium">Your portfolio at a glance</h2>
        <div className="font-mono font-medium text-[40px] leading-tight mt-[10px]">{formatCurrency(home.total_value)}</div>
        <div className={`font-mono text-[19px] mt-[4px] ${tone(home.day_change)}`}>
          {home.day_change == null ? '—' : <>{signedCurrency(home.day_change)} ({formatPercent(home.day_change_pct)}) today</>}
        </div>
        <div className="text-[15px] text-summit-ink/70 mt-[8px]">
          {home.live_prices_at ? `Prices as of ${formatTime(home.live_prices_at)}` : 'At your custodian’s last prices'} · cash included
        </div>
      </div>
      <div className={rule}>
        <RailRow label="This year"><span className={tone(home.ytd_twr_pct)}>{formatPercent(home.ytd_twr_pct)}</span></RailRow>
        <RailRow label="S&P 500">{formatPercent(home.benchmark_ytd_pct)}</RailRow>
        <RailRow label={home.first_date ? `Since ${formatDate(home.first_date).replace(/^\w+ \d+, /, '')}` : 'Since you started'}>
          <span className={tone(home.since_start_twr_pct)}>{formatPercent(home.since_start_twr_pct, 1)}</span>
        </RailRow>
        <RailRow label="Largest fall from a high">{formatPercent(home.max_drawdown_pct, 1)}</RailRow>
      </div>
      <div className={rule}>
        <RailRow label="Cash available">{home.cash_value == null ? '—' : formatCurrency(home.cash_value)}</RailRow>
        <RailRow label="Income this year">{formatCurrency(home.income_ytd)}</RailRow>
        <RailRow label="Realised this year"><span className={tone(home.realized_ytd)}>{signedCurrency(home.realized_ytd)}</span></RailRow>
      </div>
      <div className={rule}>
        <div className="font-semibold">Coming up</div>
        {coming.length === 0
          ? <div className="text-summit-ink/70">Nothing in the next few weeks.</div>
          : coming.map((c) => <div key={`${c.day}:${c.text}`}>{shortDate(c.day)} · {c.text}</div>)}
      </div>
    </aside>
  )
}

export function PortalHoldingsPage() {
  const { data: portal } = usePortalAccounts()
  const filter = useAccountStrategyFilter()
  const embedded = useContext(HomeSelection) !== null
  const accountName = useAccountName()
  const [type, setType] = useState<(typeof TYPES)[number]['value']>('')
  const [search, setSearch] = useState('')
  const q = useDebounced(search)
  const narrowed = !!(filter.scope.account_id || filter.scope.strategy_id || type || q)
  // A strategy, type or symbol shows part of an account, so its cash and options are left out of the figures.
  const partial = !!(filter.scope.strategy_id || type || q)
  const { data, isLoading, isError, error, refetch } = usePortalPositions({
    ...filter.scope, type: (type || undefined) as SecurityGroup | undefined, q: q || undefined,
  })
  // The summary follows the account chosen; it is always the whole of that account.
  const { data: home } = usePortalHome({ account_ids: filter.scope.account_ids, account_id: filter.scope.account_id })
  const clear = () => { filter.setAccountId(''); filter.setStrategyId(''); setType(''); setSearch('') }
  // Everything starts closed; null until something is opened or closed by hand.
  const [chosen, setOpen] = useState<Set<string> | null>(null)

  const accounts = useMemo<AccountGroup[]>(() => {
    const listed = portal?.accounts ?? []
    const byAccount = new Map<string, PortalPosition[]>()
    for (const row of data?.positions ?? []) {
      byAccount.set(row.account_id, [...(byAccount.get(row.account_id) ?? []), row])
    }
    // Banks, cards and cash accounts hold no investments: they are not tiles here.
    return listed.filter((account) => INVESTED.includes(account.kind)).map((account) => {
      const rows = byAccount.get(account.id) ?? []
      const balance = partial ? undefined : data?.account_balances.find((b) => b.account_id === account.id)
      const priced = summarise(account.id, account.name, rows)
      const optionsValue = balance?.options_value ?? null
      // The custodian's value for the options, less what they cost.
      const optionsGain = optionsValue != null && balance?.options_cost != null ? optionsValue - balance.options_cost : null
      // The custodian values the account's options as one figure, so they get a line of their
      // own in the account, listing the open contracts; the strategies keep what is priced.
      const contracts = optionsValue != null ? rows.filter((r) => r.security_type === 'option' && r.market_value == null) : []
      const bySleeve = new Map<string, PortalPosition[]>()
      for (const row of rows) {
        if (contracts.includes(row)) continue
        bySleeve.set(row.sleeve_id, [...(bySleeve.get(row.sleeve_id) ?? []), row])
      }
      const strategies = [...bySleeve.entries()].map(([sleeveId, held]) => summarise(sleeveId, held[0].strategy_name, held))
      return {
        ...priced,
        // Holdings at live prices, plus the custodian's options value and cash: the account's total.
        value: priced.value + (optionsValue ?? 0) + (balance?.cash_value ?? 0),
        gain: optionsGain != null ? (priced.gain ?? 0) + optionsGain : priced.gain,
        cash: balance?.cash_value ?? null, optionsValue, optionsGain, contracts,
        balancesAsOf: balance?.as_of ?? null,
        last4: account.number_last4, shared: account.shared,
        strategies: strategies.sort((a, b) => b.value - a.value),
      }
    // Largest first; accounts holding nothing go last, and are left out once a filter is on.
    }).filter((a) => filter.inView(a.id) && (!filter.scope.account_id || a.id === filter.scope.account_id) && (!partial || a.rows.length > 0))
      .sort((a, b) => b.value - a.value)
  // eslint-disable-next-line react-hooks/exhaustive-deps -- inView follows account_ids
  }, [portal, data, partial, filter.scope.account_id, filter.scope.account_ids])

  if (isLoading) return <div className="grid gap-[20px]"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load your holdings.'} onRetry={() => refetch()} />
  if (portal && accounts.length === 0) {
    return <EmptyState title="No accounts yet" message="Achalara has not set up any accounts for you to view yet." />
  }

  // A search or a type opens everything it matched, so the matches are in view.
  const open = (type || q) ? new Set(accounts.flatMap((a) => [a.id, ...a.strategies.map((st) => st.id)]))
    : chosen ?? new Set<string>()
  const toggle = (id: string) => {
    const next = new Set(open)
    if (next.has(id)) next.delete(id); else next.add(id)
    setOpen(next)
  }
  const optionsId = (accountId: string) => `options:${accountId}`
  const everything = accounts.flatMap((a) => [
    a.id, ...a.strategies.map((s) => s.id), ...(a.contracts.length ? [optionsId(a.id)] : []),
  ])
  const allOpen = everything.length > 0 && everything.every((id) => open.has(id))

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-[16px]">
        <div>
          {!embedded && <h1 className="font-display font-medium text-[40px] leading-tight">Holdings</h1>}
          <p className="text-summit-ink/70 mt-[6px]">
            Every account, the strategies within it, and what each one holds.
            {data.live_prices_at ? ` Market prices as of ${formatTime(data.live_prices_at)} today.` : ''}
          </p>
        </div>
        <button type="button" onClick={() => setOpen(allOpen ? new Set() : new Set(everything))}
          className="h-[48px] px-[18px] rounded-btn border border-stone/50 bg-surface text-[16px] hover:border-pine transition-colors">
          {allOpen ? 'Collapse all' : 'Expand all'}
        </button>
      </div>

      <div className="bg-surface border border-stone/25 rounded-[12px] p-[20px] flex flex-wrap gap-[16px] items-end">
        <AccountStrategyFields filter={filter} idPrefix="holdings" />
        <Field label="Type"><Pills label="Type" options={TYPES} value={type} onChange={setType} /></Field>
        <Field label="Symbol" htmlFor="holdings-search" grow>
          <TextInput id="holdings-search" value={search} onChange={setSearch} placeholder="e.g. AAPL" />
        </Field>
        {narrowed && <button type="button" onClick={clear} className="h-[48px] px-[8px] text-[16px] text-pine underline underline-offset-2">Clear filters</button>}
      </div>

      <div className={`grid gap-[24px] items-start ${embedded ? '' : 'xl:grid-cols-[minmax(0,1fr)_400px]'}`}>
        <div className="flex flex-col gap-[20px] min-w-0">
          {accounts.length === 0 && (
            <div className="bg-surface border border-stone/25 rounded-[12px] py-[40px] px-[20px] text-center text-summit-ink/70">
              No holdings match these filters.
            </div>
          )}
          {accounts.map((account) => {
            const expanded = open.has(account.id)
            return (
              <section key={account.id} className="bg-surface border border-stone/25 rounded-[12px] overflow-hidden">
                <button type="button" aria-expanded={expanded} onClick={() => toggle(account.id)}
                  className="w-full text-left px-[24px] py-[22px] flex flex-wrap lg:flex-nowrap items-center justify-between gap-[16px] hover:bg-mist/40 transition-colors">
                  <span className="flex items-center gap-[14px] min-w-0">
                    <Chevron open={expanded} />
                    <span className="min-w-0">
                      <span className="block text-[21px] font-semibold">
                        {accountName(account.id, account.name)}
                        {account.shared && <span className="ml-[10px] align-middle text-[13px] font-semibold px-[9px] py-[3px] rounded-full bg-gold/25">Shared with you</span>}
                      </span>
                      <span className="block text-[15px] text-summit-ink/70 mt-[2px]">
                        {account.rows.length === 0
                          ? (account.optionsValue != null || account.cash != null ? 'Options and cash only' : 'Nothing held right now')
                          : `${account.strategies.length > 1 ? `${account.strategies.length} strategies · ` : ''}${account.rows.length} ${account.rows.length === 1 ? 'holding' : 'holdings'}`}
                      </span>
                    </span>
                  </span>
                  <Figures group={account} large />
                </button>

                {expanded && (
                  <div className="px-[24px] pb-[24px] flex flex-col gap-[14px]">
                    {account.strategies.length === 0 && account.cash == null && account.optionsValue == null && <p className="text-summit-ink/70">Nothing is held in this account right now.</p>}
                    {account.strategies.map((strategy) => {
                      const shown = open.has(strategy.id)
                      return (
                        <div key={strategy.id} className="rounded-[10px] bg-mist/50 border border-stone/20 overflow-hidden">
                          <button type="button" aria-expanded={shown} onClick={() => toggle(strategy.id)}
                            className="w-full text-left px-[20px] py-[16px] flex flex-wrap items-center justify-between gap-[14px] hover:bg-mist transition-colors">
                            <span className="flex items-center gap-[12px]">
                              <Chevron open={shown} />
                              <span>
                                <span className="block text-[18px] font-semibold">{strategy.name}</span>
                                <span className="block text-[15px] text-summit-ink/70">
                                  {strategy.rows.length} {strategy.rows.length === 1 ? 'holding' : 'holdings'}
                                  {strategy.unpriced > 0 && ` · ${strategy.unpriced} without a price`}
                                </span>
                              </span>
                            </span>
                            <Figures group={strategy} />
                          </button>
                          {shown && (
                            <div className="bg-surface border-t border-stone/20">
                              <HoldingsTable rows={[...strategy.rows].sort((a, b) => (b.market_value ?? -Infinity) - (a.market_value ?? -Infinity))} />
                            </div>
                          )}
                        </div>
                      )
                    })}
                    {account.optionsValue != null && (() => {
                      const id = optionsId(account.id)
                      const shown = open.has(id)
                      const n = account.contracts.length
                      const asOf = account.balancesAsOf ? `, as of ${shortDate(account.balancesAsOf)}` : ''
                      const header = (
                        <>
                          <span className="flex items-center gap-[12px]">
                            {n > 0 ? <Chevron open={shown} /> : <span aria-hidden className="w-[22px] shrink-0" />}
                            <span>
                              <span className="block text-[18px] font-semibold">Options</span>
                              <span className="block text-[15px] text-summit-ink/70">
                                {n > 0
                                  ? `${n} open ${n === 1 ? 'contract' : 'contracts'} · priced by your custodian as a group${asOf}`
                                  : `Your custodian’s value for this account’s options together${asOf}. The contracts aren’t named in the history on file.`}
                              </span>
                            </span>
                          </span>
                          <Figures group={{ id, name: 'Options', rows: [], value: account.optionsValue, dayChange: null, gain: account.optionsGain, unpriced: 0 }} />
                        </>
                      )
                      const box = 'px-[20px] py-[16px] flex flex-wrap items-center justify-between gap-[14px]'
                      return (
                        <div className="rounded-[10px] bg-mist/50 border border-stone/20 overflow-hidden">
                          {n > 0 ? (
                            <button type="button" aria-expanded={shown} onClick={() => toggle(id)}
                              className={`w-full text-left ${box} hover:bg-mist transition-colors`}>{header}</button>
                          ) : <div className={box}>{header}</div>}
                          {n > 0 && shown && (
                            <div className="bg-surface border-t border-stone/20">
                              <ContractsTable rows={[...account.contracts].sort((a, b) => a.symbol.localeCompare(b.symbol))} />
                            </div>
                          )}
                        </div>
                      )
                    })()}
                    {account.cash != null && (
                      <div className="rounded-[10px] bg-mist/50 border border-stone/20 px-[20px] py-[16px] flex flex-wrap items-center justify-between gap-[14px]">
                        <span className="pl-[34px]">
                          <span className="block text-[18px] font-semibold">{account.cash < 0 ? 'Cash borrowed' : 'Cash'}</span>
                          <span className="block text-[15px] text-summit-ink/70">
                            {account.cash < 0 ? 'A margin loan, taken off the total' : 'Uninvested money in the account'}{account.balancesAsOf ? ` · as of ${shortDate(account.balancesAsOf)}` : ''}
                          </span>
                        </span>
                        <span className={`font-mono text-[20px] ${account.cash < 0 ? 'text-loss' : ''}`}>{formatCurrency(account.cash)}</span>
                      </div>
                    )}
                  </div>
                )}
              </section>
            )
          })}
          <p className="text-[15px] text-summit-ink/70 max-w-4xl">
            {(portal?.accounts ?? []).some((a) => filter.inView(a.id) && !INVESTED.includes(a.kind))
              && 'Bank, card and cash accounts hold no investments, so they are not listed here. '}
            An account’s value is its holdings at live prices, plus its options and cash as your custodian last
            reported them. Your custodian gives one value for all of an account’s options together, shown on the
            account’s Options line: their unrealised gain is that value less what they cost, and single contracts
            show no value of their own.
            Today covers the priced holdings only.
          </p>
        </div>

        {/* In the new app the Dashboard holds these figures. */}
        {home && !embedded && <Rail home={home} />}
      </div>
    </>
  )
}
