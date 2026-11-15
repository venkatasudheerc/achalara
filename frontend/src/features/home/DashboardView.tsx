import { useMemo, useState } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { PortalAccount } from '@/api/types'
import { usePortalInsights, usePortalPerformance } from '@/hooks/usePortal'
import { useChartColours } from '@/context/ThemeContext'
import { usePlaidRefresh } from '@/hooks/usePlaid'
import { formatCurrency, formatDate, formatPercent, formatTime } from '@/lib/formatters'
import { SkeletonCard } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { INVESTED, KINDS, accountName, netWorth, type Selection, type View } from './selection'
import { dateTicks } from '@/lib/chartTicks'
import { SharingPanel } from './SharingPanel'
import { AccountNameEditor } from './AccountNameEditor'
import { NextBestAction } from './NextBestAction'
import { InsightTiles } from './InsightTiles'

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
// A month's bar: its name, with the year on January and on the first bar, so a
// year of bars never shows the same label twice.
const monthLabel = (iso: string, first = false) => {
  const date = new Date(`${iso}T00:00:00`)
  const month = date.toLocaleDateString('en-US', { month: 'short' })
  return first || date.getMonth() === 0 ? `${month} ${date.getFullYear()}` : month
}

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
export function DashboardView({ accounts, selection, lead, onKind, onGo, onUpdateFromFile }: {
  accounts: PortalAccount[]; selection: Selection; lead: string; onKind: (s: Selection) => void
  /** A nudge's button chose accounts and a view. */
  onGo: (s: Selection, view?: View) => void
  /** A nudge asked to bring an account up to date from a file. */
  onUpdateFromFile: (accountId: string) => void
}) {
  const colours = useChartColours()
  const [chart, setChart] = useState<Chart>('balances')
  const [sharing, setSharing] = useState<string | null>(null)
  const accountIds = selection.type === 'all' ? undefined : accounts.map((a) => a.id)
  const { data, isLoading, isError, error, refetch } = usePortalPerformance({
    account_ids: accountIds, start_date: isoDaysAgo(365), grain: 'month',
  })
  // Supplementary: while it loads, or if it fails, the Dashboard is simply without it.
  const { data: insights } = usePortalInsights({ account_ids: accountIds })
  const one = selection.type === 'account' ? accounts[0] : undefined
  const total = accounts.reduce((t, a) => t + (a.value ?? 0), 0)
  const worth = netWorth(accounts)
  // Only cards and loans in view: say what is owed, not that they are "worth" a negative sum.
  const onlyOwed = accounts.length > 0 && accounts.every((a) => a.owed)
  // Banks and cards as much as a cash account: nothing there is invested, so no "gain" or "return".
  const allCash = accounts.every((a) => !INVESTED.includes(a.kind))
  const latest = accounts.map((a) => a.as_of).filter(Boolean).sort().pop()
  const priced = accounts.map((a) => a.priced_at).filter(Boolean).sort().shift()

  const incomplete = accounts.filter((a) => a.health?.state === 'incomplete')

  // A record missing a transaction cannot say what happened over time: no
  // change, gain, return or chart is shown from it, only today's value.
  const untrusted = incomplete.length > 0
  const summary = untrusted ? undefined : data?.summary
  // What changed, said so it agrees with the figures beneath it. Investments:
  // the gain or loss, which leaves out money added, taken out, and what an
  // account held when its history here begins. Banks and cards: the balance's
  // change, again without what an account brought.
  const change = summary
    ? (allCash ? summary.closing_value - summary.opening_value - (summary.brought ?? 0) : summary.gain)
    : null
  // The record can be younger than a year: say when it starts, not "the past year".
  const short = summary ? summary.start > isoDaysAgo(350) : false
  const span = summary && short ? `since ${formatDate(summary.start)}` : 'over the past year'
  const brought = summary?.brought ?? 0
  const axis = useMemo(() => dateTicks((data?.series ?? []).map((p) => p.date)), [data])
  const chartKind: Chart = allCash && chart === 'returns' ? 'balances' : chart

  const kinds = KINDS.map((k) => {
    const list = accounts.filter((a) => a.kind === k.kind)
    return { ...k, count: list.length, total: list.reduce((t, a) => t + (a.value ?? 0), 0) }
  }).filter((k) => k.count > 0)

  return (
    <div className="flex flex-col gap-[28px]">
      <section aria-label="Summary" className="flex flex-col gap-[10px]">
        <span className="text-[14px] text-stone flex flex-wrap items-center gap-x-[10px] gap-y-[4px]">
          <span>
            {priced ? `At prices of ${formatTime(priced)}` : 'At the last reported prices'}
            {latest ? ` · holdings and cash as ${one?.source ?? 'your institution'} reported them on ${formatDate(latest)}` : ''}
          </span>
          {accounts.some((a) => !a.shared && a.source) && <RefreshNow />}
        </span>
        <h1 className="font-display text-[30px] md:text-[40px] leading-[1.15]">
          {onlyOwed ? 'You owe' : lead} <span className="text-pine tabular-nums">{formatCurrency(onlyOwed ? -total : total)}</span>
        </h1>
        {worth.owed > 0 && worth.assets > 0 && (
          <p className="text-[15px] text-stone tabular-nums">
            Assets {formatCurrency(worth.assets)}, less {formatCurrency(worth.owed)} owed. Net worth of the accounts linked here.
          </p>
        )}
        {change != null && (
          <p className="text-[16px]">
            <strong className={change >= 0 ? 'text-gain' : 'text-loss'}>
              {allCash ? (change >= 0 ? 'Up' : 'Down') : (change >= 0 ? 'A gain of' : 'A loss of')} {formatCurrency(Math.abs(change))}
            </strong>
            {' '}{span}{allCash ? '.' : ', after what was added and taken out.'}
          </p>
        )}
      </section>

      <NextBestAction nudges={insights?.nudges ?? []} onSelect={onGo} onUpdateFromFile={onUpdateFromFile} />

      <section aria-labelledby="past-year" className="border border-line rounded-[20px] p-[18px] md:p-[22px] flex flex-col gap-[18px]">
        <div className="flex flex-wrap justify-between items-center gap-[12px]">
          <h2 id="past-year" className="font-display text-[20px]">{summary && short ? `Since ${formatDate(summary.start)}` : 'The past year'}</h2>
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

        {untrusted ? (
          <p className="text-[15px] leading-relaxed">
            Not shown until {incomplete.length === 1 ? 'the account above is' : `the ${incomplete.length} accounts above are`} complete:
            a missing transaction would show as a gain or a loss that never happened. Today’s values are as the institution reports them.
          </p>
        ) : isLoading ? <SkeletonCard /> : isError ? (
          <ErrorState message={error?.message ?? 'Could not load the past year.'} onRetry={() => refetch()} />
        ) : !summary ? (
          <p className="text-[15px] text-stone">No daily record yet for {accounts.length === 1 ? 'this account' : 'these accounts'}.</p>
        ) : (
          <>
            <div className={`grid grid-cols-2 gap-[16px] ${brought > 0 ? 'md:grid-cols-6' : 'md:grid-cols-5'}`}>
              <Figure label={`On ${formatDate(summary.start)}`} value={formatCurrency(summary.opening_value)} />
              <Figure label="Added" value={formatCurrency(summary.flow_in)} />
              <Figure label="Taken out" value={formatCurrency(summary.flow_out)} />
              {brought > 0 && <Figure label="Added to the record" value={formatCurrency(brought)} />}
              <Figure label={allCash ? 'Interest' : 'Gain or loss'} value={signed(summary.gain)}
                tone={summary.gain >= 0 ? 'gain' : 'loss'} />
              {!allCash && summary.twr_pct != null
                ? <Figure label="Return" value={formatPercent(summary.twr_pct)} tone={summary.twr_pct >= 0 ? 'gain' : 'loss'} />
                : <Figure label="Today" value={formatCurrency(summary.closing_value)} />}
            </div>

            <div className="h-[240px] -ml-[8px]">
              <ResponsiveContainer width="100%" height="100%">
                {chartKind === 'activity' ? (
                  <BarChart data={[...data!.periods].sort((a, b) => a.period_start.localeCompare(b.period_start)).map((p, i) => ({ month: monthLabel(p.period_start, i === 0), in: p.flow_in, out: -p.flow_out }))}>
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
                    <XAxis dataKey="date" ticks={axis.ticks} tickFormatter={axis.label} interval="preserveStartEnd" minTickGap={28} tick={{ fill: colours.axis, fontSize: 12 }} axisLine={false} tickLine={false} />
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
              {brought > 0 && ' “Added to the record” is what accounts already held on the day their history here begins: not a deposit, and not a gain.'}
            </p>
          </>
        )}
      </section>

      <InsightTiles insights={insights?.insights ?? []} onSelect={onGo} />

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
            <div className="sm:col-span-2"><dt className="text-[13px] text-stone">Name</dt><dd><AccountNameEditor account={one} /></dd></div>
            <div>
              <dt className="text-[13px] text-stone">Owner</dt>
              <dd>
                {one.shared ? `${one.owner_name} (shared with you)` : (one.owners?.map((o) => o.name).join(' and ') || one.owner_name)}
                {one.held_for ? <span className="block text-[13px] text-stone">Held for {one.held_for}, who doesn’t own it yet</span> : null}
              </dd>
            </div>
            <div><dt className="text-[13px] text-stone">Kind</dt><dd>{KINDS.find((k) => k.kind === one.kind)?.label}</dd></div>
            <div><dt className="text-[13px] text-stone">Cash in it</dt><dd className="tabular-nums">{one.cash == null ? '—' : formatCurrency(one.cash)}</dd></div>
            <div><dt className="text-[13px] text-stone">Figures from</dt><dd>{one.source ?? 'Entered by hand'}{one.synced_at ? `, last synced ${formatDate(one.synced_at)}` : ''}</dd></div>
            <div className="sm:col-span-2 border-t border-line pt-[10px]">
              <button type="button" onClick={() => setSharing(one.id)}
                className="min-h-[44px] px-[18px] rounded-[22px] border border-stone/30 text-[14px] font-semibold hover:bg-line">
                {one.shared ? 'Who owns it, who sees it' : 'Who owns it, who sees it…'}
              </button>
            </div>
          </dl>
          <SharingPanel accountId={sharing} onClose={() => setSharing(null)} />
        </section>
      )}
    </div>
  )
}

/** Ask the viewer's own institutions for what is new, now. Plaid updates
 * investment accounts about once a day, so it often has nothing newer. */
function RefreshNow() {
  const refresh = usePlaidRefresh()
  const r = refresh.data
  const said = r
    ? r.refreshed
      ? 'Updated just now'
      : r.up_to_date
        ? 'Already up to date'
        : r.needs_sign_in
          ? 'Sign in again first'
          : 'Could not update; it will try again in the morning'
    : null
  return (
    <span className="inline-flex items-center gap-[8px]">
      <button type="button" onClick={() => refresh.mutate()} disabled={refresh.isPending}
        className="h-[32px] px-[12px] rounded-[16px] border border-stone/40 text-[13px] font-semibold text-summit-ink hover:bg-line disabled:opacity-60">
        {refresh.isPending ? 'Updating…' : 'Refresh'}
      </button>
      {said && <span role="status">{said}</span>}
      {refresh.isError && <span role="alert" className="text-loss">{refresh.error.message}</span>}
    </span>
  )
}
