import { useScope } from '@/context/ScopeContext'
import { useClientSleeves } from '@/hooks/useSleeves'

/**
 * Narrows the performance view to one sleeve, or widens it back.
 *
 * It changes the app's scope, not a filter of its own, so everything that
 * reads the scope follows: the figures, the charts and the breadcrumb.
 */
export function SleeveFilter() {
  const { scope, setClient, setAccount, setSleeve } = useScope()
  const { data, isLoading } = useClientSleeves(scope.clientId ?? '')

  if (!scope.clientId) return null
  const withSleeves = data.filter((entry) => entry.sleeves.length > 0)
  if (!isLoading && withSleeves.length === 0) return null

  const single = data.length === 1
  const value =
    scope.level === 'sleeve'
      ? `sleeve:${scope.accountId}:${scope.sleeveId}`
      : scope.level === 'account' && !single
        ? `account:${scope.accountId}`
        : 'client'

  const handleChange = (next: string) => {
    const [kind, accountId, sleeveId] = next.split(':')
    // Rebuild the scope from the client down, so nothing from the previous
    // selection lingers.
    setClient(scope.clientId!, scope.clientName ?? '')
    if (kind === 'client') return
    const entry = data.find((e) => e.account.id === accountId)
    if (!entry) return
    setAccount(entry.account.id, entry.account.name)
    if (kind !== 'sleeve') return
    const sleeve = entry.sleeves.find((s) => s.id === sleeveId)
    if (sleeve) setSleeve(sleeve.id, sleeve.strategy_name ?? sleeve.strategy_id)
  }

  return (
    <select
      value={value}
      disabled={isLoading}
      onChange={(e) => handleChange(e.target.value)}
      aria-label="Show performance for"
      className="bg-transparent border border-mist/30 text-paper text-xs font-mono rounded-btn px-2 py-1.5 focus:outline-none focus:border-gold disabled:opacity-50"
    >
      <option value="client" className="text-summit-ink">
        {single ? 'All sleeves' : 'All accounts'}
      </option>
      {single
        ? data[0]?.sleeves.map((sleeve) => (
            <option
              key={sleeve.id}
              value={`sleeve:${data[0].account.id}:${sleeve.id}`}
              className="text-summit-ink"
            >
              {sleeve.strategy_name ?? sleeve.strategy_id}
            </option>
          ))
        : data.map(({ account, sleeves }) => (
            <optgroup key={account.id} label={account.name} className="text-summit-ink">
              <option value={`account:${account.id}`}>{account.name} — all sleeves</option>
              {sleeves.map((sleeve) => (
                <option key={sleeve.id} value={`sleeve:${account.id}:${sleeve.id}`}>
                  {sleeve.strategy_name ?? sleeve.strategy_id}
                </option>
              ))}
            </optgroup>
          ))}
    </select>
  )
}
