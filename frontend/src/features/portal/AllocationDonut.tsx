import { useState } from 'react'
import { useChartColours } from '@/context/ThemeContext'
import type { PortalHomeResponse } from '@/api/types'

type Slice = PortalHomeResponse['allocation'][number]
type Kind = Slice['kind']

const KIND_LABEL: Record<Kind, string> = {
  stock: 'Stocks', etf: 'ETFs', option: 'Options', other: 'Other', cash: 'Cash',
}

const SIZE = 148
const STROKE = 20
const RADIUS = (SIZE - STROKE) / 2
const ROUND = 2 * Math.PI * RADIUS
// Pixels of ring left empty between two slices.
const GAP = 3

/** Where the money is, as a ring: one arc per kind of holding, with its share beside it. */
export function AllocationDonut({ allocation }: { allocation: Slice[] }) {
  const colours = useChartColours().allocation
  const [active, setActive] = useState<Kind | null>(null)

  // The arcs split what is held. Something owed (a written option, borrowed
  // cash) counts against the total and cannot be drawn as a part of it.
  const shown = allocation.filter((a) => a.value > 0)
  const total = shown.reduce((sum, a) => sum + a.value, 0)
  const owed = allocation.filter((a) => a.value < 0)
  const share = (a?: Slice) => (a?.share == null ? null : a.share * 100)

  const cash = allocation.find((a) => a.kind === 'cash')
  const focus = active ? allocation.find((a) => a.kind === active) : undefined
  // The middle names the arc under the pointer, and otherwise how much is
  // invested. Both are shares of the whole total, as the list beside it is.
  const centre = focus
    ? { label: KIND_LABEL[focus.kind], value: share(focus) }
    : { label: 'Invested', value: cash?.share == null ? null : 100 - cash.share * 100 }

  let start = 0
  const arcs = shown.map((a) => {
    const length = (a.value / total) * ROUND
    const arc = { kind: a.kind, start, length: Math.max(length - (shown.length > 1 ? GAP : 0), 0.5) }
    start += length
    return arc
  })

  return (
    <div className="flex flex-wrap items-center gap-x-[28px] gap-y-[16px]">
      <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img"
          aria-label={allocation.map((a) => `${KIND_LABEL[a.kind]} ${share(a)?.toFixed(0) ?? 'unknown'} percent`).join(', ')}>
          <g transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}>
            <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke={colours.track} strokeWidth={STROKE} />
            {arcs.map((arc) => (
              <circle key={arc.kind} cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none"
                stroke={colours[arc.kind]} strokeWidth={STROKE}
                strokeDasharray={`${arc.length} ${ROUND - arc.length}`} strokeDashoffset={-arc.start}
                opacity={active && active !== arc.kind ? 0.3 : 1}
                style={{ transition: 'opacity 150ms' }}
                onMouseEnter={() => setActive(arc.kind)} onMouseLeave={() => setActive(null)} />
            ))}
          </g>
        </svg>
        {centre.value != null && (
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="font-mono font-medium text-[26px] leading-none">{centre.value.toFixed(0)}%</span>
            <span className="text-[13px] text-summit-ink/70 mt-[5px]">{centre.label}</span>
          </div>
        )}
      </div>

      <ul className="flex-1 min-w-[150px] flex flex-col gap-[9px] text-[16px]">
        {allocation.map((a) => (
          <li key={a.kind} className="flex items-center justify-between gap-[12px]"
            style={{ opacity: active && active !== a.kind ? 0.5 : 1, transition: 'opacity 150ms' }}
            onMouseEnter={() => a.value > 0 && setActive(a.kind)} onMouseLeave={() => setActive(null)}>
            <span className="flex items-center gap-[10px]">
              {/* Filled when it has an arc, an outline when it is owed. */}
              <span aria-hidden className="inline-block w-[11px] h-[11px] rounded-[3px] border-2"
                style={{ borderColor: colours[a.kind], backgroundColor: a.value > 0 ? colours[a.kind] : 'transparent' }} />
              {KIND_LABEL[a.kind]}
            </span>
            <span className="font-mono">{a.share == null ? '—' : `${(a.share * 100).toFixed(0)}%`}</span>
          </li>
        ))}
      </ul>
      {owed.length > 0 && (
        <p className="basis-full text-[13px] text-summit-ink/70">
          {owed.map((a) => KIND_LABEL[a.kind]).join(' and ')} {owed.length === 1 && owed[0].kind === 'cash' ? 'is' : 'are'} owed
          on balance, so {owed.length === 1 && owed[0].kind === 'cash' ? 'it counts' : 'they count'} against the total and {owed.length === 1 && owed[0].kind === 'cash' ? 'has' : 'have'} no arc.
        </p>
      )}
    </div>
  )
}
