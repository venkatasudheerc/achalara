import type { ReactNode } from 'react'
import { isAxiosError } from 'axios'
import { Skeleton } from '@/components/Skeleton'
import { formatPercent } from '@/lib/formatters'
import { useIndices } from '@/hooks/useResearch'
import type { RsIndex } from '@/api/types'
import { tone } from '@/features/portal/ui'

// Shared by every tab of Market patterns. The page is used in both the advisor workspace
// and the family portal, so every size is an explicit pixel value: the portal's spacing
// override cannot change it.

export const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August',
  'September', 'October', 'November', 'December']
export const MONTHS_SHORT = MONTHS.map((m) => m.slice(0, 3))

export const UNIVERSES = [
  { value: 'SP500', label: 'S&P 500' },
  { value: 'R1000', label: 'Russell 1000' },
  { value: 'R2000', label: 'Russell 2000' },
  { value: 'R3000', label: 'Russell 3000' },
] as const
export const UNIVERSE_LABEL: Record<string, string> = Object.fromEntries(UNIVERSES.map((u) => [u.value, u.label]))

/** The US indices as people say them, until the list of indices has loaded. */
const INDEX_NAMES: Record<string, string> = {
  SPX: 'the S&P 500', NDX: 'the Nasdaq-100', DJI: 'the Dow', RUT: 'the Russell 2000',
  RUI: 'the Russell 1000', RUA: 'the Russell 3000', VIX: 'the VIX',
}

/** What the page knows about an index (name, currency, volatility) from the list the
 *  server keeps; a symbol may come with or without its ^. */
export function useIndexInfo() {
  const { data } = useIndices()
  const byCode = new Map((data?.indices ?? []).map((i) => [i.code, i]))
  const info = (symbol: string): RsIndex | undefined => byCode.get(symbol.replace(/^\^/, '').toUpperCase())
  /** "the S&P 500", "the Nifty 50", "the VIX"; a stock or fund keeps its ticker. */
  const subject = (symbol: string): string => {
    const code = symbol.replace(/^\^/, '').toUpperCase()
    if (code === 'VIX') return 'the VIX'
    const i = byCode.get(code)
    return i ? `the ${i.name}` : INDEX_NAMES[code] ?? symbol
  }
  return { info, subject }
}

const SMALL_WORDS = new Set(['OF', 'AND', 'THE', 'FOR', 'NEW'])
/** Words that stay as written however long they are. */
const KEEP: Record<string, string> = {
  REIT: 'REIT', SPDR: 'SPDR', ETF: 'ETF', CBRE: 'CBRE', USA: 'USA', JPMORGAN: 'JPMorgan', CO: 'Co.', 'CO.': 'Co.',
}
// A legal ending, but not the "Co." of "& Co.", which is part of the name.
const LEGAL = /(?<!&)[,.]?\s+(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LTD|LIMITED|PLC|LLC|LP|NV|SA|AG)\.?$/i

/** A company's name as people say it. SEC filings give "WATERS CORP /DE/" and
 *  "KEYCORP /NEW/": drop the state tags and the legal ending, and set all-capital names
 *  in title case, keeping short initialisms (IBM, CRH) and anything with "&" as they are. */
export function displayName(name: string | null | undefined, fallback = ''): string {
  if (!name) return fallback
  let text = name.replace(/\s*\/[A-Z]{2,4}\/?\s*$/i, '').replace(/\s+DE$/, '').trim()
  text = text.replace(/\s+PUBLIC LIMITED( COMPANY| PLC)?$/i, '').trim()
  for (let i = 0; i < 2; i++) text = text.replace(LEGAL, '').trim()
  if (text === text.toUpperCase()) {
    text = text.split(/\s+/).map((w, i) => {
      if (KEEP[w]) return KEEP[w]
      if (i > 0 && SMALL_WORDS.has(w)) return w.toLowerCase()
      if (/[&\d]/.test(w) || w.length <= 3) return w
      return w.charAt(0) + w.slice(1).toLowerCase()
    }).join(' ')
  }
  return text || fallback
}

export function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export const th = 'px-[12px] py-[10px] text-[13px] font-medium text-stone text-left whitespace-nowrap'
export const thNum = 'px-[12px] py-[10px] text-[13px] font-medium text-stone text-right whitespace-nowrap'
export const td = 'px-[12px] py-[10px] text-[15px] align-top'
export const tdNum = 'px-[12px] py-[10px] text-[15px] align-top text-right font-mono whitespace-nowrap'

