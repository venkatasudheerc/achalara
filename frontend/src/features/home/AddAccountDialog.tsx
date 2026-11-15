import { useEffect, useId, useRef, useState } from 'react'
import type { AccountKind, PersonRow, PlaidChoice, PlaidConfirmed, PlaidFound, PlaidFoundAccount } from '@/api/types'
import { usePlaidAvailability, usePlaidDiscover, usePlaidLink } from '@/hooks/usePlaid'
import { usePortalAccounts, usePortalPeople } from '@/hooks/usePortal'
import { formatCurrency } from '@/lib/formatters'
import { loadPlaid } from '@/lib/plaid'
import { INVESTED, KINDS } from './selection'

type Step = 'choose' | 'checking' | 'none' | 'found' | 'done'
/** A login already linked, checked for accounts it did not have before. */
export interface Review { connectionId: string; institution: string }
interface Pick {
  action: 'link' | 'new' | 'skip'; accountId?: string; kind: AccountKind
  /** Whose it is: me, 'joint:<id>', 'for:<minorId>' (held for), or 'other:<id>' (theirs; I view it) */
  whose: string
  /** Who else sees it: nobody by default; person ids, and 'advisor' */
  sees: string[]
  costBasis: 'FIFO' | 'MIN_TAX'
}

/** Why a candidate looks like this account, in words. */
function evidence(c: PlaidFoundAccount['candidates'][number]): string {
  if (c.relinked) return 'linked before'
  const parts = [c.same_last_four ? 'same last four' : '', c.same_institution ? 'same institution' : '',
    c.same_holdings === true ? 'same holdings' : c.same_holdings === false ? 'different holdings' : '',
    c.same_balance ? 'same balance' : ''].filter(Boolean)
  return parts.join(', ')
}

const isDone = (a: PlaidFoundAccount) => a.status === 'mapped' || a.status === 'matched'
/** An account another login already feeds: it keeps updating there, so there is nothing to add. */
const isFed = (a: PlaidFoundAccount) => !isDone(a) && !!a.fed_by
const firstName = (name: string | null | undefined) => (name ?? 'someone').split(' ')[0]

/** "Sarvani's Vanguard login", or "your Vanguard login". */
function whoseLogin(f: NonNullable<PlaidFoundAccount['fed_by']>): string {
  const bank = f.institution || 'institution'
  return f.own ? `your other ${bank} login` : `${firstName(f.owner_name)}’s ${bank} login`
}

function initialPick(a: PlaidFoundAccount): Pick {
  const rest = { whose: 'me', sees: [] as string[], costBasis: 'FIFO' as const }
  if (isFed(a)) return { action: 'skip', kind: a.kind, ...rest }
  if (a.proposal === 'same' && a.account_id) return { action: 'link', accountId: a.account_id, kind: a.kind, ...rest }
  if (a.proposal === 'new') return { action: 'new', kind: a.kind, ...rest }
  return { action: 'skip', kind: a.kind, ...rest } // "choose": the person decides
}

function FoundRow({ account, pick, onPick, people, advisor }: {
  account: PlaidFoundAccount; pick: Pick; onPick: (p: Pick) => void
  people: PersonRow[]; advisor: { name: string } | null
}) {
  const done = isDone(account)
  const value = pick.action === 'link' ? `link:${pick.accountId}` : pick.action
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
            {account.candidates.filter((c) => !c.fed_by).map((c) => (
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
        {pick.action === 'new' && (
          <div className="flex flex-col gap-[10px] border-t border-line pt-[12px]">
            <label className="flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
              Whose is it
              <select value={pick.whose} className={`${field} font-normal`} onChange={(e) => onPick({ ...pick, whose: e.target.value })}>
                <option value="me">Mine</option>
                {people.filter((p) => p.relation === 'spouse').map((p) => <option key={`j${p.id}`} value={`joint:${p.id}`}>Mine, jointly with {p.name}</option>)}
                {people.filter((p) => p.is_minor).map((p) => <option key={`f${p.id}`} value={`for:${p.id}`}>Held by me for {p.name}</option>)}
                {people.filter((p) => !p.is_minor).map((p) => <option key={`o${p.id}`} value={`other:${p.id}`}>{p.name}’s (I view it)</option>)}
              </select>
            </label>
            <fieldset className="flex flex-col gap-[2px]">
              <legend className="text-[13px] font-semibold text-stone mb-[4px]">Who else sees it</legend>
              {people.length === 0 && !advisor && <span className="text-[14px] text-stone">Nobody. Add people on the People page to share with them.</span>}
              {[...(advisor ? [{ id: 'advisor', name: `${advisor.name} (your advisor)` }] : []), ...people.filter((p) => !pick.whose.endsWith(p.id) || pick.whose.startsWith('for:'))]
                .map((p) => (
                  <label key={p.id} className="min-h-[36px] flex items-center gap-[10px] text-[14px] cursor-pointer">
                    <input type="checkbox" className="w-[18px] h-[18px] accent-pine" checked={pick.sees.includes(p.id)}
                      onChange={() => onPick({ ...pick, sees: pick.sees.includes(p.id) ? pick.sees.filter((x) => x !== p.id) : [...pick.sees, p.id] })} />
                    {p.name}
                  </label>
                ))}
              <span className="text-[13px] text-stone mt-[2px]">Nobody else sees it unless you say so. They see it as it is and change nothing.</span>
            </fieldset>
            {INVESTED.includes(pick.kind) && (
              <label className="flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
                Cost basis
                <select value={pick.costBasis} className={`${field} font-normal`}
                  onChange={(e) => onPick({ ...pick, costBasis: e.target.value as Pick['costBasis'] })}>
                  <option value="FIFO">First in, first out</option>
                  <option value="MIN_TAX">Minimum tax</option>
                </select>
                <span className="text-[13px] font-normal">Match what your brokerage uses; you can change it later.</span>
              </label>
            )}
          </div>
        )}
      </>)}
    </li>
  )
}

