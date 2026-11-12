import { useEffect, useRef, useState } from 'react'
import type { AccountGroup, PortalAccount } from '@/api/types'
import { useGroupChanges } from '@/hooks/usePortal'
import { accountName } from './selection'

/**
 * Making and changing "My groups": a name, and a tick against each account in
 * it. Groups only gather accounts the viewer can already see; they share nothing.
 */
export function GroupsDialog({ open, onClose, groups, accounts }: {
  open: boolean; onClose: () => void; groups: AccountGroup[]; accounts: PortalAccount[]
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const changes = useGroupChanges()
  const [newName, setNewName] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const d = dialog.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  const fail = (e: Error) => setError(e.message)
  const create = () => {
    const name = newName.trim()
    if (!name) return
    setError('')
    changes.create.mutate({ name }, { onSuccess: () => setNewName(''), onError: fail })
  }
  const toggle = (g: AccountGroup, accountId: string) => {
    const ids = g.account_ids.includes(accountId) ? g.account_ids.filter((a) => a !== accountId) : [...g.account_ids, accountId]
    changes.setAccounts.mutate({ id: g.id, accountIds: ids }, { onError: fail })
  }

  return (
    <dialog ref={dialog} onClose={onClose} aria-labelledby="groups-title"
      className="w-[min(560px,calc(100vw-32px))] max-h-[85vh] p-0 rounded-[20px] border border-stone/30 bg-paper text-summit-ink backdrop:bg-black/40">
      <div className="p-[24px] flex flex-col gap-[20px]">
        <div className="flex items-start justify-between gap-[12px]">
          <div className="flex flex-col gap-[4px]">
            <h2 id="groups-title" className="font-display text-[22px]">My groups</h2>
            <p className="text-[14px] text-stone leading-relaxed">Gather accounts you like to see together. Nobody else sees your groups.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="w-[44px] h-[44px] rounded-full hover:bg-line flex items-center justify-center text-[22px]">×</button>
        </div>

        <form onSubmit={(e) => { e.preventDefault(); create() }} className="flex gap-[8px] items-end">
          <label className="flex-1 flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
            New group
            <input value={newName} onChange={(e) => setNewName(e.target.value)} maxLength={80} placeholder="e.g. Retirement"
              className="h-[44px] px-[14px] rounded-[12px] border border-stone/30 bg-paper text-[15px] font-normal text-summit-ink" />
          </label>
          <button type="submit" disabled={!newName.trim() || changes.create.isPending}
            className="h-[44px] px-[18px] rounded-[22px] bg-pine text-on-dark text-[14px] font-semibold disabled:opacity-50">Add</button>
        </form>
        {error && <p role="alert" className="text-[14px] text-loss">{error}</p>}

        {groups.map((g) => (
          <section key={g.id} className="border border-line rounded-[16px] p-[16px] flex flex-col gap-[10px]">
            <div className="flex items-center gap-[8px]">
              <label className="sr-only" htmlFor={`group-${g.id}`}>Group name</label>
              <input id={`group-${g.id}`} defaultValue={g.name} maxLength={80}
                onBlur={(e) => {
                  const name = e.target.value.trim()
                  if (name && name !== g.name) changes.rename.mutate({ id: g.id, name }, { onError: fail })
                }}
                className="flex-1 h-[40px] px-[12px] rounded-[10px] border border-stone/30 bg-paper text-[15px] font-semibold" />
              <button type="button" onClick={() => changes.remove.mutate(g.id, { onError: fail })}
                className="h-[40px] px-[14px] rounded-[20px] border border-stone/30 text-[14px] hover:bg-line">Delete</button>
            </div>
            <fieldset className="flex flex-col gap-[2px]">
              <legend className="sr-only">Accounts in {g.name}</legend>
              {accounts.map((a) => (
                <label key={a.id} className="min-h-[40px] flex items-center gap-[10px] text-[15px] cursor-pointer">
                  <input type="checkbox" checked={g.account_ids.includes(a.id)} onChange={() => toggle(g, a.id)}
                    className="w-[18px] h-[18px] accent-pine" />
                  <span className="flex-1">{accountName(a)}{a.number_last4 ? ` ··${a.number_last4}` : ''}</span>
                  <span className="text-[13px] text-stone">{a.owner_name.split(' ')[0]}</span>
                </label>
              ))}
            </fieldset>
          </section>
        ))}
      </div>
    </dialog>
  )
}
