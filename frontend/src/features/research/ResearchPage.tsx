import { useState, type ReactNode } from 'react'
import { isAxiosError } from 'axios'
import {
  useCalendarGrid, useMonthGrid, useResearchMonth, useResearchOutlook, useResearchWeek, useSecurityProfile,
  useSecuritySearch, useSectorScorecard, useTopPerformers,
} from '@/hooks/useResearch'
import type { RsBucket, RsPerformer, RsReturnRow, RsStats } from '@/api/types'
import { formatDate, formatNumber, formatPercent } from '@/lib/formatters'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { Field, Pills, Select, TextInput, tone, useDebounced } from '@/features/portal/ui'
import { CalendarHeatmap } from './CalendarHeatmap'
import { MonthGrid } from './MonthGrid'

// The page is shared by the advisor workspace and the family portal, so every size is
// an explicit pixel value: the portal's spacing override cannot change it.

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']

const UNIVERSES = [
  { value: 'SP500', label: 'S&P 500' },
  { value: 'R1000', label: 'Russell 1000' },
  { value: 'R2000', label: 'Russell 2000' },
  { value: 'R3000', label: 'Russell 3000' },
] as const
const UNIVERSE_LABEL: Record<string, string> = Object.fromEntries(UNIVERSES.map((u) => [u.value, u.label]))

type Tab = 'months' | 'calendar' | 'top' | 'sectors' | 'security'
const TABS: { value: Tab; label: string }[] = [
  { value: 'months', label: 'Months by year' },
  { value: 'calendar', label: 'Calendar days' },
  { value: 'top', label: 'Top performers' },
  { value: 'sectors', label: 'Sectors' },
  { value: 'security', label: 'A security' },
]

const th = 'px-[12px] py-[10px] text-[13px] font-medium text-stone text-left whitespace-nowrap'
const thNum = 'px-[12px] py-[10px] text-[13px] font-medium text-stone text-right whitespace-nowrap'
const td = 'px-[12px] py-[10px] text-[15px] align-top'
const tdNum = 'px-[12px] py-[10px] text-[15px] align-top text-right font-mono whitespace-nowrap'

function share(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

function Pct({ value }: { value: number | null | undefined }) {
  return <span className={`font-mono ${tone(value)}`}>{formatPercent(value)}</span>
}

function notFound(error: unknown) {
  return isAxiosError(error) && error.response?.status === 404
}

function unavailable(error: unknown) {
  return isAxiosError(error) && error.response?.status === 503
    ? 'Market data cannot be reached just now.'
    : 'Could not load this part of the market data.'
}

function Panel({ title, sub, children }: { title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <section className="bg-surface border border-stone/25 rounded-card p-[20px] flex flex-col gap-[14px] min-w-0">
      <div>
        <h2 className="font-display text-[20px] text-summit-ink">{title}</h2>
        {sub && <p className="text-[14px] text-stone mt-[4px]">{sub}</p>}
      </div>
      {children}
    </section>
  )
}

function Notes({ notes }: { notes: string[] }) {
  if (!notes.length) return null
  return (
    <ul className="text-[13px] text-stone space-y-[4px] list-disc pl-[18px]">
      {notes.map((n) => <li key={n}>{n}</li>)}
    </ul>
  )
}

function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-[10px]">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-[20px] w-full" />)}
    </div>
  )
}

function Box({ minWidth, children }: { minWidth: number; children: ReactNode }) {
  return (
    <div className="border border-stone/25 rounded-card bg-surface overflow-x-auto">
      <table className="w-full border-collapse" style={{ minWidth }}>{children}</table>
    </div>
  )
}

function ReturnList({ rows }: { rows: RsReturnRow[] }) {
  return (
    <ul className="divide-y divide-stone/15">
      {rows.map((r) => (
        <li key={r.symbol} className="flex justify-between gap-[12px] py-[6px] text-[15px]">
          <span className="min-w-0 truncate">{r.label} <span className="text-stone font-mono text-[13px]">{r.symbol}</span></span>
          <Pct value={r.ret} />
        </li>
      ))}
    </ul>
  )
}

