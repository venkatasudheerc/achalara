import { useState, type FormEvent } from 'react'
import { flushSync } from 'react-dom'
import { useParams, Link, useNavigate } from 'react-router-dom'
import { useSleeve, useSleeves, useSleevePositions, useSleeveClosedPositions, useSleeveTrades, useSleeveCashActivities, useFetchMarketPrices } from '@/hooks/useSleeves'
import { useScope } from '@/context/ScopeContext'
import { useCreateTrade, useReassignTrades } from '@/hooks/useTrades'
import { DataTable, type Column } from '@/components/DataTable'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatCurrency, formatDate, formatPercent } from '@/lib/formatters'
import { GainBadge } from '@/components/StatCard'
import type { PositionResponse, ClosedPosition, TradeSummary, CashActivity } from '@/api/types'

export function SleeveDetailPage() {
  const { clientId, accountId, sleeveId } = useParams<{
    clientId: string; accountId: string; sleeveId: string
  }>()
  const navigate = useNavigate()
  const { setClient, setAccount, setSleeve, scope } = useScope()

  const { data: sleeve, isLoading, isError, refetch } = useSleeve(clientId!, accountId!, sleeveId!)
  const { data: portfolioData } = useSleevePositions(clientId!, accountId!, sleeveId!)
  const { data: closedPositions } = useSleeveClosedPositions(clientId!, accountId!, sleeveId!)
  const { data: tradesData } = useSleeveTrades(clientId!, accountId!, sleeveId!, 0, 100)
  const { data: cashActivities } = useSleeveCashActivities(clientId!, accountId!, sleeveId!)
  const { data: accountSleeves } = useSleeves(clientId!, accountId!)
  const fetchPrices = useFetchMarketPrices()
  const createTrade = useCreateTrade()
  const reassign = useReassignTrades()

  const [activeTab, setActiveTab] = useState<'positions' | 'closed' | 'trades' | 'income'>('positions')
  const [moveSymbol, setMoveSymbol] = useState('')
  const [moveTarget, setMoveTarget] = useState('')
  const [moveMessage, setMoveMessage] = useState('')
  const [showTradeForm, setShowTradeForm] = useState(false)
  const [trade, setTrade] = useState({
    symbol: '', action: 'BUY' as 'BUY' | 'SELL', trade_date: '',
    quantity: '', price: '', commission: '0', notes: '',
  })
  const [tradeError, setTradeError] = useState('')

  if (isLoading) return <SkeletonCard />
  if (isError || !sleeve) return <ErrorState message="Sleeve not found." onRetry={() => refetch()} />

  const handleCreateTrade = async (e: FormEvent) => {
    e.preventDefault()
    setTradeError('')
    try {
      await createTrade.mutateAsync({
        sleeve_id: sleeveId!,
        symbol: trade.symbol,
        action: trade.action,
        trade_date: trade.trade_date,
        quantity: Number(trade.quantity),
        price: Number(trade.price),
        commission: Number(trade.commission),
        notes: trade.notes,
      })
      setTrade({ symbol: '', action: 'BUY', trade_date: '', quantity: '', price: '', commission: '0', notes: '' })
      setShowTradeForm(false)
    } catch (err) {
      setTradeError(String(err))
    }
  }

  const otherSleeves = (accountSleeves ?? []).filter((s) => s.id !== sleeveId)
  const heldSymbols = [...new Set((tradesData?.trades ?? []).map((t) => t.symbol))].sort()

  const handleMove = async (e: FormEvent) => {
    e.preventDefault()
    setMoveMessage('')
    try {
      const result = await reassign.mutateAsync({
        from_sleeve_id: sleeveId!, to_sleeve_id: moveTarget, symbols: [moveSymbol],
      })
      setMoveMessage(`Moved ${result.trades_moved} ${moveSymbol} trades.`)
      setMoveSymbol('')
    } catch {
      setMoveMessage('Could not move those trades. The destination may match lots a different way.')
    }
  }

  const incomeCols: Column<CashActivity>[] = [
    { key: 'activity_date', header: 'Date', render: (r) => formatDate(r.activity_date), sortValue: (r) => r.activity_date },
    { key: 'type', header: 'Type', render: (r) => <span className="font-mono text-xs">{r.type}</span>, sortValue: (r) => r.type },
    { key: 'symbol', header: 'Symbol', render: (r) => r.symbol ?? '—', sortValue: (r) => r.symbol ?? '' },
    { key: 'amount', header: 'Amount', render: (r) => (
      <span className={r.amount >= 0 ? 'text-gain' : 'text-loss'}>{formatCurrency(r.amount)}</span>
    ), sortValue: (r) => r.amount, numeric: true },
    { key: 'counts_toward_returns', header: 'In returns', render: (r) => (
      <span className="text-stone">{r.counts_toward_returns ? 'Yes' : 'No'}</span>
    ), sortValue: (r) => (r.counts_toward_returns ? 1 : 0) },
    { key: 'notes', header: 'Notes', render: (r) => <span className="text-stone">{r.notes}</span> },
  ]

  const openPosCols: Column<PositionResponse>[] = [
    { key: 'symbol', header: 'Symbol', render: (r) => <span className="font-medium">{r.symbol}</span>, sortValue: (r) => r.symbol },
    { key: 'quantity', header: 'Qty', render: (r) => r.quantity, sortValue: (r) => r.quantity, numeric: true },
    { key: 'avg_cost', header: 'Avg cost', render: (r) => formatCurrency(r.avg_cost), sortValue: (r) => r.avg_cost, numeric: true },
    { key: 'cost_basis', header: 'Cost basis', render: (r) => formatCurrency(r.cost_basis), sortValue: (r) => r.cost_basis, numeric: true },
    { key: 'current_price', header: 'Price', render: (r) => formatCurrency(r.current_price), sortValue: (r) => r.current_price ?? 0, numeric: true },
    { key: 'market_value', header: 'Market value', render: (r) => formatCurrency(r.market_value), sortValue: (r) => r.market_value ?? 0, numeric: true },
    { key: 'unrealized_gain', header: 'Unrealised gain', render: (r) => (
      <span className={(r.unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'}>
        {formatCurrency(r.unrealized_gain)}
      </span>
    ), sortValue: (r) => r.unrealized_gain ?? 0, numeric: true },
    { key: 'unrealized_gain_pct', header: '% Gain', render: (r) => <GainBadge value={r.unrealized_gain_pct != null ? r.unrealized_gain_pct / 100 : null} />, sortValue: (r) => r.unrealized_gain_pct ?? 0, numeric: true },
  ]

  const closedCols: Column<ClosedPosition>[] = [
    { key: 'symbol', header: 'Symbol', render: (r) => <span className="font-medium">{r.symbol}</span>, sortValue: (r) => r.symbol },
    { key: 'matched_quantity', header: 'Qty', render: (r) => r.matched_quantity ?? '—', sortValue: (r) => r.matched_quantity ?? 0, numeric: true },
    { key: 'opened_at', header: 'Opened', render: (r) => r.opened_at ? formatDate(r.opened_at) : '—', sortValue: (r) => r.opened_at ?? '' },
    { key: 'closed_at', header: 'Closed', render: (r) => r.closed_at ? formatDate(r.closed_at) : '—', sortValue: (r) => r.closed_at ?? '' },
    { key: 'entry_price', header: 'Entry', render: (r) => r.entry_price != null ? formatCurrency(r.entry_price) : '—', sortValue: (r) => r.entry_price ?? 0, numeric: true },
    { key: 'exit_price', header: 'Exit', render: (r) => r.exit_price != null ? formatCurrency(r.exit_price) : '—', sortValue: (r) => r.exit_price ?? 0, numeric: true },
    { key: 'realized_gain', header: 'Realised gain', render: (r) => (
      <span className={r.realized_gain >= 0 ? 'text-gain' : 'text-loss'}>
        {formatCurrency(r.realized_gain)}
      </span>
    ), sortValue: (r) => r.realized_gain, numeric: true },
    { key: 'realized_gain_pct', header: '% Gain', render: (r) => (
      <span className={r.realized_gain_pct >= 0 ? 'text-gain' : 'text-loss'}>
        {formatPercent(r.realized_gain_pct / 100)}
      </span>
    ), sortValue: (r) => r.realized_gain_pct, numeric: true },
  ]

  const tradeCols: Column<TradeSummary>[] = [
    { key: 'trade_date', header: 'Date', render: (r) => formatDate(r.trade_date), sortValue: (r) => r.trade_date },
    { key: 'symbol', header: 'Symbol', render: (r) => <span className="font-medium">{r.symbol}</span>, sortValue: (r) => r.symbol },
    { key: 'action', header: 'Action', render: (r) => (
      <span className={r.action === 'BUY' ? 'text-pine' : 'text-loss'}>{r.action}</span>
    ), sortValue: (r) => r.action },
    { key: 'quantity', header: 'Qty', render: (r) => r.quantity, sortValue: (r) => r.quantity, numeric: true },
    { key: 'price', header: 'Price', render: (r) => formatCurrency(r.price), sortValue: (r) => r.price, numeric: true },
    { key: 'commission', header: 'Commission', render: (r) => formatCurrency(r.commission), sortValue: (r) => r.commission, numeric: true },
    { key: 'notes', header: 'Notes', render: (r) => <span className="text-stone">{r.notes}</span> },
  ]

  const summary = portfolioData?.summary

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-stone font-mono mb-1">
            <Link to={`/app/clients/${clientId}`} className="hover:text-pine">{scope.clientName ?? 'Client'}</Link>
            {' / '}
            <Link to={`/app/clients/${clientId}/accounts/${accountId}`} className="hover:text-pine">{scope.accountName ?? 'Account'}</Link>
            {' / '}SLEEVE
          </p>
          <h1 className="font-display text-3xl text-summit-ink">
            {sleeve.strategy_name ?? sleeve.strategy_id}
          </h1>
        </div>
        <div className="flex gap-2">
          <button
            onClick={async () => {
              await fetchPrices.mutateAsync({ clientId: clientId!, accountId: accountId!, sleeveId: sleeveId! })
            }}
            disabled={fetchPrices.isPending}
            className="px-3 py-1.5 text-xs border border-stone/30 text-stone rounded-btn hover:border-pine hover:text-pine disabled:opacity-50"
          >
            {fetchPrices.isPending ? 'Fetching…' : 'Fetch prices'}
          </button>
          <button
            onClick={() => {
              flushSync(() => {
                setClient(clientId!, scope.clientName ?? '')
                setAccount(accountId!, scope.accountName ?? '')
                setSleeve(sleeveId!, sleeve.strategy_name ?? sleeve.strategy_id)
              })
              navigate('/app/performance')
            }}
            className="px-4 py-2 bg-gold text-summit-ink text-sm font-medium rounded-btn hover:opacity-90"
          >
            View performance
          </button>
        </div>
      </div>

      {/* Portfolio summary */}
      {summary && (
        <div className="grid grid-cols-3 gap-4">
          <div className="border border-stone/20 rounded-card p-5">
            <p className="text-xs text-stone mb-1">Market value</p>
            <p className="font-mono text-xl text-summit-ink tabular-nums">{formatCurrency(summary.total_market_value)}</p>
          </div>
          <div className="border border-stone/20 rounded-card p-5">
            <p className="text-xs text-stone mb-1">Cost basis</p>
            <p className="font-mono text-xl text-summit-ink tabular-nums">{formatCurrency(summary.total_cost_basis)}</p>
          </div>
          <div className="border border-stone/20 rounded-card p-5">
            <p className="text-xs text-stone mb-1">Unrealised gain</p>
            <p className={`font-mono text-xl tabular-nums ${(summary.total_unrealized_gain ?? 0) >= 0 ? 'text-gain' : 'text-loss'}`}>
              {formatCurrency(summary.total_unrealized_gain)}
            </p>
          </div>
        </div>
      )}

      {/* Tabs */}
      <section className="border border-stone/20 rounded-card overflow-hidden">
        <div className="flex border-b border-stone/20">
          {(['positions', 'closed', 'trades', 'income'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-6 py-3 text-sm font-mono capitalize transition-colors ${
                activeTab === tab
                  ? 'text-pine border-b-2 border-pine bg-mist/30'
                  : 'text-stone hover:text-summit-ink'
              }`}
            >
              {tab === 'positions' ? 'Open positions' : tab === 'closed' ? 'Closed / Realised' : tab === 'trades' ? 'Trades' : 'Income & cash'}
            </button>
          ))}
          {activeTab === 'trades' && (
            <div className="ml-auto px-4 flex items-center">
              <button
                onClick={() => setShowTradeForm(!showTradeForm)}
                className="text-xs border border-pine text-pine px-3 py-1 rounded-btn hover:bg-pine hover:text-paper"
              >
                + Add trade
              </button>
            </div>
          )}
        </div>

        <div className="p-6">
          {showTradeForm && activeTab === 'trades' && (
            <form onSubmit={handleCreateTrade} className="mb-6 p-4 bg-mist/30 rounded-btn space-y-3">
              <div className="grid grid-cols-3 gap-3">
                {[
                  { label: 'Symbol', field: 'symbol', placeholder: 'AAPL' },
                  { label: 'Date', field: 'trade_date', type: 'date' },
                  { label: 'Quantity', field: 'quantity', type: 'number', placeholder: '100' },
                  { label: 'Price', field: 'price', type: 'number', placeholder: '185.50' },
                  { label: 'Commission', field: 'commission', type: 'number', placeholder: '0' },
                ].map(({ label, field, type = 'text', placeholder }) => {
                  const key = field as keyof typeof trade
                  return (
                  <div key={field}>
                    <label className="text-xs text-stone block mb-1">{label}</label>
                    <input
                      required={field !== 'commission'}
                      type={type}
                      value={String(trade[key] ?? '')}
                      onChange={(e) => setTrade({ ...trade, [field]: e.target.value })}
                      placeholder={placeholder}
                      step={type === 'number' ? 'any' : undefined}
                      min={type === 'number' ? '0' : undefined}
                      className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm focus:outline-none focus:border-pine"
                    />
                  </div>
                  )
                })}
                <div>
                  <label className="text-xs text-stone block mb-1">Action</label>
                  <select
                    value={trade.action}
                    onChange={(e) => setTrade({ ...trade, action: e.target.value as 'BUY' | 'SELL' })}
                    className="w-full border border-stone/30 rounded-btn px-2 py-1.5 text-sm focus:outline-none focus:border-pine"
                  >
                    <option>BUY</option>
                    <option>SELL</option>
                  </select>
                </div>
              </div>
              {tradeError && <p className="text-loss text-xs">{tradeError}</p>}
              <div className="flex gap-2">
                <button type="submit" disabled={createTrade.isPending}
                  className="px-3 py-1.5 bg-pine text-paper text-xs rounded-btn disabled:opacity-50">
                  {createTrade.isPending ? 'Saving…' : 'Add trade'}
                </button>
                <button type="button" onClick={() => setShowTradeForm(false)} className="text-stone text-xs">Cancel</button>
              </div>
            </form>
          )}

          {activeTab === 'positions' && (
            <DataTable
              columns={openPosCols}
              rows={portfolioData?.positions ?? []}
              getKey={(r) => r.id}
              emptyMessage="No open positions. Add some trades first."
            />
          )}
          {activeTab === 'closed' && (
            <>
              {closedPositions && (
                <p className="text-sm font-mono text-stone mb-3">
                  Total realised gain: {' '}
                  <span className={closedPositions.total_realized_gain >= 0 ? 'text-gain' : 'text-loss'}>
                    {formatCurrency(closedPositions.total_realized_gain)}
                  </span>
                </p>
              )}
              <DataTable
                columns={closedCols}
                rows={closedPositions?.positions ?? []}
                getKey={(r) => `${r.symbol}-${r.closed_at}`}
                emptyMessage="No closed positions yet."
              />
            </>
          )}
          {activeTab === 'trades' && (
            <>
              {otherSleeves.length > 0 && heldSymbols.length > 0 && (
                <form onSubmit={handleMove} className="mb-4 flex flex-wrap items-center gap-2 text-xs">
                  <span className="text-stone">Move all trades of</span>
                  <select
                    required
                    value={moveSymbol}
                    onChange={(e) => setMoveSymbol(e.target.value)}
                    aria-label="Symbol to move"
                    className="border border-stone/30 rounded-btn px-2 py-1.5 focus:outline-none focus:border-pine"
                  >
                    <option value="">Symbol…</option>
                    {heldSymbols.map((symbol) => <option key={symbol}>{symbol}</option>)}
                  </select>
                  <span className="text-stone">to</span>
                  <select
                    required
                    value={moveTarget}
                    onChange={(e) => setMoveTarget(e.target.value)}
                    aria-label="Destination strategy"
                    className="border border-stone/30 rounded-btn px-2 py-1.5 focus:outline-none focus:border-pine"
                  >
                    <option value="">Strategy…</option>
                    {otherSleeves.map((s) => (
                      <option key={s.id} value={s.id}>{s.strategy_name ?? s.strategy_id}</option>
                    ))}
                  </select>
                  <button
                    type="submit"
                    disabled={reassign.isPending}
                    className="border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-paper disabled:opacity-50"
                  >
                    {reassign.isPending ? 'Moving…' : 'Move'}
                  </button>
                  {moveMessage && <span className="text-stone">{moveMessage}</span>}
                </form>
              )}
              <DataTable
                columns={tradeCols}
                rows={tradesData?.trades ?? []}
                getKey={(r) => r.id}
                emptyMessage="No trades yet. Add a trade above."
              />
            </>
          )}
          {activeTab === 'income' && (
            <DataTable
              columns={incomeCols}
              rows={cashActivities ?? []}
              getKey={(r) => r.id}
              emptyMessage="No dividends, fees or transfers recorded for this sleeve."
            />
          )}
        </div>
      </section>
    </div>
  )
}
