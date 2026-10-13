import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usePortalPerformance } from '@/hooks/usePortal'
import { useChartColours } from '@/context/ThemeContext'
import { performanceApi } from '@/api/endpoints/performance'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatDate, formatMonthYear, formatPercent } from '@/lib/formatters'
import {
  AccountStrategyFields, Card, Field, PageHeader, Pills, ProvisionalNote, Select, Star, TableBox, TextInput,
  daysAgo, signedCurrency, td, tdNum, th, thNum, tone, useAccountStrategyFilter,
} from '@/features/portal/ui'
import type { MonthFigure, PortalGrain, PortalPeriod } from '@/api/types'

const PERIODS = [
  { value: '1M', label: '1M' }, { value: '3M', label: '3M' }, { value: 'YTD', label: 'YTD' },
  { value: '1Y', label: '1Y' }, { value: 'All', label: 'All' },
] as const
type Period = (typeof PERIODS)[number]['value']
const GRAINS = [
  { value: 'day', label: 'Daily' }, { value: 'week', label: 'Weekly' },
  { value: 'month', label: 'Monthly' }, { value: 'quarter', label: 'Quarterly' },
] as const
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function span(period: Period): { from: string; to: string } {
  if (period === '1M') return { from: daysAgo(30), to: '' }
  if (period === '3M') return { from: daysAgo(91), to: '' }
  if (period === '1Y') return { from: daysAgo(365), to: '' }
  if (period === 'YTD') return { from: `${new Date().getFullYear()}-01-01`, to: '' }
  return { from: '', to: '' }
}

/** Background and text for a month's return, strongest at the extremes. */
function heat(value: number | null): string {
  if (value == null) return 'text-stone'
  if (value >= 0.04) return 'bg-gain text-on-dark'
  if (value >= 0.015) return 'bg-gain/40 text-summit-ink'
  if (value >= 0) return 'bg-gain/15 text-summit-ink'
  if (value > -0.015) return 'bg-loss/15 text-summit-ink'
  if (value > -0.04) return 'bg-loss/45 text-summit-ink'
  return 'bg-loss text-on-dark'
}

function plain(value: number | null): string {
  return value == null ? '–' : `${value < 0 ? '−' : ''}${Math.abs(value * 100).toFixed(1)}%`
}

function periodLabel(row: PortalPeriod, grain: PortalGrain): string {
  const [year, month] = row.period_end.split('-').map(Number)
  if (grain === 'day') return formatDate(row.period_end)
  if (grain === 'week') return `Week of ${formatDate(row.period_start)}`
  if (grain === 'quarter') return `Q${Math.floor((month - 1) / 3) + 1} ${year}`
  return formatMonthYear(year, month)
}

function monthText(figure: MonthFigure | null): string {
  return figure ? `${formatMonthYear(figure.year, figure.month)} ${formatPercent(figure.twr_pct, 1)}` : '—'
}

