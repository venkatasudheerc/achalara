import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useConnections, useStartLink, useDiscoverConnections, useRemoveConnection,
  useUpdateBrokerageAccount, useSyncBrokerageAccount,
} from '@/hooks/useConnections'
import { useCreateStrategy, useStrategies } from '@/hooks/useStrategies'
import { useClientsList } from '@/hooks/useClients'
import { ErrorState } from '@/components/ErrorState'
import { Skeleton } from '@/components/Skeleton'
import { formatDate, formatNumber } from '@/lib/formatters'
import type { BrokerageAccount, BrokerageSyncResult, Connection } from '@/api/types'

const SYNC_INTERVAL_MS = 24 * 60 * 60 * 1000

const SKIP_REASONS: Record<string, string> = {
  synced_recently: 'Already synced in the last 24 hours.',
  initial_sync_pending: 'The brokerage is still loading this account’s history. Try again later.',
  rate_limited: 'The brokerage source is rate limiting. It will retry on the next daily run.',
}

const SKIPPED_ROW_LABELS: Record<string, string> = {
  option: 'option trades',
  corporate_action: 'splits and corporate actions',
  incomplete: 'rows with no symbol or price',
  unrecognized: 'unrecognised rows',
}

function syncMessage(result: BrokerageSyncResult): string {
  if (result.status === 'skipped') return SKIP_REASONS[result.reason ?? ''] ?? 'Sync skipped.'
  return `Imported ${result.imported} trades and ${result.cash_imported} cash activities.`
}

function nextSyncAt(account: BrokerageAccount): number | null {
  if (!account.last_synced_at) return null
  const next = new Date(account.last_synced_at).getTime() + SYNC_INTERVAL_MS
  return next > Date.now() ? next : null
}

export function BrokerageConnections({ clientId }: { clientId: string }) {
  const { data: connections, isLoading, isError, refetch } = useConnections(clientId)
  const startLink = useStartLink()
  const discover = useDiscoverConnections()
  const [linking, setLinking] = useState(false)
  const [error, setError] = useState('')

  // With a connection id this signs in again to that link; without, it adds a new one.
  const handleLink = async (connectionId?: string) => {
    setError('')
    try {
      const session = await startLink.mutateAsync({ clientId, redirectUri: window.location.href, connectionId })
      // The portal URL is only valid for a few minutes, so open it right away.
      window.open(session.redirect_url, '_blank', 'noopener')
      setLinking(true)
    } catch {
      setError('Could not start linking. Check that SnapTrade is configured on the server.')
    }
  }

  const handleDiscover = async () => {
    setError('')
    try {
      await discover.mutateAsync(clientId)
      setLinking(false)
    } catch {
      setError('Could not read accounts from the brokerage source.')
    }
  }

  return (
    <section className="border border-stone/20 rounded-card p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone">Linked brokerages</h2>
        <div className="flex gap-2">
          <button
            onClick={handleDiscover}
            disabled={discover.isPending}
            className="text-xs border border-stone/30 text-stone px-3 py-1.5 rounded-btn hover:border-pine hover:text-pine disabled:opacity-50"
          >
            {discover.isPending ? 'Checking…' : 'Refresh accounts'}
          </button>
          <button
            onClick={() => handleLink()}
            disabled={startLink.isPending}
            className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-on-dark transition-colors disabled:opacity-50"
          >
            {startLink.isPending ? 'Opening…' : '+ Link brokerage'}
          </button>
        </div>
      </div>

      {linking && (
        <div className="mb-4 p-4 bg-mist/30 rounded-btn flex items-center justify-between gap-4">
          <p className="text-sm text-summit-ink">
            Sign in to the brokerage in the tab that just opened. The link expires in five minutes.
          </p>
          <button
            onClick={handleDiscover}
            disabled={discover.isPending}
            className="shrink-0 px-3 py-1.5 bg-pine text-on-dark text-xs rounded-btn hover:bg-pine-deep disabled:opacity-50"
          >
            I’ve finished linking
          </button>
        </div>
      )}
      {error && <p className="text-loss text-xs mb-4">{error}</p>}

      {isLoading ? (
        <Skeleton className="h-16 w-full" />
      ) : isError ? (
        <ErrorState message="Could not load brokerage connections." onRetry={() => refetch()} />
      ) : !connections || connections.length === 0 ? (
        <p className="text-stone text-sm py-4">
          No brokerage linked. Link one to bring trades in without a CSV upload.
        </p>
      ) : (
        <div className="space-y-6">
          {connections.map((connection) => (
            <ConnectionCard key={connection.id} clientId={clientId} connection={connection}
              onSignInAgain={() => handleLink(connection.id)} signingIn={startLink.isPending} />
          ))}
        </div>
      )}
    </section>
  )
}

