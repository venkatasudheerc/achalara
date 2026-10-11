import { useState, type FormEvent } from 'react'
import { flushSync } from 'react-dom'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useAccount, useAccountPositions } from '@/hooks/useAccounts'
import { useSleeves, useCreateSleeve } from '@/hooks/useSleeves'
import { useStrategies } from '@/hooks/useStrategies'
import { useScope, useScopeFollowsPage } from '@/context/ScopeContext'
import { useClient } from '@/hooks/useClients'
import { ShortBadge } from '@/components/ShortBadge'
import { DataTable, type Column } from '@/components/DataTable'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency } from '@/lib/formatters'
import type { SleeveResponse, AggregatedPosition } from '@/api/types'
import { GainBadge } from '@/components/StatCard'
import { performanceApi } from '@/api/endpoints/performance'

export function AccountDetailPage() {
  const { clientId, accountId } = useParams<{ clientId: string; accountId: string }>()
  const navigate = useNavigate()
  const { setAccount, setClient, scope } = useScope()

  const { data: account, isLoading, isError, refetch } = useAccount(clientId!, accountId!)
  const { data: sleeves } = useSleeves(clientId!, accountId!)
  const { data: positions } = useAccountPositions(clientId!, accountId!)
  const { data: strategies } = useStrategies()
  const createSleeve = useCreateSleeve()
  const { data: client } = useClient(clientId!)
  useScopeFollowsPage(
    client && { id: client.id, name: client.name },
    account && { id: account.id, name: account.name },
  )

  const [showSleeveForm, setShowSleeveForm] = useState(false)
  const [strategyId, setStrategyId] = useState('')
  const [formError, setFormError] = useState('')

  if (isLoading) return <SkeletonCard />
  if (isError || !account) return <ErrorState message="Account not found." onRetry={() => refetch()} />

  const handleCreateSleeve = async (e: FormEvent) => {
    e.preventDefault()
    setFormError('')
    try {
      await createSleeve.mutateAsync({ clientId: clientId!, accountId: accountId!, body: { strategy_id: strategyId } })
      setStrategyId('')
      setShowSleeveForm(false)
    } catch (err) {
      setFormError(String(err))
    }
  }

  const sleeveCols: Column<SleeveResponse>[] = [
    { key: 'strategy_name', header: 'Strategy', render: (r) => (
      <Link to={`/app/clients/${clientId}/accounts/${accountId}/sleeves/${r.id}`}
        className="text-pine hover:underline">{r.strategy_name ?? r.strategy_id}</Link>
    )},
    { key: 'actions', header: '', render: (r) => (
      <button
        onClick={() => navigate(`/app/clients/${clientId}/accounts/${accountId}/sleeves/${r.id}`)}
        className="text-xs text-stone hover:text-summit-ink"
      >View →</button>
    )},
  ]

  const posCols: Column<AggregatedPosition>[] = [
    { key: 'symbol', header: 'Symbol', render: (r) => <><span className="font-medium">{r.symbol}</span><ShortBadge quantity={r.quantity} /></>, sortValue: (r) => r.symbol },
    { key: 'quantity', header: 'Qty', render: (r) => r.quantity, sortValue: (r) => r.quantity, numeric: true },
    { key: 'market_value', header: 'Market value', render: (r) => formatCurrency(r.market_value), sortValue: (r) => r.market_value ?? 0, numeric: true },
    { key: 'unrealized_gain', header: 'Unrealised gain', render: (r) => (
      <span className={(r.unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'}>
        {formatCurrency(r.unrealized_gain)}
      </span>
    ), sortValue: (r) => r.unrealized_gain ?? 0, numeric: true },
    { key: 'unrealized_gain_pct', header: '% Gain', render: (r) => <GainBadge value={r.unrealized_gain_pct != null ? r.unrealized_gain_pct / 100 : null} />, sortValue: (r) => r.unrealized_gain_pct ?? 0, numeric: true },
  ]

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-stone font-mono mb-1">
            <Link to={`/app/clients/${clientId}`} className="hover:text-pine">{scope.clientName ?? 'Client'}</Link>
            {' / '}ACCOUNT
          </p>
          <h1 className="font-display text-3xl text-summit-ink">{account.name}</h1>
          {account.account_number && (
            <p className="text-stone text-sm font-mono mt-1"># {account.account_number}</p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <a
            href={performanceApi.reportUrl(clientId!, accountId!)}
            className="px-3 py-2 text-sm border border-stone/30 text-stone rounded-btn hover:border-pine hover:text-pine transition-colors"
          >
            Download report
          </a>
        <button
          onClick={() => { flushSync(() => { setClient(clientId!, scope.clientName ?? ''); setAccount(accountId!, account.name) }); navigate('/app/performance') }}
          className="px-4 py-2 bg-gold text-summit-ink text-sm font-medium rounded-btn hover:opacity-90"
        >
          View performance
        </button>
        </div>
      </div>

      {/* Sleeves */}
      <section className="border border-stone/20 rounded-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone">Sleeves (strategies in this account)</h2>
          <button
            onClick={() => setShowSleeveForm(!showSleeveForm)}
            className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-paper transition-colors"
          >
            + Apply strategy
          </button>
        </div>

        {showSleeveForm && (
          <form onSubmit={handleCreateSleeve} className="mb-4 p-4 bg-mist/30 rounded-btn space-y-3">
            <div>
              <label className="text-xs text-stone block mb-1">Strategy</label>
              <select
                required
                value={strategyId}
                onChange={(e) => setStrategyId(e.target.value)}
                className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm focus:outline-none focus:border-pine"
              >
                <option value="">Select a strategy…</option>
                {strategies?.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            {formError && <p className="text-loss text-xs">{formError}</p>}
            <div className="flex gap-2">
              <button type="submit" disabled={createSleeve.isPending}
                className="px-3 py-1.5 bg-pine text-paper text-xs rounded-btn disabled:opacity-50">
                {createSleeve.isPending ? 'Creating…' : 'Apply'}
              </button>
              <button type="button" onClick={() => setShowSleeveForm(false)} className="text-stone text-xs">Cancel</button>
            </div>
          </form>
        )}

        <DataTable
          columns={sleeveCols}
          rows={sleeves ?? []}
          getKey={(r) => r.id}
          emptyMessage="No sleeves yet. Apply a strategy to this account to get started."
        />
      </section>

      {/* Positions */}
      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">Positions (all sleeves)</h2>
        {positions ? (
          <>
            <div className="flex gap-6 mb-4 text-sm font-mono">
              <span className="text-stone">Market value: <span className="text-summit-ink">{formatCurrency(positions.total_market_value)}</span></span>
              <span className={`${(positions.total_unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
                Gain: {formatCurrency(positions.total_unrealized_gain)}
              </span>
            </div>
            <DataTable columns={posCols} rows={positions.positions} getKey={(r) => r.symbol} emptyMessage="No positions." />
          </>
        ) : <p className="text-stone text-sm">Loading…</p>}
      </section>
    </div>
  )
}
