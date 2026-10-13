import { isPositive } from '@/lib/formatters'

interface Props {
  label: string
  value: string
  sub?: string
  positive?: boolean | null
  highlight?: boolean
}

export function StatCard({ label, value, sub, positive, highlight }: Props) {
  const gainClass =
    positive === true ? 'text-gain' : positive === false ? 'text-loss' : 'text-summit-ink'

  return (
    <div
      className={`rounded-card p-6 border ${
        highlight
          ? 'bg-pine-deep border-pine text-on-dark dark:bg-surface dark:border-gold/70'
          : 'bg-paper border-stone/20'
      }`}
    >
      <p
        className={`text-xs font-mono tracking-widest uppercase mb-2 ${
          highlight ? 'text-on-dark/60' : 'text-stone'
        }`}
      >
        {label}
      </p>
      <p
        className={`font-mono text-2xl font-medium tabular-nums ${
          highlight ? 'text-on-dark' : gainClass
        }`}
      >
        {value}
      </p>
      {sub && (
        <p className={`text-xs mt-1 ${highlight ? 'text-on-dark/60' : 'text-stone'}`}>{sub}</p>
      )}
    </div>
  )
}

export function GainBadge({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-stone font-mono text-sm">—</span>
  const pos = isPositive(value)
  return (
    <span className={`font-mono text-sm ${pos ? 'text-gain' : 'text-loss'}`}>
      {pos ? '+' : ''}{(value * 100).toFixed(2)}%
    </span>
  )
}
