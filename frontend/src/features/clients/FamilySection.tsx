import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useClientRelatives, useClientsList, useFamilyChanges } from '@/hooks/useClients'
import { useInviteClient } from '@/hooks/useAuth'
import { OneTimeLink } from '@/features/auth/OneTimeLink'
import type { ClientResponse, LinkResponse, Relation, Relative } from '@/api/types'

const field = 'border border-stone/30 rounded-btn px-2 py-1.5 text-sm bg-surface focus:outline-none focus:border-pine'
const outline = 'text-xs border border-pine text-pine px-3 py-1.5 rounded-btn hover:bg-pine hover:text-on-dark transition-colors disabled:opacity-50'
const quiet = 'text-xs border border-stone/30 text-stone rounded-btn px-3 py-1.5 hover:border-loss hover:text-loss transition-colors disabled:opacity-50'

/**
 * Staff's view of one client's family: their spouse, their minors, and whether
 * they are themselves a minor in someone's care. These decide who sees whose
 * accounts, so the rules are stated above the controls.
 */
export function FamilySection({ client }: { client: ClientResponse }) {
  const { data: relatives, isLoading, isError, refetch } = useClientRelatives(client.id)
  const { data: clients = [] } = useClientsList()
  const changes = useFamilyChanges()
  const [error, setError] = useState('')
  const isMinor = !!client.guardian_id

  /** Applies a change; false (with the API's reason on screen) when it is refused. */
  const run = async (change: () => Promise<unknown>): Promise<boolean> => {
    setError('')
    try {
      await change()
      return true
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return false
    }
  }

  const spouse = relatives?.find((r) => r.relation === 'spouse')
  const minors = (relatives ?? []).filter((r) => r.relation === 'minor')
  const others = clients.filter((c) => c.id !== client.id)
  const nameOf = (id: string) => clients.find((c) => c.id === id)?.name ?? 'another client'
  // Who could be this client's spouse, minor or guardian, by the same rules the API applies.
  const spouseChoices = others.filter((c) => !c.guardian_id && !c.spouse_id)
  const minorChoices = others.filter((c) => !c.guardian_id && !c.spouse_id && c.id !== client.spouse_id)
  const guardianChoices = others.filter((c) => !c.guardian_id)

  return (
    <section className="border border-stone/20 rounded-card p-6">
      <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-2">Family</h2>
      <p className="text-sm text-stone mb-16">
        Spouses see each other's accounts except private ones. A minor's guardians, and their spouse, see the
        minor's accounts; a minor sees only their own. Anything else is shared below, account by account.
      </p>

      {isLoading && <p className="text-sm text-stone">Loading…</p>}
      {isError && (
        <p className="text-sm text-loss">
          Could not load the family. <button onClick={() => refetch()} className="underline underline-offset-2">Try again</button>
        </p>
      )}
      {error && <p role="alert" className="text-loss text-xs mb-3">{error}</p>}

      {relatives && (
        <div className="space-y-6">
          {/* A minor has no spouse or minors of their own; the API refuses both. */}
          {!isMinor && (
            <div>
              <h3 className="text-xs text-stone mb-2">Spouse</h3>
              {spouse ? (
                <RelativeRow relative={spouse}
                  action={<button onClick={() => run(() => changes.setSpouse.mutateAsync({ clientId: client.id, spouseId: null }))}
                    disabled={changes.setSpouse.isPending} className={quiet}>Remove</button>} />
              ) : (
                <div className="space-y-3">
                  <Choose label="Choose an existing client" choices={spouseChoices} button="Make spouse"
                    pending={changes.setSpouse.isPending}
                    onChoose={(id) => run(() => changes.setSpouse.mutateAsync({ clientId: client.id, spouseId: id }))} />
                  <AddNew relation="spouse" pending={changes.addRelative.isPending}
                    onAdd={(body) => run(() => changes.addRelative.mutateAsync({ clientId: client.id, body }))} />
                </div>
              )}
            </div>
          )}

          {!isMinor && (
            <div>
              <h3 className="text-xs text-stone mb-2">Minors</h3>
              {minors.length === 0 && <p className="text-sm text-stone py-1">None.</p>}
              {minors.length > 0 && (
                <ul className="divide-y divide-stone/10 mb-3">
                  {minors.map((m) => (
                    <li key={m.id}>
                      <RelativeRow relative={m}
                        action={<button onClick={() => run(() => changes.setGuardian.mutateAsync({ clientId: m.id, guardianId: null }))}
                          disabled={changes.setGuardian.isPending} className={quiet}>No longer a minor</button>} />
                    </li>
                  ))}
                </ul>
              )}
              <div className="space-y-3">
                <Choose label="Choose an existing client" choices={minorChoices} button="Make a minor of this client"
                  pending={changes.setGuardian.isPending}
                  onChoose={(id) => run(() => changes.setGuardian.mutateAsync({ clientId: id, guardianId: client.id }))} />
                <AddNew relation="minor" pending={changes.addRelative.isPending}
                  onAdd={(body) => run(() => changes.addRelative.mutateAsync({ clientId: client.id, body }))} />
              </div>
            </div>
          )}

          {/* Being a minor and having a spouse exclude each other. */}
          {!client.spouse_id && (
            <div>
              <h3 className="text-xs text-stone mb-2">Is a minor of</h3>
              {client.guardian_id ? (
                <div className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <p className="text-sm text-summit-ink">
                    In the care of{' '}
                    <Link to={`/app/clients/${client.guardian_id}`} className="text-pine underline underline-offset-2">{nameOf(client.guardian_id)}</Link>,
                    who (with their spouse) sees this client's accounts.
                  </p>
                  <button onClick={() => run(() => changes.setGuardian.mutateAsync({ clientId: client.id, guardianId: null }))}
                    disabled={changes.setGuardian.isPending} className={quiet}>Clear</button>
                </div>
              ) : (
                <Choose label="Guardian" choices={guardianChoices} button="Mark as their minor"
                  pending={changes.setGuardian.isPending} none="Not a minor"
                  onChoose={(id) => run(() => changes.setGuardian.mutateAsync({ clientId: client.id, guardianId: id }))} />
              )}
            </div>
          )}
        </div>
      )}
    </section>
  )
}

