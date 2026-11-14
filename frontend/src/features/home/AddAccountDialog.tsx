import { useEffect, useRef, useState } from 'react'
import type { AccountKind, PlaidChoice, PlaidConfirmed, PlaidFound, PlaidFoundAccount } from '@/api/types'
import { usePlaidAvailability, usePlaidLink } from '@/hooks/usePlaid'
import { formatCurrency } from '@/lib/formatters'
import { KINDS } from './selection'

// Plaid's own script opens its sign-in window. It is loaded only when needed.
const PLAID_SCRIPT = 'https://cdn.plaid.com/link/v2/stable/link-initialize.js'
interface PlaidHandler { open: () => void; destroy: () => void }
interface PlaidStatic {
  create: (options: {
    token: string
    onSuccess: (publicToken: string) => void
    onExit: (error: { display_message?: string; error_message?: string } | null) => void
  }) => PlaidHandler
}
declare global { interface Window { Plaid?: PlaidStatic } }

function loadPlaid(): Promise<PlaidStatic> {
  if (window.Plaid) return Promise.resolve(window.Plaid)
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = PLAID_SCRIPT
    script.async = true
    script.onload = () => (window.Plaid ? resolve(window.Plaid) : reject(new Error('Plaid could not be loaded.')))
    script.onerror = () => reject(new Error('Plaid could not be loaded. Check your connection and try again.'))
    document.head.appendChild(script)
  })
}

type Step = 'choose' | 'found' | 'done'
interface Pick { action: 'link' | 'new' | 'skip'; accountId?: string; kind: AccountKind }

/** Why a candidate looks like this account, in words. */
function evidence(c: PlaidFoundAccount['candidates'][number]): string {
  if (c.relinked) return 'linked before'
  const parts = [c.same_last_four ? 'same last four' : '', c.same_institution ? 'same institution' : '',
    c.same_holdings === true ? 'same holdings' : c.same_holdings === false ? 'different holdings' : '',
    c.same_balance ? 'same balance' : ''].filter(Boolean)
  return parts.join(', ')
}

function initialPick(a: PlaidFoundAccount): Pick {
  if (a.proposal === 'same' && a.account_id) return { action: 'link', accountId: a.account_id, kind: a.kind }
  if (a.proposal === 'new') return { action: 'new', kind: a.kind }
  return { action: 'skip', kind: a.kind } // "choose": the person decides
}

