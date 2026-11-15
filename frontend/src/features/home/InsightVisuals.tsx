import type { InsightVisual } from '@/api/types'
import { formatCurrency } from '@/lib/formatters'

/** The colours a split takes, in order: kinds of account, so none is a gain or a loss. */
const PARTS = ['bg-k-owed', 'bg-k-kids', 'bg-k-retire', 'bg-k-cash', 'bg-k-bank', 'bg-k-taxable']

/**
 * The closed set of visuals a finding may ask for. A new rule picks one of
 * these, so it never needs a new component.
 */
export function VisualFor({ visual }: { visual: InsightVisual }) {
  switch (visual.type) {
    case 'meter': return <Meter v={visual} />
    case 'split': return <Split v={visual} />
    case 'countdown': return <Countdown v={visual} />
    case 'record': return <RecordSpans v={visual} />
    case 'figure': return <p className="font-display text-[30px] leading-[1.1] tabular-nums">{visual.text}</p>
    default: return null
  }
}

function Meter({ v }: { v: InsightVisual }) {
  const share = v.whole ? Math.min(100, Math.max(0, ((v.part ?? 0) / v.whole) * 100)) : 0
  return (
    <div role="img" aria-label={`${v.left} ${v.right}`}>
      <div className="h-[10px] rounded-[5px] bg-line overflow-hidden">
        <i className={`block h-full rounded-[5px] ${v.warn ? 'bg-loss' : 'bg-pine'}`} style={{ width: `${share}%` }} />
      </div>
      <div className="flex justify-between text-[12px] text-stone mt-[6px] tabular-nums"><span>{v.left}</span><span>{v.right}</span></div>
    </div>
  )
}

function Split({ v }: { v: InsightVisual }) {
  const parts = v.parts ?? []
  const total = parts.reduce((t, p) => t + p.value, 0)
  return (
    <div>
      <div className="flex h-[14px] rounded-[7px] overflow-hidden gap-[2px]" aria-hidden="true">
        {parts.map((p, i) => <i key={p.label} className={`block h-full ${PARTS[i % PARTS.length]}`} style={{ width: `${total ? (p.value / total) * 100 : 0}%` }} />)}
      </div>
      <ul className="grid gap-[4px] mt-[8px] text-[13px] tabular-nums">
        {parts.map((p, i) => (
          <li key={p.label} className="flex justify-between gap-[10px]">
            <span><s className={`inline-block w-[9px] h-[9px] rounded-[3px] mr-[7px] no-underline ${PARTS[i % PARTS.length]}`} />{p.label}</span>
            <span>{formatCurrency(p.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Countdown({ v }: { v: InsightVisual }) {
  return (
    <div className="flex flex-col gap-[10px]">
      <div className="flex items-baseline gap-[8px]">
        <b className="font-display text-[38px] leading-none tabular-nums">{v.days}</b>
        <span className="text-[14px] text-stone">{v.note}</span>
      </div>
      {!!v.rows?.length && (
        <ul className="grid gap-[6px] text-[13px] tabular-nums">
          {v.rows.map((r) => (
            <li key={r.label} className="flex justify-between gap-[10px] border-t border-line pt-[6px]">
              <span>{r.label}</span><span className="text-stone">{r.value}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * What a period did in past years: a square per year, oldest first, green when
 * it rose and clay when it fell, so a poor record is as visible as a good one.
 */
function RecordSpans({ v }: { v: InsightVisual }) {
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-[22px]">
      {(v.spans ?? []).map((s) => (
        <div key={s.when}>
          <h4 className="text-[13px] font-semibold text-stone">{s.when}</h4>
          <p className="text-[15px] font-semibold mb-[8px]">{s.said}</p>
          <div role="img" aria-label={`${s.said}, oldest year first`} className="flex flex-wrap gap-[4px]">
            {s.years.map((up, i) => <i key={i} className={`block w-[12px] h-[12px] rounded-[3px] ${up ? 'bg-gain' : 'bg-loss'}`} />)}
          </div>
          <p className="text-[13px] text-stone mt-[8px] tabular-nums">{s.nums}</p>
        </div>
      ))}
    </div>
  )
}
