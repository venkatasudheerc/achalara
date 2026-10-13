import { useMemo } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'
import type { BenchmarkPoint, TimeseriesPoint } from '@/api/types'
import { formatCurrency } from '@/lib/formatters'
import { useChartColours } from '@/context/ThemeContext'

interface Props {
  data: TimeseriesPoint[]
  benchmark?: BenchmarkPoint[]
  benchmarkTicker?: string
  label?: string
}

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function fmtAxisDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${MONTH_ABBR[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`
}

function pickTicks(data: { date: string }[]): string[] {
  if (data.length <= 1) return data.map((d) => d.date)
  const first = new Date(data[0].date)
  const last = new Date(data[data.length - 1].date)
  const targetCount = Math.min(6, data.length)
  const ticks: string[] = []
  for (let i = 0; i < targetCount; i++) {
    const fraction = i / (targetCount - 1)
    const targetMs = first.getTime() + fraction * (last.getTime() - first.getTime())
    let best = data[0]
    let bestDiff = Infinity
    for (const pt of data) {
      const diff = Math.abs(new Date(pt.date).getTime() - targetMs)
      if (diff < bestDiff) { bestDiff = diff; best = pt }
    }
    if (!ticks.includes(best.date)) ticks.push(best.date)
  }
  return ticks
}

/** Latest benchmark close on or before `date` (benchmark sorted ascending). */
function closeOnOrBefore(benchmark: BenchmarkPoint[], date: string): number | null {
  let lo = 0
  let hi = benchmark.length - 1
  let match: BenchmarkPoint | null = null
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (benchmark[mid].date <= date) {
      match = benchmark[mid]
      lo = mid + 1
    } else {
      hi = mid - 1
    }
  }
  return match ? match.close : null
}

/**
 * What the same money would be worth in the benchmark.
 *
 * The benchmark starts with the portfolio's opening value and is then given
 * every later deposit and withdrawal on the day it happened, buying or selling
 * benchmark units at that day's close. Without this, a deposit lifts the
 * portfolio line and not the benchmark's, and the gap between them is mostly
 * money added rather than performance.
 */
function flowMatchedBenchmark(
  data: TimeseriesPoint[],
  benchmark: BenchmarkPoint[],
): (number | null)[] {
  if (!benchmark.length) return data.map(() => null)

  let units: number | null = null
  return data.map((pt) => {
    const close = closeOnOrBefore(benchmark, pt.date)
    if (close == null || close <= 0) return null
    if (units == null) {
      units = pt.value / close
    } else {
      units += (pt.net_flow ?? 0) / close
    }
    return units * close
  })
}

export function PerformanceChart({
  data,
  benchmark,
  benchmarkTicker = 'Benchmark',
  label = 'Portfolio value over time',
}: Props) {
  const chart = useChartColours()
  const chartData = useMemo(() => {
    if (!benchmark?.length || !data.length) return data as (TimeseriesPoint & { benchmark_value?: number | null })[]

    const benchmarkValues = flowMatchedBenchmark(data, benchmark)

    return data.map((pt, i) => ({ ...pt, benchmark_value: benchmarkValues[i] }))
  }, [data, benchmark])

  if (!data.length) {
    return (
      <div className="flex items-center justify-center h-48 text-stone text-sm">
        No timeseries data available for this period.
      </div>
    )
  }

  const ticks = pickTicks(data)
  const hasBenchmark = benchmark && benchmark.length > 0

  return (
    <div aria-label={label}>
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={chartData} margin={{ top: 4, right: 40, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
          <XAxis
            dataKey="date"
            ticks={ticks}
            tickFormatter={fmtAxisDate}
            tick={{ fontFamily: 'IBM Plex Mono', fontSize: 11, fill: chart.axis }}
            tickLine={false}
            axisLine={false}
            interval={0}
          />
          <YAxis
            tickFormatter={(v) => formatCurrency(v)}
            tick={{ fontFamily: 'IBM Plex Mono', fontSize: 11, fill: chart.axis }}
            tickLine={false}
            axisLine={false}
            width={90}
          />
          <Tooltip
            formatter={(v: number, name: string) => [
              formatCurrency(v),
              name === 'benchmark_value' ? `${benchmarkTicker} (same deposits)` : 'Portfolio',
            ]}
            labelFormatter={fmtAxisDate}
            contentStyle={{
              fontFamily: 'IBM Plex Mono',
              fontSize: 12,
              border: chart.tooltip.border,
              backgroundColor: chart.tooltip.backgroundColor,
              color: chart.tooltip.color,
              borderRadius: 8,
            }}
          />
          {hasBenchmark && (
            <Legend
              formatter={(value) => (value === 'benchmark_value' ? `${benchmarkTicker} (same deposits)` : 'Portfolio')}
              wrapperStyle={{ fontFamily: 'IBM Plex Mono', fontSize: 11, paddingTop: 8 }}
            />
          )}
          <Line
            type="monotone"
            dataKey="value"
            stroke={chart.primary}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: chart.gold }}
          />
          {hasBenchmark && (
            <Line
              type="monotone"
              dataKey="benchmark_value"
              stroke={chart.gold}
              strokeWidth={1.5}
              strokeDasharray="5 3"
              dot={false}
              activeDot={{ r: 4, fill: chart.primary }}
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
