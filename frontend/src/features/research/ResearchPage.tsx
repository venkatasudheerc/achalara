import { useState } from 'react'
import { useCalendarGrid, useSectorScorecard, useTopPerformers } from '@/hooks/useResearch'
import type { RsPerformer } from '@/api/types'
import { formatNumber } from '@/lib/formatters'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { Select } from '@/features/portal/ui'
import { CalendarHeatmap } from './CalendarHeatmap'
import { GlanceCards, OverviewTab } from './Overview'
import { MonthsTab } from './MonthsTab'
import { LookupTab } from './LookupTab'
import { SymbolPicker, indexChoice, type Choice } from './SymbolPicker'
import {
  Box, Controls, HowToRead, Loading, MONTHS, Pct, Section, Segmented, Tabs, UNIVERSES, UNIVERSE_LABEL,
  capitalise, displayName, notFound, pct1, share, subjectName, td, tdNum, th, thNum, unavailable,
} from './ui'

type Tab = 'overview' | 'months' | 'calendar' | 'top' | 'sectors' | 'lookup'
const TABS: { value: Tab; label: string }[] = [
  { value: 'overview', label: 'Overview' },
  { value: 'months', label: 'Months by year' },
  { value: 'calendar', label: 'Calendar days' },
  { value: 'top', label: 'Top performers' },
  { value: 'sectors', label: 'Sectors' },
  { value: 'lookup', label: 'Stock/ETF look-up' },
]

function MonthSelect({ id, value, onChange }: { id: string; value: number; onChange: (m: number) => void }) {
  return (
    <div className="flex flex-col gap-[6px]">
      <label htmlFor={id} className="text-[13px] text-stone">Month</label>
      <Select id={id} value={String(value)} onChange={(v) => onChange(Number(v))} minWidth={160}>
        {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
      </Select>
    </div>
  )
}

// -- Calendar days ---------------------------------------------------------------

const RANGES = [
  { value: '1950', label: 'Since 1950' },
  { value: '25', label: '25 years' },
  { value: 'all', label: 'All' },
] as const

function CalendarTab({ choice, onChoice }: { choice: Choice; onChoice: (c: Choice) => void }) {
  const [stat, setStat] = useState<'mean' | 'median'>('mean')
  const [range, setRange] = useState<(typeof RANGES)[number]['value']>('1950')
  const typed = choice.symbol
  const lastYear = new Date().getFullYear() - 1
  const start_year = range === 'all' ? undefined : range === '1950' ? 1950 : lastYear - 24
  const { data, isLoading, isError, error, refetch, isFetching } = useCalendarGrid({ symbol: typed, stat, start_year, end_year: lastYear })
  const best = data?.best[0]
  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <SymbolPicker id="cal-symbol" label="Index, company or fund" placeholder="S&P 500, Apple, SPY"
          choice={choice} onChoose={onChoice} withIndices />
        <Segmented label="Show" value={stat} onChange={setStat}
          options={[{ value: 'mean', label: 'Average' }, { value: 'median', label: 'Median' }]} />
        <Segmented label="Years" value={range} onChange={setRange} options={RANGES} />
      </Controls>
      {!typed ? <EmptyState title="Name an index or a ticker" message="SPX, NDX and RUT go back decades; a stock's record is about five years." />
        : isLoading ? <Section title="Loading…"><Loading rows={10} /></Section>
        : notFound(error) ? <EmptyState title={`Nothing on file for ${typed}`} message="Try an index (SPX, NDX, RUT) or a ticker in one of the tracked indices." />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={isFetching ? 'opacity-70 transition-opacity' : ''}>
            <Section
              title={`${capitalise(subjectName(data.symbol))}, date by date through the year`}
              sub={<>{data.stat === 'mean' ? 'Average' : 'Median'} change on each date, {data.years.first} to {data.years.last}.
                {best && <> The strongest date: {MONTHS[best.month - 1]} {best.day}, <span className="font-mono">{pct1(best.value)}</span> over {best.days} years.</>}</>}>
              <CalendarHeatmap grid={data} />
              <HowToRead notes={data.notes} />
            </Section>
          </div>
        )}
    </div>
  )
}

