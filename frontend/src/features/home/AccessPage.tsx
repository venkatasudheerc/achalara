import { useState, type FormEvent, type ReactNode } from 'react'
import type { LinkResponse, PersonRow, PortalAccount, Relation } from '@/api/types'
import { usePortalAccounts, usePortalPeople, useRelativeChanges, useSharingChanges } from '@/hooks/usePortal'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { OneTimeLink } from '@/features/auth/OneTimeLink'
import { useAccountName } from '@/features/portal/ui'
import { SharingPanel } from './SharingPanel'
import { kindOf } from './selection'

const input = 'h-[44px] px-[14px] rounded-[12px] border border-stone/30 bg-paper text-[15px] text-summit-ink'
const pill = 'h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold disabled:opacity-50'

export const RELATION_LABELS: Record<Relation, string> = {
  spouse: 'Spouse or partner', minor: 'Child (a minor)', child_grown: 'Child, grown up',
  parent: 'Parent', friend: 'Friend', other: 'Other',
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** What a row says about both directions of sharing with one person. */
function sharingLine(p: PersonRow): string {
  const parts: string[] = []
  parts.push(p.you_share ? `You share ${plural(p.you_share, 'account')}` : 'You share no accounts')
  if (p.shares_with_you) parts.push(`${first(p.name)} shares ${plural(p.shares_with_you, 'account')} with you`)
  if (p.own_together) parts.push(`You own ${plural(p.own_together, 'account')} together`)
  if (p.you_hold_for) parts.push(`You hold ${plural(p.you_hold_for, 'account')} for ${first(p.name)}`)
  return parts.join(' · ')
}
const first = (name: string) => name.split(' ')[0]

/**
 * Manage Access, in the new app, account first: every account the viewer owns is
 * private until a person is switched on for it (view only), with a switch per person on
 * each row, "Make everything private", then the people who can be shared with and what
 * is shared with the viewer. Nobody sees an account until its owner shares it.
 * Works the same in a staff preview.
 */
export function AccessPage() {
  const { data: portal } = usePortalAccounts()
  const isMinor = portal?.viewer.is_minor ?? false
  const { data, isLoading, isError, refetch } = usePortalPeople(!!portal && !isMinor)
  const changes = useSharingChanges()
  const [open, setOpen] = useState<string | null>(null)
  const [confirmAll, setConfirmAll] = useState(false)
  // Several accounts can share a name ("Individual"), so each row carries its last four.
  const accountName = useAccountName()

  if (portal && isMinor) {
    return (
      <Frame>
        <p className="text-[16px] leading-relaxed">
          You see your own accounts and any held for you. Your parents or guardians look after sharing here.
        </p>
      </Frame>
    )
  }

  const people = data?.people ?? []
  const family = people.filter((p) => p.group === 'family')
  const others = people.filter((p) => p.group === 'others')
  const mine = data?.your_accounts ?? []
  const sharedCount = mine.filter((a) => a.seen_by_ids.length > 0 || a.advisor_sees).length
  const details = new Map((portal?.accounts ?? []).map((a) => [a.id, a]))

  return (
    <Frame>
      {isLoading || !portal ? <Skeleton className="h-[72px] rounded-[18px]" /> : data && (
        <div className="flex flex-wrap items-center justify-between gap-[12px]">
          <p className="text-[16px] leading-relaxed max-w-[520px]">
            {mine.length === 0 ? 'You have no accounts yet.'
              : sharedCount === 0 ? `All ${plural(mine.length, 'account')} are private. Only you see them.`
              : `${sharedCount} of your ${plural(mine.length, 'account')} ${sharedCount === 1 ? 'is' : 'are'} shared. The rest are private.`}
          </p>
          {sharedCount > 0 && !confirmAll && (
            <button type="button" onClick={() => setConfirmAll(true)} className={`${pill} border border-stone/30 hover:bg-line`}>Make everything private</button>
          )}
          {confirmAll && (
            <div role="alertdialog" aria-label="Make everything private" className="flex flex-wrap items-center gap-[8px]">
              <span className="text-[14px]">Stop sharing all {plural(sharedCount, 'account')}?</span>
              <button type="button" disabled={changes.makePrivate.isPending}
                onClick={() => changes.makePrivate.mutate(undefined, { onSettled: () => setConfirmAll(false) })}
                className={`${pill} bg-pine text-on-dark`}>{changes.makePrivate.isPending ? 'Working…' : 'Yes, make private'}</button>
              <button type="button" onClick={() => setConfirmAll(false)} className={`${pill} text-stone hover:text-summit-ink`}>Cancel</button>
            </div>
          )}
        </div>
      )}
      {isError && <ErrorState message="Could not load who sees your accounts." onRetry={() => refetch()} />}
      {changes.makePrivate.isError && <p role="alert" className="text-[14px] text-loss">{changes.makePrivate.error.message}</p>}

      {data?.notice && (
        <div role="status" className="border border-line rounded-[18px] p-[16px] bg-accent-soft flex flex-wrap items-center justify-between gap-[12px]">
          <p className="text-[15px] leading-relaxed max-w-[520px]">
            Earlier versions let spouses and guardians see accounts automatically. Those are listed below as shares, switched on. Switch off any you do not want, or make everything private.
          </p>
          <button type="button" onClick={() => changes.dismissNotice.mutate()} className={`${pill} border border-stone/30 hover:bg-line`}>Got it</button>
        </div>
      )}

      {data && (
        <>
          <section aria-labelledby="mine-h" className="flex flex-col gap-[12px]">
            <div>
              <h2 id="mine-h" className="font-display text-[20px]">Your accounts</h2>
              <p className="text-[13px] text-stone">Every account starts private. Switch a person on to let them view it; they can never change anything.</p>
            </div>
            {mine.length === 0 ? null : (
              <ul className="border border-line rounded-[18px] divide-y divide-line">
                {mine.map((a) => (
                  <AccountRow key={a.id} row={a} name={accountName(a.id, a.name)} detail={details.get(a.id)} people={people} advisor={data.advisor} onMore={() => setOpen(a.id)} />
                ))}
              </ul>
            )}
            {mine.length > 0 && people.length === 0 && !data.advisor && (
              <p className="text-[14px] text-stone">To share an account, add the person below first.</p>
            )}
          </section>

          <section aria-labelledby="people-h" className="flex flex-col gap-[16px]">
            <div>
              <h2 id="people-h" className="font-display text-[20px]">People you can share with</h2>
              <p className="text-[13px] text-stone">Adding someone shares nothing. They need a sign-in before they can see what you switch on.</p>
            </div>
            {people.length === 0 && <p className="text-[15px] text-stone">Nobody added yet.</p>}
            {family.length > 0 && <Group title="Family" people={family} />}
            {others.length > 0 && <Group title="Others" people={others} />}
            {data.advisor && (
              <div className="border border-line rounded-[18px] p-[16px] flex flex-col gap-[2px]">
                <span className="text-[16px] font-semibold">{data.advisor.name}</span>
                <span className="text-[13px] text-stone">
                  Your advisor · {data.advisor.you_share ? `sees ${plural(data.advisor.you_share, 'account')}` : 'sees none of your accounts'}
                </span>
              </div>
            )}
            <AddPerson />
          </section>

          {data.shared_with_you.length > 0 && (
            <section aria-labelledby="with-h" className="flex flex-col gap-[12px]">
              <h2 id="with-h" className="font-display text-[20px]">Shared with you</h2>
              <ul className="border border-line rounded-[18px] divide-y divide-line">
                {data.shared_with_you.map((a) => (
                  <li key={a.id} className="px-[16px] py-[10px] flex flex-wrap items-center justify-between gap-x-[16px]">
                    <div className="flex flex-col">
                      <span className="text-[15px] font-semibold">{accountName(a.id, a.name)}</span>
                      <span className="text-[13px] text-stone">{a.owner} · View only</span>
                    </div>
                    <button type="button" disabled={changes.stopSeeing.isPending} onClick={() => changes.stopSeeing.mutate(a.id)}
                      className="text-[14px] text-stone hover:text-summit-ink min-h-[44px]">Stop seeing</button>
                  </li>
                ))}
              </ul>
              <p className="text-[13px] text-stone">Hiding an account only removes it from your screens; its owner is not told.</p>
            </section>
          )}
        </>
      )}
      <SharingPanel accountId={open} onClose={() => setOpen(null)} />
    </Frame>
  )
}

type OwnRow = NonNullable<ReturnType<typeof usePortalPeople>['data']>['your_accounts'][number]

/** One account: its name and kind, whether it is private, and a switch per person. Private is the default state. */
function AccountRow({ row, name, detail, people, advisor, onMore }: {
  row: OwnRow; name: string; detail?: PortalAccount; people: PersonRow[]
  advisor: { name: string } | null | undefined; onMore: () => void
}) {
  const changes = useSharingChanges()
  const [error, setError] = useState('')
  const owners = new Set(row.owner_ids)
  const seen = new Set(row.seen_by_ids)
  const count = seen.size + (row.advisor_sees ? 1 : 0)
  const sub = [detail?.institution, detail ? kindOf(detail.kind).label : null]
    .filter(Boolean).join(' · ')

  const toggle = (id: string | 'advisor', on: boolean) => {
    setError('')
    const accountId = row.id
    const v = id === 'advisor' ? { accountId, advisor: true } : { accountId, personId: id }
    ;(on ? changes.share : changes.unshare).mutate(v, { onError: (e: Error) => setError(e.message) })
  }
  const busy = changes.share.isPending || changes.unshare.isPending
  const targets = people.filter((p) => !owners.has(p.id))

  return (
    <li className="px-[16px] py-[12px] flex flex-col gap-[10px]">
      <div className="flex flex-wrap items-start justify-between gap-x-[16px] gap-y-[4px]">
        <div className="flex flex-col min-w-0">
          <span className="text-[15px] font-semibold">{name}</span>
          {sub && <span className="text-[13px] text-stone">{sub}</span>}
        </div>
        <span className={`inline-flex items-center h-[28px] px-[10px] rounded-[14px] text-[13px] font-semibold ${count ? 'bg-accent-soft text-pine' : 'bg-line text-stone'}`}>
          {count ? `Shared with ${count}` : 'Private'}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-[8px]">
        {targets.map((p) => (
          <Switch key={p.id} label={first(p.name)} on={seen.has(p.id)} disabled={busy} onChange={(on) => toggle(p.id, on)} />
        ))}
        {advisor && <Switch label={`${first(advisor.name)} (advisor)`} on={row.advisor_sees} disabled={busy} onChange={(on) => toggle('advisor', on)} />}
        <button type="button" onClick={onMore} className="ml-auto text-[14px] text-pine underline underline-offset-2 min-h-[44px]">
          Owners and more
        </button>
      </div>
      {row.owners.length > 1 && <span className="text-[13px] text-stone">Owned with {row.owners.slice(1).join(', ')}</span>}
      {error && <p role="alert" className="text-[14px] text-loss">{error}</p>}
    </li>
  )
}

/** A named on/off control: off is the default and reads as "can't see". */
function Switch({ label, on, disabled, onChange }: { label: string; on: boolean; disabled?: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} disabled={disabled} onClick={() => onChange(!on)}
      className={`h-[44px] pl-[8px] pr-[14px] rounded-[22px] border flex items-center gap-[10px] text-[14px] font-semibold disabled:opacity-60 ${on ? 'border-pine bg-accent-soft' : 'border-stone/30 hover:bg-line'}`}>
      <span aria-hidden="true" className={`w-[36px] h-[22px] rounded-full p-[2px] flex transition-colors ${on ? 'bg-pine justify-end' : 'bg-stone/40 justify-start'}`}>
        <span className="w-[18px] h-[18px] rounded-full bg-surface" />
      </span>
      <span>{label}</span>
      <span className="sr-only">{on ? 'can view this account' : 'cannot view this account'}</span>
    </button>
  )
}

