import { useState } from 'react'
import { usePerformancePeriods } from '@/hooks/usePerformancePeriods'
import type { PerformanceTarget } from '@/api/endpoints/performance'
import type { PeriodGrain, PeriodPerformance } from '@/api/types'
import { DataTable, type Column } from '@/components/DataTable'
import { ErrorState } from '@/components/ErrorState'
import { Skeleton } from '@/components/Skeleton'
import { formatCurrency, formatDate, formatPercent } from '@/lib/formatters'

const GRAINS: { value: PeriodGrain; label: string }[] = [
  { value: 'day', label: 'Daily' },
  { value: 'week', label: 'Weekly' },
  { value: 'month', label: 'Monthly' },
  { value: 'quarter', label: 'Quarterly' },
]

// Enough to scroll through without rendering years of days at once.
const MAX_ROWS = 120

function periodLabel(row: PeriodPerformance, grain: PeriodGrain): string {
  const [year, month] = row.period_end.split('-').map(Number)
  if (grain === 'day') return formatDate(row.period_end)
  if (grain === 'week') return `Week to ${formatDate(row.period_end)}`
  if (grain === 'quarter') return `Q${Math.floor((month - 1) / 3) + 1} ${year}`
  return formatDate(row.period_end).replace(/ \d+,/, '')
}

function Signed({ value }: { value: number | null }) {
  if (value == null) return <span className="text-stone">—</span>
  return <span className={value >= 0 ? 'text-gain' : 'text-loss'}>{formatPercent(value)}</span>
}

/**
 * Performance by day, week, month or quarter for the entity in scope.
 * Every row is read from the stored daily record, so the grains agree.
 */
export function PeriodTable({
  target,
  benchmark,
}: {
  target: PerformanceTarget
  benchmark?: string
}) {
  const [grain, setGrain] = useState<PeriodGrain>('month')
  const { data, isLoading, isError, refetch } = usePerformancePeriods(target, grain, benchmark)

  // Most recent first.
  const rows = [...(data?.periods ?? [])].reverse()
  const shown = rows.slice(0, MAX_ROWS)
  const showCash = shown.some((r) => r.cash_value != null)
  const showBenchmark = shown.some((r) => r.benchmark_return_pct != null)

  const columns: Column<PeriodPerformance>[] = [
    {
      key: 'period', header: 'Period', sortValue: (r) => r.period_end,
      render: (r) => (
        <span className="whitespace-nowrap">
          {periodLabel(r, grain)}
          {r.is_provisional && (
            <span
              className="ml-2 text-[10px] uppercase tracking-wide text-stone"
              title="The brokerage's transactions for these days may still be arriving. The value is final; the split between deposits and gain can change."
            >
              provisional
            </span>
          )}
        </span>
      ),
    },
    { key: 'opening', header: 'Opening (at cost)', numeric: true, sortValue: (r) => r.opening_value, render: (r) => formatCurrency(r.opening_value) },
    { key: 'net_flow', header: 'Net deposits', numeric: true, sortValue: (r) => r.net_flow, render: (r) => (r.net_flow === 0 ? <span className="text-stone">—</span> : formatCurrency(r.net_flow)) },
    { key: 'gain', header: 'Realised gain', numeric: true, sortValue: (r) => r.gain, render: (r) => <span className={r.gain >= 0 ? 'text-gain' : 'text-loss'}>{formatCurrency(r.gain)}</span> },
    { key: 'closing', header: 'Closing (at cost)', numeric: true, sortValue: (r) => r.closing_value, render: (r) => formatCurrency(r.closing_value) },
    ...(showCash
      ? [{ key: 'cash', header: 'Cash', numeric: true, sortValue: (r: PeriodPerformance) => r.cash_value ?? 0, render: (r: PeriodPerformance) => formatCurrency(r.cash_value) }]
      : []),
    { key: 'twr', header: 'TWR', numeric: true, sortValue: (r) => r.twr_pct ?? -Infinity, render: (r) => <Signed value={r.twr_pct} /> },
    { key: 'mwr', header: 'MWR', numeric: true, sortValue: (r) => r.mwr_pct ?? -Infinity, render: (r) => <Signed value={r.mwr_pct} /> },
    ...(showBenchmark
      ? [
          { key: 'benchmark', header: benchmark ?? 'Benchmark', numeric: true, sortValue: (r: PeriodPerformance) => r.benchmark_return_pct ?? -Infinity, render: (r: PeriodPerformance) => <Signed value={r.benchmark_return_pct} /> },
          { key: 'excess', header: 'Excess', numeric: true, sortValue: (r: PeriodPerformance) => r.excess_return_pct ?? -Infinity, render: (r: PeriodPerformance) => <Signed value={r.excess_return_pct} /> },
        ]
      : []),
    { key: 'ytd', header: 'YTD', numeric: true, sortValue: (r) => r.twr_ytd_pct ?? -Infinity, render: (r) => <Signed value={r.twr_ytd_pct} /> },
    {
      key: 'basis', header: 'Source', sortValue: (r) => r.basis,
      render: (r) => (
        <span
          className="text-xs text-stone"
          title={
            r.basis === 'observed'
              ? "Recorded from the brokerage's own holdings, cash and total on the day."
              : r.basis === 'reconstructed'
                ? 'Rebuilt from trades and daily closing prices.'
                : 'Partly recorded from the brokerage, partly rebuilt from trades and prices.'
          }
        >
          {r.basis === 'observed' ? 'Observed' : r.basis === 'reconstructed' ? 'Rebuilt' : 'Mixed'}
        </span>
      ),
    },
  ]

  return (
    <section className="bg-paper border border-stone/20 rounded-card p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone">Performance by period</h2>
          <p className="text-xs text-stone/60 mt-1">
            Realised basis: positions are carried at cost, so unrealised gains are left out of values and returns.
          </p>
        </div>
        <div className="flex gap-1" role="tablist" aria-label="Period length">
          {GRAINS.map((g) => (
            <button
              key={g.value}
              role="tab"
              aria-selected={grain === g.value}
              onClick={() => setGrain(g.value)}
              className={`px-3 py-1 text-xs font-mono rounded-btn transition-colors ${
                grain === g.value
                  ? 'bg-pine text-paper'
                  : 'text-stone hover:text-summit-ink'
              }`}
            >
              {g.label}
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : isError ? (
        <ErrorState message="Could not load performance by period." onRetry={() => refetch()} />
      ) : (
        <>
          {rows.length > shown.length && (
            <p className="text-xs text-stone mb-3">
              Showing the {shown.length} most recent of {rows.length} periods.
            </p>
          )}
          <DataTable
            columns={columns}
            rows={shown}
            getKey={(r) => r.period_end}
            emptyMessage="No daily performance record has been built for this yet."
          />
        </>
      )}
    </section>
  )
}