function Record({ stats }: { stats: RsStats | null }) {
  if (!stats) return <span className="text-stone">no record</span>
  return (
    <span className="text-[13px] text-stone">
      median <Pct value={stats.median} /> · up {share(stats.share_up)} of {stats.count} years
    </span>
  )
}

// -- the three summary panels ----------------------------------------------------

function ThisWeek() {
  const { data, isLoading, isError, error, refetch } = useResearchWeek()
  if (isLoading) return <Panel title="This week"><Loading /></Panel>
  if (isError || !data) return <Panel title="This week"><ErrorState message={unavailable(error)} onRetry={() => refetch()} /></Panel>
  const sectors = [...data.sectors].sort((a, b) => b.ret - a.ret)
  return (
    <Panel title="This week" sub={`${formatDate(data.start)} to ${formatDate(data.end)} · week ${data.period}`}>
      <ReturnList rows={[...data.indices, ...data.funds]} />
      {sectors.length > 0 && (
        <div className="text-[14px] text-stone">
          Best sector: <span className="text-summit-ink">{sectors[0].label}</span> <Pct value={sectors[0].ret} />
          {' · '}worst: <span className="text-summit-ink">{sectors[sectors.length - 1].label}</span> <Pct value={sectors[sectors.length - 1].ret} />
        </div>
      )}
      {(data.best.length > 0 || data.worst.length > 0) && (
        <div className="grid grid-cols-2 gap-[12px] text-[14px]">
          {([['Rose most', data.best], ['Fell most', data.worst]] as const).map(([label, movers]) => (
            <div key={label}>
              <div className="text-stone text-[13px] mb-[4px]">{label}</div>
              {movers.slice(0, 5).map((m) => (
                <div key={m.symbol} className="flex justify-between font-mono"><span>{m.symbol}</span><Pct value={m.ret} /></div>
              ))}
            </div>
          ))}
        </div>
      )}
      <Notes notes={data.notes} />
    </Panel>
  )
}

function ThisMonth() {
  const { data, isLoading, isError, error, refetch } = useResearchMonth()
  if (isLoading) return <Panel title="This month so far"><Loading /></Panel>
  if (isError || !data) return <Panel title="This month so far"><ErrorState message={unavailable(error)} onRetry={() => refetch()} /></Panel>
  return (
    <Panel title={`${MONTHS[Number(data.month.slice(5, 7)) - 1] ?? data.month_name} so far`} sub={data.as_of ? `Through ${formatDate(data.as_of)}, against the month's own record` : undefined}>
      <ul className="divide-y divide-stone/15">
        {data.rows.slice(0, 8).map((r) => (
          <li key={r.symbol} className="py-[6px]">
            <div className="flex justify-between gap-[12px] text-[15px]">
              <span className="min-w-0 truncate">{r.label}</span>
              <Pct value={r.month_to_date} />
            </div>
            <Record stats={r.record} />
          </li>
        ))}
      </ul>
      <Notes notes={data.notes} />
    </Panel>
  )
}

// The luck estimate (how many perfect records coin flips would give) is shown on the
// advisor's page only: family members found it confusing (Sai, 2026-11-08).

function NextMonth({ forAdvisor }: { forAdvisor: boolean }) {
  const next = (new Date().getMonth() + 1) % 12 + 1
  const { data, isLoading, isError, error, refetch } = useResearchOutlook(next)
  const title = `${MONTHS[next - 1]}'s record`
  if (isLoading) return <Panel title={title}><Loading /></Panel>
  if (isError || !data) return <Panel title={title}><ErrorState message={unavailable(error)} onRetry={() => refetch()} /></Panel>
  const universe = data.sectors.universes[0]
  const sectors = [...data.sectors.sectors]
    .filter((s) => s.results[universe])
    .sort((a, b) => b.results[universe].beat_share - a.results[universe].beat_share)
  return (
    <Panel title={title} sub="What past years did in this month. A record, not a forecast.">
      <ul className="divide-y divide-stone/15">
        {data.indices.map((i) => (
          <li key={i.symbol} className="py-[6px]">
            <div className="flex justify-between gap-[12px] text-[15px]">
              <span>{i.label}</span><Pct value={i.record.mean} />
            </div>
            <span className="text-[13px] text-stone">
              average{i.record.first_year ? ` since ${i.record.first_year}` : ''} · <Record stats={i.record} />
            </span>
          </li>
        ))}
      </ul>
      {sectors.length > 0 && (
        <div className="text-[14px] text-stone">
          Sector most often ahead of {UNIVERSE_LABEL[universe] ?? universe}:{' '}
          <span className="text-summit-ink">{sectors[0].sector}</span>, {share(sectors[0].results[universe].beat_share)} of the time
        </div>
      )}
      <div className="text-[14px] text-stone">
        {data.steadiest.found} stocks beat {data.steadiest.benchmark.symbol} in every one of at least {data.steadiest.min_years} years.
        {forAdvisor && <> If results were coin flips, about {formatNumber(data.steadiest.expected_by_luck, 0)} would still show a perfect record.</>}
      </div>
      <Notes notes={data.notes} />
    </Panel>
  )
}