function ConnectionCard({ clientId, connection, onSignInAgain, signingIn }: {
  clientId: string; connection: Connection; onSignInAgain: () => void; signingIn: boolean
}) {
  const remove = useRemoveConnection()
  const broken = connection.status === 'broken'

  const handleRemove = () => {
    const ok = window.confirm(
      `Remove the ${connection.institution || 'brokerage'} link? Trades already imported are kept, ` +
        'but you will need to link again to sync.',
    )
    if (ok) remove.mutate(connection.id)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium text-summit-ink">
          {connection.institution || 'Brokerage'}
          {broken && <span className="ml-2 text-xs text-loss font-mono">CONNECTION BROKEN</span>}
        </p>
        <button
          onClick={handleRemove}
          disabled={remove.isPending}
          className="text-xs text-stone hover:text-loss disabled:opacity-50"
        >
          Remove link
        </button>
      </div>
      {broken && (
        <div className="flex flex-wrap items-center justify-between gap-3 mb-3 p-3 rounded-btn border border-loss/40 bg-loss/10">
          <p className="text-xs text-summit-ink">
            The brokerage stopped sharing data, so syncing is paused. Sign in to it again to carry on;
            the accounts and how they are set up stay as they are.
          </p>
          <button onClick={onSignInAgain} disabled={signingIn}
            className="text-xs bg-pine text-on-dark px-3 py-1.5 rounded-btn hover:bg-pine-deep disabled:opacity-50 shrink-0">
            {signingIn ? 'Opening…' : 'Sign in again'}
          </button>
        </div>
      )}
      <div className="divide-y divide-stone/10 border-t border-stone/10">
        {connection.brokerage_accounts.map((account) => (
          <BrokerageAccountRow
            key={account.id}
            clientId={clientId}
            account={account}
            connectionActive={connection.status === 'active'}
          />
        ))}
      </div>
    </div>
  )
}

// Chosen in place of one strategy: the account's trades are split by what is traded.
const BY_TYPE = 'by-type'
// Which strategy takes each security type; anything else goes to the last one.
const TYPE_STRATEGIES = [
  { type: 'STOCK', name: 'Stocks' }, { type: 'ETF', name: 'ETFs' }, { type: 'OPTION', name: 'Options' },
] as const
const REST_STRATEGY = 'Other'