function FoundRow({ account, pick, onPick }: { account: PlaidFoundAccount; pick: Pick; onPick: (p: Pick) => void }) {
  const done = account.status === 'mapped' || account.status === 'matched'
  const value = pick.action === 'link' ? `link:${pick.accountId}` : pick.action
  const replacing = pick.action === 'link'
    ? account.candidates.find((c) => c.account_id === pick.accountId)?.replaces : null
  const field = 'h-[44px] px-[12px] rounded-[12px] border border-stone/40 bg-surface text-[14px]'
  return (
    <li className="border border-line rounded-[16px] p-[16px] flex flex-col gap-[12px]">
      <div className="flex justify-between gap-[12px]">
        <div className="flex flex-col">
          <span className="font-semibold">{account.name}{account.mask ? <span className="text-stone"> ··{account.mask}</span> : null}</span>
          {account.proposal === 'choose' && !done && (
            <span className="text-[13px] text-loss">Choose which account this is: the last four alone isn’t enough to be sure.</span>
          )}
        </div>
        <span className="tabular-nums font-semibold whitespace-nowrap">
          {account.balance == null ? '—' : account.owed ? `owes ${formatCurrency(account.balance)}` : formatCurrency(account.balance)}
        </span>
      </div>
      {done ? (
        <span className="text-[14px] text-stone">Already linked.</span>
      ) : (<>
        <div className="flex flex-wrap gap-[8px]">
          <select aria-label={`What to do with ${account.name}`} value={value} className={`${field} flex-1 min-w-[220px]`}
            onChange={(e) => {
              const v = e.target.value
              onPick(v.startsWith('link:') ? { ...pick, action: 'link', accountId: v.slice(5) } : { ...pick, action: v as Pick['action'], accountId: undefined })
            }}>
            {account.candidates.map((c) => (
              <option key={c.account_id} value={`link:${c.account_id}`}>
                Same as {c.name}{c.last_four ? ` ··${c.last_four}` : ''}{evidence(c) ? ` (${evidence(c)})` : ''}
              </option>
            ))}
            <option value="new">Add as a new account</option>
            <option value="skip">Don’t add</option>
          </select>
          <select aria-label={`Kind of ${account.name}`} value={pick.kind} className={field}
            onChange={(e) => onPick({ ...pick, kind: e.target.value as AccountKind })}>
            {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
          </select>
        </div>
        {replacing && (
          <p className="text-[13px] text-loss leading-relaxed">
            This account is updated by {replacing} today. Linking it here starts it afresh from Plaid: the history from {replacing} is
            removed, and earlier history can be added from your institution’s files with Update from a file.
          </p>
        )}
      </>)}
    </li>
  )
}

/**
 * Add an account: sign in to the institution through Plaid, then say which of
 * the accounts it found are which. Nothing is added until "Add these".
 */
export function AddAccountDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const availability = usePlaidAvailability()
  const { start, finish, confirm } = usePlaidLink()
  const [step, setStep] = useState<Step>('choose')
  const [found, setFound] = useState<PlaidFound | null>(null)
  const [picks, setPicks] = useState<Record<string, Pick>>({})
  const [result, setResult] = useState<PlaidConfirmed | null>(null)
  const [error, setError] = useState('')
  const [opening, setOpening] = useState(false)

  useEffect(() => {
    const d = dialog.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  const close = () => {
    setStep('choose'); setFound(null); setPicks({}); setResult(null); setError('')
    onClose()
  }

  const link = async () => {
    setError(''); setOpening(true)
    try {
      const [{ link_token }, Plaid] = await Promise.all([start.mutateAsync(), loadPlaid()])
      // Plaid's window sits above this dialog; close ours while it is open.
      dialog.current?.close()
      const handler = Plaid.create({
        token: link_token,
        onSuccess: (publicToken) => {
          dialog.current?.showModal()
          finish.mutate(publicToken, {
            onSuccess: (f) => {
              setFound(f)
              setPicks(Object.fromEntries(f.accounts.map((a) => [a.link_id, initialPick(a)])))
              setStep('found')
            },
            onError: (e) => setError(e.message),
          })
        },
        onExit: (err) => {
          dialog.current?.showModal()
          if (err) setError(err.display_message || err.error_message || 'The institution’s sign-in did not finish.')
        },
      })
      handler.open()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setOpening(false)
    }
  }

  const add = () => {
    if (!found) return
    const choices: PlaidChoice[] = found.accounts
      .filter((a) => a.status !== 'mapped' && a.status !== 'matched')
      .map((a) => {
        const p = picks[a.link_id]
        return { link_id: a.link_id, action: p.action, account_id: p.accountId, kind: p.kind }
      })
    if (!choices.length) { close(); return }
    confirm.mutate({ connectionId: found.connection_id, choices }, {
      onSuccess: (r) => { setResult(r); setStep('done') },
      onError: (e) => setError(e.message),
    })
  }

  const button = 'h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold'
  const available = availability.data?.available
  const left = availability.data?.logins_left ?? 0

  return (
    <dialog ref={dialog} onClose={close} aria-labelledby="add-title"
      className="w-[min(640px,calc(100vw-32px))] max-h-[90vh] p-0 rounded-[20px] border border-stone/30 bg-paper text-summit-ink backdrop:bg-black/40">
      <div className="p-[24px] flex flex-col gap-[20px]">
        <div className="flex items-start justify-between gap-[12px]">
          <div className="flex flex-col gap-[4px]">
            <h2 id="add-title" className="font-display text-[22px]">
              {step === 'found' ? `What we found at ${found?.institution || 'your institution'}` : step === 'done' ? 'Accounts added' : 'Add an account'}
            </h2>
            {step === 'found' && (
              <p className="text-[14px] text-stone leading-relaxed">Check each one: link it to an account that’s already here, add it as new, or leave it out.</p>
            )}
          </div>
          <button type="button" onClick={close} aria-label="Close"
            className="w-[44px] h-[44px] rounded-full hover:bg-line flex items-center justify-center text-[22px]">×</button>
        </div>

        {step === 'choose' && (
          <div className="flex flex-col gap-[12px]">
            <button type="button" onClick={link} disabled={!available || left <= 0 || opening || finish.isPending}
              className="text-left border border-stone/30 rounded-[16px] p-[18px] hover:bg-line disabled:opacity-60 flex flex-col gap-[4px]">
              <span className="text-[16px] font-semibold">{opening ? 'Opening…' : finish.isPending ? 'Reading your accounts…' : 'Link with Plaid'}</span>
              <span className="text-[14px] text-stone leading-relaxed">
                Sign in to your bank, card, lender or brokerage. Its accounts then update every day by themselves. Achalara never sees your password.
              </span>
            </button>
            <div className="border border-dashed border-stone/30 rounded-[16px] p-[18px] flex flex-col gap-[4px] opacity-70">
              <span className="text-[16px] font-semibold">Upload files <span className="text-[13px] font-normal text-stone">· coming later</span></span>
              <span className="text-[14px] text-stone leading-relaxed">For an institution Plaid doesn’t reach: add the account from its downloads.</span>
            </div>
            {availability.data && !available && (
              <p className="text-[14px] text-stone">Linking isn’t set up on this server yet.</p>
            )}
            {available && left <= 2 && (
              <p className="text-[14px] text-stone">
                {left > 0 ? `${left} more institution login${left === 1 ? '' : 's'} can be linked on the current plan.` : 'No more institution logins can be linked on the current plan.'} Ask your Achalara contact for more.
              </p>
            )}
          </div>
        )}

        {step === 'found' && found && (
          <ul className="flex flex-col gap-[12px] max-h-[55vh] overflow-y-auto">
            {found.accounts.map((a) => (
              <FoundRow key={a.link_id} account={a} pick={picks[a.link_id]}
                onPick={(p) => setPicks((all) => ({ ...all, [a.link_id]: p }))} />
            ))}
          </ul>
        )}

        {step === 'done' && result && (
          <div className="flex flex-col gap-[8px] text-[15px] leading-relaxed">
            {result.added > 0 && <p>Added {result.added} new account{result.added === 1 ? '' : 's'}.</p>}
            {result.linked > 0 && <p>Linked {result.linked} to account{result.linked === 1 ? '' : 's'} already here.</p>}
            {result.skipped > 0 && <p>Left out {result.skipped}.</p>}
          </div>
        )}

        {error && <p role="alert" className="text-[14px] text-loss">{error}</p>}

        <div className="flex flex-wrap justify-end gap-[8px]">
          {step === 'found' ? (
            <>
              <button type="button" onClick={close} className={`${button} border border-stone/40 hover:bg-line`}>Not now</button>
              <button type="button" onClick={add} disabled={confirm.isPending} className={`${button} bg-pine text-on-dark disabled:opacity-50`}>
                {confirm.isPending ? 'Adding…' : 'Add these'}
              </button>
            </>
          ) : (
            <button type="button" onClick={close} className={`${button} ${step === 'done' ? 'bg-pine text-on-dark' : 'border border-stone/40 hover:bg-line'}`}>
              {step === 'done' ? 'Done' : 'Cancel'}
            </button>
          )}
        </div>
      </div>
    </dialog>
  )
}