export function share(value: number | null | undefined) {
  return value == null ? '—' : `${Math.round(value * 100)}%`
}

/** A decimal fraction with one decimal place and a sign: 0.016 → "+1.6%". */
export function pct1(value: number | null | undefined) {
  // A value that rounds to zero has no direction: "0.0%", never "-0.0%".
  return value != null && Math.abs(value) < 0.0005 ? '0.0%' : formatPercent(value, 1)
}

export function Pct({ value, decimals = 2 }: { value: number | null | undefined; decimals?: number }) {
  return <span className={`font-mono ${tone(value)}`}>{formatPercent(value, decimals)}</span>
}

export function notFound(error: unknown) {
  return isAxiosError(error) && error.response?.status === 404
}

export function unavailable(error: unknown) {
  return isAxiosError(error) && error.response?.status === 503
    ? 'Market data cannot be reached just now.'
    : 'Could not load this part of the market data.'
}

export function Loading({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-[10px]">
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-[20px] w-full" />)}
    </div>
  )
}

export function Box({ minWidth, children }: { minWidth: number; children: ReactNode }) {
  return (
    <div className="border border-stone/25 rounded-card bg-surface overflow-x-auto">
      <table className="w-full border-collapse" style={{ minWidth }}>{children}</table>
    </div>
  )
}

/** A card that opens with its answer in one sentence. */
export function Section({ title, sub, aside, children }: {
  title: ReactNode; sub?: ReactNode; aside?: ReactNode; children?: ReactNode
}) {
  return (
    <section className="bg-surface border border-stone/25 rounded-[14px] p-[20px] md:p-[28px] flex flex-col gap-[24px] min-w-0">
      <div className="flex flex-wrap items-start justify-between gap-[16px]">
        <div className="flex flex-col gap-[6px] min-w-0 max-w-[880px]">
          <h2 className="font-display font-medium text-[24px] md:text-[28px] leading-tight text-summit-ink">{title}</h2>
          {sub && <p className="text-[16px] text-stone">{sub}</p>}
        </div>
        {aside}
      </div>
      {children}
    </section>
  )
}

/** The caveats behind a view, in one line that opens on demand. */
export function HowToRead({ notes }: { notes: (string | null | undefined | false)[] }) {
  const items = [...new Set(notes.filter(Boolean) as string[])]
  if (!items.length) return null
  return (
    <details className="border-t border-stone/20 pt-[16px]">
      <summary className="cursor-pointer text-[14px] text-pine">How to read this</summary>
      <ul className="mt-[12px] pl-[20px] list-disc text-[14px] leading-[1.6] text-stone">
        {items.map((n) => <li key={n}>{n}</li>)}
      </ul>
    </details>
  )
}

/** The views of the page: underlined, so they never look like a setting. */
export function Tabs<T extends string>({ tabs, value, onChange }: {
  tabs: readonly { value: T; label: string }[]; value: T; onChange: (v: T) => void
}) {
  return (
    <div role="tablist" aria-label="Market patterns views"
      className="flex overflow-x-auto overflow-y-hidden border-b border-stone/30 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {tabs.map((t) => {
        const on = t.value === value
        return (
          <button key={t.value} type="button" role="tab" aria-selected={on} onClick={() => onChange(t.value)}
            className={`shrink-0 mr-[28px] py-[14px] text-[16px] whitespace-nowrap border-b-[3px] transition-colors ${
              on ? 'border-gold text-summit-ink font-semibold' : 'border-transparent text-stone hover:text-summit-ink'
            }`}>
            {t.label}
          </button>
        )
      })}
    </div>
  )
}

