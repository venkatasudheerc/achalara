import { useMemo } from 'react'
import { useChartColours } from '@/context/ThemeContext'
import type { RsMonthGrid, RsMonthSummary } from '@/api/types'
import { capOf, heat, signed } from './heat'

const MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ')
type Stat = 'mean' | 'median'

const SUMMARY_ROWS: { label: string; key: keyof RsMonthSummary; kind: 'ret' | 'share' | 'count' }[] = [
  { label: 'Average', key: 'mean', kind: 'ret' },
  { label: 'Median', key: 'median', kind: 'ret' },
  { label: 'Up', key: 'share_up', kind: 'share' },
  { label: 'Down', key: 'share_down', kind: 'share' },
  { label: 'Best', key: 'best', kind: 'ret' },
  { label: 'Worst', key: 'worst', kind: 'ret' },
  { label: 'Average size', key: 'abs_mean', kind: 'ret' },
  { label: 'Largest move', key: 'abs_best', kind: 'ret' },
  { label: 'Smallest move', key: 'abs_worst', kind: 'ret' },
  { label: 'Years', key: 'count', kind: 'count' },
]

const cellBase = 'h-[30px] px-[6px] text-right rounded-[4px] whitespace-nowrap'
const head = 'px-[6px] py-[6px] text-[13px] font-medium text-stone text-right font-sans'

function show(s: RsMonthSummary | null | undefined, key: keyof RsMonthSummary, kind: 'ret' | 'share' | 'count') {
  if (!s) return '—'
  const v = s[key]
  if (kind === 'count') return String(v)
  if (kind === 'share') return `${Math.round(v * 100)}%`
  // A size has no direction, so no sign.
  if (String(key).startsWith('abs')) return `${(v * 100).toFixed(2)}%`
  return `${signed(v)}%`
}

/** Each month's return year by year (newest first), with every calendar month's full
 *  record on demand beneath. The chosen statistic is drawn above it as a bar chart. */
export function MonthGrid({ grid, stat }: { grid: RsMonthGrid; stat: Stat }) {
  const colours = useChartColours().diverging
  const cap = useMemo(
    () => capOf(grid.rows.flatMap((r) => Object.values(r.months))),
    [grid],
  )
  const yearCap = useMemo(() => capOf(grid.rows.map((r) => r.ret)), [grid])
  const fill = (value: number, c = cap) => ({ background: heat(colours, value, c), color: colours.text })

  return (
    <div className="space-y-[16px]">
      <div className="overflow-x-auto rounded-[8px]">
        <table className="w-full min-w-[980px] border-separate border-spacing-[2px] font-mono text-[13px]">
          <caption className="sr-only">
            {grid.symbol} monthly returns, {grid.years.first} to {grid.years.last}
          </caption>
          <thead>
            <tr>
              <th scope="col" className={`${head} text-left sticky left-0 z-10 bg-surface`}>Year</th>
              {MONTHS.map((m) => <th key={m} scope="col" className={head}>{m}</th>)}
              <th scope="col" className={head}>Year</th>
            </tr>
          </thead>
          <tbody>
            {grid.rows.map((row) => (
              <tr key={row.year}>
                <th scope="row" className="sticky left-0 z-10 bg-surface px-[6px] text-left font-normal text-summit-ink">
                  {row.year}{!row.complete && <span className="text-stone">*</span>}
                </th>
                {MONTHS.map((_, i) => {
                  const v = row.months[String(i + 1)]
                  if (v == null) return <td key={i} className={cellBase} />
                  const running = row.running_month === i + 1
                  return (
                    <td key={i} className={`${cellBase} ${running ? 'outline-dashed outline-1 outline-stone' : ''}`}
                      style={fill(v)} title={running ? 'This month is still running' : undefined}>
                      {signed(v)}%
                    </td>
                  )
                })}
                <td className={`${cellBase} font-semibold`} style={fill(row.ret, yearCap)}
                  title={row.complete ? undefined : 'Not a whole year on file'}>
                  {signed(row.ret)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[13px] text-stone">
        * Not a whole year on file: the year's figure covers only the months shown. A dashed cell is the month still running.
      </p>

      <details>
      <summary className="cursor-pointer text-[15px] font-medium text-pine">Every figure, month by month</summary>
      <div className="mt-[12px] overflow-x-auto rounded-[8px] border border-stone/25">
        <table className="w-full min-w-[980px] border-collapse font-mono text-[13px]">
          <thead>
            <tr className="border-b border-stone/20">
              <th scope="col" className={`${head} text-left px-[10px] sticky left-0 z-10 bg-surface`}>{' '}</th>
              {MONTHS.map((m) => <th key={m} scope="col" className={head}>{m}</th>)}
              <th scope="col" className={head}>Year</th>
            </tr>
          </thead>
          <tbody>
            {SUMMARY_ROWS.map((r) => (
              <tr key={r.key} className={`border-b border-stone/10 last:border-0 ${r.key === stat ? 'bg-mist/50' : ''}`}>
                <th scope="row" className="sticky left-0 z-10 bg-surface px-[10px] py-[8px] text-left font-sans text-[14px] font-normal text-summit-ink whitespace-nowrap">{r.label}</th>
                {MONTHS.map((_, i) => {
                  const s = grid.summary[String(i + 1)]
                  const tone = r.kind === 'ret' && s && !r.key.startsWith('abs') ? (s[r.key] > 0 ? 'text-gain' : s[r.key] < 0 ? 'text-loss' : '') : ''
                  return <td key={i} className={`px-[6px] py-[8px] text-right ${tone}`}>{show(s, r.key, r.kind)}</td>
                })}
                <td className="px-[6px] py-[8px] text-right">{show(grid.year_summary, r.key, r.kind)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[13px] text-stone">
        The record counts whole months only; the Year column counts whole years only. Sizes ignore the sign:
        the largest and smallest moves either way.
      </p>
      </details>
    </div>
  )
}
