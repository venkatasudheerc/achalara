/**
 * Date ticks for a chart's x-axis that never repeat a label.
 *
 * The spacing follows the range shown: about three months or less is marked on
 * the first day on file from the 1st, 10th and 20th of each month ("Sep 2",
 * "Sep 10"); up to about a year
 * and a month on the 1st of each month ("Sep", with the year on January and on
 * the first tick); anything longer on the 1st of each quarter ("Jan 2026").
 * Every tick is a date in the data, since a category axis can only mark those.
 */

const DAY = 86_400_000

type Grain = 'days' | 'months' | 'quarters'

const at = (iso: string) => new Date(`${iso}T00:00:00`)

function grainOf(dates: string[]): Grain {
  if (dates.length < 2) return 'days'
  const span = (at(dates[dates.length - 1]).getTime() - at(dates[0]).getTime()) / DAY
  if (span <= 100) return 'days'
  if (span <= 400) return 'months'
  return 'quarters'
}

/** The boundary a date's tick belongs to, as a key: one tick per key. */
function boundary(iso: string, grain: Grain): string {
  const [y, m, d] = iso.split('-').map(Number)
  if (grain === 'quarters') return `${y}-Q${Math.floor((m - 1) / 3)}`
  if (grain === 'months') return `${y}-${m}`
  return `${y}-${m}-${d >= 20 ? 20 : d >= 10 ? 10 : 1}`
}

export function dateTicks(dates: string[]): { ticks: string[]; label: (iso: string) => string } {
  const sorted = [...dates].sort()
  const grain = grainOf(sorted)
  const ticks: string[] = []
  const seen = new Set<string>()
  for (const iso of sorted) {
    const key = boundary(iso, grain)
    if (!seen.has(key)) {
      seen.add(key)
      ticks.push(iso)
    }
  }
  // The first point starts mid-period more often than not; keep it only when it
  // is not crowding the next tick.
  if (ticks.length > 2 && grain !== 'days') {
    const gap = (at(ticks[1]).getTime() - at(ticks[0]).getTime()) / DAY
    if (gap < (grain === 'months' ? 12 : 40)) ticks.shift()
  }
  const first = ticks[0]
  const label = (iso: string) => {
    const date = at(iso)
    const month = date.toLocaleDateString('en-US', { month: 'short' })
    // The day the data has nearest after the 1st, 10th or 20th (a weekend moves it).
    if (grain === 'days') return `${month} ${date.getDate()}`
    const year = date.getFullYear()
    if (grain === 'quarters') return `${month} ${year}`
    return iso === first || date.getMonth() === 0 ? `${month} ${year}` : month
  }
  return { ticks, label }
}
