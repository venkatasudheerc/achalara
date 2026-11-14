import { useState, type FormEvent, type ReactNode } from 'react'
import type { LinkResponse, Relation, Relative } from '@/api/types'
import { usePortalAccounts, usePortalRelatives, useRelativeChanges } from '@/hooks/usePortal'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { OneTimeLink } from '@/features/auth/OneTimeLink'
import { PRIVATE_NOTE, PrivateToggle } from './PrivateToggle'
import { accountName } from './selection'

/** What the guardrails are, in one line each, in the order people ask. */
const RULES = [
  'Spouses see each other’s accounts, except ones kept private.',
  'A minor’s guardians, and their spouse, see the minor’s accounts.',
  'A minor sees only their own.',
]

const input = 'h-[44px] px-[14px] rounded-[12px] border border-stone/30 bg-paper text-[15px] text-summit-ink'
const pill = 'h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold disabled:opacity-50'

/**
 * Family, in the new app: the viewer's spouse and minors, whether each can sign
 * in (and a link for one who cannot), adding either, and which of the viewer's
 * own accounts are kept from their spouse. Works the same in a staff preview.
 */
export function FamilyPage() {
  const { data: portal } = usePortalAccounts()
  const isMinor = portal?.viewer.is_minor ?? false
  const { data: relatives, isLoading, isError, refetch } = usePortalRelatives(!!portal && !isMinor)

  if (portal && isMinor) {
    return (
      <Frame>
        <p className="text-[16px] leading-relaxed">
          You see your own accounts. Your parents or guardians look after the family’s side of things here.
        </p>
      </Frame>
    )
  }

  const spouse = relatives?.find((r) => r.relation === 'spouse')
  const minors = (relatives ?? []).filter((r) => r.relation === 'minor')
  const own = (portal?.accounts ?? []).filter((a) => !a.shared)

  return (
    <Frame>
      <ul className="flex flex-col gap-[6px] text-[15px] text-summit-ink/80">
        {RULES.map((r) => <li key={r} className="flex gap-[10px]"><span aria-hidden="true" className="w-[6px] h-[6px] mt-[9px] rounded-full bg-pine shrink-0" />{r}</li>)}
      </ul>

      {isError && <ErrorState message="Could not load your family." onRetry={() => refetch()} />}

      <section aria-labelledby="spouse" className="flex flex-col gap-[12px]">
        <h2 id="spouse" className="font-display text-[20px]">Spouse</h2>
        {isLoading || !portal ? <Skeleton className="h-[72px] rounded-[18px]" />
          : spouse ? <Person relative={spouse} />
            : <AddPerson relation="spouse" />}
      </section>

      <section aria-labelledby="minors" className="flex flex-col gap-[12px]">
        <h2 id="minors" className="font-display text-[20px]">Minors in your care</h2>
        {isLoading || !portal ? <Skeleton className="h-[72px] rounded-[18px]" /> : (
          <>
            {minors.length === 0 && !isError && (
              <p className="text-[15px] text-stone">None added. A minor added here sees only their own accounts; you{spouse ? ' and your spouse' : ''} see theirs.</p>
            )}
            {minors.map((m) => <Person key={m.id} relative={m} />)}
            <AddPerson relation="minor" />
          </>
        )}
      </section>

      {own.length > 0 && (
        <section aria-labelledby="private" className="flex flex-col gap-[12px]">
          <h2 id="private" className="font-display text-[20px]">Private accounts</h2>
          <p className="text-[14px] text-stone">{PRIVATE_NOTE}</p>
          <ul className="border border-line rounded-[18px] divide-y divide-line">
            {own.map((a) => (
              <li key={a.id} className="px-[16px] py-[8px] flex flex-wrap items-center justify-between gap-x-[16px]">
                <span className="text-[15px] font-medium">
                  {accountName(a)}{a.number_last4 ? <span className="text-stone font-normal"> ··{a.number_last4}</span> : null}
                </span>
                <PrivateToggle account={a} showNote={false} />
              </li>
            ))}
          </ul>
        </section>
      )}
    </Frame>
  )
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <main className="w-full max-w-[720px] mx-auto px-[20px] md:px-[24px] pt-[32px] pb-[72px] flex flex-col gap-[28px]">
      <h1 className="font-display text-[32px] md:text-[36px] leading-tight">Family</h1>
      {children}
    </main>
  )
}