/** A refusal that is a setting on the server, not something the person did. */
const SERVER_SETTING = 'This is a setting on the server, not something you did. Ask the person who runs Achalara to fix it, then try again.'

/**
 * What went wrong, in plain words, with the raw text kept for "Details" when it
 * says more than the plain words do. Linking not set up on the server (503) and
 * Plaid refusing the redirect address are both settings on the server.
 */
function explainLinkError(raw: string): { plain: string; details: string | null } {
  const text = raw.trim()
  if (/not set up on this server/i.test(text)) {
    return { plain: `Linking with Plaid isn’t switched on for this Achalara. ${SERVER_SETTING}`, details: text }
  }
  if (/redirect[ _-]?uri/i.test(text) || /oauth/i.test(text)) {
    return {
      plain: `Plaid refused the address it is asked to return to after a bank’s sign-in. ${SERVER_SETTING}`,
      details: text,
    }
  }
  return { plain: text, details: null }
}

function LinkError({ raw }: { raw: string }) {
  const { plain, details } = explainLinkError(raw)
  return (
    <div role="alert" className="flex flex-col gap-[4px]">
      <p className="text-[14px] text-loss leading-relaxed">{plain}</p>
      {details && <p className="text-[12px] text-stone break-words">Details: {details}</p>}
    </div>
  )
}

/**
 * Add an account: sign in to the institution through Plaid, then say which of
 * the accounts it found are which. Nothing is added until "Add these".
 *
 * With `review`, it instead checks a login already linked for accounts not seen
 * before and offers only those; accounts already linked stay as they are.
 */
