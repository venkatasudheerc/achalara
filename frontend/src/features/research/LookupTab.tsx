import { useState, type KeyboardEvent } from 'react'
import { useSecurityProfile, useSecuritySearch } from '@/hooks/useResearch'
import type { RsBucket, RsMonthPath, RsProfile } from '@/api/types'
import { useChartColours } from '@/context/ThemeContext'
import { formatDate } from '@/lib/formatters'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { Select, tone, useDebounced } from '@/features/portal/ui'
import {
  Bars, Controls, HowToRead, Loading, MONTHS, MONTHS_SHORT, Section, UNIVERSE_LABEL,
  displayName, notFound, pct1, unavailable,
} from './ui'

/** The one index worth naming: the S&P 500 if it is in it, else the largest it is in. */
function biggestIndex(indices: string[]): string | null {
  const first = ['SP500', 'R1000', 'R2000', 'R3000'].find((i) => indices.includes(i))
  return first ? `In the ${UNIVERSE_LABEL[first] ?? first}` : null
}

const byMonth = (buckets: RsBucket[]) => new Map(buckets.map((b) => [Number(b.order), b]))

/** The strongest month in plain words, and whether its sector shared it. */
function headline(p: RsProfile) {
  const own = p.month_of_year.buckets
  if (!own.length) return null
  const best = own.reduce((a, b) => (b.mean > a.mean ? b : a))
  const month = MONTHS[Number(best.order) - 1]
  const ups = Math.round(best.share_up * best.count)
  const name = displayName(p.name, p.symbol)
  const sector = p.sector_month_of_year ? byMonth(p.sector_month_of_year.buckets).get(Number(best.order)) : undefined
  const sectorUps = sector ? Math.round(sector.share_up * sector.count) : 0
  return {
    title: `${month} has been ${name}’s strongest month: up in ${ups} of ${best.count} years, by ${pct1(best.mean)} on average`,
    sub: sector && p.sector
      ? `Its sector, ${p.sector}, rose in ${sectorUps} of those ${sector.count} ${month}s, by ${pct1(sector.mean)} on average.`
      : undefined,
  }
}

/** The stock and its sector, side by side for each month: the stock in the portfolio's own
 *  colour, the sector in the benchmark colour. */
