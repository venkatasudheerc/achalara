import { useEffect, useMemo, useState } from 'react'
import { usePortalAccounts, usePortalGroups } from '@/hooks/usePortal'
import { formatCurrency } from '@/lib/formatters'
import { Tabs } from '@/features/research/ui'
import { HomeSelection } from '@/features/portal/ui'
import { PortalHoldingsPage } from '@/features/portal/PortalHoldingsPage'
import { PortalActivityPage } from '@/features/portal/PortalActivityPage'
import { PortalPerformancePage } from '@/features/portal/PortalPerformancePage'
import { PortalRealizedPage } from '@/features/portal/PortalRealizedPage'
import { SkeletonCard } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { EmptyState } from '@/components/EmptyState'
import { AccountRail } from './AccountRail'
import { DashboardView } from './DashboardView'
import { AccountsView, AnalysisView, IncomeView } from './MoreViews'
import { GroupsDialog } from './GroupsDialog'
import { ImportDialog } from '@/components/ImportDialog'
import { KINDS, VIEWS, accountName, resolveSelection, useGroupBy, useHomeSelection, type View } from './selection'

const narrowScreen = () => window.matchMedia?.('(max-width: 767px)').matches ?? false

/**
 * The landing page: the account list on the left chooses which accounts, the
 * tabs across the page choose the view, and every view answers for that choice.
 */
