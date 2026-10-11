import { useState, type FormEvent } from 'react'
import { flushSync } from 'react-dom'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useClient, useClientPositions, useClientTrades } from '@/hooks/useClients'
import { useAccounts, useCreateAccount } from '@/hooks/useAccounts'
import { useScope, useScopeFollowsPage } from '@/context/ScopeContext'
import { ShortBadge } from '@/components/ShortBadge'
import { DataTable, type Column } from '@/components/DataTable'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatDate } from '@/lib/formatters'
import type { AggregatedPosition, TradeSummary } from '@/api/types'
import { GainBadge } from '@/components/StatCard'
import { BrokerageConnections } from '@/features/connections/BrokerageConnections'

export function ClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const navigate = useNavigate()
  const { setClient } = useScope()

  const { data: client, isLoading, isError, refetch } = useClient(clientId!)
  const { data: accounts } = useAccounts(clientId!)
  const { data: positions } = useClientPositions(clientId!)
  const { data: tradesData } = useClientTrades(clientId!, 0, 100)

  const [showAccountForm, setShowAccountForm] = useState(false)
  const [accName, setAccName] = useState('')
  const [accDesc, setAccDesc] = useState('')
  const [accNum, setAccNum] = useState('')
  const [formError, setFormError] = useState('')
  const createAccount = useCreateAccount()
  useScopeFollowsPage(client && { id: client.id, name: client.name })

  if (isLoading) return <SkeletonCard />
  if (isError || !client) return <ErrorState message="Client not found." onRetry={() => refetch()} />

  const handleCreateAccount = async (e: FormEvent) => {
    e.preventDefault()
    setFormError('')
    try {
      await createAccount.mutateAsync({
        clientId: clientId!,
        body: { name: accName, description: accDesc, account_number: accNum || null },
      })
      setAccName(''); setAccDesc(''); setAccNum('')
      setShowAccountForm(false)
    } catch (err) {
      setFormError(String(err))
    }
  }

  const positionCols: Column<AggregatedPosition>[] = [
    { key: 'symbol', header: 'Symbol', render: (r) => <><span className="font-medium">{r.symbol}</span><ShortBadge quantity={r.quantity} /></>, sortValue: (r) => r.symbol },
    { key: 'quantity', header: 'Qty', render: (r) => r.quantity, sortValue: (r) => r.quantity, numeric: true },
    { key: 'avg_cost', header: 'Avg cost', render: (r) => formatCurrency(r.avg_cost), sortValue: (r) => r.avg_cost, numeric: true },
    { key: 'market_value', header: 'Market value', render: (r) => formatCurrency(r.market_value), sortValue: (r) => r.market_value ?? 0, numeric: true },
    { key: 'unrealized_gain', header: 'Unrealised gain', render: (r) => (
      <span className={(r.unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'}>
        {formatCurrency(r.unrealized_gain)}
      </span>
    ), sortValue: (r) => r.unrealized_gain ?? 0, numeric: true },
    { key: 'unrealized_gain_pct', header: '% Gain', render: (r) => <GainBadge value={r.unrealized_gain_pct != null ? r.unrealized_gain_pct / 100 : null} />, sortValue: (r) => r.unrealized_gain_pct ?? 0, numeric: true },
  ]

  const tradeCols: Column<TradeSummary>[] = [
    { key: 'trade_date', header: 'Date', render: (r) => formatDate(r.trade_date), sortValue: (r) => r.trade_date },
    { key: 'symbol', header: 'Symbol', render: (r) => <span className="font-medium">{r.symbol}</span>, sortValue: (r) => r.symbol },
    { key: 'security_type', header: 'Type', render: (r) => <span className="font-mono text-xs text-stone">{r.security_type ?? '—'}</span>, sortValue: (r) => r.security_type ?? '' },
    { key: 'action', header: 'Action', render: (r) => (
      <span className={r.action === 'BUY' ? 'text-pine' : 'text-loss'}>{r.action}</span>
    ), sortValue: (r) => r.action },
    { key: 'quantity', header: 'Qty', render: (r) => r.quantity, sortValue: (r) => r.quantity, numeric: true },
    { key: 'price', header: 'Price', render: (r) => formatCurrency(r.price), sortValue: (r) => r.price, numeric: true },
    { key: 'commission', header: 'Commission', render: (r) => formatCurrency(r.commission), sortValue: (r) => r.commission, numeric: true },
  ]

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-stone font-mono mb-1">CLIENT</p>
          <h1 className="font-display text-3xl text-summit-ink">{client.name}</h1>
          <p className="text-stone text-sm mt-1">{client.email}</p>
        </div>
        <button
          onClick={() => { flushSync(() => setClient(client.id, client.name)); navigate('/app/performance') }}
          className="px-4 py-2 bg-gold text-summit-ink text-sm font-medium rounded-btn hover:opacity-90"
        >
          View performance
        </button>
      </div>

      {/* Accounts */}
      <section className="border border-stone/20 rounded-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-mono uppercase tracking-wide text-stone">Accounts</h2>
          <button
            onClick={() => setShowAccountForm(!showAccountForm)}
            className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-paper transition-colors"
          >
            + Add account
          </button>
        </div>

        {showAccountForm && (
          <form onSubmit={handleCreateAccount} className="mb-4 p-4 bg-mist/30 rounded-btn space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs text-stone block mb-1">Name *</label>
                <input required value={accName} onChange={(e) => setAccName(e.target.value)}
                  placeholder="Taxable Brokerage"
                  className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm focus:outline-none focus:border-pine" />
              </div>
              <div>
                <label className="text-xs text-stone block mb-1">Description</label>
                <input value={accDesc} onChange={(e) => setAccDesc(e.target.value)}
                  className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm focus:outline-none focus:border-pine" />
              </div>
              <div>
                <label className="text-xs text-stone block mb-1">Account number</label>
                <input value={accNum} onChange={(e) => setAccNum(e.target.value)}
                  className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm focus:outline-none focus:border-pine" />
              </div>
            </div>
            {formError && <p className="text-loss text-xs">{formError}</p>}
            <div className="flex gap-2">
              <button type="submit" disabled={createAccount.isPending}
                className="px-3 py-1.5 bg-pine text-paper text-xs rounded-btn hover:bg-pine-deep disabled:opacity-50">
                {createAccount.isPending ? 'Creating…' : 'Create'}
              </button>
              <button type="button" onClick={() => setShowAccountForm(false)}
                className="px-3 py-1.5 text-stone text-xs">Cancel</button>
            </div>
          </form>
        )}

        {accounts && accounts.length > 0 ? (
          <div className="divide-y divide-stone/10">
            {accounts.map((acc) => (
              <div key={acc.id} className="flex items-center justify-between py-3">
                <div>
                  <p className="text-sm font-medium text-summit-ink">{acc.name}</p>
                  {acc.account_number && (
                    <p className="text-xs text-stone font-mono"># {acc.account_number}</p>
                  )}
                </div>
                <Link
                  to={`/app/clients/${clientId}/accounts/${acc.id}`}
                  className="text-xs border border-stone/30 text-stone rounded-btn px-3 py-1.5 hover:border-pine hover:text-pine transition-colors"
                >
                  Manage →
                </Link>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-stone text-sm py-4">No accounts yet.</p>
        )}
      </section>

      <BrokerageConnections clientId={clientId!} />

      {/* Positions */}
      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">Positions (all accounts)</h2>
        {positions ? (
          <>
            <div className="flex gap-6 mb-4 text-sm font-mono">
              <span className="text-stone">Market value: <span className="text-summit-ink">{formatCurrency(positions.total_market_value)}</span></span>
              <span className="text-stone">Invested: <span className="text-summit-ink">{formatCurrency(positions.total_cost_basis)}</span></span>
              <span className={`${(positions.total_unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
                Gain: {formatCurrency(positions.total_unrealized_gain)}
              </span>
            </div>
            <DataTable
              columns={positionCols}
              rows={positions.positions}
              getKey={(r) => r.symbol}
              emptyMessage="No positions found."
            />
          </>
        ) : <p className="text-stone text-sm">Loading positions…</p>}
      </section>

      {/* Trades */}
      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">
          Recent trades
        </h2>
        <DataTable
          columns={tradeCols}
          rows={tradesData?.trades ?? []}
          getKey={(r) => r.id}
          emptyMessage="No trades found."
        />
      </section>
    </div>
  )
}