// -- the four tabs -----------------------------------------------------------------

const RANGES = [
  { value: 'all', label: 'All years' },
  { value: '1950', label: 'Since 1950' },
  { value: '25', label: 'Last 25 years' },
] as const

function CalendarTab() {
  const [symbol, setSymbol] = useState('SPX')
  const [stat, setStat] = useState<'mean' | 'median'>('mean')
  const [range, setRange] = useState<(typeof RANGES)[number]['value']>('1950')
  const typed = useDebounced(symbol.trim().toUpperCase(), 400)
  const lastYear = new Date().getFullYear() - 1
  const start_year = range === 'all' ? undefined : range === '1950' ? 1950 : lastYear - 24
  const { data, isLoading, isError, error, refetch, isFetching } = useCalendarGrid({ symbol: typed, stat, start_year, end_year: lastYear })
  return (
    <div className="space-y-[16px]">
      <div className="flex flex-wrap gap-[16px] items-end">
        <div className="w-[180px]">
          <Field label="Index or ticker" htmlFor="cal-symbol">
            <TextInput id="cal-symbol" value={symbol} onChange={setSymbol} placeholder="SPX, NDX, AAPL" />
          </Field>
        </div>
        <Pills label="Statistic" value={stat} onChange={setStat}
          options={[{ value: 'mean', label: 'Average' }, { value: 'median', label: 'Median' }]} />
        <Pills label="Years" value={range} onChange={setRange} options={RANGES} />
      </div>
      {!typed ? <EmptyState title="Name an index or a ticker" message="SPX, NDX and RUT go back decades; a stock's record is about five years." />
        : isLoading ? <Loading rows={10} />
        : notFound(error) ? <EmptyState title={`Nothing on file for ${typed}`} message="Try an index (SPX, NDX, RUT) or a ticker in one of the tracked indices." />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={`space-y-[12px] ${isFetching ? 'opacity-70' : ''}`}>
            <p className="text-[15px] text-stone">
              {data.symbol}: {data.stat === 'mean' ? 'average' : 'median'} change on each calendar date,{' '}
              {data.years.first} to {data.years.last} ({data.years.count} years) · {data.basis === 'total' ? 'dividends included' : 'price only, dividends left out'}
            </p>
            <CalendarHeatmap grid={data} />
            <Notes notes={data.notes} />
          </div>
        )}
    </div>
  )
}

const SPANS = [
  { value: '10', label: 'Last 10 years' },
  { value: '20', label: 'Last 20 years' },
  { value: 'all', label: 'All years' },
  { value: 'custom', label: 'Choose' },
] as const
type Span = (typeof SPANS)[number]['value']

