import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { AccountGroup, AccountKind, PortalAccount } from '@/api/types'
import { shortAccountName } from '@/lib/formatters'

/** The kinds of account, in the order they are listed, with their names and colour classes. */
export const KINDS: { kind: AccountKind; label: string; plural: string; text: string; bg: string; dot: string }[] = [
  { kind: 'cash', label: 'Cash', plural: 'cash accounts', text: 'text-k-cash', bg: 'bg-k-cash-bg', dot: 'bg-k-cash' },
  { kind: 'taxable', label: 'Taxable', plural: 'taxable accounts', text: 'text-k-taxable', bg: 'bg-k-taxable-bg', dot: 'bg-k-taxable' },
  { kind: 'retirement', label: 'Retirement', plural: 'retirement accounts', text: 'text-k-retire', bg: 'bg-k-retire-bg', dot: 'bg-k-retire' },
  { kind: 'kids', label: 'Kids', plural: 'accounts for the kids', text: 'text-k-kids', bg: 'bg-k-kids-bg', dot: 'bg-k-kids' },
]
export const kindOf = (kind: AccountKind) => KINDS.find((k) => k.kind === kind) ?? KINDS[1]

export type GroupBy = 'person' | 'kind' | 'mine'

/** The views of the chosen accounts, as tabs. */
export const VIEWS = [
  { value: 'dashboard', label: 'Dashboard' },
  { value: 'accounts', label: 'Accounts' },
  { value: 'holdings', label: 'Holdings' },
  { value: 'transactions', label: 'Transactions' },
  { value: 'performance', label: 'Performance' },
  { value: 'cost-basis', label: 'Cost basis' },
  { value: 'income', label: 'Income' },
  { value: 'analysis', label: 'Analysis' },
] as const
export type View = (typeof VIEWS)[number]['value']

/** A selection: every account, one person's, one kind, one of my groups, or one account. */
export type Selection =
  | { type: 'all' }
  | { type: 'owner' | 'kind' | 'group' | 'account'; id: string }

function parse(sel: string | null): Selection {
  if (!sel || sel === 'all') return { type: 'all' }
  const [type, ...rest] = sel.split(':')
  const id = rest.join(':')
  if (id && (type === 'owner' || type === 'kind' || type === 'group' || type === 'account')) return { type, id }
  return { type: 'all' }
}
export const selectionKey = (s: Selection) => (s.type === 'all' ? 'all' : `${s.type}:${s.id}`)

/**
 * What is chosen and which view is open, kept in the address (`?sel=…&view=…`)
 * so a reload or a shared link opens the same page, and every view sees the
 * same choice. Other parameters (an advisor's `as`) are kept.
 */
export function useHomeSelection() {
  const [params, setParams] = useSearchParams()
  const selection = useMemo(() => parse(params.get('sel')), [params])
  const viewParam = params.get('view')
  const view: View = VIEWS.some((v) => v.value === viewParam) ? (viewParam as View) : 'dashboard'

  const update = useCallback((changes: Record<string, string | null>) => {
    setParams((current) => {
      const next = new URLSearchParams(current)
      for (const [k, v] of Object.entries(changes)) {
        if (v == null) next.delete(k)
        else next.set(k, v)
      }
      return next
    })
  }, [setParams])

  return {
    selection, view,
    select: (s: Selection) => update({ sel: s.type === 'all' ? null : selectionKey(s) }),
    setView: (v: View) => update({ view: v === 'dashboard' ? null : v }),
  }
}

/** The accounts a selection stands for. A group or account no longer there falls back to all. */
export function resolveSelection(selection: Selection, accounts: PortalAccount[], groups: AccountGroup[]) {
  const pick = (test: (a: PortalAccount) => boolean) => accounts.filter(test)
  switch (selection.type) {
    case 'owner': return pick((a) => a.client_id === selection.id)
    case 'kind': return pick((a) => a.kind === selection.id)
    case 'account': return pick((a) => a.id === selection.id)
    case 'group': {
      const group = groups.find((g) => g.id === selection.id)
      return group ? pick((a) => group.account_ids.includes(a.id)) : accounts
    }
    default: return accounts
  }
}

/** How the account list is grouped, remembered on this device. */
export function useGroupBy(): [GroupBy, (g: GroupBy) => void] {
  const [groupBy, set] = useState<GroupBy>(() => {
    try {
      const saved = localStorage.getItem('achalara-group-by')
      if (saved === 'person' || saved === 'kind' || saved === 'mine') return saved
    } catch {
      // Not remembered; start from the default.
    }
    return 'person'
  })
  const choose = (g: GroupBy) => {
    set(g)
    try {
      localStorage.setItem('achalara-group-by', g)
    } catch {
      // The choice still applies for this visit.
    }
  }
  return [groupBy, choose]
}

/** An account's short name ("Roth IRA Brokerage"); see shortAccountName. */
export const accountName = (a: Pick<PortalAccount, 'name'>): string => shortAccountName(a.name)
