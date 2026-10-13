import { useState, type ReactNode } from 'react'
import { usePortalHome, usePortalRealized, usePreviewClient } from '@/hooks/usePortal'
import { portalApi } from '@/api/endpoints/portal'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatDate, formatNumber, securityLabel } from '@/lib/formatters'
import {
  AccountStrategyFields, ExportLink, Field, PageHeader, Pills, Quantity, Select, TextInput,
  TYPE_OPTIONS, signedCurrency, tone, useAccountStrategyFilter, useDebounced,
} from '@/features/portal/ui'
import type { PortalClosedLot, PortalGainFigures, SecurityGroup } from '@/api/types'

const THIS_YEAR = new Date().getFullYear()
const YEARS = [
  { value: 'this', label: String(THIS_YEAR) }, { value: 'last', label: String(THIS_YEAR - 1) }, { value: 'all', label: 'All time' },
] as const
type Year = (typeof YEARS)[number]['value']
const RANGE: Record<Year, { start: string; end: string }> = {
  this: { start: `${THIS_YEAR}-01-01`, end: '' },
  last: { start: `${THIS_YEAR - 1}-01-01`, end: `${THIS_YEAR - 1}-12-31` },
  all: { start: '', end: '' },
}
const GRAINS = [{ value: 'quarter', label: 'Quarterly' }, { value: 'month', label: 'Monthly' }] as const
// Periods listed before the rest are asked for.
const PERIOD_ROWS = 4
type Grain = (typeof GRAINS)[number]['value']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Aug 2026" or "Q3 2026", from the first day of the period. */
function periodLabel(start: string, grain: Grain): string {
  const [year, month] = start.split('-').map(Number)
  return grain === 'quarter' ? `Q${Math.floor((month - 1) / 3) + 1} ${year}` : `${MONTHS[month - 1]} ${year}`
}

/** A signed amount in gain or loss colour; plain when it is nothing. */
function Signed({ value }: { value: number }) {
  if (Math.abs(value) < 0.005) return <span className="text-summit-ink/60">{formatCurrency(0)}</span>
  return <span className={tone(value)}>{signedCurrency(value)}</span>
}

/** The cells every breakdown row shares: capital gains by term, then income, then both. */
function FigureCells({ row, className }: { row: PortalGainFigures; className: string }) {
  return (
    <>
      <td className={className}><Signed value={row.short_term} /></td>
      <td className={className}><Signed value={row.long_term} /></td>
      <td className={`${className} font-semibold`}><Signed value={row.realized} /></td>
      <td className={className}><Signed value={row.dividends} /></td>
      <td className={className}><Signed value={row.interest} /></td>
      <td className={className}><Signed value={row.margin_interest} /></td>
      <td className={`${className} font-semibold`}><Signed value={row.realized + row.dividends + row.interest + row.margin_interest} /></td>
    </>
  )
}

function FigureHeads({ first, className }: { first: string; className: string }) {
  return (
    <tr>
      <th scope="col" className={`${className} text-left pl-[22px]`}>{first}</th>
      <th scope="col" className={`${className} text-right`}>Short-term</th>
      <th scope="col" className={`${className} text-right`}>Long-term</th>
      <th scope="col" className={`${className} text-right`}>Capital gains</th>
      <th scope="col" className={`${className} text-right`}>Dividends</th>
      <th scope="col" className={`${className} text-right`}>Interest</th>
      <th scope="col" className={`${className} text-right`}>Margin interest</th>
      <th scope="col" className={`${className} text-right pr-[22px]`}>Net of all</th>
    </tr>
  )
}