function MonthsTab() {
  const [symbol, setSymbol] = useState('SPX')
  const [stat, setStat] = useState<'mean' | 'median'>('mean')
  const [span, setSpan] = useState<Span>('20')
  const [from, setFrom] = useState<number | undefined>()
  const [to, setTo] = useState<number | undefined>()
  const typed = useDebounced(symbol.trim().toUpperCase(), 400)
  const thisYear = new Date().getFullYear()
  const params = span === 'custom' ? { start_year: from, end_year: to }
    : span === 'all' ? {} : { start_year: thisYear - Number(span) + 1 }
  const { data, isLoading, isError, error, refetch, isFetching } = useMonthGrid({ symbol: typed, ...params })
  const years = data ? Array.from({ length: data.available.last - data.available.first + 1 }, (_, i) => data.available.last - i) : []
  const choose = (v: Span) => {
    if (v === 'custom' && data) { setFrom(data.years.first); setTo(data.years.last) }
    setSpan(v)
  }
  return (
    <div className="space-y-[16px]">
      <div className="flex flex-wrap gap-[16px] items-end">
        <div className="w-[180px]">
          <Field label="Index or ticker" htmlFor="grid-symbol">
            <TextInput id="grid-symbol" value={symbol} onChange={setSymbol} placeholder="SPX, AAPL, SPY" />
          </Field>
        </div>
        <Pills label="Headline row" value={stat} onChange={setStat}
          options={[{ value: 'mean', label: 'Average' }, { value: 'median', label: 'Median' }]} />
        <Pills label="Years" value={span} onChange={choose} options={SPANS} />
        {span === 'custom' && years.length > 0 && (
          <>
            <Field label="From" htmlFor="grid-from">
              <Select id="grid-from" value={String(from ?? '')} minWidth={110}
                onChange={(v) => { setFrom(Number(v)); if (to && Number(v) > to) setTo(Number(v)) }}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </Field>
            <Field label="To" htmlFor="grid-to">
              <Select id="grid-to" value={String(to ?? '')} minWidth={110}
                onChange={(v) => { setTo(Number(v)); if (from && Number(v) < from) setFrom(Number(v)) }}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </Field>
          </>
        )}
      </div>
      {!typed ? <EmptyState title="Name an index or a ticker" message="SPX, NDX and RUT go back decades; a stock's record is about five years." />
        : isLoading ? <Loading rows={12} />
        : notFound(error) ? <EmptyState title={`Nothing on file for ${typed}`} message="Try an index (SPX, NDX, RUT) or a ticker in one of the tracked indices." />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={`space-y-[12px] ${isFetching ? 'opacity-70' : ''}`}>
            <p className="text-[15px] text-stone">
              {data.symbol}: each month's return, {data.years.first} to {data.years.last} ({data.years.count} years;
              on file {data.available.first} to {data.available.last}) · {data.basis === 'total' ? 'dividends included' : 'price only, dividends left out'}
            </p>
            <MonthGrid grid={data} stat={stat} />
            <Notes notes={data.notes} />
          </div>
        )}
    </div>
  )
}

function MonthSelect({ id, value, onChange }: { id: string; value: number; onChange: (m: number) => void }) {
  return (
    <Field label="Month" htmlFor={id}>
      <Select id={id} value={String(value)} onChange={(v) => onChange(Number(v))} minWidth={160}>
        {MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}
      </Select>
    </Field>
  )
}

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