export function PortalPerformancePage() {
  const filter = useAccountStrategyFilter()
  // A preset fills the two dates; editing a date leaves no preset selected.
  const [period, setPeriod] = useState<Period | null>('YTD')
  const [dates, setDates] = useState(span('YTD'))
  const [grain, setGrain] = useState<PortalGrain>('month')
  // Empty until one is chosen: the server then compares with its default.
  const [benchmark, setBenchmark] = useState('')
  const chart = useChartColours()
  const axisTick = { fontSize: 12, fill: chart.axis, fontFamily: 'IBM Plex Mono' }
  const backwards = !!dates.from && !!dates.to && dates.from > dates.to

  const { data, isLoading, isError, error, refetch } = usePortalPerformance(
    { ...filter.scope, start_date: dates.from || undefined, end_date: dates.to || undefined, grain, benchmark: benchmark || undefined },
    !backwards,
  )
  const pickPeriod = (p: Period) => { setPeriod(p); setDates(span(p)) }
  const setDate = (key: 'from' | 'to') => (v: string) => { setPeriod(null); setDates({ ...dates, [key]: v }) }

  if (isLoading) return <div className="grid gap-16 md:grid-cols-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
  if (isError || !data) return <ErrorState message={error?.message ?? 'Could not load performance.'} onRetry={() => refetch()} />

  const s = data.summary
  const compared = data.benchmarks.find((b) => b.code === data.benchmark)
  const benchmarkName = compared?.name ?? data.benchmark
  const report = filter.account
    ? `${performanceApi.reportUrl(filter.account.client_id, filter.account.id)}${dates.to ? `?as_of=${dates.to}` : ''}`
    : null
  const years = [...new Set(data.months.map((m) => m.year))].sort()
  const anyProvisional = !!s?.is_provisional || data.months.some((m) => m.is_provisional)

  return (
    <>
      <PageHeader title="Performance"
        sub={s
          ? `${formatDate(s.start)} to ${formatDate(s.end)} · through market close · ${data.includes_cash ? 'includes cash' : 'securities only'}`
          : 'No performance recorded for this selection'}
        action={
          <div className="flex flex-col items-end gap-1.5">
            {report ? (
              <a href={report} target="_blank" rel="noreferrer"
                className="h-11 px-16 inline-flex items-center rounded-btn bg-pine-deep dark:bg-pine text-on-dark text-sm font-medium hover:bg-pine dark:hover:bg-pine-deep transition-colors">
                Download report
              </a>
            ) : (
              <button type="button" disabled
                className="h-11 px-16 rounded-btn bg-mist text-stone text-sm font-medium cursor-not-allowed">
                Download report
              </button>
            )}
            <span className="text-xs text-stone">
              {report ? 'PDF for the chosen account' : 'Choose one account to download its PDF report'}
            </span>
          </div>
        } />

      <div className="p-5 border border-stone/25 rounded-card bg-surface flex flex-wrap gap-x-5 gap-y-16 items-end">
        <AccountStrategyFields filter={filter} idPrefix="performance" />
        <Field label="Period"><Pills mono label="Period" options={PERIODS} value={period} onChange={pickPeriod} /></Field>
        {/* The two dates travel together, so one never wraps away from the other. */}
        <div className="flex gap-3 items-end">
          <Field label="Start date" htmlFor="performance-from">
            <TextInput id="performance-from" type="date" value={dates.from} onChange={setDate('from')} />
          </Field>
          <Field label="End date" htmlFor="performance-to">
            <TextInput id="performance-to" type="date" value={dates.to} onChange={setDate('to')} />
          </Field>
        </div>
        <Field label="Compare with" htmlFor="performance-benchmark">
          <Select id="performance-benchmark" value={data.benchmark} onChange={setBenchmark} minWidth={230}>
            {data.benchmarks.map((b) => <option key={b.code} value={b.code}>{b.name}</option>)}
          </Select>
        </Field>
        <p role="status" className={`basis-full text-xs ${backwards ? 'text-loss' : 'text-stone'}`}>
          {backwards
            ? 'The start date is after the end date.'
            : data.first_date
              ? `The record runs from ${formatDate(data.first_date)} to ${formatDate(data.as_of)}.`
              : ''}
        </p>
      </div>

      {!s ? (
        <EmptyState title="Nothing to show for this selection"
          message={filter.strategyId
            ? 'This strategy has no daily record in the chosen dates. Try another period, or all strategies.'
            : 'There is no daily record in the chosen dates. Try a wider period.'} />
      ) : (
        <>
          <section aria-label="Summary" className="space-y-16">
            <div className="grid gap-16 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
              <Card dark label="Value at the end" sub={`Started the period at ${formatCurrency(s.opening_value)}`}>
                <span className="text-3xl">{formatCurrency(s.closing_value)}</span>
              </Card>
              <Card label="Time-weighted return" sub="How the investments did, ignoring when money moved">
                <span className={`text-3xl ${tone(s.twr_pct)}`}>{formatPercent(s.twr_pct)}</span><Star show={s.is_provisional} />
              </Card>
              <Card label="Money-weighted return"
                sub={data.includes_cash ? 'What your own money earned, given your deposits' : 'Shown for whole accounts, not for one strategy'}>
                <span className={`text-3xl ${tone(s.mwr_pct)}`}>{formatPercent(s.mwr_pct)}</span>
                <Star show={s.is_provisional && s.mwr_pct != null} />
              </Card>
              <Card label={`Against ${benchmarkName}`}
                sub={s.benchmark_return_pct == null
                  ? `No ${data.benchmark} prices on file for this period`
                  : `${data.benchmark} returned ${formatPercent(s.benchmark_return_pct)} ${s.benchmark_from
                    ? `since ${formatDate(s.benchmark_from)}, where its price history here begins`
                    : 'over the same period'}${compared && !compared.includes_dividends ? ', dividends not included' : ''}`}>
                <span className={`text-3xl ${tone(s.excess_return_pct)}`}>{formatPercent(s.excess_return_pct)}</span>
              </Card>
            </div>
            <div className="px-6 py-16 border border-stone/25 rounded-card bg-surface flex flex-wrap gap-x-48 gap-y-3 text-sm text-summit-ink/85">
              <div>Gain / loss <span className={`font-mono font-medium ${tone(s.gain)}`}>{signedCurrency(s.gain)}</span></div>
              <div>Net deposits <span className="font-mono font-medium text-summit-ink">{signedCurrency(s.net_flow)}</span></div>
              <div>Best month <span className="font-mono font-medium text-summit-ink">{monthText(s.best_month)}</span></div>
              <div>Worst month <span className="font-mono font-medium text-summit-ink">{monthText(s.worst_month)}</span></div>
              <div>Months up <span className="font-mono font-medium text-summit-ink">{s.months_up} of {s.months_total}</span></div>
            </div>
          </section>

          <section className="p-6 border border-stone/25 rounded-card bg-surface space-y-16">
            <div className="flex flex-wrap justify-between items-center gap-x-6 gap-y-3">
              <div className="space-y-1">
                <h2 className="text-base font-semibold">Cumulative returns</h2>
                <p className="text-[13px] text-stone">All lines start at 0% at the beginning of the selected period.</p>
              </div>
              <div className="flex flex-wrap gap-5 text-[13px] text-summit-ink/85">
                <span className="flex items-center gap-2"><span className="w-7 border-t-[3px]" style={{ borderColor: chart.primary }} />Time-weighted</span>
                {data.includes_cash && <span className="flex items-center gap-2"><span className="w-7 border-t-[3px] border-dashed border-gold" />Money-weighted</span>}
                <span className="flex items-center gap-2"><span className="w-7 border-t-2" style={{ borderColor: chart.benchmark }} />{data.benchmark}</span>
              </div>
            </div>
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.series} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke={chart.grid} vertical={false} />
                  <XAxis dataKey="date" minTickGap={70} tick={axisTick} axisLine={false} tickLine={false}
                    tickFormatter={(d: string) => formatDate(d).replace(/ \d+,/, '')} />
                  <YAxis width={64} tick={axisTick} axisLine={false} tickLine={false}
                    tickFormatter={(v: number) => formatPercent(v, 1)} />
                  <ReferenceLine y={0} stroke={chart.zero} strokeDasharray="4 4" />
                  <Tooltip contentStyle={chart.tooltip} labelFormatter={(d: string) => formatDate(d)}
                    formatter={(v: number, name: string) => [formatPercent(v), name]} />
                  <Line name={data.benchmark} dataKey="benchmark" stroke={chart.benchmark} strokeWidth={1.75} dot={false} connectNulls isAnimationActive={false} />
                  {data.includes_cash && <Line name="Money-weighted" dataKey="mwr" stroke={chart.gold} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls isAnimationActive={false} />}
                  <Line name="Time-weighted" dataKey="twr" stroke={chart.primary} strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}

      {years.length > 0 && (
        <section className="p-6 border border-stone/25 rounded-card bg-surface space-y-16">
          <h2 className="text-base font-semibold">Month-on-month returns</h2>
          <div className="overflow-x-auto">
            <div className="min-w-[920px] flex flex-col gap-1.5 font-mono text-[13px]">
              <div className="grid gap-1.5 text-stone text-center [grid-template-columns:56px_repeat(12,minmax(0,1fr))_12px_minmax(0,1.1fr)]">
                <span className="text-left">Year</span>
                {MONTHS.map((m) => <span key={m}>{m}</span>)}
                <span /><span>YTD</span>
              </div>
              {years.map((year) => {
                const total = data.years.find((y) => y.year === year)
                return (
                  <div key={year} className="grid gap-1.5 items-center [grid-template-columns:56px_repeat(12,minmax(0,1fr))_12px_minmax(0,1.1fr)]">
                    <span className="text-summit-ink/85">{year}</span>
                    {MONTHS.map((_, i) => {
                      const cell = data.months.find((m) => m.year === year && m.month === i + 1)
                      return (
                        <span key={i} className={`flex items-center justify-center h-9 rounded ${heat(cell?.twr_pct ?? null)}`}>
                          {plain(cell?.twr_pct ?? null)}{cell?.is_provisional && cell.twr_pct != null ? '*' : ''}
                        </span>
                      )
                    })}
                    <span />
                    <span className={`flex items-center justify-center h-9 rounded font-medium ${heat(total?.twr_pct ?? null)}`}>
                      {plain(total?.twr_pct ?? null)}{total?.is_provisional && total.twr_pct != null ? '*' : ''}
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </section>
      )}

      <section className="p-6 border border-stone/25 rounded-card bg-surface space-y-16">
        <div className="flex flex-wrap justify-between items-center gap-x-6 gap-y-3">
          <h2 className="text-base font-semibold">Performance by period</h2>
          <Pills label="Group by" options={GRAINS} value={grain} onChange={setGrain} />
        </div>
        <TableBox minWidth={1000} empty={data.periods.length === 0 && 'No periods in the chosen dates.'}>
          <thead>
            <tr>
              <th scope="col" className={th}>Period</th><th scope="col" className={thNum}>Opening</th>
              <th scope="col" className={thNum}>Net deposits</th><th scope="col" className={thNum}>Gain / loss</th>
              <th scope="col" className={thNum}>Closing</th><th scope="col" className={thNum}>Time-weighted</th>
              <th scope="col" className={thNum}>{data.benchmark}</th><th scope="col" className={thNum}>Excess</th>
              <th scope="col" className={thNum}>Year to date</th>
            </tr>
          </thead>
          <tbody>
            {data.periods.map((row) => (
              <tr key={row.period_start} className="border-t border-stone/15">
                <td className={`${td} font-mono whitespace-nowrap`}>{periodLabel(row, grain)}<Star show={row.is_provisional} /></td>
                <td className={tdNum}>{formatCurrency(row.opening_value)}</td>
                <td className={`${tdNum} text-summit-ink/85`}>{row.net_flow ? signedCurrency(row.net_flow) : '–'}</td>
                <td className={`${tdNum} ${tone(row.gain)}`}>{signedCurrency(row.gain)}</td>
                <td className={tdNum}>{formatCurrency(row.closing_value)}</td>
                <td className={`${tdNum} ${tone(row.twr_pct)}`}>{formatPercent(row.twr_pct)}</td>
                <td className={`${tdNum} ${tone(row.benchmark_return_pct)}`}>{formatPercent(row.benchmark_return_pct)}</td>
                <td className={`${tdNum} ${tone(row.excess_return_pct)}`}>{formatPercent(row.excess_return_pct)}</td>
                <td className={`${tdNum} ${tone(row.twr_ytd_pct)}`}>{formatPercent(row.twr_ytd_pct)}</td>
              </tr>
            ))}
          </tbody>
        </TableBox>
        <p className="text-[13px] text-stone leading-relaxed">
          {data.includes_cash
            ? 'Returns are for whole accounts, cash included.'
            : 'Returns are for securities only; cash is held by the account, not by a strategy.'}{' '}
          A single strategy shows a time-weighted return only, since deposits are made to the account, not to a strategy.
          {grain === 'day' && data.periods.length >= 400 && ' The most recent 400 days are listed; narrow the dates to see earlier ones.'}
        </p>
      </section>

      {anyProvisional && <ProvisionalNote />}
    </>
  )
}