export function LandingPage() {
  const { data: portal, isLoading, isError, error, refetch } = usePortalAccounts()
  const { data: groups = [] } = usePortalGroups()
  const { selection, view, select, setView } = useHomeSelection()
  const [groupBy, setGroupBy] = useGroupBy()
  const [railOpen, setRailOpen] = useState(() => !narrowScreen())
  const [editing, setEditing] = useState(false)
  const [importing, setImporting] = useState(false)
  const narrow = narrowScreen()

  const accounts = useMemo(() => portal?.accounts ?? [], [portal])
  const viewerId = portal?.viewer.client_id
  // "Person" only when what this login sees belongs to more than one owner.
  const owners = new Set(accounts.map((a) => a.client_id))
  const showPerson = owners.size > 1
  const grouping = groupBy === 'person' && !showPerson ? 'kind' : groupBy

  const chosen = resolveSelection(selection, accounts, groups)
  const accountIds = selection.type === 'all' ? undefined : chosen.map((a) => a.id)
  const allCash = chosen.length > 0 && chosen.every((a) => a.kind === 'cash')

  // Views that cannot apply to what is chosen are not offered.
  const tabs = VIEWS.filter((v) => {
    if (v.value === 'accounts') return chosen.length > 1
    if (allCash && (v.value === 'holdings' || v.value === 'cost-basis' || v.value === 'analysis')) return false
    return true
  })
  const shown: View = tabs.some((t) => t.value === view) ? view : 'dashboard'
  useEffect(() => {
    if (shown !== view) setView(shown)
  }, [shown, view, setView])

  if (isLoading) return <div className="p-[24px] grid gap-[20px]"><SkeletonCard /><SkeletonCard /></div>
  if (isError || !portal) return <div className="p-[24px]"><ErrorState message={error?.message ?? 'Could not load your accounts.'} onRetry={() => refetch()} /></div>
  if (!accounts.length) {
    return <div className="p-[24px]"><EmptyState title="No accounts yet" message="Once an account is linked, it will show here." /></div>
  }

  const name = (() => {
    switch (selection.type) {
      case 'owner': return chosen[0]?.owner_name ?? 'Accounts'
      case 'kind': return KINDS.find((k) => k.kind === selection.id)?.label ?? 'Accounts'
      case 'group': return groups.find((g) => g.id === selection.id)?.name ?? 'All accounts'
      case 'account': return chosen[0] ? `${accountName(chosen[0])}${chosen[0].number_last4 ? ` ··${chosen[0].number_last4}` : ''}` : 'All accounts'
      default: return 'All accounts'
    }
  })()
  const lead = (() => {
    const first = (n: string) => n.split(' ')[0]
    switch (selection.type) {
      case 'owner': return selection.id === viewerId ? 'Your own accounts are worth' : `${first(chosen[0]?.owner_name ?? '')}’s accounts are worth`
      case 'kind': return `Your ${KINDS.find((k) => k.kind === selection.id)?.plural ?? 'accounts'} are worth`
      case 'group': return `“${name}” is worth`
      case 'account': {
        const a = chosen[0]
        return a?.shared ? `${first(a.owner_name)}’s ${accountName(a)} is worth` : `Your ${a ? accountName(a) : 'account'} is worth`
      }
      default: return showPerson ? 'Your household is worth' : 'Everything you have is worth'
    }
  })()
  const total = chosen.reduce((t, a) => t + (a.value ?? 0), 0)
  // One of the client's own accounts can be brought up to date from a file. An
  // advisor's preview shows exactly what the client sees, this button included.
  const own = selection.type === 'account' && chosen[0] && !chosen[0].shared ? chosen[0] : undefined
  const pick = (s: Parameters<typeof select>[0]) => {
    select(s)
    if (narrow) setRailOpen(false)
  }

  const body = (() => {
    switch (shown) {
      case 'accounts': return <AccountsView accounts={chosen} accountIds={accountIds} />
      case 'holdings': return <PortalHoldingsPage />
      case 'transactions': return <PortalActivityPage />
      case 'performance': return <PortalPerformancePage />
      case 'cost-basis': return <PortalRealizedPage />
      case 'income': return <IncomeView accountIds={accountIds} />
      case 'analysis': return <AnalysisView accountIds={accountIds} />
      default: return <DashboardView accounts={chosen} selection={selection} lead={lead} onKind={pick} />
    }
  })()

  return (
    <div className="flex-1 flex items-stretch">
      {railOpen && (
        <div className={`${narrow ? 'w-full' : 'w-[312px] shrink-0 border-r border-line'} bg-mist px-[14px] pt-[16px] pb-[24px]`}>
          <AccountRail
            accounts={accounts} groups={groups} viewerId={viewerId}
            groupBy={grouping} onGroupBy={setGroupBy} showPerson={showPerson}
            selection={selection} onSelect={pick} onHide={() => setRailOpen(false)}
            onEditGroups={() => setEditing(true)} canEditGroups
          />
        </div>
      )}
      {!(narrow && railOpen) && (
        <main className="flex-1 min-w-0 px-[20px] md:px-[40px] pt-[8px] pb-[56px] flex flex-col gap-[24px]">
          {!railOpen && (
            <button type="button" onClick={() => setRailOpen(true)} aria-label="Choose accounts"
              className="mt-[12px] min-h-[52px] px-[14px] py-[6px] flex items-center gap-[10px] border border-stone/30 rounded-[16px] bg-mist text-left">
              <span className="flex-1 min-w-0 flex flex-col">
                <span className="text-[12px] text-stone">Showing</span>
                <span className="text-[15px] font-semibold truncate">{name}</span>
              </span>
              <span className="text-[15px] font-bold tabular-nums">{formatCurrency(total)}</span>
              <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 9l6 6 6-6" /></svg>
            </button>
          )}
          {own && (
            <div className="flex justify-end -mb-[8px]">
              <button type="button" onClick={() => setImporting(true)}
                className="h-[44px] px-[18px] rounded-[22px] border border-stone/40 text-[14px] font-semibold hover:bg-line">
                Update from a file
              </button>
            </div>
          )}
          <Tabs label="Views of the chosen accounts" tabs={tabs} value={shown} onChange={setView} />
          <HomeSelection.Provider value={{ accountIds }}>
            {/* A new view (and new accounts) start the old pages' own filters afresh. */}
            <div key={`${shown}:${accountIds?.join(',') ?? 'all'}`}>{body}</div>
          </HomeSelection.Provider>
        </main>
      )}
      <GroupsDialog open={editing} onClose={() => setEditing(false)} groups={groups} accounts={accounts} />
      {own && (
        <ImportDialog open={importing} onClose={() => setImporting(false)} door={{ kind: 'portal', accountId: own.id, asClient: preview }}
          accountName={`${accountName(own)}${own.number_last4 ? ` ··${own.number_last4}` : ''}`} />
      )}
    </div>
  )
}
