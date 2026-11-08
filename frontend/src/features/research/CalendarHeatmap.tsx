import { useMemo, useState } from 'react'
import { useChartColours } from '@/context/ThemeContext'
import type { RsCalendar, RsCell } from '@/api/types'
import { capOf, heat, signed } from './heat'

const MONTHS = 'Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(' ')


/** Average (or median) daily change by calendar date: a diverging heatmap, loss to
 *  gain through a neutral grey, with the value printed in every cell and the days
 *  behind it on hover or focus. */
export function CalendarHeatmap({ grid }: { grid: RsCalendar }) {
  const colours = useChartColours().diverging
  const [picked, setPicked] = useState<RsCell | null>(null)

  const { byKey, cap } = useMemo(() => {
    const byKey = new Map(grid.cells.map((c) => [`${c.month}-${c.day}`, c]))
    return { byKey, cap: capOf(grid.cells.map((c) => c.value)) }
  }, [grid])

  const fill = (value: number) => heat(colours, value, cap)

  const describe = (c: RsCell) =>
    `${MONTHS[c.month - 1]} ${c.day}: ${grid.stat} ${signed(c.value)}% over ${c.days} ${c.days === 1 ? 'day' : 'days'}` +
    ` (mean ${signed(c.mean)}%, median ${signed(c.median)}%)`

  return (
    <div className="space-y-[12px]">
      <div className="flex flex-wrap items-center justify-between gap-[12px]">
        <p className="text-[14px] text-stone min-h-[20px]" aria-live="polite">
          {picked ? describe(picked) : 'Point at or tab to a cell for its days and median.'}
        </p>
        <div className="flex items-center gap-[8px] text-[12px] text-stone font-mono" aria-label="Colour scale">
          <span>{signed(-cap)}%</span>
          <span className="block h-[10px] w-[140px] rounded-[4px]"
            style={{ background: `linear-gradient(90deg, ${colours.loss}, ${colours.mid}, ${colours.gain})` }} />
          <span>{signed(cap)}%</span>
        </div>
      </div>
      <div className="overflow-x-auto rounded-[8px]">
        <table className="w-full min-w-[760px] border-separate border-spacing-[2px] font-mono text-[12px]">
          <caption className="sr-only">
            {grid.symbol} {grid.stat} daily change by calendar date, {grid.years.first} to {grid.years.last}
          </caption>
          <thead>
            <tr>
              <th className="w-[36px] text-stone font-normal text-right pr-[6px]" scope="col">Day</th>
              {MONTHS.map((m) => (
                <th key={m} scope="col" className="text-stone font-normal font-sans text-[13px] py-[4px]">{m}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: 31 }, (_, i) => i + 1).map((day) => (
              <tr key={day}>
                <th scope="row" className="text-stone font-normal text-right pr-[6px]">{day}</th>
                {MONTHS.map((_, m) => {
                  const cell = byKey.get(`${m + 1}-${day}`)
                  if (!cell) return <td key={m} aria-hidden className="h-[24px]" />
                  return (
                    <td key={m} tabIndex={0} title={describe(cell)}
                      onMouseEnter={() => setPicked(cell)} onFocus={() => setPicked(cell)}
                      className="h-[24px] text-center rounded-[4px] cursor-default outline-none focus:ring-2 focus:ring-gold"
                      style={{ background: fill(cell.value), color: colours.text }}>
                      {signed(cell.value)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