/** A spouse or minor: name, email, whether they can sign in, and an invite if not. */
function RelativeRow({ relative, action }: { relative: Relative; action: ReactNode }) {
  const invite = useInviteClient()
  const [open, setOpen] = useState(false)
  const [email, setEmail] = useState(relative.email ?? '')
  const [link, setLink] = useState<LinkResponse | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      setLink(await invite.mutateAsync({ clientId: relative.id, email: email.trim().toLowerCase() || undefined }))
      setOpen(false)
    } catch {
      // Shown below from the mutation's error.
    }
  }

  return (
    <div className="py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <Link to={`/app/clients/${relative.id}`} className="text-sm font-medium text-summit-ink hover:text-pine">{relative.name}</Link>
          <p className="text-xs text-stone">
            <span className="font-mono">{relative.email ?? 'No email'}</span>
            {' · '}{relative.has_login || link ? 'Has a login' : 'No login yet'}
          </p>
        </div>
        <div className="flex gap-2">
          {!relative.has_login && !link && !open && (
            <button onClick={() => { invite.reset(); setOpen(true) }} className={outline}>Invite</button>
          )}
          {action}
        </div>
      </div>
      {open && (
        <form onSubmit={submit} className="flex flex-wrap items-end gap-2 mt-2">
          <div className="flex-1 min-w-[220px]">
            <label htmlFor={`invite-${relative.id}`} className="text-xs text-stone block mb-1">Sign-in email</label>
            <input id={`invite-${relative.id}`} type="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              className={`${field} w-full font-mono`} />
          </div>
          <button type="submit" disabled={invite.isPending} className={outline}>
            {invite.isPending ? 'Working…' : 'Create invite link'}
          </button>
          <button type="button" onClick={() => setOpen(false)} className="text-xs text-stone px-2 py-1.5">Cancel</button>
        </form>
      )}
      {invite.isError && <p className="text-loss text-xs mt-2">{invite.error.message}</p>}
      {link && <OneTimeLink link={link} whose={`${relative.name}'s login`} />}
    </div>
  )
}

/** A select of existing clients and a button to apply the choice. */
function Choose({ label, choices, button, pending, onChoose, none = 'Choose…' }: {
  label: string; choices: ClientResponse[]; button: string; pending: boolean
  onChoose: (id: string) => Promise<boolean>; none?: string
}) {
  const [id, setId] = useState('')
  if (choices.length === 0) return null
  return (
    <div className="flex flex-wrap items-end gap-2">
      <div>
        <label className="text-xs text-stone block mb-1">{label}</label>
        <select aria-label={label} value={id} onChange={(e) => setId(e.target.value)} className={field}>
          <option value="">{none}</option>
          {choices.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </div>
      <button onClick={async () => { if (await onChoose(id)) setId('') }} disabled={!id || pending} className={outline}>{button}</button>
    </div>
  )
}

/** "Add spouse" or "Add a minor" as a new client: a name, and an email if they have one. */
function AddNew({ relation, pending, onAdd }: {
  relation: Relation; pending: boolean; onAdd: (body: { name: string; relation: Relation; email: string | null }) => Promise<boolean>
}) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const label = relation === 'spouse' ? 'Add spouse' : 'Add a minor'

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!(await onAdd({ name: name.trim(), relation, email: email.trim().toLowerCase() || null }))) return
    setName(''); setEmail(''); setOpen(false)
  }

  if (!open) return <button onClick={() => setOpen(true)} className={outline}>+ {label} as a new client</button>
  return (
    <form onSubmit={submit} className="p-16 bg-mist/30 rounded-btn space-y-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor={`new-${relation}-name`} className="text-xs text-stone block mb-1">Name</label>
          <input id={`new-${relation}-name`} required autoFocus value={name} onChange={(e) => setName(e.target.value)} className={`${field} w-full`} />
        </div>
        <div>
          <label htmlFor={`new-${relation}-email`} className="text-xs text-stone block mb-1">Email (optional)</label>
          <input id={`new-${relation}-email`} type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={`${field} w-full font-mono`} />
        </div>
      </div>
      <div className="flex gap-2">
        <button type="submit" disabled={pending || !name.trim()}
          className="px-3 py-1.5 bg-pine text-on-dark text-xs rounded-btn hover:bg-pine-deep disabled:opacity-50">
          {pending ? 'Adding…' : label}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="px-3 py-1.5 text-stone text-xs">Cancel</button>
      </div>
    </form>
  )
}
