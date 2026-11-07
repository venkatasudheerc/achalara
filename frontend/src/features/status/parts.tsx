import type { ReactNode } from 'react'

/** "Oct 13, 2:30 PM EDT": every time on these pages is US Eastern. */
export function when(instant: string | null): string {
  if (!instant) return '—'
  return new Date(instant).toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    timeZone: 'America/New_York', timeZoneName: 'short',
  })
}

/** "3 hours ago", "in 2 days": how far an instant is from now. */
export function distance(instant: string | null, now: number): string {
  if (!instant) return ''
  const minutes = Math.round((new Date(instant).getTime() - now) / 60000)
  const size = Math.abs(minutes)
  const text = size < 1 ? 'a moment' : size < 60 ? `${size} min` : size < 1440 ? `${Math.round(size / 60)} h` : `${Math.round(size / 1440)} d`
  return minutes <= 0 ? `${text} ago` : `in ${text}`
}

export function bytes(value: number | null): string {
  if (value == null) return '—'
  if (value >= 1e9) return `${(value / 1e9).toFixed(1)} GB`
  if (value >= 1e6) return `${(value / 1e6).toFixed(0)} MB`
  return `${(value / 1e3).toFixed(0)} KB`
}

export type Tone = 'ok' | 'attention' | 'quiet'
const DOT: Record<Tone, string> = { ok: 'bg-gain', attention: 'bg-loss', quiet: 'bg-stone/50' }

export function Dot({ tone }: { tone: Tone }) {
  return <span aria-hidden className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${DOT[tone]}`} />
}

export function Tile({ label, tone, value, note }: { label: string; tone: Tone; value: string; note?: string }) {
  return (
    <div className="bg-surface border border-stone/20 rounded-card p-16">
      <div className="flex items-center gap-2 text-xs text-stone uppercase tracking-wide"><Dot tone={tone} />{label}</div>
      <div className="font-mono text-lg text-summit-ink mt-2">{value}</div>
      {note && <div className="text-xs text-stone mt-1">{note}</div>}
    </div>
  )
}

export function Section({ title, sub, children }: { title: string; sub?: string; children: ReactNode }) {
  return (
    <section className="bg-surface border border-stone/20 rounded-card">
      <div className="px-6 py-4 border-b border-stone/15">
        <h2 className="text-sm font-medium text-summit-ink">{title}</h2>
        {sub && <p className="text-xs text-stone mt-0.5">{sub}</p>}
      </div>
      <div className="overflow-x-auto">{children}</div>
    </section>
  )
}

export const th = 'px-6 py-2.5 text-left text-xs font-normal text-stone whitespace-nowrap'
export const td = 'px-6 py-3 text-sm text-summit-ink align-top'
export const mono = `${td} font-mono whitespace-nowrap`