function TopTab({ forAdvisor }: { forAdvisor: boolean }) {
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [universe, setUniverse] = useState<string>('SP500')
  const { data, isLoading, isError, error, refetch, isFetching } = useTopPerformers({ month, universe })
  return (
    <div className="space-y-[16px]">
      <div className="flex flex-wrap gap-[16px] items-end">
        <MonthSelect id="top-month" value={month} onChange={setMonth} />
        <Pills label="Index" value={universe} onChange={setUniverse} options={UNIVERSES} />
      </div>
      {isLoading ? <Loading rows={8} />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={`space-y-[12px] ${isFetching ? 'opacity-70' : ''}`}>
            <div className="flex flex-wrap justify-between items-end gap-[12px]">
              <p className="text-[15px] text-stone max-w-[760px]">
                Stocks in the {UNIVERSE_LABEL[data.universe] ?? data.universe} that beat {data.benchmark.symbol} in{' '}
                {MONTHS[data.month - 1]} in every year on file (at least {data.min_years}).{' '}
                <span className="text-summit-ink">{data.found} of {data.eligible}</span> did.
                {forAdvisor && <>{' '}If {MONTHS[data.month - 1]} results were coin flips, about{' '}
                  <span className="text-summit-ink font-mono">{formatNumber(data.expected_by_luck, 0)}</span> would still show a
                  perfect record, so most of this list may be luck.</>}
              </p>
              {data.rows.length > 0 && (
                <button type="button" onClick={() => downloadCsv(`top-${data.universe}-${data.month_name}.csv`, data.rows)}
                  className="h-[44px] px-[16px] border border-pine rounded-btn bg-surface text-pine text-[15px] font-semibold hover:bg-pine hover:text-on-dark transition-colors">
                  Export CSV
                </button>
              )}
            </div>
            {data.rows.length === 0 ? <EmptyState title="None this month" message="No stock beat its benchmark in every year on file." /> : (
              <Box minWidth={820}>
                <thead><tr className="border-b border-stone/20">
                  <th className={th}>Symbol</th><th className={th}>Name</th><th className={th}>Sector · industry</th>
                  <th className={thNum}>Years</th><th className={thNum}>Median lead</th><th className={thNum}>Smallest lead</th>
                  <th className={thNum}>Median return</th>
                </tr></thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.symbol} className="border-b border-stone/10 last:border-0">
                      <td className={`${td} font-mono`}>{r.symbol}</td>
                      <td className={td}>{r.name ?? '—'}</td>
                      <td className={`${td} text-[14px] text-stone`}>{[r.sector, r.industry].filter(Boolean).join(' · ') || '—'}</td>
                      <td className={tdNum}>{r.years}</td>
                      <td className={tdNum}><Pct value={r.median_excess} /></td>
                      <td className={tdNum}><Pct value={r.worst_excess} /></td>
                      <td className={tdNum}><Pct value={r.median_return} /></td>
                    </tr>
                  ))}
                </tbody>
              </Box>
            )}
            <Notes notes={data.notes} />
          </div>
        )}
    </div>
  )
}

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

function SectorsTab() {
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const [universe, setUniverse] = useState('SP500')
  const [compare, setCompare] = useState('')
  const { data, isLoading, isError, error, refetch, isFetching } = useSectorScorecard({ month, universe, compare: compare || undefined })
  return (
    <div className="space-y-[16px]">
      <div className="flex flex-wrap gap-[16px] items-end">
        <MonthSelect id="sec-month" value={month} onChange={setMonth} />
        <Field label="Index" htmlFor="sec-universe">
          <Select id="sec-universe" value={universe} onChange={(v) => { setUniverse(v); if (v === compare) setCompare('') }}>
            {UNIVERSES.map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
          </Select>
        </Field>
        <Field label="Compare with" htmlFor="sec-compare">
          <Select id="sec-compare" value={compare} onChange={setCompare}>
            <option value="">Nothing</option>
            {UNIVERSES.filter((u) => u.value !== universe).map((u) => <option key={u.value} value={u.value}>{u.label}</option>)}
          </Select>
        </Field>
      </div>
      {isLoading ? <Loading rows={11} />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={`space-y-[12px] ${isFetching ? 'opacity-70' : ''}`}>
            <p className="text-[15px] text-stone">
              How often a sector's stocks beat their benchmark in {MONTHS[data.month - 1]}{' '}
              ({data.benchmarks.map((b) => `${UNIVERSE_LABEL[b.universe ?? ''] ?? b.universe}: ${b.symbol}`).join(', ')};
              50% would be an even split), what they returned, and how far ahead of the benchmark they finished
              (median lead). Highest lead first.
            </p>
            <Box minWidth={data.universes.length > 1 ? 980 : 640}>
              <thead>
                <tr className="border-b border-stone/20">
                  <th className={th} rowSpan={data.universes.length > 1 ? 2 : 1}>Sector</th>
                  {data.universes.length > 1 && data.universes.map((u) => (
                    <th key={u} colSpan={4} className={`${thNum} text-center border-l border-stone/15`}>{UNIVERSE_LABEL[u] ?? u}</th>
                  ))}
                  {data.universes.length === 1 && <><th className={thNum}>Beat the benchmark</th><th className={thNum}>Median return</th><th className={thNum}>Median lead</th><th className={thNum}>Stocks</th></>}
                </tr>
                {data.universes.length > 1 && (
                  <tr className="border-b border-stone/20">
                    {data.universes.map((u) => (
                      <SectorHeads key={u} />
                    ))}
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
                        <td key={`${u}-b`} className={`${tdNum} ${data.universes.length > 1 ? 'border-l border-stone/15' : ''}`}><BeatBar value={r.beat_share} /></td>,
                        <td key={`${u}-r`} className={tdNum}><Pct value={r.median_return} /></td>,
                        <td key={`${u}-m`} className={tdNum}><Pct value={r.median_excess} /></td>,
                        <td key={`${u}-n`} className={`${tdNum} text-stone`}>{r.stocks.toLocaleString('en-US')}</td>,
                      ]
                    })}
                  </tr>
                ))}
              </tbody>
            </Box>
            <Notes notes={data.notes} />
          </div>
        )}
    </div>
  )
}

