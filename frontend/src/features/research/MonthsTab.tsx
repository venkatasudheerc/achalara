import { useState } from 'react'
import { useMonthGrid } from '@/hooks/useResearch'
import type { RsMonthGrid } from '@/api/types'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { Select, useDebounced } from '@/features/portal/ui'
import { MonthGrid } from './MonthGrid'
import {
  Bars, Controls, HowToRead, Loading, MONTHS, MONTHS_SHORT, SearchBox, Section, Segmented, capitalise,
  notFound, pct1, subjectName, unavailable,
} from './ui'

const SPANS = [
  { value: '10', label: '10' },
  { value: '20', label: '20' },
  { value: 'all', label: 'All' },
  { value: 'custom', label: 'Custom' },
] as const
type Span = (typeof SPANS)[number]['value']
type Stat = 'mean' | 'median'

/** The answer the chart gives, in words: the strongest month, how often it rose, the weakest. */
function headline(grid: RsMonthGrid, stat: Stat) {
  const months = Array.from({ length: 12 }, (_, i) => ({ i, s: grid.summary[String(i + 1)] }))
    .filter((m): m is { i: number; s: NonNullable<typeof m.s> } => m.s != null)
  if (!months.length) return null
  const best = months.reduce((a, b) => (b.s[stat] > a.s[stat] ? b : a))
  const worst = months.reduce((a, b) => (b.s[stat] < a.s[stat] ? b : a))
  const ups = Math.round(best.s.share_up * best.s.count)
  const span = grid.years.first === grid.years.last ? `In ${grid.years.first}` : `From ${grid.years.first} to ${grid.years.last}`
  return {
    best: best.i,
    title: `${span}, ${MONTHS[best.i]} was ${subjectName(grid.symbol)}’s strongest month`,
    sub: `${stat === 'mean' ? 'Average' : 'Median'} ${pct1(best.s[stat])}, up in ${ups} of ${best.s.count} years. `
      + `${MONTHS[worst.i]} was the weakest: ${pct1(worst.s[stat])}.`,
  }
}

export function MonthsTab({ symbol, onSymbol }: { symbol: string; onSymbol: (s: string) => void }) {
  const [stat, setStat] = useState<Stat>('mean')
  const [span, setSpan] = useState<Span>('10')
  const [from, setFrom] = useState<number | undefined>()
  const [to, setTo] = useState<number | undefined>()
  const typed = useDebounced(symbol.trim().toUpperCase(), 400)
  const thisYear = new Date().getFullYear()
  const params = span === 'custom' ? { start_year: from, end_year: to }
    : span === 'all' ? {} : { start_year: thisYear - Number(span) + 1 }
  const { data, isLoading, isError, error, refetch, isFetching } = useMonthGrid({ symbol: typed, ...params })
  const years = data ? Array.from({ length: data.available.last - data.available.first + 1 }, (_, i) => data.available.last - i) : []
  const choose = (v: Span) => {
    if (v === 'custom' && data) { setFrom(data.years.first); setTo(data.years.last) }
    setSpan(v)
  }
  const answer = data ? headline(data, stat) : null

  return (
    <div className="flex flex-col gap-[24px]">
      <Controls>
        <SearchBox id="grid-symbol" label="Index or ticker" value={symbol} onChange={onSymbol} placeholder="SPX, NDX, AAPL, SPY" />
        <Segmented label="Show" value={stat} onChange={setStat}
          options={[{ value: 'mean', label: 'Average' }, { value: 'median', label: 'Median' }]} />
        <Segmented label="Years" value={span} onChange={choose} options={SPANS} />
        {span === 'custom' && years.length > 0 && (
          <div className="flex gap-[12px]">
            <div className="flex flex-col gap-[6px]">
              <label htmlFor="grid-from" className="text-[13px] text-stone">From</label>
              <Select id="grid-from" value={String(from ?? '')} minWidth={110}
                onChange={(v) => { setFrom(Number(v)); if (to && Number(v) > to) setTo(Number(v)) }}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </div>
            <div className="flex flex-col gap-[6px]">
              <label htmlFor="grid-to" className="text-[13px] text-stone">To</label>
              <Select id="grid-to" value={String(to ?? '')} minWidth={110}
                onChange={(v) => { setTo(Number(v)); if (from && Number(v) < from) setFrom(Number(v)) }}>
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </Select>
            </div>
          </div>
        )}
      </Controls>

      {!typed ? <EmptyState title="Name an index or a ticker" message="SPX, NDX and RUT go back decades; a stock's record is about five years." />
        : isLoading ? <Section title="Loading…"><Loading rows={12} /></Section>
        : notFound(error) ? <EmptyState title={`Nothing on file for ${typed}`} message="Try an index (SPX, NDX, RUT) or a ticker in one of the tracked indices." />
        : isError || !data ? <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
        : (
          <div className={isFetching ? 'opacity-70 transition-opacity' : ''}>
            <Section title={answer ? answer.title : capitalise(subjectName(data.symbol))} sub={answer?.sub}>
              <Bars
                ariaLabel={`${stat === 'mean' ? 'Average' : 'Median'} monthly change of ${subjectName(data.symbol)}, ${data.years.first} to ${data.years.last}, by month`}
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
