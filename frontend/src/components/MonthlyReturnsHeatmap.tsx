import type { MonthlyReturn } from '@/api/types'

const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

function cellColor(ret: number): string {
  if (ret > 5) return 'bg-gain text-on-dark'
  if (ret > 2) return 'bg-gain/60 text-summit-ink'
  if (ret > 0) return 'bg-gain/30 text-summit-ink'
  if (ret === 0) return 'bg-mist text-stone'
  if (ret > -2) return 'bg-loss/30 text-summit-ink'
  if (ret > -5) return 'bg-loss/60 text-on-dark'
  return 'bg-loss text-on-dark'
}

interface Props { monthlyReturns: MonthlyReturn[] }

export function MonthlyReturnsHeatmap({ monthlyReturns }: Props) {
  if (!monthlyReturns.length) {
    return (
      <div className="text-stone text-sm py-8 text-center">
        No monthly return data available.
      </div>
    )
  }

  const years = [...new Set(monthlyReturns.map((r) => r.year))].sort()
  const byYearMonth = new Map(
    monthlyReturns.map((r) => [`${r.year}-${r.month}`, r.return_pct])
  )

  // Each year's return is its months compounded, not added.
  const byYear = new Map<number, number>()
  for (const r of monthlyReturns) {
    if (r.return_pct == null) continue
    byYear.set(r.year, (byYear.get(r.year) ?? 1) * (1 + r.return_pct / 100))
  }
  const yearReturn = (year: number): number | null =>
    byYear.has(year) ? (byYear.get(year)! - 1) * 100 : null

  const marked = monthlyReturns.find((r) => r.includes_unrealized)
  const markedKey = marked ? `${marked.year}-${marked.month}` : null

  // Only show months that have data in at least one year
  const activeMonths = monthlyReturns.map((r) => r.month)
  const minMonth = Math.min(...activeMonths)
  const maxMonth = Math.max(...activeMonths)
  const visibleMonthIdxs = Array.from(
    { length: maxMonth - minMonth + 1 },
    (_, i) => minMonth - 1 + i  // 0-based index into MONTHS
  )

  return (
    <div
      className="overflow-x-auto"
      aria-label="Monthly returns heatmap — each cell shows the return for that month"
    >
      <table className="text-xs font-mono w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left text-stone pr-4 pb-2 font-normal w-12">Year</th>
            {visibleMonthIdxs.map((idx) => (
              <th key={idx} className="text-stone font-normal pb-2 px-1 text-center">{MONTHS[idx]}</th>
            ))}
            <th className="text-stone font-normal pb-2 pl-3 pr-1 text-center border-l border-stone/20">YTD</th>
          </tr>
        </thead>
        <tbody>
          {years.map((year) => (
            <tr key={year}>
              <td className="text-stone pr-4 py-1">{year}</td>
              {visibleMonthIdxs.map((idx) => {
                const ret = byYearMonth.get(`${year}-${idx + 1}`)
                return (
                  <td key={idx} className="py-1 px-0.5">
                    {ret != null ? (
                      <div
                        className={`rounded text-center py-1 px-1 tabular-nums ${cellColor(ret)}`}
                        title={
                          `${MONTHS[idx]} ${year}: ${ret.toFixed(2)}%` +
                          (markedKey === `${year}-${idx + 1}` ? ' — includes unrealised gain to date' : '')
                        }
                      >
                        {ret.toFixed(1)}%{markedKey === `${year}-${idx + 1}` ? '*' : ''}
                      </div>
                    ) : (
                      <div className="text-center text-stone/30 py-1">—</div>
                    )}
                  </td>
                )
              })}
              <td className="py-1 pl-3 pr-0.5 border-l border-stone/20">
                {yearReturn(year) != null ? (
                  <div
                    className={`rounded text-center py-1 px-1 tabular-nums font-medium ${cellColor(yearReturn(year)!)}`}
                    title={`${year}: ${yearReturn(year)!.toFixed(2)}% (months compounded)`}
                  >
                    {yearReturn(year)!.toFixed(1)}%
                  </div>
                ) : (
                  <div className="text-center text-stone/30 py-1">—</div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {marked && (
        <p className="text-xs text-stone/60 mt-3 font-sans">
          * {marked.month_label} includes all unrealised gain on open positions to date. Earlier
          months show gains in the month they were realised.
        </p>
      )}
    </div>
  )
}
