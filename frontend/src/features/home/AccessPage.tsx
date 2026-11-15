import { useState, type FormEvent, type ReactNode } from 'react'
import type { LinkResponse, PersonRow, Relation } from '@/api/types'
import { usePortalAccounts, usePortalPeople, useRelativeChanges, useSharingChanges } from '@/hooks/usePortal'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'
import { OneTimeLink } from '@/features/auth/OneTimeLink'
import { SharingPanel } from './SharingPanel'

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
  parts.push(p.you_share ? `You share ${p.you_share}` : 'You share none')
  if (p.shares_with_you) parts.push(`${first(p.name)} shares ${p.shares_with_you} with you`)
  if (p.own_together) parts.push(`You own ${plural(p.own_together, 'account')} together`)
  if (p.you_hold_for) parts.push(`You hold ${plural(p.you_hold_for, 'account')} for ${first(p.name)}`)
  return parts.join(' · ')
}
const first = (name: string) => name.split(' ')[0]

/**
 * Manage Access, in the new app: everyone the viewer shares with or sees accounts from,
 * grouped Family · Others · Your advisor; the viewer's accounts and who sees them;
 * and what is shared with the viewer. Nobody sees an account until its owner
 * shares it. Works the same in a staff preview.
 */
export function AccessPage() {
  const { data: portal } = usePortalAccounts()
  const isMinor = portal?.viewer.is_minor ?? false
  const { data, isLoading, isError, refetch } = usePortalPeople(!!portal && !isMinor)
  const changes = useSharingChanges()
  const [open, setOpen] = useState<string | null>(null)

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
  const sharingCount = people.filter((p) => p.you_share > 0).length + (data?.advisor?.you_share ? 1 : 0)
  const incoming = people.filter((p) => p.shares_with_you > 0).length
  const mineCount = data?.your_accounts.length ?? 0

  const lead = !data ? '' : sharingCount === 0 && incoming === 0
    ? `Only you see your ${plural(mineCount, 'account')}. Add a person to share one with them.`
    : `${sharingCount ? `${plural(sharingCount, 'person').replace('persons', 'people')} see${sharingCount === 1 ? 's' : ''} some of your accounts` : 'Nobody sees your accounts'}${incoming ? `, and ${plural(incoming, 'person').replace('persons', 'people')} share${incoming === 1 ? 's' : ''} theirs with you` : ''}. Nobody sees an account until you share it.`

  return (
    <Frame>
      {isLoading || !portal ? <Skeleton className="h-[72px] rounded-[18px]" /> : data && <p className="text-[16px] leading-relaxed">{lead}</p>}
      {isError && <ErrorState message="Could not load who sees your accounts." onRetry={() => refetch()} />}

      {data?.notice && (
        <div role="status" className="border border-line rounded-[18px] p-[16px] bg-accent-soft flex flex-wrap items-center justify-between gap-[12px]">
          <p className="text-[15px] leading-relaxed max-w-[520px]">
            Until now spouses and guardians saw accounts automatically. Those are now shares you control: each person below sees exactly what is listed, and you can change it here.
          </p>
          <button type="button" onClick={() => changes.dismissNotice.mutate()} className={`${pill} border border-stone/30 hover:bg-line`}>Got it</button>
        </div>
      )}

      {data && (
        <>
          <Group title="Family" people={family} onOpen={setOpen} empty="No family added yet." />
          <Group title="Others" people={others} onOpen={setOpen} empty="Nobody else added. Add a friend or relative whose accounts you look after, or who looks after yours." />
          {data.advisor && (
            <section aria-labelledby="advisor-h" className="flex flex-col gap-[12px]">
              <h2 id="advisor-h" className="font-display text-[20px]">Your advisor</h2>
              <div className="border border-line rounded-[18px] p-[16px] flex flex-col gap-[2px]">
                <span className="text-[16px] font-semibold">{data.advisor.name}</span>
                <span className="text-[13px] text-stone">
                  {data.advisor.you_share ? `Sees ${plural(data.advisor.you_share, 'of your accounts').replace('of your accounts', 'account')}` : 'Sees none of your accounts'}
                  {data.advisor.not_shared ? ` · ${data.advisor.not_shared} not shared` : ''}
                </span>
              </div>
            </section>
          )}
          <AddPerson />

          <section aria-labelledby="mine-h" className="flex flex-col gap-[12px]">
            <h2 id="mine-h" className="font-display text-[20px]">Your accounts, and who sees them</h2>
            {data.your_accounts.length === 0 ? <p className="text-[15px] text-stone">You have no accounts yet.</p> : (
              <ul className="border border-line rounded-[18px] divide-y divide-line">
                {data.your_accounts.map((a) => (
                  <li key={a.id} className="px-[16px] py-[10px] flex flex-wrap items-center justify-between gap-x-[16px] gap-y-[4px]">
                    <div className="flex flex-col min-w-0">
                      <span className="text-[15px] font-semibold">{a.name}</span>
                      <span className="text-[13px] text-stone">
                        {a.owners.length > 1 ? `Owners: ${a.owners.join(', ')} · ` : ''}Seen by {a.seen_by.length ? a.seen_by.join(', ') : 'nobody else'}
                      </span>
                    </div>
                    <button type="button" onClick={() => setOpen(a.id)} className="text-[14px] text-pine underline underline-offset-2 min-h-[44px]">
                      Who owns it, who sees it
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {data.shared_with_you.length > 0 && (
            <section aria-labelledby="with-h" className="flex flex-col gap-[12px]">
              <h2 id="with-h" className="font-display text-[20px]">Shared with you</h2>
              <ul className="border border-line rounded-[18px] divide-y divide-line">
                {data.shared_with_you.map((a) => (
                  <li key={a.id} className="px-[16px] py-[10px] flex flex-wrap items-center justify-between gap-x-[16px]">
                    <div className="flex flex-col">
                      <span className="text-[15px] font-semibold">{a.name}</span>
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

function Frame({ children }: { children: ReactNode }) {
  return (
    <main className="w-full max-w-[720px] mx-auto px-[20px] md:px-[24px] pt-[32px] pb-[72px] flex flex-col gap-[28px]">
      <h1 className="font-display text-[32px] md:text-[36px] leading-tight">Manage Access</h1>
      {children}
    </main>
  )
}

function Group({ title, people, onOpen, empty }: { title: string; people: PersonRow[]; onOpen: (id: string) => void; empty: string }) {
  const id = `group-${title.toLowerCase()}`
  return (
    <section aria-labelledby={id} className="flex flex-col gap-[12px]">
      <h2 id={id} className="font-display text-[20px]">{title}</h2>
      {people.length === 0 && <p className="text-[15px] text-stone">{empty}</p>}
      {people.map((p) => <Person key={p.id} person={p} onOpen={onOpen} />)}
    </section>
  )
}

/** One person: relation, whether they can sign in (and a link for one who cannot), and what is shared each way. */
function Person({ person }: { person: PersonRow; onOpen: (id: string) => void }) {
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