// -- Top performers ---------------------------------------------------------------

function downloadCsv(name: string, rows: RsPerformer[]) {
  const quote = (v: string | number | null) => (v == null ? '' : /[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v))
  const lines = [['symbol', 'name', 'sector', 'industry', 'years', 'median_excess', 'worst_excess', 'median_return']]
    .concat(rows.map((r) => [r.symbol, r.name ?? '', r.sector ?? '', r.industry ?? '', String(r.years),
      String(r.median_excess), String(r.worst_excess), String(r.median_return)]))
  const blob = new Blob([lines.map((l) => l.map(quote).join(',')).join('\n')], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}

function TopTab({ forAdvisor, onLookup }: { forAdvisor: boolean; onLookup: (symbol: string) => void }) {
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [universe, setUniverse] = useState<string>('SP500')
  const [all, setAll] = useState(false)
  const { data, isLoading, isError, error, refetch, isFetching } = useTopPerformers({ month, universe })
  const SHOWN = 15
  const name = MONTHS[month - 1]
  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <MonthSelect id="top-month" value={month} onChange={setMonth} />
        <Segmented label="Index" value={universe} onChange={setUniverse} options={UNIVERSES} />
      </Controls>
      {isLoading ? <Section title="Loading…"><Loading rows={8} /></Section>
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={isFetching ? 'opacity-70 transition-opacity' : ''}>
            <Section
              title={`${data.found} ${UNIVERSE_LABEL[data.universe] ?? data.universe} stocks beat ${data.benchmark.symbol} in every ${name} on file`}
              sub={<>Each with at least {data.min_years} {name}s on file, out of {data.eligible}. Highest typical lead first.
                {forAdvisor && <> If results were coin flips, about {formatNumber(data.expected_by_luck, 0)} would still show a perfect record, so most of this list may be luck.</>}</>}
              aside={data.rows.length > 0 && (
                <button type="button" onClick={() => downloadCsv(`top-${data.universe}-${name}.csv`, data.rows)}
                  className="h-[44px] px-[16px] rounded-[10px] border border-pine text-pine text-[15px] font-semibold hover:bg-pine hover:text-on-dark transition-colors">
                  Download CSV
                </button>
              )}>
              {data.rows.length === 0 ? <EmptyState title={`None this ${name}`} message="No stock beat its benchmark in every year on file." /> : (
                <Box minWidth={820}>
                  <thead><tr className="border-b border-stone/20">
                    <th className={th}>Stock</th><th className={th}>Sector · industry</th>
                    <th className={thNum}>Years</th><th className={thNum}>Typical return</th>
                    <th className={thNum}>Typical lead over {data.benchmark.symbol}</th><th className={thNum}>Smallest lead</th>
                  </tr></thead>
                  <tbody>
                    {(all ? data.rows : data.rows.slice(0, SHOWN)).map((r) => (
                      <tr key={r.symbol} className="border-b border-stone/10 last:border-0">
                        <td className={td}>
                          <button type="button" onClick={() => onLookup(r.symbol)} className="text-left hover:underline">
                            <span className="font-mono font-semibold">{r.symbol}</span> <span className="text-stone text-[14px]">{displayName(r.name)}</span>
                          </button>
                        </td>
                        <td className={`${td} text-[14px] text-stone`}>{[r.sector, r.industry].filter(Boolean).join(' · ') || '—'}</td>
                        <td className={tdNum}>{r.years}</td>
                        <td className={tdNum}><Pct value={r.median_return} /></td>
                        <td className={tdNum}><Pct value={r.median_excess} /></td>
                        <td className={tdNum}><Pct value={r.worst_excess} /></td>
                      </tr>
                    ))}
                  </tbody>
                </Box>
              )}
              {data.rows.length > SHOWN && (
                <button type="button" onClick={() => setAll(!all)}
                  className="self-start text-[15px] font-medium text-pine hover:underline">
                  {all ? `Show the first ${SHOWN}` : `Show all ${data.rows.length}`}
                </button>
              )}
              <HowToRead notes={[
                `“Typical” is the median: the middle year. A lead is how far the stock finished ahead of ${data.benchmark.symbol} that ${name}.`,
                ...data.notes,
              ]} />
            </Section>
          </div>
        )}
    </div>
  )
}