/** A setting with a few choices, grouped in one control. */
export function Segmented<T extends string>({ label, options, value, onChange }: {
  label: string; options: readonly { value: T; label: string }[]; value: T; onChange: (v: T) => void
}) {
  return (
    <div className="flex flex-col gap-[6px]">
      <span className="text-[13px] text-stone">{label}</span>
      <div role="group" aria-label={label} className="inline-flex gap-[2px] p-[3px] rounded-[10px] border border-stone/40 bg-paper">
        {options.map((o) => {
          const on = o.value === value
          return (
            <button key={o.value} type="button" aria-pressed={on} onClick={() => onChange(o.value)}
              className={`h-[38px] px-[14px] rounded-[7px] text-[14px] font-medium transition-colors ${
                on ? 'bg-pine text-on-dark' : 'text-stone hover:text-summit-ink'
              }`}>
              {o.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function Controls({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-end gap-[20px]">{children}</div>
}

export type Bar = { key: string; label: string; value: number | null; note?: string; highlight?: boolean }

/** Bars up or down from a zero line, labelled with their values: a month-of-year pattern,
 *  the last 12 months. Gains in the gain colour, losses in clay; one scale for both, so a
 *  bar's length always means the same size of move. */
export function Bars({ bars, ariaLabel, height = 200 }: { bars: Bar[]; ariaLabel: string; height?: number }) {
  const label = 22 // room for the value printed beside each bar
  const ups = Math.max(0, ...bars.map((b) => b.value ?? 0))
  const downs = Math.max(0, ...bars.map((b) => -(b.value ?? 0)))
  const scale = (height - 2 * label) / Math.max(ups + downs, 0.0001)
  const upArea = ups * scale + label
  const downArea = downs * scale + label
  return (
    <div role="img" aria-label={ariaLabel} className="overflow-x-auto">
      <div className="grid gap-[8px] min-w-[560px]" style={{ gridTemplateColumns: `repeat(${bars.length}, minmax(0, 1fr))` }}>
        {bars.map((b) => {
          const v = b.value ?? 0
          const h = Math.round(Math.abs(v) * scale)
          return (
            <div key={b.key} className="flex flex-col items-stretch">
              <div className="flex flex-col justify-end items-center gap-[4px]" style={{ height: upArea }}>
                {v >= 0 && b.value != null && <span className={`font-mono text-[12px] ${b.highlight ? 'text-gold' : 'text-gain'}`}>{pct1(v)}</span>}
                <div className={`w-[64%] rounded-t-[4px] bg-gain ${b.highlight ? 'ring-2 ring-gold' : ''}`} style={{ height: v > 0 ? h : 0 }} />
              </div>
              <div className="h-[2px] bg-stone/60" />
              <div className="flex flex-col justify-start items-center gap-[4px]" style={{ height: downArea }}>
                <div className={`w-[64%] rounded-b-[4px] bg-loss ${b.highlight ? 'ring-2 ring-gold' : ''}`} style={{ height: v < 0 ? h : 0 }} />
                {v < 0 && <span className="font-mono text-[12px] text-loss">{pct1(v)}</span>}
              </div>
              <span className="text-center text-[14px] font-semibold text-summit-ink mt-[6px]">{b.label}</span>
              {b.note && <span className="text-center text-[12px] text-stone">{b.note}</span>}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** One row per market: a bar to the left of zero for a fall, to the right for a rise. */
export function DivergingRows({ rows, onPick }: {
  rows: { key: string; label: string; sub?: string; value: number }[]
  onPick?: (key: string) => void
}) {
  const max = Math.max(...rows.map((r) => Math.abs(r.value)), 0.0001)
  return (
    <div className="flex flex-col gap-[10px]">
      {rows.map((r) => {
        const w = `${(Math.abs(r.value) / max) * 100}%`
        const name = (
          <span className="text-[15px] text-summit-ink truncate">
            {r.label} {r.sub && <span className="font-mono text-[12px] text-stone">{r.sub}</span>}
          </span>
        )
        return (
          <div key={r.key} className="grid items-center gap-x-[12px] gap-y-[6px] grid-cols-[minmax(0,1fr)_auto] md:[grid-template-columns:minmax(0,250px)_1fr_72px]">
            {onPick ? <button type="button" onClick={() => onPick(r.key)} className="text-left min-w-0 hover:underline">{name}</button> : name}
            <div className="grid grid-cols-2 h-[14px] col-span-2 order-3 md:col-span-1 md:order-none" aria-hidden>
              <div className="flex justify-end border-r-2 border-stone/60">
                <div className="h-full rounded-l-[3px] bg-loss" style={{ width: r.value < 0 ? w : 0 }} />
              </div>
              <div className="flex">
                <div className="h-full rounded-r-[3px] bg-gain" style={{ width: r.value > 0 ? w : 0 }} />
              </div>
            </div>
            <span className={`text-right font-mono text-[14px] ${tone(r.value)}`}>{formatPercent(r.value)}</span>
          </div>
        )
      })}
    </div>
  )
}