function Frame({ children }: { children: ReactNode }) {
  return (
    <main className="w-full max-w-[720px] mx-auto px-[20px] md:px-[24px] pt-[32px] pb-[72px] flex flex-col gap-[28px]">
      <h1 className="font-display text-[32px] md:text-[36px] leading-tight">Manage Access</h1>
      {children}
    </main>
  )
}

function Group({ title, people }: { title: string; people: PersonRow[] }) {
  const id = `group-${title.toLowerCase()}`
  return (
    <div role="group" aria-labelledby={id} className="flex flex-col gap-[8px]">
      <h3 id={id} className="text-[13px] font-semibold text-stone">{title}</h3>
      {people.map((p) => <Person key={p.id} person={p} />)}
    </div>
  )
}

/** One person: relation, whether they can sign in (and a link for one who cannot), and what is shared each way. */
function Person({ person }: { person: PersonRow }) {
  const { invite } = useRelativeChanges()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [link, setLink] = useState<LinkResponse | null>(null)
  const name = first(person.name)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      setLink(await invite.mutateAsync({ relativeId: person.id, email: email.trim().toLowerCase() || undefined }))
      setOpen(false)
    } catch {
      // Shown below from the mutation's error.
    }
  }

  return (
    <div className="border border-line rounded-[18px] p-[16px] flex flex-col gap-[10px]">
      <div className="flex flex-wrap items-center justify-between gap-[12px]">
        <div className="flex flex-col gap-[2px] min-w-0">
          <span className="text-[16px] font-semibold">{person.name}</span>
          <span className="text-[13px] text-stone">{RELATION_LABELS[person.relation]} · {person.has_login || link ? 'Has a sign-in' : 'Cannot sign in yet'}</span>
          <span className="text-[13px] text-stone">{sharingLine(person)}</span>
        </div>
        {!person.has_login && !link && !open && (
          <button type="button" onClick={() => setOpen(true)} className={`${pill} border border-stone/30 hover:bg-line`}>Invite {name}</button>
        )}
      </div>
      {!person.has_login && !link && (
        <p className="text-[13px] text-stone">{name} can’t sign in yet, so nothing you share reaches {name} until they accept an invitation.</p>
      )}
      {open && (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-[8px]">
          <label className="flex-1 min-w-[220px] flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
            Email {name} will sign in with
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} font-normal`} />
          </label>
          <button type="submit" disabled={invite.isPending} className={`${pill} bg-pine text-on-dark`}>{invite.isPending ? 'Making link…' : 'Make a sign-in link'}</button>
          <button type="button" onClick={() => setOpen(false)} className={`${pill} text-stone hover:text-summit-ink`}>Cancel</button>
        </form>
      )}
      {invite.isError && <p role="alert" className="text-[14px] text-loss">{invite.error.message}</p>}
      {link && <OneTimeLink link={link} whose={`${name}’s sign-in`} />}
    </div>
  )
}

/** "Add a person": a name, how the viewer knows them, an email if they have one. */
function AddPerson() {
  const { add } = useRelativeChanges()
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [relation, setRelation] = useState<Relation>('spouse')

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
      <button type="button" onClick={() => { add.reset(); setOpen(true) }} className={`${pill} self-start bg-pine text-on-dark`}>
        + Add a person
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
          How you know them
          <select value={relation} onChange={(e) => setRelation(e.target.value as Relation)} className={`${input} font-normal`}>
            {(Object.keys(RELATION_LABELS) as Relation[]).map((r) => <option key={r} value={r}>{RELATION_LABELS[r]}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-[6px] text-[13px] font-semibold text-stone sm:col-span-2">
          Email (optional)
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} font-normal`} />
        </label>
      </div>
      <p className="text-[13px] text-stone">
        Adding someone shares nothing. You choose, account by account, who sees what.
        {relation === 'minor' ? ' A minor does not own accounts: hold an account for them instead.' : ''}
      </p>
      {add.isError && <p role="alert" className="text-[14px] text-loss">{add.error.message}</p>}
      <div className="flex gap-[8px]">
        <button type="submit" disabled={add.isPending || !name.trim()} className={`${pill} bg-pine text-on-dark`}>{add.isPending ? 'Adding…' : 'Add'}</button>
        <button type="button" onClick={() => setOpen(false)} className={`${pill} text-stone hover:text-summit-ink`}>Cancel</button>
      </div>
    </form>
  )
}
