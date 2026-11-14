import { useMemo, useState } from 'react'
import type { AccountGroup, PortalAccount } from '@/api/types'
import { formatCurrency } from '@/lib/formatters'
import { KINDS, accountName, kindOf, selectionKey, type GroupBy, type Selection } from './selection'

interface Section { key: string; label: string; selection: Selection | null; accounts: PortalAccount[] }

/** The sections of the list for a grouping. "Not in a group" cannot be chosen as a whole. */
export function sectionsFor(
  groupBy: GroupBy, accounts: PortalAccount[], groups: AccountGroup[], viewerId: string | undefined,
): Section[] {
  if (groupBy === 'person') {
    const owners = new Map<string, string>()
    for (const a of accounts) owners.set(a.client_id, a.owner_name)
    // The viewer first, then everyone who shares with them.
    return [...owners].sort(([a], [b]) => (a === viewerId ? -1 : b === viewerId ? 1 : 0)).map(([id, name]) => ({
      key: `owner:${id}`, label: id === viewerId ? name : `${name} · shared with you`,
      selection: { type: 'owner', id }, accounts: accounts.filter((a) => a.client_id === id),
    }))
  }
  if (groupBy === 'kind') {
    return KINDS.map((k) => ({
      key: `kind:${k.kind}`, label: k.label, selection: { type: 'kind' as const, id: k.kind },
      accounts: accounts.filter((a) => a.kind === k.kind),
    })).filter((s) => s.accounts.length > 0)
  }
  const sections: Section[] = groups.map((g) => ({
    key: `group:${g.id}`, label: g.name, selection: { type: 'group' as const, id: g.id },
    accounts: accounts.filter((a) => g.account_ids.includes(a.id)),
  }))
  const grouped = new Set(groups.flatMap((g) => g.account_ids))
  const rest = accounts.filter((a) => !grouped.has(a.id))
  if (rest.length) sections.push({ key: 'ungrouped', label: 'Not in a group', selection: null, accounts: rest })
  return sections
}

const sum = (xs: PortalAccount[]) => xs.reduce((t, a) => t + (a.value ?? 0), 0)

/**
 * The account list beside the landing page: every account in view, grouped by
 * person (only when more than one owner is in view), by kind, or by the
 * viewer's own groups. Choosing All, a group or one account narrows every view.
 */
