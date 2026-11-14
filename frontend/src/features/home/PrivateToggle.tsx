import type { PortalAccount } from '@/api/types'
import { useSetAccountPrivate } from '@/hooks/usePortal'

/** The one line that says what "private" does and does not do. */
export const PRIVATE_NOTE = 'A private account is hidden from your spouse. A minor’s guardians always see a minor’s accounts.'

/**
 * "Keep private from my spouse" for one of the viewer's own accounts. Shown only
 * for an account they own: one shared with them is the owner's to keep private.
 */
export function PrivateToggle({ account, showNote = true }: { account: PortalAccount; showNote?: boolean }) {
  const change = useSetAccountPrivate()
  if (account.shared) return null
  const id = `private-${account.id}`
  // While the change is on its way, show where it is going.
  const on = change.isPending ? !!change.variables?.isPrivate : account.is_private
  return (
    <div className="flex flex-col gap-[6px]">
      <label htmlFor={id} className="min-h-[44px] flex items-center gap-[12px] cursor-pointer">
        <button id={id} type="button" role="switch" aria-checked={on} disabled={change.isPending}
          onClick={() => change.mutate({ accountId: account.id, isPrivate: !account.is_private })}
          className={`relative w-[44px] h-[26px] rounded-[13px] shrink-0 transition-colors disabled:opacity-60 ${on ? 'bg-pine' : 'bg-stone/40'}`}>
          <span aria-hidden="true"
            className={`absolute top-[3px] w-[20px] h-[20px] rounded-full bg-paper transition-[left] ${on ? 'left-[21px]' : 'left-[3px]'}`} />
        </button>
        <span className="text-[15px]">Keep private from my spouse</span>
      </label>
      {showNote && <p className="text-[13px] text-stone">{PRIVATE_NOTE}</p>}
      {change.isError && <p role="alert" className="text-[13px] text-loss">{change.error.message}</p>}
    </div>
  )
}