// -- Sectors ------------------------------------------------------------------------

function BeatBar({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-[8px] justify-end">
      <span className="font-mono">{share(value)}</span>
      <span className="relative block h-[8px] w-[80px] rounded-[4px] bg-mist" aria-hidden>
        <span className="absolute inset-y-0 left-1/2 w-[2px] -ml-[1px] bg-stone/60" />
        <span className={`absolute inset-y-0 left-0 rounded-[4px] ${value >= 0.5 ? 'bg-gain' : 'bg-loss'}`} style={{ width: `${value * 100}%` }} />
      </span>
    </span>
  )
}

const SECTOR_HEADS = ['Beat the benchmark', 'Typical return', 'Typical lead', 'Stocks']

function SectorsTab() {
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [universe, setUniverse] = useState('SP500')
  const [compare, setCompare] = useState('')
  const { data, isLoading, isError, error, refetch, isFetching } = useSectorScorecard({ month, universe, compare: compare || undefined })
  const name = MONTHS[month - 1]
  const two = (data?.universes.length ?? 0) > 1
  const leader = data?.sectors[0]
  const lead = leader?.results[data!.universes[0]]
  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <MonthSelect id="sec-month" value={month} onChange={setMonth} />
        <div className="flex flex-col gap-[6px]">
          <label htmlFor="sec-universe" className="text-[13px] text-stone">Index</label>
          <Select id="sec-universe" value={universe} onChange={(v) => { setUniverse(v); if (v === compare) setCompare('') }}>
            {UNIVERSES.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
          </Select>
        </div>
        <div className="flex flex-col gap-[6px]">
          <label htmlFor="sec-compare" className="text-[13px] text-stone">Compare with</label>
          <Select id="sec-compare" value={compare} onChange={setCompare}>
            <option value="">Nothing</option>
            {UNIVERSES.filter((u) => u.value !== universe).map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
          </Select>
        </div>
      </Controls>
      {isLoading ? <Section title="Loading…"><Loading rows={11} /></Section>
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={isFetching ? 'opacity-70 transition-opacity' : ''}>
            <Section
              title={leader && lead
                ? `In ${name}, ${leader.sector} stocks have done best against the ${UNIVERSE_LABEL[data.universes[0]] ?? data.universes[0]}`
                : `Sectors in ${name}`}
              sub={lead && <>A typical lead of <span className="font-mono">{pct1(lead.median_excess)}</span>; {share(lead.beat_share)} of its stocks’ {name}s beat {data.benchmarks[0]?.symbol}. Sectors are ordered by typical lead.</>}>
              <Box minWidth={two ? 980 : 640}>
                <thead>
                  <tr className="border-b border-stone/20">
                    <th className={th} rowSpan={two ? 2 : 1}>Sector</th>
                    {two
                      ? data.universes.map((u) => {
                        const bench = data.benchmarks.find((b) => b.universe === u)?.symbol
                        return <th key={u} colSpan={4} className={`${thNum} text-center border-l border-stone/15`}>{UNIVERSE_LABEL[u] ?? u}{bench ? ` (against ${bench})` : ''}</th>
                      })
                      : SECTOR_HEADS.map((h) => <th key={h} className={thNum}>{h}</th>)}
                  </tr>
                  {two && (
                    <tr className="border-b border-stone/20">
                      {data.universes.map((u) => SECTOR_HEADS.map((h, i) => (
                        <th key={`${u}-${h}`} className={`${thNum} ${i === 0 ? 'border-l border-stone/15' : ''}`}>{h}</th>
                      )))}
                    </tr>
                  )}
                </thead>
                <tbody>
                  {data.sectors.map((s) => (
                    <tr key={s.sector_code} className="border-b border-stone/10 last:border-0">
                      <td className={td}>{s.sector}</td>
                      {data.universes.map((u) => {
                        const r = s.results[u]
                        if (!r) return <td key={u} colSpan={4} className={`${tdNum} text-stone`}>—</td>
                        return [
                          <td key={`${u}-b`} className={`${tdNum} ${two ? 'border-l border-stone/15' : ''}`}><BeatBar value={r.beat_share} /></td>,
                          <td key={`${u}-r`} className={tdNum}><Pct value={r.median_return} /></td>,
                          <td key={`${u}-m`} className={tdNum}><Pct value={r.median_excess} /></td>,
                          <td key={`${u}-n`} className={`${tdNum} text-stone`}>{r.stocks.toLocaleString('en-US')}</td>,
                        ]
                      })}
                    </tr>
                  ))}
                </tbody>
              </Box>
              <HowToRead notes={[
                `Beat the benchmark: how often a sector’s stocks finished ${name} ahead of their index’s fund (${data.benchmarks.map((b) => `${UNIVERSE_LABEL[b.universe ?? ''] ?? b.universe}: ${b.symbol}`).join(', ')}). 50% would be an even split.`,
                '“Typical” is the median: the middle value across the sector’s stocks and years.',
                ...data.notes,
              ]} />
            </Section>
          </div>
        )}
    </div>
  )
}