export function AddAccountDialog({ open, onClose, review: reviewProp }: { open: boolean; onClose: () => void; review?: Review | null }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const availability = usePlaidAvailability()
  const { data: peopleData } = usePortalPeople(open)
  const { data: portal } = usePortalAccounts()
  const { start, finish, confirm } = usePlaidLink()
  const discover = usePlaidDiscover()
  // Plaid's window closes this dialog and so clears the parent's choice; the login being checked is kept here.
  const [kept, setKept] = useState<Review | null>(null)
  const review = reviewProp ?? kept
  useEffect(() => { if (reviewProp) setKept(reviewProp) }, [reviewProp])
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

  const check = (connectionId: string) => {
    setError(''); setStep('checking')
    discover.one.mutate(connectionId, {
      onSuccess: (f) => {
        const waiting = f.accounts.filter((a) => a.status !== 'mapped' && a.status !== 'matched')
        setFound(f)
        setPicks(Object.fromEntries(f.accounts.map((a) => [a.link_id, initialPick(a)])))
        setStep(waiting.length ? 'found' : 'none')
      },
      onError: (e) => { setError(e.message); setStep('none') },
    })
  }

  useEffect(() => {
    if (open && reviewProp) check(reviewProp.connectionId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reviewProp?.connectionId])

  /** Plaid Link in update mode, where the client may share accounts it did not share before. */
  const shareMore = async () => {
    if (!review) return
    setError(''); setOpening(true)
    try {
      const [{ link_token }, Plaid] = await Promise.all([discover.select.mutateAsync(review.connectionId), loadPlaid()])
      dialog.current?.close()
      const handler = Plaid.create({
        token: link_token,
        onSuccess: () => { dialog.current?.showModal(); handler.destroy(); check(review.connectionId) },
        onExit: (err) => {
          dialog.current?.showModal()
          if (err) setError(err.display_message || err.error_message || 'Sharing more accounts did not finish.')
          handler.destroy()
        },
      })
      handler.open()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setOpening(false)
    }
  }

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
    const viewerId = portal?.viewer.client_id ?? ''
    const choices: PlaidChoice[] = found.accounts
      .filter((a) => a.status !== 'mapped' && a.status !== 'matched')
      .map((a) => {
        const p = picks[a.link_id]
        const choice: PlaidChoice = { link_id: a.link_id, action: p.action, account_id: p.accountId, kind: p.kind }
        if (p.action === 'new') {
          const [how, who] = p.whose.split(':')
          if (how === 'joint') choice.owner_ids = [viewerId, who]
          if (how === 'other') choice.owner_ids = [who]
          if (how === 'for') choice.held_for = who
          choice.share_with = p.sees.filter((x) => x !== 'advisor')
          choice.share_advisor = p.sees.includes('advisor')
          if (INVESTED.includes(p.kind)) choice.cost_basis = p.costBasis
        }
        return choice
      })
    if (!choices.length) { close(); return }
    confirm.mutate({ connectionId: found.connection_id, choices }, {
      onSuccess: (r) => { setResult(r); setStep('done') },
      onError: (e) => setError(e.message),
    })
  }

  // What the person is deciding: accounts another login already feeds need nothing.
  const undecided = found ? found.accounts.filter((a) => !isDone(a)) : []
  const fedCount = undecided.filter(isFed).length
  const toAdd = undecided.filter((a) => !isFed(a) && picks[a.link_id] && picks[a.link_id].action !== 'skip').length
  const newCount = undecided.length - fedCount
  const button = 'h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold'
  const available = availability.data?.available
  const left = availability.data?.logins_left ?? 0

  return (
    <dialog ref={dialog} onClose={close} aria-labelledby={titleId}
      className="w-[min(640px,calc(100vw-32px))] max-h-[90vh] p-0 rounded-[20px] border border-stone/30 bg-paper text-summit-ink backdrop:bg-black/40">
      <div className="p-[24px] flex flex-col gap-[20px]">
        <div className="flex items-start justify-between gap-[12px]">
          <div className="flex flex-col gap-[4px]">
            <h2 id={titleId} className="font-display text-[22px]">
              {step === 'found' ? `What we found at ${found?.institution || 'your institution'}`
                : step === 'done' ? 'Accounts added'
                : review ? `Check ${review.institution || 'your institution'} for new accounts` : 'Add an account'}
            </h2>
            {step === 'found' && (
              <p className="text-[14px] text-stone leading-relaxed">
                {newCount > 0 ? `${newCount} to add.` : 'Nothing new to add.'}
                {fedCount > 0 && ` ${fedCount} already ${fedCount === 1 ? 'updates' : 'update'} through another login and stay${fedCount === 1 ? 's' : ''} as ${fedCount === 1 ? 'it is' : 'they are'}.`}
                {newCount > 0 && ' Check each one: link it to an account that’s already here, add it as new, or leave it out. Nobody else sees a new account unless you say so.'}
              </p>
            )}
          </div>
          <button type="button" onClick={close} aria-label="Close"
            className="w-[44px] h-[44px] rounded-full hover:bg-line flex items-center justify-center text-[22px]">×</button>
        </div>

        {step === 'choose' && !review && (
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
              <p className="text-[14px] text-stone leading-relaxed">Linking with Plaid isn’t switched on for this Achalara yet. {SERVER_SETTING}</p>
            )}
            {available && left <= 2 && (
              <p className="text-[14px] text-stone">
                {left > 0 ? `${left} more institution login${left === 1 ? '' : 's'} can be linked on the current plan.` : 'No more institution logins can be linked on the current plan.'} Ask your Achalara contact for more.
              </p>
            )}
          </div>
        )}

        {step === 'found' && found && (
          <div className="flex flex-col gap-[16px] max-h-[55vh] overflow-y-auto">
            {found.accounts.filter((a) => !isFed(a) && (!review || !isDone(a))).length > 0 && (
              <ul className="flex flex-col gap-[12px]">
                {found.accounts.filter((a) => !isFed(a) && (!review || !isDone(a))).map((a) => (
                  <FoundRow key={a.link_id} account={a} pick={picks[a.link_id]}
                    people={peopleData?.people ?? []} advisor={peopleData?.advisor ?? null}
                    onPick={(p) => setPicks((all) => ({ ...all, [a.link_id]: p }))} />
                ))}
              </ul>
            )}
            {[...new Set(found.accounts.filter(isFed).map((a) => whoseLogin(a.fed_by!)))].map((login) => (
              <section key={login} aria-label={`Already updated through ${login}`} className="border border-line rounded-[16px] p-[16px] flex flex-col gap-[8px]">
                <h3 className="text-[14px] font-semibold">Already updated through {login}</h3>
                <p className="text-[13px] text-stone">Nothing to add: these keep updating there, and nothing about them changes.</p>
                <ul className="flex flex-col divide-y divide-line text-[14px]">
                  {found.accounts.filter((a) => isFed(a) && whoseLogin(a.fed_by!) === login).map((a) => (
                    <li key={a.link_id} className="flex items-baseline justify-between gap-[12px] py-[6px]">
                      <span>{a.name}{a.mask ? <span className="text-stone"> ··{a.mask}</span> : null}</span>
                      <span className="tabular-nums text-stone">{a.balance == null ? '' : formatCurrency(a.balance)}</span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}

        {step === 'found' && review && found && found.accounts.some((a) => a.status === 'mapped' || a.status === 'matched') && (
          <p className="text-[14px] text-stone">
            The {found.accounts.filter((a) => a.status === 'mapped' || a.status === 'matched').length} account(s) already linked here stay exactly as they are.
          </p>
        )}

        {step === 'checking' && (
          <p role="status" className="text-[15px] text-stone">Checking with {review?.institution || 'your institution'}…</p>
        )}

        {step === 'none' && review && (
          <div className="flex flex-col gap-[12px]">
            {!error && <p className="text-[15px] leading-relaxed">No new accounts at {review.institution || 'this institution'}. Everything it shares is already here.</p>}
            <div className="border border-line rounded-[16px] p-[16px] flex flex-col gap-[8px]">
              <span className="font-semibold text-[15px]">Opened an account there lately?</span>
              <span className="text-[14px] text-stone leading-relaxed">
                Some institutions share only the accounts you chose when you first connected. Open their window and tick the new one; nothing else changes.
              </span>
              <div>
                <button type="button" onClick={shareMore} disabled={opening}
                  className="h-[44px] px-[18px] rounded-[22px] border border-stone/40 text-[14px] font-semibold hover:bg-line disabled:opacity-60">
                  {opening ? 'Opening…' : `Share another account at ${review.institution || 'this institution'}`}
                </button>
              </div>
            </div>
          </div>
        )}

        {step === 'done' && result && (
          <div className="flex flex-col gap-[8px] text-[15px] leading-relaxed">
            {result.added > 0 && <p>Added {result.added} new account{result.added === 1 ? '' : 's'}.</p>}
            {result.linked > 0 && <p>Linked {result.linked} to account{result.linked === 1 ? '' : 's'} already here.</p>}
            {result.skipped > 0 && <p>Left out {result.skipped}.</p>}
            {found?.accounts.some((a) => a.plaid_type === 'investment') && (
              <p className="text-stone">
                A brokerage shares only a few weeks of its history this way. To see further back, open each investment
                account and use <strong className="text-summit-ink">Update from a file</strong> with its activity report.
                Until then its record starts where the brokerage’s shared history does.
              </p>
            )}
          </div>
        )}

        {error && <LinkError raw={error} />}

        <div className="flex flex-wrap justify-end gap-[8px]">
          {step === 'found' ? (
            <>
              <button type="button" onClick={close} className={`${button} border border-stone/40 hover:bg-line`}>Not now</button>
              <button type="button" onClick={add} disabled={confirm.isPending} className={`${button} bg-pine text-on-dark disabled:opacity-50`}>
                {confirm.isPending ? 'Adding…' : toAdd > 0 ? `Add ${toAdd} ${toAdd === 1 ? 'account' : 'accounts'}` : 'Done'}
              </button>
            </>
          ) : (
            <button type="button" onClick={close} className={`${button} ${step === 'done' ? 'bg-pine text-on-dark' : 'border border-stone/40 hover:bg-line'}`}>
              {step === 'done' ? 'Done' : step === 'none' ? 'Close' : 'Cancel'}
            </button>
          )}
        </div>
      </div>
    </dialog>
  )
}
