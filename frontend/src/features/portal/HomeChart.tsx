import { useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { usePortalPerformance } from '@/hooks/usePortal'
import { useChartColours } from '@/context/ThemeContext'
import { formatCurrency, formatDate, formatPercent } from '@/lib/formatters'
import { daysAgo } from '@/features/portal/ui'

const PERIODS = [
  { value: '1M', label: '1M' }, { value: '3M', label: '3M' }, { value: 'YTD', label: 'YTD' },
  { value: '1Y', label: '1Y' }, { value: '3Y', label: '3Y' },
] as const
type Period = (typeof PERIODS)[number]['value']
const VIEWS = [{ value: 'value', label: 'Value' }, { value: 'return', label: 'Return vs S&P 500' }] as const
type View = (typeof VIEWS)[number]['value']

function since(period: Period): string {
  if (period === '1M') return daysAgo(30)
  if (period === '3M') return daysAgo(91)
  if (period === '1Y') return daysAgo(365)
  if (period === '3Y') return daysAgo(365 * 3)
  return `${new Date().getFullYear()}-01-01`
}

/** "$680k", "$1.2M": an axis has no room for the cents. */
function shortCurrency(value: number): string {
  const size = Math.abs(value)
  if (size >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  if (size >= 1e3) return `$${(value / 1e3).toFixed(0)}k`
  return `$${value.toFixed(0)}`
}

function Choice<T extends string>({ label, options, value, onChange }: {
  label: string; options: readonly { value: T; label: string }[]; value: T; onChange: (v: T) => void
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-[6px]">
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}
          className={`h-[40px] px-[14px] rounded-btn border text-[15px] transition-colors ${value === o.value
            ? 'bg-pine-deep border-pine-deep text-on-dark dark:bg-pine dark:border-pine'
            : 'bg-surface border-stone/50 hover:border-pine'}`}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** The home page's chart: what the accounts were worth over time, or their return beside the S&P 500. */
export function HomeChart({ accountId }: { accountId?: string }) {
  const [period, setPeriod] = useState<Period>('YTD')
  const [view, setView] = useState<View>('value')
  const chart = useChartColours()
  const { data, isLoading, isError } = usePortalPerformance({ account_id: accountId, start_date: since(period) })
  const axisTick = { fontSize: 13, fill: chart.axis, fontFamily: 'IBM Plex Mono' }
  // The first point of a return line is the day before the window, where no value may be on file.
  const points = (data?.series ?? []).filter((p) => view === 'return' || p.value != null)
  const first = points[0]?.value
  const last = points[points.length - 1]?.value
  const summary = data?.summary

  return (
    <section className="bg-surface border border-stone/25 rounded-[12px] p-[24px] md:p-[28px]">
      <div className="flex flex-wrap items-start justify-between gap-[14px] mb-[18px]">
        <div>
          <h2 className="text-[20px] font-semibold">{view === 'value' ? 'Portfolio value' : 'Your return against the S&P 500'}</h2>
          <p className="text-[15px] text-summit-ink/70 mt-[3px]">
            {view === 'value'
              ? first != null && last != null
                ? <>From <span className="font-mono">{formatCurrency(first)}</span> to <span className="font-mono">{formatCurrency(last)}</span>, deposits and withdrawals included.</>
                : 'What your accounts were worth at each day’s close.'
              : summary
                ? <>You <span className="font-mono">{formatPercent(summary.twr_pct)}</span> · S&amp;P 500 <span className="font-mono">{formatPercent(summary.benchmark_return_pct)}</span>, both from 0% at the start.</>
                : 'Both lines start at 0% at the beginning of the period.'}
            {data?.as_of ? ` Through ${formatDate(data.as_of)}.` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-[12px]">
          <Choice label="Chart" options={VIEWS} value={view} onChange={setView} />
          <Choice label="Period" options={PERIODS} value={period} onChange={setPeriod} />
        </div>
      </div>
      <div className="h-[320px]">
        {isLoading ? <div className="h-full rounded-[8px] bg-mist/60 animate-pulse" />
          : isError || points.length < 2
            ? <div className="h-full flex items-center justify-center text-summit-ink/70">No daily record for this period yet.</div>
            : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 6, right: 10, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke={chart.grid} vertical={false} />
                  <XAxis dataKey="date" minTickGap={70} tick={axisTick} axisLine={false} tickLine={false}
                    tickFormatter={(d: string) => formatDate(d).replace(/ \d+,/, '')} />
                  {view === 'value' ? (
                    <YAxis width={70} tick={axisTick} axisLine={false} tickLine={false} domain={['auto', 'auto']}
                      tickFormatter={shortCurrency} />
                  ) : (
                    <YAxis width={70} tick={axisTick} axisLine={false} tickLine={false}
                      tickFormatter={(v: number) => formatPercent(v, 0)} />
                  )}
                  {view === 'return' && <ReferenceLine y={0} stroke={chart.zero} strokeDasharray="4 4" />}
                  <Tooltip contentStyle={chart.tooltip} labelFormatter={(d: string) => formatDate(d)}
                    formatter={(v: number, name: string) => [view === 'value' ? formatCurrency(v) : formatPercent(v), name]} />
                  {view === 'value'
                    ? <Line name="Value" dataKey="value" stroke={chart.primary} strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />
                    : [
                      <Line key="benchmark" name="S&P 500" dataKey="benchmark" stroke={chart.benchmark} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />,
                      <Line key="twr" name="Your return" dataKey="twr" stroke={chart.primary} strokeWidth={2.5} dot={false} connectNulls isAnimationActive={false} />,
                    ]}
                </LineChart>
              </ResponsiveContainer>
            )}
      </div>
    </section>
  )
}