function SectorHeads() {
  return <><th className={`${thNum} border-l border-stone/15`}>Beat the benchmark</th><th className={thNum}>Median return</th><th className={thNum}>Median lead</th><th className={thNum}>Stocks</th></>
}

function BucketTable({ buckets, label }: { buckets: RsBucket[]; label: string }) {
  return (
    <Box minWidth={520}>
      <thead><tr className="border-b border-stone/20">
        <th className={th}>{label}</th><th className={thNum}>Average</th><th className={thNum}>Median</th>
        <th className={thNum}>Up</th><th className={thNum}>Best</th><th className={thNum}>Worst</th><th className={thNum}>Count</th>
      </tr></thead>
      <tbody>
        {buckets.map((b) => (
          <tr key={b.bucket} className="border-b border-stone/10 last:border-0">
            <td className={td}>{b.bucket}</td>
            <td className={tdNum}><Pct value={b.mean} /></td>
            <td className={tdNum}><Pct value={b.median} /></td>
            <td className={tdNum}>{share(b.share_up)}</td>
            <td className={tdNum}><Pct value={b.best} /></td>
            <td className={tdNum}><Pct value={b.worst} /></td>
            <td className={`${tdNum} text-stone`}>{b.count}</td>
          </tr>
        ))}
      </tbody>
    </Box>
  )
}