/** One relative: who, and whether they can sign in; an invite for one who cannot. */
function Person({ relative }: { relative: Relative }) {
  const { invite } = useRelativeChanges()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState(relative.email ?? '')
  const [link, setLink] = useState<LinkResponse | null>(null)
  const first = relative.name.split(' ')[0]

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      setLink(await invite.mutateAsync({ relativeId: relative.id, email: email.trim().toLowerCase() || undefined }))
      setOpen(false)
    } catch {
      // Shown below from the mutation's error.
    }
  }

  return (
    <div className="border border-line rounded-[18px] p-[16px] flex flex-col gap-[10px]">
      <div className="flex flex-wrap items-center justify-between gap-[12px]">
        <div className="flex flex-col gap-[2px] min-w-0">
          <span className="text-[16px] font-semibold">{relative.name}</span>
          <span className="text-[13px] text-stone">
            {relative.email ?? 'No email'} · {relative.has_login || link ? 'Has a sign-in' : 'Cannot sign in yet'}
          </span>
        </div>
        {!relative.has_login && !link && !open && (
          <button type="button" onClick={() => setOpen(true)} className={`${pill} border border-stone/30 hover:bg-line`}>
            Invite {first}
          </button>
        )}
      </div>
      {open && (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-[8px]">
          <label className="flex-1 min-w-[220px] flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
            Email {first} will sign in with
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} font-normal`} />
          </label>
          <button type="submit" disabled={invite.isPending} className={`${pill} bg-pine text-on-dark`}>
            {invite.isPending ? 'Making link…' : 'Make a sign-in link'}
          </button>
          <button type="button" onClick={() => setOpen(false)} className={`${pill} text-stone hover:text-summit-ink`}>Cancel</button>
        </form>
      )}
      {invite.isError && <p role="alert" className="text-[14px] text-loss">{invite.error.message}</p>}
      {link && <OneTimeLink link={link} whose={`${first}’s sign-in`} />}
    </div>
  )
}

/** "Add your spouse" or "Add a minor": a name, and an email if they have one. */
function AddPerson({ relation }: { relation: Relation }) {
  const { add } = useRelativeChanges()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const label = relation === 'spouse' ? 'Add your spouse' : 'Add a minor'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      await add.mutateAsync({ name: name.trim(), relation, email: email.trim().toLowerCase() || null })
      setName(''); setEmail(''); setOpen(false)
    } catch {
      // Shown below from the mutation's error.
    }
  }

  if (!open) {
    return (
      <button type="button" onClick={() => { add.reset(); setOpen(true) }}
        className={`${pill} self-start border border-stone/30 hover:bg-line`}>
        + {label}
      </button>
    )
  }
  return (
    <form onSubmit={submit} className="border border-line rounded-[18px] p-[16px] flex flex-col gap-[12px]">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-[12px]">
        <label className="flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
          Name
          <input required autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} className={`${input} font-normal`} />
        </label>
        <label className="flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
          Email (optional)
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} font-normal`} />
        </label>
      </div>
      <p className="text-[13px] text-stone">
        {relation === 'spouse'
          ? 'You will see each other’s accounts, except ones either of you keeps private.'
          : 'They will see only their own accounts. You can invite them to sign in once they are added.'}
      </p>
      {add.isError && <p role="alert" className="text-[14px] text-loss">{add.error.message}</p>}
      <div className="flex gap-[8px]">
        <button type="submit" disabled={add.isPending || !name.trim()} className={`${pill} bg-pine text-on-dark`}>
          {add.isPending ? 'Adding…' : label}
        </button>
        <button type="button" onClick={() => setOpen(false)} className={`${pill} text-stone hover:text-summit-ink`}>Cancel</button>
      </div>
    </form>
  )
}
