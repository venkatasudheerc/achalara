import { useState } from 'react'
import { useIndexContributors } from '@/hooks/useResearch'
import { formatDate } from '@/lib/formatters'
import { tone } from '@/features/portal/ui'
import { ErrorState } from '@/components/ErrorState'
import type { RsContributor } from '@/api/types'
import { Loading, Segmented, displayName, notFound, unavailable } from './ui'

// Only indices whose members' weights are on file (the server says 404 for the rest).
const INDICES = [
  { value: 'SP500', label: 'S&P 500' },
  { value: 'R1000', label: 'Russell 1000' },
  { value: 'R2000', label: 'Russell 2000' },
] as const

const TOP = 10

/** A member's share of the index's move, in percentage points. */
function points(value: number): string {
  const x = value * 100
  return Math.abs(x) < 0.005 ? '0.00 pts' : `${x > 0 ? '+' : ''}${x.toFixed(2)} pts`
}

function Row({ row, max, onLookup }: { row: RsContributor; max: number; onLookup: (symbol: string) => void }) {
  const w = `${(Math.abs(row.contribution) / max) * 100}%`
  return (
    <div className="grid items-center gap-x-[12px] gap-y-[6px] grid-cols-[minmax(0,1fr)_auto] md:[grid-template-columns:minmax(0,260px)_1fr_90px]">
      <button type="button" onClick={() => onLookup(row.symbol)} className="text-left min-w-0 hover:underline">
        <span className="text-[15px] text-summit-ink">{displayName(row.name, row.symbol)} </span>
        <span className="font-mono text-[12px] text-stone">{row.symbol}</span>
        <span className="block text-[13px] text-stone">
          {(row.weight * 100).toFixed(1)}% of the index, {row.ret >= 0 ? 'up' : 'down'} {Math.abs(row.ret * 100).toFixed(1)}%
        </span>
      </button>
      <div className="grid grid-cols-2 h-[14px] col-span-2 order-3 md:col-span-1 md:order-none" aria-hidden>
        <div className="flex justify-end border-r-2 border-stone/60">
          <div className="h-full rounded-l-[3px] bg-loss" style={{ width: row.contribution < 0 ? w : 0 }} />
        </div>
        <div className="flex">
          <div className="h-full rounded-r-[3px] bg-gain" style={{ width: row.contribution > 0 ? w : 0 }} />
        </div>
      </div>
      <span className={`text-right font-mono text-[14px] ${tone(row.contribution)}`}>{points(row.contribution)}</span>
    </div>
  )
}

/** What moved an index over the week: the members that added or took away most,
 *  one list ranked by size so the biggest movers come first whichever way they went. */
export function IndexContributors({ onLookup }: { onLookup: (symbol: string) => void }) {
  const [index, setIndex] = useState<string>('SP500')
  const [all, setAll] = useState(false)
  const { data, isLoading, isError, error, refetch } = useIndexContributors(index)
  const name = INDICES.find((i) => i.value === index)?.label ?? index
  const rows = data?.contributors ?? []
  const shown = all ? rows : rows.slice(0, TOP)
  const max = Math.max(...rows.map((r) => Math.abs(r.contribution)), 0.0001)
  const topShare = rows.slice(0, TOP).reduce((s, r) => s + Math.abs(r.contribution), 0)
  const allShare = rows.reduce((s, r) => s + Math.abs(r.contribution), 0)

  return (
    <div className="flex flex-col gap-[16px] border-t border-stone/20 pt-[24px] min-w-0">
      <div className="flex flex-wrap items-end justify-between gap-[16px]">
        <div className="flex flex-col gap-[4px] min-w-0">
          <h3 className="text-[16px] font-semibold">What moved the index</h3>
          <p className="text-[14px] text-stone">
            Each member&rsquo;s weight at the start of the week times its return, in points of the index&rsquo;s move.
          </p>
        </div>
        <Segmented label="Index" options={INDICES} value={index} onChange={(v) => { setIndex(v); setAll(false) }} />
      </div>
      {isLoading ? <Loading rows={6} /> : isError && notFound(error) ? (
        <p className="text-[15px] text-stone">Not available for {name}: its members&rsquo; weights are not on file yet.</p>
      ) : isError || !data ? (
        <ErrorState message={unavailable(error)} onRetry={() => refetch()} />
      ) : (
        <>
          <p className="text-[15px] text-summit-ink">
            {data.running ? 'So far this week' : 'This week'} ({formatDate(data.start)} to {formatDate(data.end)}), the members together
            moved {name} <span className={`font-mono ${tone(data.members_return)}`}>{points(data.members_return)}</span>.
            {allShare > 0 && <> The {Math.min(TOP, rows.length)} largest movers account for {Math.round((topShare / allShare) * 100)}% of the movement, up or down.</>}
          </p>
          <div className="flex flex-col gap-[12px]">
            {shown.map((r) => <Row key={r.symbol} row={r} max={max} onLookup={onLookup} />)}
          </div>
          {rows.length > TOP && (
            <button type="button" onClick={() => setAll((v) => !v)} aria-expanded={all}
              className="self-start h-[40px] px-[16px] rounded-[8px] border border-stone/40 text-[14px] font-medium text-summit-ink hover:bg-mist/40">
              {all ? `Show the top ${TOP} only` : `Show all ${rows.length}`}
            </button>
          )}
          <ul className="text-[13px] text-stone list-disc pl-[18px] flex flex-col gap-[2px]">
            {data.notes.map((n) => <li key={n}>{n}</li>)}
            <li>Not available for the Nasdaq-100, the Dow or the Russell 3000: no member weights are on file for them.</li>
          </ul>
        </>
      )}
    </div>
  )
}
