import { Link } from 'react-router-dom'
import type { PerformanceChild } from '@/api/types'
import { formatCurrency } from '@/lib/formatters'
import { GainBadge } from './StatCard'

interface Props {
  children: PerformanceChild[]
  /** Where a row opens; null when it has no page of its own (the row is then not a link). */
  makeHref: (child: PerformanceChild) => string | null
  label: string
}

export function LevelBreakdown({ children, makeHref, label }: Props) {
  if (!children.length) {
    return <p className="text-stone text-sm py-6">No {label} to display.</p>
  }

  return (
    <div className="divide-y divide-stone/10">
      {children.map((child) => {
        const href = makeHref(child)
        const row = 'grid grid-cols-5 items-center py-4 px-2 rounded transition-colors group gap-4'
        const cells = (
          <>
          {/* Name + market value */}
          <div className="col-span-2">
            <p className="font-medium text-summit-ink group-hover:text-pine transition-colors">
              {child.name}
            </p>
            <p className="text-xs text-stone font-mono mt-0.5">
              {formatCurrency(child.summary.total_market_value)} market value
            </p>
          </div>
          {/* MWR */}
          <div>
            <p className="text-xs text-stone mb-0.5">MWR</p>
            <GainBadge value={child.summary.mwr_pct} />
          </div>
          {/* TWR */}
          <div>
            <p className="text-xs text-stone mb-0.5">TWR</p>
            <GainBadge value={child.summary.twr_pct} />
          </div>
          {/* Unrealised gain */}
          <div className="text-right">
            <p className="text-xs text-stone mb-0.5">Unrealised gain</p>
            <span className={`font-mono text-sm ${
              (child.summary.total_unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'
            }`}>
              {formatCurrency(child.summary.total_unrealized_gain)}
            </span>
          </div>
          </>
        )
        return href
          ? <Link key={child.id} to={href} className={`${row} hover:bg-mist/50`}>{cells}</Link>
          : <div key={child.id} className={row}>{cells}</div>
      })}
    </div>
  )
}
