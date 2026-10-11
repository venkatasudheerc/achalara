import { useMemo, useState, useCallback, useRef } from 'react'
import { useScope } from '@/context/ScopeContext'
import { useDateRange } from '@/context/DateRangeContext'

const PRESETS = [
  { label: '1M',  months: 1 },
  { label: '3M',  months: 3 },
  { label: '6M',  months: 6 },
  { label: '1Y',  months: 12 },
  { label: '3Y',  months: 36 },
  { label: 'MAX', months: null },
] as const

const QUICK_TICKERS = ['SPY', 'QQQ', 'AGG', 'DIA']

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

import { useClientPerformance, useClientMonthlyPerformance, useClientReturnsSeries } from '@/hooks/useClients'
import { useAccountPerformance, useAccountMonthlyPerformance, useAccountReturnsSeries } from '@/hooks/useAccounts'
import { useSleevePerformance, useSleeveMonthlyPerformance, useSleeveReturnsSeries } from '@/hooks/useSleeves'
import { useStrategyPerformance, useStrategyMonthlyPerformance, useStrategyReturnsSeries } from '@/hooks/useStrategies'
import { useBenchmark } from '@/hooks/useBenchmark'
import { PerformanceChart } from '@/components/PerformanceChart'
import { ReturnsSeriesChart } from '@/components/ReturnsSeriesChart'
import { MonthlyReturnsHeatmap } from '@/components/MonthlyReturnsHeatmap'
import { LevelBreakdown } from '@/components/LevelBreakdown'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatPercent } from '@/lib/formatters'
import { useNavigate } from 'react-router-dom'
import type { LevelPerformance, PerformanceChild, WeeklyReturnPoint } from '@/api/types'

/** Intermediate shape used while interpolating the benchmark close onto each series point. */
interface PointWithClose extends WeeklyReturnPoint {
  _bmk_close: number | null
}