function BrokerageAccountRow({
  clientId, account, connectionActive,
}: { clientId: string; account: BrokerageAccount; connectionActive: boolean }) {
  const { data: strategies } = useStrategies()
  const { data: clients } = useClientsList()
  const update = useUpdateBrokerageAccount()
  const createStrategy = useCreateStrategy()
  const sync = useSyncBrokerageAccount()
  const [strategyId, setStrategyId] = useState('')
  // The login's holder may only be an agent on this account, so its owner is a choice.
  const [ownerId, setOwnerId] = useState(clientId)
  const [message, setMessage] = useState('')
  const [showDrift, setShowDrift] = useState(false)

  /** The id of the strategy with this name, made first if the firm does not have it yet. */
  const strategyNamed = async (name: string): Promise<string> => {
    const found = strategies?.find((s) => s.name.toLowerCase() === name.toLowerCase())
    return found ? found.id : (await createStrategy.mutateAsync({ name })).id
  }

  const handleMap = async () => {
    setMessage('')
    try {
      if (strategyId === BY_TYPE) {
        const routes: Record<string, string> = {}
        for (const { type, name } of TYPE_STRATEGIES) routes[type] = await strategyNamed(name)
        await update.mutateAsync({
          id: account.id,
          body: {
            status: 'mapped', client_id: ownerId,
            strategy_id: await strategyNamed(REST_STRATEGY), strategy_routes: routes,
          },
        })
        return
      }
      await update.mutateAsync({
        id: account.id,
        body: { status: 'mapped', strategy_id: strategyId || null, client_id: ownerId },
      })
    } catch {
      setMessage('Could not map this account. The chosen strategy may already hold trades.')
    }
  }

  const handleSync = async () => {
    setMessage('')
    try {
      setMessage(syncMessage(await sync.mutateAsync(account.id)))
    } catch {
      setMessage('Sync failed. The brokerage source did not respond.')
    }
  }

  const reconciliation = account.reconciliation
  const drifted = reconciliation?.drifted ?? []
  const skipped = Object.entries(reconciliation?.skipped_rows ?? {}).filter(
    ([reason]) => reason in SKIPPED_ROW_LABELS,
  )
  const waitUntil = nextSyncAt(account)

  return (
    <div className="py-3">
      <div className="flex items-center justify-between gap-4">
        <div>
          <p className="text-sm text-summit-ink">
            {account.name}
            {account.number_last4 && (
              <span className="ml-2 text-xs text-stone font-mono">····{account.number_last4}</span>
            )}
          </p>
          {account.status === 'mapped' && (
            <p className="text-xs text-stone font-mono mt-0.5">
              {account.transactions_synced_through
                ? `Transactions through ${formatDate(account.transactions_synced_through)}`
                : account.initial_sync_completed
                  ? 'Not synced yet'
                  : 'Brokerage is still loading history'}
            </p>
          )}
          {account.status === 'ignored' && <p className="text-xs text-stone mt-0.5">Ignored</p>}
        </div>

        {account.status === 'mapped' ? (
          <div className="flex items-center gap-2 shrink-0">
            {reconciliation && (
              <button
                onClick={() => setShowDrift(!showDrift)}
                className={`text-xs font-mono ${drifted.length > 0 ? 'text-loss' : 'text-gain'}`}
              >
                {drifted.length > 0 ? `${drifted.length} holdings differ` : 'Holdings match'}
              </button>
            )}
            {account.account_id && (
              <Link
                to={`/app/clients/${account.owner_client_id ?? clientId}/accounts/${account.account_id}`}
                className="text-xs border border-stone/30 text-stone rounded-btn px-3 py-1.5 hover:border-pine hover:text-pine"
              >
                Open →
              </Link>
            )}
            <button
              onClick={handleSync}
              disabled={sync.isPending || !connectionActive || waitUntil !== null}
              title={waitUntil ? `Next sync after ${new Date(waitUntil).toLocaleString()}` : undefined}
              className="text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-on-dark disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:text-pine"
            >
              {sync.isPending ? 'Syncing…' : 'Sync now'}
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2 shrink-0">
            <select
              value={ownerId}
              onChange={(e) => setOwnerId(e.target.value)}
              aria-label="Client who owns this account"
              className="border border-stone/30 rounded-btn px-2 py-1.5 text-xs focus:outline-none focus:border-pine"
            >
              {(clients ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <select
              value={strategyId}
              onChange={(e) => setStrategyId(e.target.value)}
              aria-label="Strategy for this account"
              className="border border-stone/30 rounded-btn px-2 py-1.5 text-xs focus:outline-none focus:border-pine"
            >
              <option value="">Unallocated</option>
              <option value={BY_TYPE}>Split by type: Stocks, ETFs, Options, Other</option>
              {strategies?.map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
            <button
              onClick={handleMap}
              disabled={update.isPending || createStrategy.isPending}
              className="text-xs bg-pine text-on-dark px-3 py-1.5 rounded-btn hover:bg-pine-deep disabled:opacity-50"
            >
              Add account
            </button>
            {account.status === 'unmapped' && (
              <button
                onClick={() => update.mutate({ id: account.id, body: { status: 'ignored' } })}
                disabled={update.isPending}
                className="text-xs text-stone hover:text-summit-ink disabled:opacity-50"
              >
                Ignore
              </button>
            )}
          </div>
        )}
      </div>

      {message && <p className="text-xs text-stone mt-2">{message}</p>}

      {showDrift && reconciliation && (
        <div className="mt-3 p-3 bg-mist/30 rounded-btn text-xs">
          {drifted.length > 0 ? (
            <table className="w-full font-mono tabular-nums">
              <thead>
                <tr className="text-stone">
                  <th className="text-left font-normal pb-1">Symbol</th>
                  <th className="text-right font-normal pb-1">At brokerage</th>
                  <th className="text-right font-normal pb-1">From trades</th>
                  <th className="text-right font-normal pb-1">Difference</th>
                  <th className="text-left font-normal pb-1 pl-4">Likely cause</th>
                </tr>
              </thead>
              <tbody>
                {drifted.map((row) => (
                  <tr key={row.symbol}>
                    <td className="text-left text-summit-ink">{row.symbol}</td>
                    <td className="text-right">{formatNumber(row.brokerage_quantity, 4)}</td>
                    <td className="text-right">{formatNumber(row.derived_quantity, 4)}</td>
                    <td className="text-right text-loss">{formatNumber(row.difference, 4)}</td>
                    <td className="text-left pl-4 font-sans text-stone">
                      {row.awaiting_transactions ? 'Recent purchase not yet in transactions' : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="text-stone">Every holding matches the trades on file.</p>
          )}
          {(skipped.length > 0 || reconciliation.unmatched_sells > 0) && (
            <p className="text-stone mt-2">
              Not fully covered by the last sync:{' '}
              {[
                ...skipped.map(([reason, count]) => `${count} ${SKIPPED_ROW_LABELS[reason]}`),
                ...(reconciliation.unmatched_sells > 0
                  ? [`${reconciliation.unmatched_sells} symbols left net short (a short sale, or shares bought before the history starts)`]
                  : []),
              ].join(', ')}
              .
            </p>
          )}
        </div>
      )}
    </div>
  )
}