// -- the page -------------------------------------------------------------------------

/** Market patterns: how markets have behaved in the past, the same for every signed-in user.
 *  Shared by the advisor workspace (`forAdvisor`) and the family portal. */
export function ResearchPage({ forAdvisor = false }: { forAdvisor?: boolean }) {
  const [tab, setTab] = useState<Tab>('overview')
  // One choice for the views of a single index or stock, so it carries from tab to tab,
  // and one for the look-up (stocks and funds only).
  const [series, setSeries] = useState<Choice>(indexChoice('SPX')!)
  const [choice, setChoice] = useState<Choice | null>(null)
  // Choosing a name elsewhere on the page is a decision, so it opens the profile at once.
  const openLookup = (s: string) => { setChoice({ symbol: s, label: s }); setTab('lookup') }
  const openMonths = (c: Choice) => { setSeries(c); setTab('months') }
  return (
    <div className="max-w-[1280px] w-full mx-auto flex flex-col gap-[32px]">
      <div className="flex flex-col gap-[8px]">
        <h1 className="font-display font-medium text-[32px] md:text-[40px] leading-tight">Market patterns</h1>
        <p className="text-[17px] text-stone max-w-[820px]">
          How markets have behaved in the past: months, days, sectors and single stocks. A record of history, not advice.
        </p>
      </div>
      <GlanceCards />
      <div className="flex flex-col gap-[24px]">
        <Tabs tabs={TABS} value={tab} onChange={setTab} />
        {tab === 'overview' && <OverviewTab forAdvisor={forAdvisor} onLookup={openLookup} />}
        {tab === 'months' && <MonthsTab choice={series} onChoice={setSeries} />}
        {tab === 'calendar' && <CalendarTab choice={series} onChoice={setSeries} />}
        {tab === 'top' && <TopTab forAdvisor={forAdvisor} onLookup={openLookup} />}
        {tab === 'sectors' && <SectorsTab />}
        {tab === 'lookup' && <LookupTab choice={choice} onChoice={setChoice} onOpenMonths={openMonths} />}
      </div>
    </div>
  )
}