function SecurityTab() {
  const [query, setQuery] = useState('')
  const [symbol, setSymbol] = useState<string | null>(null)
  const [month, setMonth] = useState(new Date().getMonth() + 1)
  const typed = useDebounced(query.trim(), 300)
  const search = useSecuritySearch(typed)
  const profile = useSecurityProfile(symbol, month)
  const p = profile.data
  return (
    <div className="space-y-[16px]">
      <div className="max-w-[420px]">
        <Field label="Find a security by name or ticker" htmlFor="sec-search">
          <TextInput id="sec-search" value={query} onChange={setQuery} placeholder="Schwab, AAPL, utilities fund" />
        </Field>
      </div>
      {typed && (search.isLoading ? <Loading rows={3} />
        : search.isError ? <ErrorState message={unavailable(search.error)} onRetry={() => search.refetch()} />
        : search.data && search.data.results.length === 0 ? <p className="text-[15px] text-stone">Nothing matches “{typed}”.</p>
        : (
          <div className="flex flex-wrap gap-[8px]">
            {search.data?.results.map((r) => (
              <button key={r.symbol} type="button" onClick={() => setSymbol(r.symbol)} aria-pressed={symbol === r.symbol}
                className={`text-left px-[12px] py-[8px] rounded-btn border text-[14px] ${symbol === r.symbol ? 'bg-pine border-pine text-on-dark' : 'bg-surface border-stone/40 hover:border-pine'}`}>
                <span className="font-mono font-semibold">{r.symbol}</span> {r.name ?? ''}
                {r.indices.length > 0 && <span className={`${symbol === r.symbol ? 'text-on-dark/75' : 'text-stone'} text-[12px]`}> · {r.indices.join(', ')}</span>}
              </button>
            ))}
          </div>
        ))}
      {!symbol ? null
        : profile.isLoading ? <Loading rows={8} />
        : notFound(profile.error) ? <EmptyState title={`No prices on file for ${symbol}`} message="Market data knows this security but holds no daily history for it yet." />
        : profile.isError || !p ? <ErrorState message={unavailable(profile.error)} onRetry={() => profile.refetch()} />
        : (
          <div className="space-y-[20px]">
            <div>
              <h3 className="font-display text-[24px]">{p.name ?? p.symbol} <span className="font-mono text-[18px] text-stone">{p.symbol}</span></h3>
              <p className="text-[14px] text-stone">
                {[p.sector, p.industry].filter(Boolean).join(' · ') || p.kind}
                {p.indices.length > 0 && ` · in ${p.indices.map((i) => UNIVERSE_LABEL[i] ?? i).join(', ')}`}
                {` · prices ${formatDate(p.first_day)} to ${formatDate(p.last_day)} · ${p.basis === 'total' ? 'dividends included' : 'price only'}`}
              </p>
            </div>
            <div>
              <h4 className="text-[15px] font-medium mb-[8px]">The last 12 months</h4>
              <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-[8px]">
                {p.last_12_months.map((m) => (
                  <div key={m.period} className="bg-mist/60 rounded-[8px] px-[10px] py-[8px]">
                    <div className="text-[12px] text-stone">{m.period}</div>
                    <Pct value={m.ret} />
                  </div>
                ))}
              </div>
            </div>
            <div className="grid gap-[20px] xl:grid-cols-2">
              <div className="space-y-[8px] min-w-0">
                <h4 className="text-[15px] font-medium">Month by month{p.month_of_year.years ? `, ${p.month_of_year.years.first} to ${p.month_of_year.years.last}` : ''}</h4>
                <BucketTable buckets={p.month_of_year.buckets} label="Month" />
              </div>
              {p.sector_month_of_year && (
                <div className="space-y-[8px] min-w-0">
                  <h4 className="text-[15px] font-medium">
                    Its sector, {p.sector}{p.sector_month_of_year.members ? ` (${p.sector_month_of_year.members} stocks today)` : ''}
                  </h4>
                  <BucketTable buckets={p.sector_month_of_year.buckets} label="Month" />
                  {p.sector_month_of_year.survivorship && (
                    <p className="text-[13px] text-stone">Today's members only: stocks that left the index are not counted.</p>
                  )}
                </div>
              )}
            </div>
            <div className="space-y-[8px]">
              <div className="flex flex-wrap items-end gap-[16px]">
                <h4 className="text-[15px] font-medium">{p.month_name}, trading day by trading day</h4>
                <MonthSelect id="profile-month" value={month} onChange={setMonth} />
              </div>
              <BucketTable buckets={p.month_by_trading_day.buckets} label="Day" />
            </div>
            <Notes notes={p.notes} />
          </div>
        )}
    </div>
  )
}

/** Market insights from the md schema, the same for every signed-in user. */
export function ResearchPage({ forAdvisor = false }: { forAdvisor?: boolean }) {
  const [tab, setTab] = useState<Tab>('months')
  return (
    <div className="max-w-[1400px] w-full mx-auto flex flex-col gap-[24px]">
      <div>
        <h1 className="font-display font-medium text-[32px] md:text-[40px] leading-tight">Market insights</h1>
        <p className="text-[16px] text-summit-ink/70 mt-[6px] max-w-[820px]">
          What the market data records about the past: weeks, months and seasons for indices, sectors and stocks.
          A description of history, not advice or a forecast.
        </p>
      </div>
      <div className="grid gap-[16px] lg:grid-cols-3">
        <ThisWeek />
        <ThisMonth />
        <NextMonth forAdvisor={forAdvisor} />
      </div>
      <section className="flex flex-col gap-[16px]">
        <h2 className="font-display text-[24px]">Explore</h2>
        <Pills label="Explore" value={tab} onChange={setTab} options={TABS} />
        <div className="bg-surface border border-stone/25 rounded-card p-[16px] md:p-[24px] min-w-0">
          {tab === 'months' && <MonthsTab />}
          {tab === 'calendar' && <CalendarTab />}
          {tab === 'top' && <TopTab forAdvisor={forAdvisor} />}
          {tab === 'sectors' && <SectorsTab />}
          {tab === 'security' && <SecurityTab />}
        </div>
      </section>
    </div>
  )
}
