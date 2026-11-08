import { useState } from 'react'
import { useMonthGrid } from '@/hooks/useResearch'
import type { RsMonthGrid } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { SymbolPicker, type Choice } from './SymbolPicker'
import { MonthGrid } from './MonthGrid'
import { YearSpanControl, useYearSpan } from './YearSpan'
import {
  Bars, Controls, HowToRead, Loading, MONTHS, MONTHS_SHORT, Section, Segmented, capitalise,
  notFound, pct1, unavailable, useIndexInfo,
} from './ui'

type Stat = 'mean' | 'median'

/** The answer the chart gives, in words: the strongest month, how often it rose, the weakest. */
function headline(grid: RsMonthGrid, stat: Stat, subject: string, volatility: boolean) {
  const months = Array.from({ length: 12 }, (_, i) => ({ i, s: grid.summary[String(i + 1)] }))
    .filter((m): m is { i: number; s: NonNullable<typeof m.s> } => m.s != null)
  if (!months.length) return null
  const best = months.reduce((a, b) => (b.s[stat] > a.s[stat] ? b : a))
  const worst = months.reduce((a, b) => (b.s[stat] < a.s[stat] ? b : a))
  const ups = Math.round(best.s.share_up * best.s.count)
  const span = grid.years.first === grid.years.last ? `In ${grid.years.first}` : `From ${grid.years.first} to ${grid.years.last}`
  if (volatility) {
    // A rising volatility index is rising fear, not a good month: say where it rose and fell.
    return {
      best: best.i,
      title: `${span}, ${subject} rose most in ${MONTHS[best.i]} and fell most in ${MONTHS[worst.i]}`,
      sub: `${stat === 'mean' ? 'Average' : 'Median'} change ${pct1(best.s[stat])} in ${MONTHS[best.i]}, up in ${ups} of ${best.s.count} years; `
        + `${pct1(worst.s[stat])} in ${MONTHS[worst.i]}.`,
    }
  }
  return {
    best: best.i,
    title: `${span}, ${MONTHS[best.i]} was ${subject}’s strongest month`,
    sub: `${stat === 'mean' ? 'Average' : 'Median'} ${pct1(best.s[stat])}, up in ${ups} of ${best.s.count} years. `
      + `${MONTHS[worst.i]} was the weakest: ${pct1(worst.s[stat])}.`,
  }
}

export function MonthsTab({ choice, onChoice }: { choice: Choice; onChoice: (c: Choice) => void }) {
  const [stat, setStat] = useState<Stat>('mean')
  const years = useYearSpan('10')
  const typed = choice.symbol
  const { data, isLoading, isError, error, refetch, isFetching } = useMonthGrid({ symbol: typed, ...years.params })
  const ix = useIndexInfo()
  const answer = data ? headline(data, stat, ix.subject(data.symbol), Boolean(ix.info(data.symbol)?.volatility)) : null

  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <SymbolPicker id="grid-symbol" label="Index, company or fund" placeholder="S&P 500, Apple, SPY"
          choice={choice} onChoose={onChoice} withIndices />
        <Segmented label="Show" value={stat} onChange={setStat}
          options={[{ value: 'mean', label: 'Average' }, { value: 'median', label: 'Median' }]} />
        <YearSpanControl id="grid" state={years} available={data?.available} shown={data?.years} />
      </Controls>

      {!typed ? <EmptyState title="Name an index or a ticker" message="SPX, NDX and RUT go back decades; a stock's record is about five years." />
        : isLoading ? <Section title="Loading…"><Loading rows={12} /></Section>
        : notFound(error) ? <EmptyState title={`Nothing on file for ${typed}`} message="Try an index (SPX, NDX, RUT) or a ticker in one of the tracked indices." />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={isFetching ? 'opacity-70 transition-opacity' : ''}>
            <Section title={answer ? answer.title : capitalise(ix.subject(data.symbol))} sub={answer?.sub}>
              <Bars
                ariaLabel={`${stat === 'mean' ? 'Average' : 'Median'} monthly change of ${ix.subject(data.symbol)}, ${data.years.first} to ${data.years.last}, by month`}
                bars={MONTHS_SHORT.map((m, i) => {
                  const s = data.summary[String(i + 1)]
                  return {
                    key: m, label: m, value: s ? s[stat] : null,
                    note: s ? `up ${Math.round(s.share_up * s.count)}/${s.count}` : undefined,
                    highlight: answer?.best === i,
                  }
                })} />
              <div className="flex flex-col gap-[12px]">
                <div className="flex flex-wrap items-baseline justify-between gap-[8px]">
                  <h3 className="text-[18px] font-semibold">Year by year</h3>
                  <span className="text-[13px] text-stone">Darker green, a bigger gain; darker orange, a bigger fall.</span>
                </div>
                <MonthGrid grid={data} stat={stat} />
              </div>
              <HowToRead notes={[
                `Prices on file for ${data.symbol}: ${data.available.first} to ${data.available.last}.`,
                ...data.notes,
              ]} />
            </Section>
          </div>
        )}
    </div>
  )
}