export function AccountRail({
  accounts, groups, viewerId, groupBy, onGroupBy, showPerson, selection, onSelect, onHide, onEditGroups,
  canEditGroups, privateNote, onAddAccount,
}: {
  accounts: PortalAccount[]; groups: AccountGroup[]; viewerId?: string
  groupBy: GroupBy; onGroupBy: (g: GroupBy) => void; showPerson: boolean
  selection: Selection; onSelect: (s: Selection) => void; onHide: () => void
  onEditGroups: () => void; canEditGroups: boolean; privateNote?: string
  /** Offered where the viewer may add accounts of their own */
  onAddAccount?: () => void
}) {
  const [closed, setClosed] = useState<Record<string, boolean>>({})
  const [search, setSearch] = useState('')
  const [searching, setSearching] = useState(false)
  const chosen = selectionKey(selection)

  const matching = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? accounts.filter((a) => `${a.name} ${a.number_last4 ?? ''} ${a.owner_name}`.toLowerCase().includes(q)) : accounts
  }, [accounts, search])
  const sections = sectionsFor(groupBy, matching, groups, viewerId)

  const options: { value: GroupBy; label: string }[] = [
    ...(showPerson ? [{ value: 'person' as const, label: 'Person' }] : []),
    { value: 'kind', label: 'Kind' }, { value: 'mine', label: 'My groups' },
  ]
  const rowBase = 'w-full text-left flex items-center gap-[10px] rounded-[12px] hover:bg-line'

  return (
    <aside aria-label="Accounts" className="flex flex-col gap-[14px]">
      <div className="flex items-center justify-between">
        <button type="button" onClick={onHide} aria-label="Hide the account list"
          className="w-[44px] h-[44px] rounded-full flex items-center justify-center hover:bg-line">
          <svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M11 6l-6 6 6 6" /><path d="M19 6l-6 6 6 6" /></svg>
        </button>
        <button type="button" onClick={() => { setSearching((s) => !s); setSearch('') }} aria-label="Find an account" aria-expanded={searching}
          className="w-[44px] h-[44px] rounded-full border border-stone/30 bg-paper flex items-center justify-center">
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></svg>
        </button>
      </div>
      {searching && (
        <label className="flex flex-col gap-[6px] text-[12px] font-semibold text-stone px-[4px]">
          Find an account
          <input autoFocus value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or last four"
            className="h-[44px] px-[14px] rounded-[12px] border border-stone/30 bg-paper text-[15px] font-normal text-summit-ink" />
        </label>
      )}

      <button type="button" onClick={() => onSelect({ type: 'all' })} aria-pressed={chosen === 'all'}
        className={`${rowBase} flex-col !items-start gap-[2px] p-[12px] ${chosen === 'all' ? 'bg-accent-soft' : ''}`}>
        <span className={`text-[14px] ${chosen === 'all' ? 'font-bold' : ''}`}>All accounts</span>
        <span className="font-display text-[26px] tabular-nums">{formatCurrency(sum(accounts))}</span>
      </button>

      <div className="flex flex-col gap-[6px]">
        <span id="group-by" className="text-[12px] font-semibold text-stone px-[4px]">Group by</span>
        <div role="group" aria-labelledby="group-by" className="flex border border-stone/30 rounded-[21px] p-[2px] gap-[2px] bg-paper">
          {options.map((o) => (
            <button key={o.value} type="button" aria-pressed={groupBy === o.value} onClick={() => onGroupBy(o.value)}
              className={`flex-1 h-[36px] px-[10px] rounded-[18px] text-[13px] whitespace-nowrap ${
                groupBy === o.value ? 'bg-summit-ink text-paper font-semibold' : 'text-summit-ink/80'
              }`}>
              {o.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-[10px]">
        {sections.length === 0 && (
          <p className="text-[14px] text-stone px-[4px] leading-relaxed">
            {groupBy === 'mine' ? 'No groups yet. Make one to see a set of accounts together.' : 'No account matches.'}
          </p>
        )}
        {sections.map((s) => {
          const shut = !!closed[s.key]
          const on = s.selection && chosen === selectionKey(s.selection)
          return (
            <section key={s.key} className="flex flex-col gap-[2px]">
              <div className="flex items-center gap-[2px]">
                {s.selection ? (
                  <button type="button" onClick={() => onSelect(s.selection!)} aria-pressed={!!on}
                    className={`${rowBase} min-h-[44px] px-[10px] flex-1 ${on ? 'bg-accent-soft' : ''}`}>
                    <span className={`flex-1 text-[13px] font-semibold ${on ? 'text-summit-ink' : 'text-stone'}`}>{s.label}</span>
                    <span className="text-[13px] font-semibold text-stone tabular-nums">{formatCurrency(sum(s.accounts))}</span>
                  </button>
                ) : (
                  <span className="min-h-[44px] px-[10px] flex-1 flex items-center text-[13px] font-semibold text-stone">{s.label}</span>
                )}
                <button type="button" onClick={() => setClosed((c) => ({ ...c, [s.key]: !shut }))} aria-expanded={!shut}
                  aria-label={`${shut ? 'Show' : 'Hide'} ${s.label}`}
                  className="w-[40px] h-[44px] rounded-[12px] text-stone hover:bg-line flex items-center justify-center">
                  <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" className={shut ? '-rotate-90' : ''}><path d="M6 9l6 6 6-6" /></svg>
                </button>
              </div>
              {!shut && s.accounts.map((a) => {
                const k = kindOf(a.kind)
                const picked = chosen === `account:${a.id}`
                return (
                  <button key={a.id} type="button" onClick={() => onSelect({ type: 'account', id: a.id })} aria-pressed={picked}
                    className={`${rowBase} min-h-[52px] px-[10px] py-[6px] ${picked ? 'bg-accent-soft' : ''}`}>
                    <span aria-hidden="true" className={`w-[10px] h-[10px] rounded-full shrink-0 ${k.dot}`} />
                    <span className="flex-1 min-w-0 flex flex-col">
                      <span className={`text-[15px] truncate ${picked ? 'font-bold' : ''}`}>{accountName(a)}</span>
                      <span className="text-[12px] text-stone truncate">
                        {a.number_last4 ? `··${a.number_last4} · ` : ''}{groupBy === 'kind' && showPerson ? a.owner_name.split(' ')[0] : k.label}
                      </span>
                    </span>
                    {a.health?.state === 'incomplete' && (
                      <span role="img" aria-label="Record incomplete" title="A transaction is missing from this account's record"
                        className="w-[18px] h-[18px] rounded-full bg-loss text-on-dark text-[12px] font-bold flex items-center justify-center shrink-0">!</span>
                    )}
                    <span className="text-[15px] font-semibold tabular-nums">{a.value == null ? '—' : formatCurrency(a.value)}</span>
                  </button>
                )
              })}
            </section>
          )
        })}
      </div>

      <div className="flex flex-col gap-[10px] px-[4px] pt-[6px]">
        {privateNote && <p className="text-[13px] text-stone leading-relaxed">{privateNote}</p>}
        {groupBy === 'mine' && canEditGroups && (
          <button type="button" onClick={onEditGroups}
            className="h-[44px] rounded-[22px] border border-dashed border-stone/40 text-pine text-[14px] font-semibold hover:bg-line">
            {groups.length ? 'Edit my groups' : 'Make a group'}
          </button>
        )}
        {onAddAccount && (
          <button type="button" onClick={onAddAccount}
            className="h-[44px] rounded-[22px] border border-stone/40 text-[14px] font-semibold hover:bg-line">
            + Add an account
          </button>
        )}
      </div>
    </aside>
  )
}