function PerformanceHero({ perf }: { perf: LevelPerformance }) {
  const { summary, level, name } = perf
  const gainPos = (summary.total_unrealized_gain ?? 0) >= 0

  return (
    <div className="rounded-card p-8 bg-pine-deep text-paper mb-8">
      <div>
        <p className="text-xs font-mono tracking-widest text-mist/60 uppercase mb-1">
          {level} · {name}
        </p>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-6 mt-6">
          <div>
            <p className="text-xs text-mist/60 mb-1">TWR</p>
            <p className={`font-mono text-3xl font-medium tabular-nums ${
              summary.twr_pct != null && summary.twr_pct >= 0 ? 'text-gain' : 'text-loss'
            }`}>
              {summary.twr_pct != null ? formatPercent(summary.twr_pct) : '—'}
            </p>
            <p className="text-xs text-mist/40 mt-0.5">Time Weighted</p>
          </div>
          <div>
            <p className="text-xs text-mist/60 mb-1">MWR</p>
            <p className={`font-mono text-3xl font-medium tabular-nums ${
              summary.mwr_pct != null && summary.mwr_pct >= 0 ? 'text-gain' : 'text-loss'
            }`}>
              {summary.mwr_pct != null ? formatPercent(summary.mwr_pct) : '—'}
            </p>
            <p className="text-xs text-mist/40 mt-0.5">Money Weighted</p>
          </div>
          <div>
            <p className="text-xs text-mist/60 mb-1">
              {summary.cash_balance != null ? 'Total value' : 'Market value'}
            </p>
            <p className="font-mono text-2xl text-paper tabular-nums">
              {formatCurrency(summary.total_market_value + (summary.cash_balance ?? 0))}
            </p>
            <p className="text-xs text-mist/40 mt-0.5">
              {summary.cash_balance != null
                ? `${formatCurrency(summary.total_market_value)} securities · ${formatCurrency(summary.cash_balance)} cash`
                : `${formatCurrency(summary.total_cost_basis)} cost basis`}
            </p>
          </div>
          <div>
            <p className="text-xs text-mist/60 mb-1">Unrealised gain</p>
            <p className={`font-mono text-2xl tabular-nums ${gainPos ? 'text-gain' : 'text-loss'}`}>
              {formatCurrency(summary.total_unrealized_gain)}
            </p>
            <p className="text-xs text-mist/40 mt-0.5">On open positions</p>
          </div>
          <div>
            <p className="text-xs text-mist/60 mb-1">Realised gain</p>
            <p className={`font-mono text-2xl tabular-nums ${
              summary.total_realized_gain >= 0 ? 'text-gain' : 'text-loss'
            }`}>
              {formatCurrency(summary.total_realized_gain)}
            </p>
            <p className="text-xs text-mist/40 mt-0.5">
              {summary.closed_positions_count} closed
              {summary.total_income ? ` · ${formatCurrency(summary.total_income)} income` : ''}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function useActivePerformance() {
  const { scope } = useScope()
  const { startDate, endDate } = useDateRange()
  const dateParams = { start_date: startDate, end_date: endDate }

  const client = useClientPerformance(scope.clientId ?? '', dateParams)
  const account = useAccountPerformance(
    scope.clientId ?? '', scope.accountId ?? '', dateParams
  )
  const sleeve = useSleevePerformance(
    scope.clientId ?? '', scope.accountId ?? '', scope.sleeveId ?? '', dateParams
  )
  const strategy = useStrategyPerformance(scope.strategyId ?? '', dateParams)

  if (scope.level === 'sleeve') return sleeve
  if (scope.level === 'account') return account
  if (scope.level === 'strategy') return strategy
  if (scope.level === 'client') return client
  return { data: undefined, isLoading: false, isError: false, refetch: () => {} }
}

function useActiveMonthly() {
  const { scope } = useScope()
  const client = useClientMonthlyPerformance(scope.clientId ?? '')
  const account = useAccountMonthlyPerformance(scope.clientId ?? '', scope.accountId ?? '')
  const sleeve = useSleeveMonthlyPerformance(scope.clientId ?? '', scope.accountId ?? '', scope.sleeveId ?? '')
  const strategy = useStrategyMonthlyPerformance(scope.strategyId ?? '')

  if (scope.level === 'sleeve') return sleeve
  if (scope.level === 'account') return account
  if (scope.level === 'strategy') return strategy
  if (scope.level === 'client') return client
  return { data: undefined, isLoading: false, isError: false }
}

function useActiveReturnsSeries() {
  const { scope } = useScope()
  const client = useClientReturnsSeries(scope.clientId ?? '')
  const account = useAccountReturnsSeries(scope.clientId ?? '', scope.accountId ?? '')
  const sleeve = useSleeveReturnsSeries(scope.clientId ?? '', scope.accountId ?? '', scope.sleeveId ?? '')
  const strategy = useStrategyReturnsSeries(scope.strategyId ?? '')

  if (scope.level === 'sleeve') return sleeve
  if (scope.level === 'account') return account
  if (scope.level === 'strategy') return strategy
  if (scope.level === 'client') return client
  return { data: undefined }
}

export function PerformancePage() {
  const { scope } = useScope()
  const navigate = useNavigate()
  const { startDate, endDate, setDateRange } = useDateRange()
  const { data: perf, isLoading, isError, refetch } = useActivePerformance()
  const { data: monthly } = useActiveMonthly()
  const { data: returnsSeries } = useActiveReturnsSeries()

  // Benchmark state — local to this page
  const [benchmarkTicker, setBenchmarkTicker] = useState('SPY')
  const [inputValue, setInputValue] = useState('SPY')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch full benchmark history (no date filter) — client-side filtering happens in
  // filteredSeries below, same pattern as perf.timeseries.
  const { data: benchmarkData } = useBenchmark(benchmarkTicker)

  const handleTickerInput = useCallback((raw: string) => {
    const val = raw.toUpperCase().replace(/[^A-Z0-9.\-^]/g, '')
    setInputValue(val)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      if (val.length >= 1 && val.length <= 10) setBenchmarkTicker(val)
    }, 500)
  }, [])

  // Build the returns series for the chart: filter to visible window, attach benchmark
  // via nearest-prior lookup, then rebase all three lines to 0% at the first visible point.
  const filteredSeries = useMemo(() => {
    const series = returnsSeries?.series
    const bmk = benchmarkData?.timeseries

    if (!series || !series.length) return []

    const visible = series.filter((pt) => {
      if (startDate && pt.date < startDate) return false
      if (endDate && pt.date > endDate) return false
      return true
    })
    if (!visible.length) return []

    // Nearest-prior benchmark close for each visible point
    const withClose: PointWithClose[] = visible.map((pt) => {
      if (!bmk?.length) return { ...pt, _bmk_close: null }
      let lo = 0; let hi = bmk.length - 1; let match = null
      while (lo <= hi) {
        const mid = (lo + hi) >> 1
        if (bmk[mid].date <= pt.date) { match = bmk[mid]; lo = mid + 1 } else { hi = mid - 1 }
      }
      return { ...pt, _bmk_close: match?.close ?? null }
    })

    // Rebase to 0% at first visible point
    const baseTwr = withClose[0].twr_cumul ?? 0
    const baseMwr = withClose[0].mwr_cumul ?? 0
    const baseBmkClose = withClose[0]._bmk_close

    return withClose.map((pt) => ({
      date: pt.date,
      twr_cumul: pt.twr_cumul != null ? pt.twr_cumul - baseTwr : null,
      mwr_cumul: pt.mwr_cumul != null ? pt.mwr_cumul - baseMwr : null,
      benchmark_cumul: pt._bmk_close != null && baseBmkClose != null
        ? (pt._bmk_close / baseBmkClose) - 1
        : null,
    }))
  }, [returnsSeries, benchmarkData, startDate, endDate])

  const filteredTimeseries = useMemo(
    () => (perf?.timeseries ?? []).filter((pt) => {
      if (startDate && pt.date < startDate) return false
      if (endDate && pt.date > endDate) return false
      return true
    }),
    [perf, startDate, endDate],
  )

  const filteredBenchmark = useMemo(
    () => benchmarkData?.timeseries.filter((pt) => {
      if (startDate && pt.date < startDate) return false
      if (endDate && pt.date > endDate) return false
      return true
    }),
    [benchmarkData, startDate, endDate],
  )

  const applyPreset = (months: number | null) => {
    if (months === null) {
      setDateRange(undefined, undefined)
    } else {
      const end = new Date()
      const start = new Date()
      start.setMonth(start.getMonth() - months)
      setDateRange(toISODate(start), toISODate(end))
    }
  }

  const activePreset = (() => {
    if (!startDate && !endDate) return 'MAX'
    const end = endDate ? new Date(endDate) : new Date()
    const start = startDate ? new Date(startDate) : null
    if (!start) return null
    const diffMonths = (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth())
    const match = PRESETS.find((p) => p.months === diffMonths)
    return match?.label ?? null
  })()

  if (!scope.level) {
    return (
      <EmptyState
        title="Select a client or strategy"
        message="Choose a client from the Clients tab to view their performance, or browse Strategies to see firm-wide roll-ups."
        action={{ label: 'Browse clients', onClick: () => navigate('/app/clients') }}
      />
    )
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <SkeletonCard />
        <SkeletonCard />
      </div>
    )
  }

  if (isError || !perf) {
    return <ErrorState message="Could not load performance data." onRetry={() => refetch()} />
  }

  const makeChildHref = (child: PerformanceChild) => {
    if (scope.level === 'client') return `/app/clients/${scope.clientId}/accounts/${child.id}`
    if (scope.level === 'account') return `/app/clients/${scope.clientId}/accounts/${scope.accountId}/sleeves/${child.id}`
    if (scope.level === 'strategy' && child.client_id && child.account_id) {
      return `/app/clients/${child.client_id}/accounts/${child.account_id}/sleeves/${child.id}`
    }
    if (scope.level === 'strategy') return `/app/strategies/${scope.strategyId}`
    return '#'
  }

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      <PerformanceHero perf={perf} />

      {/* Timeseries chart */}
      <section className="bg-paper border border-stone/20 rounded-card p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone">
            Portfolio value over time
          </h2>
          <div className="flex items-center gap-3 flex-wrap">
            {/* Benchmark ticker selector */}
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-mono text-stone">vs</span>
              <div className="flex gap-1">
                {QUICK_TICKERS.map((t) => (
                  <button
                    key={t}
                    onClick={() => { setInputValue(t); setBenchmarkTicker(t) }}
                    className={`px-2 py-0.5 text-xs font-mono rounded transition-colors ${
                      benchmarkTicker === t
                        ? 'bg-gold/20 text-gold border border-gold/40'
                        : 'text-stone hover:text-summit-ink hover:bg-mist'
                    }`}
                  >
                    {t}
                  </button>
                ))}
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => handleTickerInput(e.target.value)}
                  placeholder="ticker"
                  maxLength={10}
                  className={`w-16 px-2 py-0.5 text-xs font-mono rounded border transition-colors bg-paper outline-none ${
                    !QUICK_TICKERS.includes(benchmarkTicker) && benchmarkTicker === inputValue
                      ? 'border-gold/60 text-gold'
                      : 'border-stone/30 text-stone focus:border-stone/60'
                  }`}
                />
              </div>
            </div>
            {/* Date presets */}
            <div className="flex gap-1">
              {PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => applyPreset(p.months)}
                  className={`px-2.5 py-1 text-xs font-mono rounded transition-colors ${
                    activePreset === p.label
                      ? 'bg-pine text-paper'
                      : 'text-stone hover:text-summit-ink hover:bg-mist'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        <PerformanceChart
          data={filteredTimeseries}
          benchmark={filteredBenchmark}
          benchmarkTicker={benchmarkTicker}
        />
        {benchmarkData?.warning && (
          <p className="text-xs font-mono text-stone/50 mt-2 text-right">
            Benchmark unavailable: {benchmarkData.warning}
          </p>
        )}
      </section>

      {/* TWR vs MWR returns series */}
      {returnsSeries && returnsSeries.series.length > 0 && (
        <section className="bg-paper border border-stone/20 rounded-card p-6">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-sm font-mono uppercase tracking-wide text-stone">
              TWR vs MWR — cumulative returns
            </h2>
            <div className="flex gap-4 text-xs font-mono text-stone">
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-6 border-t-2 border-pine" />
                TWR
              </span>
              <span className="flex items-center gap-1.5">
                <span className="inline-block w-6 border-t-2 border-dashed border-gold" />
                MWR
              </span>
              {filteredSeries.some((pt) => pt.benchmark_cumul != null) && (
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-6 border-t-2 border-dashed border-loss" />
                  {benchmarkTicker}
                </span>
              )}
            </div>
          </div>
          <p className="text-xs text-stone/60 mb-4">
            All lines rebased to 0% at the start of the selected period · lifetime returns shown in the hero above
          </p>
          <ReturnsSeriesChart
            data={filteredSeries ?? []}
            benchmarkTicker={benchmarkTicker}
          />
        </section>
      )}

      {/* Monthly heatmap */}
      {monthly && (
        <section className="bg-paper border border-stone/20 rounded-card p-6">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">
            Month-on-month returns
          </h2>
          <MonthlyReturnsHeatmap monthlyReturns={monthly.months} />
        </section>
      )}

      {/* Level breakdown */}
      {perf.children.length > 0 && (
        <section className="bg-paper border border-stone/20 rounded-card p-6">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">
            {scope.level === 'client' ? 'Accounts' : scope.level === 'account' ? 'Sleeves' : 'Breakdown'}
          </h2>
          <LevelBreakdown
            children={perf.children}
            makeHref={makeChildHref}
            label={scope.level === 'client' ? 'accounts' : 'sleeves'}
          />
        </section>
      )}
    </div>
  )
}