function Section({ id, title, sub, action, children }: { id?: string; title: string; sub?: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section id={id} className="bg-surface border border-stone/25 rounded-[12px] overflow-hidden scroll-mt-[16px]">
      <div className="px-[22px] py-[18px] flex flex-wrap items-center justify-between gap-[12px]">
        <div>
          <h2 className="text-[20px] font-semibold">{title}</h2>
          {sub && <p className="text-[15px] text-summit-ink/70 mt-[2px]">{sub}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}
const PAGE = 200
const RESULTS = [{ value: 'all', label: 'All' }, { value: 'gain', label: 'Gains' }, { value: 'loss', label: 'Losses' }] as const

const EVENT_LABEL: Record<NonNullable<PortalClosedLot['event']>, string> = {
  assigned: 'assigned', expired: 'expired', marked: 'year-end value',
}

/** "Aug 28 – Oct 9" within the current year; the year is added where it is another one. */
function held(lot: PortalClosedLot): string {
  const day = (iso: string | null) =>
    iso ? formatDate(iso).replace(new RegExp(`, ${THIS_YEAR}$`), '') : '—'
  return `${day(lot.opened_at)} – ${day(lot.closed_at)}`
}

/** A gain in one term's column: a dash where the lot has none in that term. */
function TermGain({ lot, term }: { lot: PortalClosedLot; term: 'short' | 'long' }) {
  const value = term === 'short' ? lot.short_term_gain : lot.long_term_gain
  if (lot.term !== term && lot.term !== 'mixed') return <span className="text-summit-ink/60">—</span>
  return <span className={value === 0 ? '' : tone(value)}>{value === 0 ? formatCurrency(0) : signedCurrency(value)}</span>
}

export function PortalRealizedPage() {
  const as_client = usePreviewClient()
  const filter = useAccountStrategyFilter()
  const [start, setStart] = useState(RANGE.this.start)
  const [end, setEnd] = useState(RANGE.this.end)
  const [grain, setGrain] = useState<Grain>('quarter')
  const [allPeriods, setAllPeriods] = useState(false)
  const [openAccounts, setOpenAccounts] = useState<Set<string>>(new Set())
  // The year button that matches the dates, if one does.
  const year = (Object.keys(RANGE) as Year[]).find((y) => RANGE[y].start === start && RANGE[y].end === end) ?? null
  const setYear = (y: Year) => { setStart(RANGE[y].start); setEnd(RANGE[y].end) }
  const backwards = !!start && !!end && start > end
  const [term, setTerm] = useState('')
  const [type, setType] = useState('')
  const [result, setResult] = useState<(typeof RESULTS)[number]['value']>('all')
  const [search, setSearch] = useState('')
  // Closed positions are listed under their account; an opened account shows a page of rows at a time.
  const [openLots, setOpenLots] = useState<Set<string>>(new Set())
  const [shownLots, setShownLots] = useState<Record<string, number>>({})
  const q = useDebounced(search)

  const filters = {
    ...filter.scope,
    start_date: start || undefined, end_date: backwards ? undefined : end || undefined,
    grain,
    term: (term || undefined) as 'short' | 'long' | undefined,
    type: (type || undefined) as SecurityGroup | undefined,
    result: result === 'all' ? undefined : result,
    q: q || undefined,
  }
  const { data, isLoading, isError, error, refetch } = usePortalRealized(filters)
  // Losses still carried in shares held now, for the account in view.
  const { data: home } = usePortalHome({ account_id: filter.scope.account_id })
  const clear = () => {
    filter.setAccountId(''); filter.setStrategyId('')
    setYear('this'); setTerm(''); setType(''); setResult('all'); setSearch('')
  }

  if (isLoading) return <div className="grid gap-[20px] md:grid-cols-3"><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load realised gains.'} onRetry={() => refetch()} />

  const period = year === 'this' ? `in ${THIS_YEAR}` : year === 'last' ? `in ${THIS_YEAR - 1}` : year === 'all' ? 'so far'
    : `${start ? `from ${formatDate(start)}` : ''}${start && end ? ' ' : ''}${end ? `to ${formatDate(end)}` : ''}`
  const everything: PortalGainFigures = {
    count: data.count, short_term: data.short_term, long_term: data.long_term, realized: data.net_realized,
    disallowed_loss: data.disallowed_loss, dividends: data.dividends, interest: data.interest,
    margin_interest: data.margin_interest,
  }
  const toggleLots = (id: string) => {
    const next = new Set(openLots)
    if (next.has(id)) next.delete(id); else next.add(id)
    setOpenLots(next)
  }
  // Accounts in the order the summary above lists them, each with its closed positions, newest first.
  const lotGroups = data.accounts
    .map((a) => {
      const lots = data.positions.filter((p) => p.account_id === a.account_id)
      return {
        id: a.account_id, name: a.account_name, shared: a.shared, lots,
        realized: lots.reduce((sum, p) => sum + p.realized_gain, 0),
      }
    })
    .filter((g) => g.lots.length > 0)
  const toggleAccount = (id: string) => {
    const next = new Set(openAccounts)
    if (next.has(id)) next.delete(id); else next.add(id)
    setOpenAccounts(next)
  }
  const shortShare = Math.abs(data.short_term) + Math.abs(data.long_term) > 0
    ? Math.abs(data.short_term) / (Math.abs(data.short_term) + Math.abs(data.long_term))
    : null
  const panel = 'bg-surface border border-stone/25 rounded-[12px] px-[30px] py-[26px] flex flex-col gap-[12px]'
  const head = 'px-[14px] py-[16px] text-[15px] font-medium text-summit-ink/70 whitespace-nowrap'
  const cell = 'px-[14px] py-[16px] align-top'
  const num = `${cell} text-right font-mono whitespace-nowrap`

  return (
    <>
      <PageHeader title="Realised gains"
        action={<ExportLink href={portalApi.csvUrl('realized', { ...filters, as_client })} />} />

      <div className="bg-surface border border-stone/25 rounded-[12px] p-[20px] flex flex-wrap gap-[16px] items-end">
        <Field label="Period"><Pills label="Period" options={YEARS} value={year} onChange={setYear} /></Field>
        <Field label="From" htmlFor="realized-start"><TextInput id="realized-start" type="date" value={start} onChange={setStart} /></Field>
        <Field label="To" htmlFor="realized-end"><TextInput id="realized-end" type="date" value={end} onChange={setEnd} /></Field>
        <AccountStrategyFields filter={filter} idPrefix="realized" />
        <nav aria-label="On this page" className="basis-full flex flex-wrap items-center gap-x-[24px] gap-y-[4px] pt-[14px] border-t border-stone/20">
          <span className="text-[15px] font-medium text-summit-ink/70">Jump to</span>
          {[
            { id: 'gains-by-period', label: grain === 'quarter' ? 'By Quarter' : 'By Month' },
            { id: 'gains-by-account', label: 'By Account and Sleeve' },
            { id: 'gains-by-position', label: 'By Position' },
          ].map((link) => (
            <a key={link.id} href={`#${link.id}`}
              onClick={(e) => { e.preventDefault(); document.getElementById(link.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }}
              className="min-h-[44px] inline-flex items-center font-semibold text-pine underline underline-offset-2">
              {link.label}
            </a>
          ))}
        </nav>
        {backwards && <p role="alert" className="text-loss text-[15px] pb-[12px]">From is after To; To is ignored.</p>}
      </div>

      <div className="grid gap-[20px] [grid-template-columns:repeat(auto-fit,minmax(min(300px,100%),1fr))]">
        <section className="rounded-[12px] px-[30px] py-[26px] bg-pine-deep text-on-dark dark:bg-surface dark:border dark:border-gold/70">
          <div className="text-[16px] text-on-dark/80">Net realised {period}</div>
          <div className="font-mono font-medium text-[40px] xl:text-[46px] leading-tight mt-[6px]">{signedCurrency(data.net_realized)}</div>
          <div className="text-[16px] text-on-dark/80 mt-[6px]">
            {formatNumber(data.count, 0)} closed · <span className="font-mono">{signedCurrency(data.gains)}</span> gains ·{' '}
            <span className="font-mono">{signedCurrency(data.losses)}</span> losses
          </div>
        </section>

        <section className={panel}>
          <div className="text-[16px] text-summit-ink/70">By term</div>
          <div className="flex justify-between gap-[12px]">
            <span>Short-term</span>
            <span className={`font-mono ${tone(data.short_term)}`}>{signedCurrency(data.short_term)}</span>
          </div>
          <div className="flex justify-between gap-[12px]">
            <span>Long-term</span>
            <span className={`font-mono ${tone(data.long_term)}`}>{signedCurrency(data.long_term)}</span>
          </div>
          {shortShare != null && (
            <div role="img" aria-label={`${(shortShare * 100).toFixed(0)} percent short-term, ${((1 - shortShare) * 100).toFixed(0)} percent long-term, by size`}
              className="flex h-[14px] rounded-full overflow-hidden bg-mist">
              <div className="bg-pine" style={{ width: `${shortShare * 100}%` }} />
              <div className="bg-pine-deep dark:bg-gold" style={{ width: `${(1 - shortShare) * 100}%` }} />
            </div>
          )}
        </section>

        <section className={panel}>
          <div className="text-[16px] text-summit-ink/70">Dividends and interest {period}</div>
          <div className="font-mono text-[32px] leading-tight"><Signed value={data.dividends + data.interest} /></div>
          <div className="text-[16px] text-summit-ink/70">
            Dividends <span className="font-mono text-summit-ink">{formatCurrency(data.dividends)}</span> · interest{' '}
            <span className="font-mono text-summit-ink">{formatCurrency(data.interest)}</span>
            {data.margin_interest < 0 && (
              <> · margin interest <span className="font-mono text-loss whitespace-nowrap">{signedCurrency(data.margin_interest)}</span></>
            )}
          </div>
        </section>

        <section className={panel}>
          <div className="text-[16px] text-summit-ink/70">Losses not yet counted</div>
          <div className="font-mono text-[32px] leading-tight">{home ? formatCurrency(home.carried_losses) : '—'}</div>
          <div className="text-[16px] text-summit-ink/70">Wash-sale losses carried in shares you still hold.</div>
        </section>
      </div>

      <Section id="gains-by-period" title={grain === 'quarter' ? 'Quarter by quarter' : 'Month by month'}
        action={<Pills label="Breakdown" options={GRAINS} value={grain} onChange={setGrain} />}>
        {data.periods.length === 0 ? (
          <div className="py-[32px] px-[20px] text-center text-summit-ink/70 border-t border-stone/20">Nothing closed and no income in these dates.</div>
        ) : (
          <div className="overflow-x-auto border-t border-stone/20">
            <table className="w-full min-w-[1040px] border-collapse text-[17px]">
              <thead><FigureHeads first="Period" className={head} /></thead>
              <tbody>
                {(allPeriods ? data.periods : data.periods.slice(0, PERIOD_ROWS)).map((p) => (
                  <tr key={p.period_start} className="border-t border-stone/20">
                    <td className={`${cell} pl-[22px] font-semibold whitespace-nowrap`}>
                      {periodLabel(p.period_start, grain)}
                      <div className="font-normal text-[15px] text-summit-ink/70">{formatNumber(p.count, 0)} closed</div>
                    </td>
                    <FigureCells row={p} className={num} />
                  </tr>
                ))}
                <tr className="border-t-2 border-stone/40 bg-mist/40">
                  <td className={`${cell} pl-[22px] font-semibold`}>
                    Total
                    {data.periods.length > PERIOD_ROWS && !allPeriods && (
                      <div className="font-normal text-[15px] text-summit-ink/70">all {data.periods.length} periods</div>
                    )}
                  </td>
                  <FigureCells row={everything} className={num} />
                </tr>
              </tbody>
            </table>
            {data.periods.length > PERIOD_ROWS && (
              <div className="px-[22px] py-[12px] border-t border-stone/20">
                <button type="button" aria-expanded={allPeriods} onClick={() => setAllPeriods(!allPeriods)}
                  className="min-h-[44px] font-semibold text-pine underline underline-offset-2">
                  {allPeriods ? `Show the latest ${PERIOD_ROWS} only` : `Show ${data.periods.length - PERIOD_ROWS} earlier ${data.periods.length - PERIOD_ROWS === 1 ? 'period' : 'periods'}`}
                </button>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section id="gains-by-account" title="By account and sleeve">
        {data.accounts.length === 0 ? (
          <div className="py-[32px] px-[20px] text-center text-summit-ink/70 border-t border-stone/20">Nothing closed and no income in these dates.</div>
        ) : (
          <div className="overflow-x-auto border-t border-stone/20">
            <table className="w-full min-w-[1040px] border-collapse text-[17px]">
              <thead><FigureHeads first="Account" className={head} /></thead>
              <tbody>
                {data.accounts.map((a) => {
                  const expanded = openAccounts.has(a.account_id)
                  return [
                    <tr key={a.account_id} className="border-t border-stone/20">
                      <td className={`${cell} pl-[14px]`}>
                        <button type="button" aria-expanded={expanded} onClick={() => toggleAccount(a.account_id)}
                          className="flex items-center gap-[8px] text-left font-semibold min-h-[44px] hover:text-pine">
                          <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                            strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}>
                            <path d="M9 6l6 6-6 6" />
                          </svg>
                          <span>
                            {a.account_name}
                            <span className="block font-normal text-[15px] text-summit-ink/70">
                              {formatNumber(a.count, 0)} closed · {a.sleeves.length} {a.sleeves.length === 1 ? 'strategy' : 'strategies'}{a.shared && ' · shared'}
                            </span>
                          </span>
                        </button>
                      </td>
                      <FigureCells row={a} className={num} />
                    </tr>,
                    ...(expanded ? a.sleeves.map((sl) => (
                      <tr key={sl.sleeve_id} className="border-t border-stone/15 bg-mist/40">
                        <td className={`${cell} pl-[50px]`}>
                          {sl.strategy_name}
                          <span className="block text-[15px] text-summit-ink/70">{formatNumber(sl.count, 0)} closed</span>
                        </td>
                        <FigureCells row={sl} className={num} />
                      </tr>
                    )) : []),
                  ]
                })}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <div id="gains-by-position" className="scroll-mt-[16px] bg-surface border border-stone/25 rounded-[12px] p-[20px] flex flex-wrap gap-[16px] items-end">
        <h2 className="basis-full text-[20px] font-semibold">By position</h2>
        <Field label="Term" htmlFor="realized-term">
          <Select id="realized-term" value={term} onChange={setTerm} minWidth={190}>
            <option value="">Short and long</option>
            <option value="short">Short-term</option>
            <option value="long">Long-term</option>
          </Select>
        </Field>
        <Field label="Type" htmlFor="realized-type">
          <Select id="realized-type" value={type} onChange={setType} minWidth={140}>
            {TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </Select>
        </Field>
        <Field label="Result"><Pills label="Result" options={RESULTS} value={result} onChange={setResult} /></Field>
        <Field label="Symbol" htmlFor="realized-search" grow>
          <TextInput id="realized-search" value={search} onChange={setSearch} placeholder="e.g. AMD" />
        </Field>
        <button type="button" onClick={clear} className="h-[48px] px-[8px] text-[16px] text-pine underline underline-offset-2">Clear filters</button>
      </div>

      {lotGroups.length === 0 && (
        <div className="bg-surface border border-stone/25 rounded-[12px] py-[40px] px-[20px] text-center text-summit-ink/70">
          No closed positions match these filters.
        </div>
      )}
      {lotGroups.map((group) => {
        const expanded = lotGroups.length === 1 || openLots.has(group.id)
        const limit = shownLots[group.id] ?? PAGE
        return (
          <section key={group.id} className="bg-surface border border-stone/25 rounded-[12px] overflow-hidden">
            <button type="button" aria-expanded={expanded} onClick={() => toggleLots(group.id)}
              className="w-full text-left px-[22px] py-[18px] flex flex-wrap items-center justify-between gap-[12px] hover:bg-mist/40 transition-colors">
              <span className="flex items-center gap-[12px]">
                <svg aria-hidden width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                  strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}>
                  <path d="M9 6l6 6-6 6" />
                </svg>
                <span>
                  <span className="block text-[19px] font-semibold">{group.name}</span>
                  <span className="block text-[15px] text-summit-ink/70">
                    {formatNumber(group.lots.length, 0)} closed{group.shared && ' · shared'}
                  </span>
                </span>
              </span>
              <span className="font-mono text-[20px] text-right"><Signed value={group.realized} /></span>
            </button>
            {expanded && (
              <div className="border-t border-stone/20">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1040px] border-collapse text-[17px]">
                    <thead>
                      <tr>
                        <th scope="col" className={`${head} text-left pl-[22px]`}>Holding</th>
                        <th scope="col" className={`${head} text-left`}>Bought and sold</th>
                        <th scope="col" className={`${head} text-right`}>Quantity</th>
                        <th scope="col" className={`${head} text-right`}>Cost</th>
                        <th scope="col" className={`${head} text-right`}>Proceeds</th>
                        <th scope="col" className={`${head} text-right`}>Short-term</th>
                        <th scope="col" className={`${head} text-right`}>Long-term</th>
                        <th scope="col" className={`${head} text-right pr-[22px]`}>Gain or loss</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.lots.slice(0, limit).map((p, i) => (
                        <tr key={`${p.sleeve_id}:${p.symbol}:${p.closed_at}:${i}`} className="border-t border-stone/20">
                          <td className={`${cell} pl-[22px]`}>
                            <div className="font-semibold">{securityLabel(p.symbol)}</div>
                            <div className="text-[15px] text-summit-ink/70">
                              {p.strategy_name}
                              {p.event && ` · ${EVENT_LABEL[p.event]}`}
                              {p.adjustments.includes('unmarked') && ' · no year-end price'}
                            </div>
                          </td>
                          <td className={`${cell} font-mono whitespace-nowrap`}>
                            {held(p)}
                            {p.days_held != null && <div className="font-sans text-[15px] text-summit-ink/70">{formatNumber(p.days_held, 0)} {p.days_held === 1 ? 'day' : 'days'}</div>}
                          </td>
                          <td className={num}><Quantity value={p.quantity} multiplier={p.multiplier} /></td>
                          <td className={num}>{formatCurrency(p.cost)}</td>
                          <td className={num}>{formatCurrency(p.proceeds)}</td>
                          <td className={num}><TermGain lot={p} term="short" /></td>
                          <td className={num}><TermGain lot={p} term="long" /></td>
                          <td className={`${num} pr-[22px] ${p.realized_gain === 0 ? '' : tone(p.realized_gain)}`}>
                            {p.realized_gain === 0 ? formatCurrency(0) : signedCurrency(p.realized_gain)}
                            {p.disallowed_loss > 0 && (
                              <div className="font-sans text-[15px] text-summit-ink/70 whitespace-normal max-w-[240px] ml-auto">
                                {formatCurrency(p.disallowed_loss)} deferred, wash sale
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {group.lots.length > limit && (
                  <div className="px-[22px] py-[12px] border-t border-stone/20 flex flex-wrap items-center justify-between gap-[12px] text-summit-ink/70">
                    <span>Showing {formatNumber(limit, 0)} of {formatNumber(group.lots.length, 0)}</span>
                    <button type="button" onClick={() => setShownLots({ ...shownLots, [group.id]: limit + PAGE })}
                      className="h-[48px] px-[18px] border border-stone/50 rounded-btn bg-surface text-summit-ink">Show {PAGE} more</button>
                  </div>
                )}
              </div>
            )}
          </section>
        )
      })}

      <div className="flex flex-col gap-[6px] text-[15px] text-summit-ink/70 max-w-5xl">
        <p>
          Wash sale: a loss on shares bought back within 30 days is deferred into the new shares' cost.
          Index options count as 60% long-term and 40% short-term. Margin interest is a cost, shown in its own column.
        </p>
        <p>Not a tax document; use your custodian's forms. Transactions arrive with a lag of 1–2 business days.</p>
      </div>
    </>
  )
}
