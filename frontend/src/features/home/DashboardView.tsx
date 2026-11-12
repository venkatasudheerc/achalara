import { useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PortalAccount } from '@/api/types'
import { usePortalPerformance } from '@/hooks/usePortal'
import { useChartColours } from '@/context/ThemeContext'
import { formatCurrency, formatDate, formatPercent } from '@/lib/formatters'
import { SkeletonCard } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { KINDS, type Selection } from './selection'

type Chart = 'balances' | 'activity' | 'returns'

const isoDaysAgo = (days: number) => {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}
const signed = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${formatCurrency(Math.abs(n))}`
const compact = (n: number) => {
  const a = Math.abs(n)
  const s = a >= 1e6 ? `$${(a / 1e6).toFixed(2)}M` : a >= 1e3 ? `$${Math.round(a / 1e3)}K` : `$${Math.round(a)}`
  return n < 0 ? `−${s}` : s
}
const monthLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString('en-US', { month: 'short' })

function Figure({ label, value, tone }: { label: string; value: string; tone?: 'gain' | 'loss' }) {
  return (
    <div className="flex flex-col gap-[4px]">
      <span className="text-[13px] text-stone">{label}</span>
      <span className={`font-display text-[20px] tabular-nums ${tone === 'gain' ? 'text-gain' : tone === 'loss' ? 'text-loss' : ''}`}>{value}</span>
    </div>
  )
}

/**
 * The first view of whatever is chosen in the account list: what it is worth,
 * how that changed over the past year, and the kinds of account in it.
 */
export function DashboardView({ accounts, selection, lead, onKind }: {
  accounts: PortalAccount[]; selection: Selection; lead: string; onKind: (s: Selection) => void
}) {
  const colours = useChartColours()
  const [chart, setChart] = useState<Chart>('balances')
  const accountIds = selection.type === 'all' ? undefined : accounts.map((a) => a.id)
  const { data, isLoading, isError, error, refetch } = usePortalPerformance({
    account_ids: accountIds, start_date: isoDaysAgo(365), grain: 'month',
  })
  const one = selection.type === 'account' ? accounts[0] : undefined
  const total = accounts.reduce((t, a) => t + (a.value ?? 0), 0)
  const allCash = accounts.every((a) => a.kind === 'cash')
  const latest = accounts.map((a) => a.as_of).filter(Boolean).sort().pop()

  const summary = data?.summary
  const change = summary ? summary.closing_value - summary.opening_value : null
  const chartKind: Chart = allCash && chart === 'returns' ? 'balances' : chart

  const kinds = KINDS.map((k) => {
    const list = accounts.filter((a) => a.kind === k.kind)
    return { ...k, count: list.length, total: list.reduce((t, a) => t + (a.value ?? 0), 0) }
  }).filter((k) => k.count > 0)

  return (
    <div className="flex flex-col gap-[28px]">
      <section aria-label="Summary" className="flex flex-col gap-[10px]">
        <span className="text-[14px] text-stone">
          {one?.source ? `From ${one.source}` : 'Up to date'}{latest ? ` · as of ${formatDate(latest)}` : ''}
        </span>
        <h1 className="font-display text-[30px] md:text-[40px] leading-[1.15]">
          {lead} <span className="text-pine tabular-nums">{formatCurrency(total)}</span>
        </h1>
        {change != null && (
          <p className="text-[16px]">
            <strong className={change >= 0 ? 'text-gain' : 'text-loss'}>{change >= 0 ? 'Up' : 'Down'} {formatCurrency(Math.abs(change))}</strong>
            {' '}over the past year.
          </p>
        )}
      </section>

      <section aria-labelledby="past-year" className="border border-line rounded-[20px] p-[18px] md:p-[22px] flex flex-col gap-[18px]">
        <div className="flex flex-wrap justify-between items-center gap-[12px]">
          <h2 id="past-year" className="font-display text-[20px]">The past year</h2>
          <div role="group" aria-label="What the chart shows" className="flex border border-stone/30 rounded-[21px] p-[2px] gap-[2px]">
            {(['balances', 'activity', 'returns'] as Chart[]).filter((c) => !(allCash && c === 'returns')).map((c) => (
              <button key={c} type="button" aria-pressed={chartKind === c} onClick={() => setChart(c)}
                className={`h-[36px] px-[12px] rounded-[18px] text-[13px] capitalize ${
                  chartKind === c ? 'bg-summit-ink text-paper font-semibold' : 'text-summit-ink/80'
                }`}>
                {c}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? <SkeletonCard /> : isError ? (
          <ErrorState message={error?.message ?? 'Could not load the past year.'} onRetry={() => refetch()} />
        ) : !summary ? (
          <p className="text-[15px] text-stone">No daily record yet for {accounts.length === 1 ? 'this account' : 'these accounts'}.</p>
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-[16px]">
              <Figure label={`On ${formatDate(summary.start)}`} value={formatCurrency(summary.opening_value)} />
              <Figure label="Added" value={formatCurrency(summary.flow_in)} />
              <Figure label="Taken out" value={formatCurrency(summary.flow_out)} />
              <Figure label={allCash ? 'Interest and gains' : 'Gain or loss'} value={signed(summary.gain)}
                tone={summary.gain >= 0 ? 'gain' : 'loss'} />
              {!allCash && summary.twr_pct != null
                ? <Figure label="Return" value={formatPercent(summary.twr_pct)} tone={summary.twr_pct >= 0 ? 'gain' : 'loss'} />
                : <Figure label="Today" value={formatCurrency(summary.closing_value)} />}
            </div>

            <div className="h-[240px] -ml-[8px]">
              <ResponsiveContainer width="100%" height="100%">
                {chartKind === 'activity' ? (
                  <BarChart data={[...data!.periods].sort((a, b) => a.period_start.localeCompare(b.period_start)).map((p) => ({ month: monthLabel(p.period_start), in: p.flow_in, out: -p.flow_out }))}>
                    <CartesianGrid vertical={false} stroke={colours.grid} />
                    <XAxis dataKey="month" tick={{ fill: colours.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis tickFormatter={compact} tick={{ fill: colours.axis, fontSize: 12 }} axisLine={false} tickLine={false} width={64} />
                    <ReferenceLine y={0} stroke={colours.zero} />
                    <Tooltip contentStyle={colours.tooltip} formatter={(v: number, k: string) => [formatCurrency(Math.abs(v)), k === 'in' ? 'Added' : 'Taken out']} />
                    <Bar dataKey="in" fill={colours.allocation.etf} radius={[4, 4, 0, 0]} isAnimationActive={false} />
                    <Bar dataKey="out" fill={colours.loss} radius={[0, 0, 4, 4]} isAnimationActive={false} />
                  </BarChart>
                ) : (
                  <AreaChart data={data!.series.map((p) => ({ date: p.date, v: chartKind === 'returns' ? p.twr : p.value }))}>
                    <CartesianGrid vertical={false} stroke={colours.grid} />
                    <XAxis dataKey="date" tickFormatter={monthLabel} minTickGap={40} tick={{ fill: colours.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis domain={['auto', 'auto']} tickFormatter={(v: number) => (chartKind === 'returns' ? formatPercent(v, 0) : compact(v))}
                      tick={{ fill: colours.axis, fontSize: 12 }} axisLine={false} tickLine={false} width={64} />
                    <Tooltip contentStyle={colours.tooltip} labelFormatter={(d: string) => formatDate(d)}
                      formatter={(v: number) => [chartKind === 'returns' ? formatPercent(v) : formatCurrency(v), chartKind === 'returns' ? 'Return' : 'Value']} />
                    <Area type="monotone" dataKey="v" stroke={colours.primary} strokeWidth={2.5} fill={colours.area} isAnimationActive={false} />
                  </AreaChart>
                )}
              </ResponsiveContainer>
            </div>
            <p className="text-[13px] text-stone">
              {chartKind === 'activity' ? 'Money added and taken out each month.'
                : chartKind === 'returns' ? 'Time-weighted return since the start of the year shown: deposits and withdrawals leave it unchanged.'
                  : 'Value each day, as the custodian recorded it.'}
            </p>
          </>
        )}
      </section>

      {kinds.length > 1 && (
        <section aria-label="By kind of account" className="grid grid-cols-2 md:grid-cols-4 gap-[14px]">
          {kinds.map((k) => (
            <button key={k.kind} type="button" onClick={() => onKind({ type: 'kind', id: k.kind })}
              className={`${k.bg} rounded-[18px] p-[18px] flex flex-col gap-[8px] text-left`}>
              <span className={`text-[14px] font-bold ${k.text}`}>{k.label}</span>
              <span className="font-display text-[22px] md:text-[24px] tabular-nums">{formatCurrency(k.total)}</span>
              <span className="text-[13px] text-summit-ink/75">{k.count} {k.count === 1 ? 'account' : 'accounts'}</span>
            </button>
          ))}
        </section>
      )}

      {one && (
        <section aria-labelledby="about" className="flex flex-col gap-[12px]">
          <h2 id="about" className="font-display text-[20px]">About this account</h2>
          <dl className="border border-line rounded-[18px] p-[18px] grid grid-cols-1 sm:grid-cols-2 gap-[14px] text-[15px]">
            <div><dt className="text-[13px] text-stone">Owner</dt><dd>{one.owner_name}{one.shared ? ' (shared with you)' : ''}</dd></div>
            <div><dt className="text-[13px] text-stone">Kind</dt><dd>{KINDS.find((k) => k.kind === one.kind)?.label}</dd></div>
            <div><dt className="text-[13px] text-stone">Cash in it</dt><dd className="tabular-nums">{one.cash == null ? '—' : formatCurrency(one.cash)}</dd></div>
            <div><dt className="text-[13px] text-stone">Figures from</dt><dd>{one.source ?? 'Entered by hand'}{one.synced_at ? `, last synced ${formatDate(one.synced_at)}` : ''}</dd></div>
          </dl>
        </section>
      )}
    </div>
  )
}