function PairBars({ own, sector, ownLabel, sectorLabel }: {
  own: RsBucket[]; sector: RsBucket[] | null; ownLabel: string; sectorLabel: string | null
}) {
  const colours = useChartColours()
  const a = byMonth(own)
  const s = byMonth(sector ?? [])
  const values = [...own.map((b) => b.mean), ...(sector ?? []).map((b) => b.mean)]
  const ups = Math.max(0, ...values)
  const downs = Math.max(0, ...values.map((v) => -v))
  const height = 170
  const scale = height / Math.max(ups + downs, 0.0001)
  const bar = (v: number | undefined, colour: string, up: boolean) => (
    <div className={`w-[38%] ${up ? 'rounded-t-[3px]' : 'rounded-b-[3px]'}`}
      style={{ background: colour, height: v != null && (up ? v > 0 : v < 0) ? Math.abs(v) * scale : 0 }} />
  )
  return (
    <div className="flex flex-col gap-[12px]">
      <div className="flex flex-wrap gap-[18px] text-[13px] text-stone">
        <span className="inline-flex items-center gap-[6px]"><span className="w-[12px] h-[12px] rounded-[3px]" style={{ background: colours.primary }} />{ownLabel}</span>
        {sectorLabel && <span className="inline-flex items-center gap-[6px]"><span className="w-[12px] h-[12px] rounded-[3px]" style={{ background: colours.benchmark }} />{sectorLabel}</span>}
      </div>
      <div role="img" aria-label={`Average change in each month: ${ownLabel}${sectorLabel ? ` beside ${sectorLabel}` : ''}`} className="overflow-x-auto">
        <div className="grid grid-cols-12 gap-[8px] min-w-[680px]">
          {MONTHS_SHORT.map((m, i) => {
            const av = a.get(i + 1)?.mean
            const sv = s.get(i + 1)?.mean
            return (
              <div key={m} className="flex flex-col">
                <div className="flex justify-center items-end gap-[3px]" style={{ height: ups * scale }}>
                  {bar(av, colours.primary, true)}{sector && bar(sv, colours.benchmark, true)}
                </div>
                <div className="h-[2px] bg-stone/60" />
                <div className="flex justify-center items-start gap-[3px]" style={{ height: downs * scale }}>
                  {bar(av, colours.primary, false)}{sector && bar(sv, colours.benchmark, false)}
                </div>
                <span className="text-center text-[14px] font-semibold mt-[6px]">{m}</span>
                <span className="text-center font-mono text-[11px] text-stone">
                  {av != null ? pct1(av) : '—'}{sector ? ` · ${sv != null ? pct1(sv) : '—'}` : ''}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function ordinal(n: number): string {
  const tens = n % 100
  const suffix = tens >= 11 && tens <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[n % 10] ?? 'th'
  return `${n}${suffix}`
}

/** Where the stock has stood after each date of a month: on average over the years on
 *  file, and, for the month now running, this year so far. Both measured from the last
 *  close of the month before; a weekend carries the last close forward. */
function MonthPath({ path, name, month }: { path: RsMonthPath; name: string; month: string }) {
  const colours = useChartColours()
  const typical = path.typical
  const current = path.current
  const last = Math.max(typical.length ? typical[typical.length - 1].day : 0, current?.days.length ?? 0, 28)
  const values = [0, ...typical.map((d) => d.mean), ...(current?.days.map((d) => d.ret) ?? [])]
  const lo = Math.min(...values) - 0.005
  const hi = Math.max(...values) + 0.005
  const x = (day: number) => (day / last) * 1000
  const y = (v: number) => 250 - ((v - lo) / (hi - lo)) * 230 - 10
  const line = (pts: { day: number; v: number }[]) => [{ day: 0, v: 0 }, ...pts].map((p) => `${x(p.day)},${y(p.v)}`).join(' ')
  const end = typical.length ? typical[typical.length - 1].mean : null
  const now = current?.days.length ? current.days[current.days.length - 1].ret : null
  const thin = typical.filter((d) => d.years < path.years).map((d) => d.day)
  const ticks = [1, 10, 20, last]
  return (
    <div className="flex flex-col gap-[8px]">
      <div className="flex flex-wrap gap-x-[24px] gap-y-[8px] items-baseline">
        <span className="inline-flex items-baseline gap-[8px] text-[14px] text-stone">
          <span className="w-[18px] h-[3px] rounded self-center" style={{ background: colours.primary }} />
          A typical {month}{end != null && <>, by the {ordinal(last)}: <span className={`font-mono text-[18px] ${tone(end)}`}>{pct1(end)}</span></>}
        </span>
        {current && now != null && (
          <span className="inline-flex items-baseline gap-[8px] text-[14px] text-stone">
            <span className="w-[18px] h-[3px] rounded self-center" style={{ background: colours.gold }} />
            {month} {current.year} so far, through the {ordinal(current.days.length)}:{' '}
            <span className={`font-mono text-[18px] ${tone(now)}`}>{pct1(now)}</span>
          </span>
        )}
      </div>
      <div className="rounded-[10px] bg-paper px-[16px] pt-[16px] pb-[8px]">
        <svg role="img" viewBox="0 0 1000 260" width="100%" height="240" preserveAspectRatio="none"
          aria-label={`${name} through ${month}, by date: typically ${end != null ? pct1(end) : 'unknown'} by the month's end${current && now != null ? `; this year ${pct1(now)} so far` : ''}`}>
          <line x1="0" x2="1000" y1={y(0)} y2={y(0)} stroke={colours.zero} strokeWidth="1.5" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
          {typical.length > 0 && (
            <polyline points={line(typical.map((d) => ({ day: d.day, v: d.mean })))} fill="none" stroke={colours.primary}
              strokeWidth="3" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          )}
          {current && (
            <polyline points={line(current.days.map((d) => ({ day: d.day, v: d.ret })))} fill="none" stroke={colours.gold}
              strokeWidth="3.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
          )}
        </svg>
        <div className="relative h-[18px] text-[12px] text-stone">
          {ticks.map((t) => (
            // The last label ends at the right edge rather than centring past it.
            <span key={t} className={`absolute whitespace-nowrap ${t === last ? '-translate-x-full' : '-translate-x-1/2'}`}
              style={{ left: `${(t / last) * 100}%` }}>{MONTHS_SHORT[MONTHS.indexOf(month)]} {t}</span>
          ))}
        </div>
      </div>
      <p className="text-[13px] text-stone">
        The typical line is the average of {path.years} {month}s, each measured from the last close of the month before.
        Weekends and holidays carry the last close forward.
        {thin.length > 0 && ` The ${thin.map(ordinal).join(' and ')} come from fewer years, since not every ${month} has them.`}
      </p>
    </div>
  )
}

type Match = { symbol: string; name: string | null; kind: string; sector: string | null; indices: string[] }

/** The typed text highlighted where it appears in a ticker or a name. */
function Marked({ text, query }: { text: string; query: string }) {
  const q = query.trim().toLowerCase()
  const at = q ? text.toLowerCase().indexOf(q) : -1
  if (at < 0) return <>{text}</>
  return <>{text.slice(0, at)}<span className="font-semibold text-pine">{text.slice(at, at + q.length)}</span>{text.slice(at + q.length)}</>
}

const GROUPS = [
  { label: 'Stocks', kinds: ['stock', 'adr'] },
  { label: 'ETFs and funds', kinds: ['etf', 'fund'] },
]

/** A search box whose matches drop down as you type, a ticker column and a name column,
 *  stocks and funds apart, as a quote screen lists them: arrow keys move, Enter or a
 *  click chooses, Escape closes. Choosing puts the choice in the box. */
function SecurityCombobox({ query, onQuery, results, loading, onChoose }: {
  query: string; onQuery: (q: string) => void; results: Match[]; loading: boolean
  onChoose: (m: Match) => void
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  // Grouped, but in one order for the arrow keys: the server's ranking within each group.
  const groups = GROUPS.map((g) => ({ ...g, items: results.filter((r) => g.kinds.includes(r.kind)) }))
  groups.push({ label: 'Other', kinds: [], items: results.filter((r) => !GROUPS.some((g) => g.kinds.includes(r.kind))) })
  // The group holding the best match comes first: typing "spy" leads with the SPY fund.
  groups.sort((a, b) => (a.items.length ? results.indexOf(a.items[0]) : 99) - (b.items.length ? results.indexOf(b.items[0]) : 99))
  const shown = groups.flatMap((g) => g.items)
  const showList = open && query.trim().length > 0 && (shown.length > 0 || !loading)
  const choose = (m: Match) => { onChoose(m); setOpen(false) }
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, shown.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter' && showList && shown[active]) { e.preventDefault(); choose(shown[active]) }
    else if (e.key === 'Escape') setOpen(false)
  }
  const q = query.trim()
  return (
    <div className="flex flex-col gap-[6px] w-full max-w-[520px]">
      <label htmlFor="lookup" className="text-[13px] text-stone">Company, fund or ticker</label>
      <div className="relative">
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" className="absolute left-[14px] top-[13px] text-stone">
          <circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" />
        </svg>
        <input id="lookup" type="search" value={query} placeholder="Apple, Schwab, SPY" autoComplete="off"
          role="combobox" aria-expanded={showList} aria-controls="lookup-list" aria-autocomplete="list"
          aria-activedescendant={showList && shown[active] ? `lookup-${shown[active].symbol}` : undefined}
          onChange={(e) => { onQuery(e.target.value); setOpen(true); setActive(0) }}
          onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={onKey}
          className="w-full h-[44px] pl-[42px] pr-[14px] rounded-[10px] border border-stone/40 bg-surface text-[15px] text-summit-ink focus:outline-none focus:ring-2 focus:ring-gold" />
        {showList && (
          <div id="lookup-list" role="listbox" aria-label="Matches"
            className="absolute z-20 left-0 right-0 top-[50px] max-h-[420px] overflow-y-auto rounded-[10px] border border-stone/40 bg-surface shadow-xl py-[4px]">
            {shown.length === 0
              ? <div className="px-[14px] py-[10px] text-[14px] text-stone">Nothing matches “{q}”</div>
              : groups.filter((g) => g.items.length).map((g) => (
                <div key={g.label} role="group" aria-label={g.label}>
                  <div className="px-[14px] pt-[10px] pb-[4px] text-[12px] font-semibold uppercase tracking-wide text-stone">{g.label}</div>
                  {g.items.map((m) => {
                    const i = shown.indexOf(m)
                    return (
                      <div key={m.symbol} id={`lookup-${m.symbol}`} role="option" aria-selected={i === active}
                        // mousedown, not click: it runs before the input loses focus and closes the list
                        onMouseDown={(e) => { e.preventDefault(); choose(m) }} onMouseEnter={() => setActive(i)}
                        className={`grid [grid-template-columns:84px_minmax(0,1fr)] gap-[12px] px-[14px] py-[8px] cursor-pointer ${i === active ? 'bg-mist' : ''}`}>
                        <span className="font-mono text-[14px] text-summit-ink"><Marked text={m.symbol} query={q} /></span>
                        <span className="truncate text-[15px] text-summit-ink"><Marked text={displayName(m.name)} query={q} /></span>
                      </div>
                    )
                  })}
                </div>
              ))}
          </div>
        )}
      </div>
    </div>
  )
}

export function LookupTab({ query, onQuery, onOpenMonths }: {
  query: string; onQuery: (q: string) => void; onOpenMonths: (symbol: string) => void
}) {
  const [selected, setSelected] = useState<{ symbol: string; label: string } | null>(null)
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const typed = useDebounced(query.trim(), 200)
  // The box shows the choice once made; that text is not a new search.
  const showingChoice = selected != null && query === selected.label
  const searching = showingChoice || (selected && typed === selected.label) ? '' : typed
  const search = useSecuritySearch(searching)
  const results = searching ? search.data?.results ?? [] : []
  // Only what is chosen is shown; an exact ticker (typed, or opened from another tab)
  // counts as chosen, so it needs no click.
  const exact = results.find((r) => r.symbol === searching.toUpperCase())
  const chosen = showingChoice ? selected.symbol : exact?.symbol ?? selected?.symbol ?? null
  const choose = (m: Match) => {
    const label = `${displayName(m.name, m.symbol)} · ${m.symbol}`
    setSelected({ symbol: m.symbol, label })
    onQuery(label)
  }
  const profile = useSecurityProfile(chosen, month)
  const p = profile.data
  const answer = p ? headline(p) : null
  const total = p ? p.last_12_months.reduce((g, m) => g * (1 + m.ret), 1) - 1 : 0

  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <SecurityCombobox query={query} onQuery={onQuery} results={results} loading={search.isLoading} onChoose={choose} />
      </Controls>

      {!chosen ? (
        !query.trim() ? <EmptyState title="Look up a stock or a fund" message="Type a company's name or a ticker: Apple, Schwab, SPY." />
          : search.isError ? <ErrorState message={unavailable(search.error)} onRetry={() => search.refetch()} />
          : <p className="text-[15px] text-stone">Choose a match from the list.</p>
      )
        : profile.isLoading ? <Section title="Loading…"><Loading rows={10} /></Section>
        : notFound(profile.error) ? <EmptyState title={`No prices on file for ${chosen}`} message="Market data knows this security but holds no daily history for it yet." />
        : profile.isError || !p ? <ErrorState message={unavailable(profile.error)} onRetry={() => profile.refetch()} />
        : (
          <Section
            title={<>{displayName(p.name, p.symbol)} <span className="font-mono text-[20px] text-stone">{p.symbol}</span></>}
            aside={
              <button type="button" onClick={() => onOpenMonths(p.symbol)}
                className="h-[44px] px-[18px] rounded-[10px] border border-pine text-pine text-[15px] font-semibold hover:bg-pine hover:text-on-dark transition-colors">
                Every month, year by year →
              </button>
            }>
            <div className="flex flex-wrap gap-[8px] -mt-[12px]">
              {[p.sector, p.industry, biggestIndex(p.indices)].filter(Boolean).map((c) => (
                <span key={c} className="h-[30px] px-[12px] inline-flex items-center rounded-full bg-mist text-[13px] text-summit-ink">{c}</span>
              ))}
            </div>

            {answer && (
              <div className="flex flex-col gap-[6px]">
                <p className="font-display text-[22px] leading-snug text-summit-ink">{answer.title}.</p>
                {answer.sub && <p className="text-[15px] text-stone">{answer.sub}</p>}
              </div>
            )}

            <div className="flex flex-col gap-[14px]">
              <div className="flex flex-wrap items-baseline justify-between gap-[8px]">
                <h3 className="text-[18px] font-semibold">The last 12 months</h3>
                <span className="text-[14px] text-stone">Together <span className={`font-mono ${tone(total)}`}>{pct1(total)}</span>
                  {p.basis === 'total' ? ', dividends included' : ''}</span>
              </div>
              <Bars height={150} ariaLabel={`${p.symbol}'s return in each of the last 12 months`}
                bars={p.last_12_months.map((m) => ({ key: m.period, label: MONTHS_SHORT[Number(m.period.slice(5, 7)) - 1], value: m.ret, note: m.period.slice(0, 4) }))} />
            </div>

            <div className="flex flex-col gap-[14px]">
              <h3 className="text-[18px] font-semibold">Each month, {displayName(p.name, p.symbol)} beside its sector</h3>
              <PairBars own={p.month_of_year.buckets} sector={p.sector_month_of_year?.buckets ?? null}
                ownLabel={displayName(p.name, p.symbol)} sectorLabel={p.sector} />
              <p className="text-[13px] text-stone">
                Average change in each month{p.month_of_year.years ? `, ${p.month_of_year.years.first} to ${p.month_of_year.years.last}` : ''}.
                {p.sector_month_of_year?.members ? ` The sector’s figures rest on ${p.sector_month_of_year.members} stocks.` : ''}
              </p>
            </div>

            <div className="flex flex-col gap-[14px]">
              <div className="flex flex-wrap items-end justify-between gap-[12px]">
                <div>
                  <h3 className="text-[18px] font-semibold">{MONTHS[month - 1]}, date by date</h3>
                  <p className="text-[14px] text-stone mt-[4px]">Where {displayName(p.name, p.symbol)} has stood after each date of the month</p>
                </div>
                <div className="flex flex-col gap-[6px]">
                  <label htmlFor="lookup-month" className="text-[13px] text-stone">Month</label>
                  <Select id="lookup-month" value={String(month)} onChange={(v) => setMonth(Number(v))} minWidth={160}>
                    {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
                  </Select>
                </div>
              </div>
              {p.month_path.typical.length > 0 || p.month_path.current
                ? <MonthPath path={p.month_path} name={displayName(p.name, p.symbol)} month={MONTHS[month - 1]} />
                : <p className="text-[15px] text-stone">No whole {MONTHS[month - 1]} on file yet.</p>}
            </div>

            <HowToRead notes={[`Prices on file from ${formatDate(p.first_day)} to ${formatDate(p.last_day)}.`, ...p.notes]} />
          </Section>
        )}
    </div>
  )
}
