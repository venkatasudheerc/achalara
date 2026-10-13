import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from 'recharts'
import type { WeeklyReturnPoint } from '@/api/types'
import { useChartColours } from '@/context/ThemeContext'

interface Props {
  data: WeeklyReturnPoint[]
  benchmarkTicker?: string
}

const MONTH_ABBR = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function fmtAxisDate(dateStr: string): string {
  const d = new Date(dateStr)
  return `${MONTH_ABBR[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(1)}%`
}

function pickTicks(data: WeeklyReturnPoint[]): string[] {
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

export function ReturnsSeriesChart({ data, benchmarkTicker }: Props) {
  const chart = useChartColours()
  if (!data.length) {
    return (
      <div className="flex items-center justify-center h-48 text-stone text-sm">
        No returns data yet — run a snapshot rebuild or add trades to populate this chart.
      </div>
    )
  }

  const ticks = pickTicks(data)
  const hasBenchmark = benchmarkTicker && data.some((pt) => pt.benchmark_cumul != null)

  const legendFormatter = (value: string) => {
    if (value === 'twr_cumul') return 'TWR'
    if (value === 'mwr_cumul') return 'MWR'
    if (value === 'benchmark_cumul') return benchmarkTicker ?? 'Benchmark'
    return value
  }

  const tooltipFormatter = (v: number, name: string) => [
    fmtPct(v),
    legendFormatter(name),
  ]

  return (
    <div>
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={data} margin={{ top: 4, right: 40, left: 0, bottom: 0 }}>
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
            tickFormatter={(v: number) => fmtPct(v)}
            tick={{ fontFamily: 'IBM Plex Mono', fontSize: 11, fill: chart.axis }}
            tickLine={false}
            axisLine={false}
            width={72}
          />
          <Tooltip
            formatter={tooltipFormatter}
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
          <Legend
            formatter={legendFormatter}
            wrapperStyle={{ fontFamily: 'IBM Plex Mono', fontSize: 11, paddingTop: 8 }}
          />
          <Line
            type="monotone"
            dataKey="twr_cumul"
            stroke={chart.primary}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: chart.gold }}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="mwr_cumul"
            stroke={chart.gold}
            strokeWidth={2}
            strokeDasharray="5 3"
            dot={false}
            activeDot={{ r: 4, fill: chart.primary }}
            connectNulls
          />
          {hasBenchmark && (
            <Line
              type="monotone"
              dataKey="benchmark_cumul"
              stroke={chart.benchmark}
              strokeWidth={1.5}
              strokeDasharray="3 3"
              dot={false}
              activeDot={{ r: 4, fill: chart.axis }}
              connectNulls
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
