import { useState } from 'react'
import { Select } from '@/features/portal/ui'
import { Segmented } from './ui'

/** The years a view covers, the same control on every tab that has one (Sai, 2026-11-08):
 *  the last 10 or 20 years, all on file, or a chosen From and To. */
export const SPANS = [
  { value: '10', label: '10' },
  { value: '20', label: '20' },
  { value: 'all', label: 'All' },
  { value: 'custom', label: 'Custom' },
] as const
export type Span = (typeof SPANS)[number]['value']

export type YearRange = { first: number; last: number }

export function useYearSpan(initial: Span = '10') {
  const [span, setSpan] = useState<Span>(initial)
  const [from, setFrom] = useState<number | undefined>()
  const [to, setTo] = useState<number | undefined>()
  const thisYear = new Date().getFullYear()
  const params: { start_year?: number; end_year?: number } = span === 'custom' ? { start_year: from, end_year: to }
    : span === 'all' ? {} : { start_year: thisYear - Number(span) + 1 }
  /** Choosing Custom starts from the years shown now, so nothing jumps. */
  const choose = (v: Span, shown?: YearRange) => {
    if (v === 'custom' && shown) { setFrom(shown.first); setTo(shown.last) }
    setSpan(v)
  }
  return { span, from, to, setFrom, setTo, params, choose }
}

export function YearSpanControl({ id, state, available, shown }: {
  id: string; state: ReturnType<typeof useYearSpan>; available?: YearRange | null; shown?: YearRange | null
}) {
  const { span, from, to, setFrom, setTo, choose } = state
  const years = available
    ? Array.from({ length: available.last - available.first + 1 }, (_, i) => available.last - i)
    : []
  return (
    <>
      <Segmented label="Years" value={span} onChange={(v) => choose(v, shown ?? undefined)} options={SPANS} />
      {span === 'custom' && years.length > 0 && (
        <div className="flex gap-[12px]">
          <div className="flex flex-col gap-[6px]">
            <label htmlFor={`${id}-from`} className="text-[13px] text-stone">From</label>
            <Select id={`${id}-from`} value={String(from ?? '')} minWidth={110}
              onChange={(v) => { setFrom(Number(v)); if (to && Number(v) > to) setTo(Number(v)) }}>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </Select>
          </div>
          <div className="flex flex-col gap-[6px]">
            <label htmlFor={`${id}-to`} className="text-[13px] text-stone">To</label>
            <Select id={`${id}-to`} value={String(to ?? '')} minWidth={110}
              onChange={(v) => { setTo(Number(v)); if (from && Number(v) < from) setFrom(Number(v)) }}>
              {years.map((y) => <option key={y} value={y}>{y}</option>)}
            </Select>
          </div>
        </div>
      )}
    </>
  )
}
