import { useState, type FormEvent } from 'react'
import type { PortalAccount } from '@/api/types'
import { useRenameAccount } from '@/hooks/usePortal'
import { accountName, custodianName } from './selection'

/** The longest name the server keeps (accounts.display_name). */
const MAX = 60

/**
 * An account's name, with "Rename" for one the viewer owns: a name of their own
 * ("Pat's trading account") is shown everywhere in place of the custodian's,
 * which stays beneath in small text. Shared accounts are the owner's to name.
 */
export function AccountNameEditor({ account, size = 'text-[15px]' }: { account: PortalAccount; size?: string }) {
  const rename = useRenameAccount()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const inputId = `rename-${account.id}`
  const custodian = custodianName(account)

  const start = () => {
    rename.reset()
    setDraft(account.display_name ?? '')
    setEditing(true)
  }
  const save = (name: string) =>
    rename.mutate({ accountId: account.id, displayName: name }, { onSuccess: () => setEditing(false) })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    save(draft.trim())
  }

  if (editing) {
    return (
      <form onSubmit={submit} className="flex flex-col gap-[6px] w-full">
        <label htmlFor={inputId} className="text-[13px] text-stone">
          Your name for this account (the custodian calls it {account.display_name ? custodian : accountName(account)})
        </label>
        <div className="flex flex-wrap items-center gap-[8px]">
          <input id={inputId} value={draft} maxLength={MAX} autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Escape') setEditing(false) }}
            placeholder="e.g. Trading account"
            className="min-h-[44px] flex-1 min-w-[200px] rounded-[10px] border border-line bg-surface px-[12px] text-[15px]" />
          <button type="submit" disabled={rename.isPending}
            className="min-h-[44px] px-[16px] rounded-[10px] bg-pine text-on-dark text-[15px] font-semibold disabled:opacity-60">
            Save
          </button>
          <button type="button" onClick={() => setEditing(false)}
            className="min-h-[44px] px-[12px] text-[15px] text-stone hover:text-summit-ink">
            Cancel
          </button>
        </div>
        {account.display_name && (
          <button type="button" onClick={() => save('')} disabled={rename.isPending}
            className="self-start text-[13px] text-pine underline underline-offset-2">
            Use the custodian’s name again
          </button>
        )}
        {rename.isError && <p role="alert" className="text-[13px] text-loss">{rename.error.message}</p>}
      </form>
    )
  }

  return (
    <div className="flex flex-col">
      <span className="flex flex-wrap items-baseline gap-x-[10px]">
        <span className={`${size} font-medium`}>
          {accountName(account)}
          {account.number_last4 ? <span className="text-stone font-normal"> ··{account.number_last4}</span> : null}
        </span>
        {!account.shared && (
          <button type="button" onClick={start} className="text-[13px] text-pine underline underline-offset-2 min-h-[32px]">
            Rename
          </button>
        )}
      </span>
      {custodian && <span className="text-[12px] text-stone">{custodian} at the custodian</span>}
    </div>
  )
}
