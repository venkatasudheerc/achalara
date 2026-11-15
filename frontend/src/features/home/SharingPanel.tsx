import { useEffect, useRef, useState } from 'react'
import { useAccountSharing, usePortalPeople, useSharingChanges } from '@/hooks/usePortal'
import { Skeleton } from '@/components/Skeleton'
import { ErrorState } from '@/components/ErrorState'

const pill = 'h-[44px] px-[18px] rounded-[22px] text-[14px] font-semibold disabled:opacity-50'
const select = 'h-[44px] px-[12px] rounded-[12px] border border-stone/30 bg-paper text-[15px] text-summit-ink'

/** "Sam and Jordan Avery" / "Sam, Lee and Jordan Avery" */
function list(names: string[]): string {
  if (names.length <= 1) return names.join('')
  return `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
}

/**
 * "Who owns it, who sees it" for one account, opened from About this account and
 * from Manage Access. Says the answer first; an owner can share it (view only), stop
 * sharing, change the owner, hold it for a minor and hand it over. Anyone else
 * who can see the account reads it and changes nothing.
 */
export function SharingPanel({ accountId, onClose }: { accountId: string | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const { data, isLoading, isError, refetch } = useAccountSharing(accountId)
  const { data: people } = usePortalPeople(!!accountId)
  const changes = useSharingChanges()
  const [pick, setPick] = useState('')
  const [newOwner, setNewOwner] = useState('')
  const [keepView, setKeepView] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const d = dialog.current
    if (!d) return
    if (accountId && !d.open) d.showModal()
    if (!accountId && d.open) d.close()
  }, [accountId])

  const fail = (e: Error) => setError(e.message)
  const run = <T,>(m: { mutate: (v: T, o: { onError: (e: Error) => void; onSuccess?: () => void }) => void }, v: T, done?: () => void) => {
    setError('')
    m.mutate(v, { onError: fail, onSuccess: done })
  }

  const ownerIds = new Set(data?.owners.map((o) => o.id))
  const sharedIds = new Set(data?.shared_with.filter((s) => s.kind === 'person').map((s) => s.id))
  const advisorShared = !!data?.shared_with.some((s) => s.kind === 'advisor')
  // People it could be shared with: added people who do not own it and do not see it.
  const canShare = (people?.people ?? []).filter((p) => !ownerIds.has(p.id) && !sharedIds.has(p.id))
  const canOwn = (people?.people ?? []).filter((p) => !p.is_minor && !ownerIds.has(p.id))
  const seers = (data?.shared_with ?? []).map((s) => s.name)
  const ownerNames = data?.owners.map((o) => o.name) ?? []
  const first = (n: string) => n.split(' ')[0]

  const others = ownerNames.slice(1)
  const headline = !data ? '' : data.can_manage
    ? `${others.length ? `You own this account with ${list(others)}.` : 'You own this account.'} ${
      seers.length ? `${list(seers)} can see it; nobody else can.` : 'Nobody else sees it.'}`
    : `${list(ownerNames)} ${ownerNames.length > 1 ? 'own' : 'owns'} this account and can change who sees it.`

  return (
    <dialog ref={dialog} onClose={onClose} aria-labelledby="sharing-title"
      className="w-[min(560px,calc(100vw-32px))] max-h-[85vh] p-0 rounded-[20px] border border-stone/30 bg-paper text-summit-ink backdrop:bg-black/40">
      <div className="p-[24px] flex flex-col gap-[20px]">
        <div className="flex items-start justify-between gap-[12px]">
          <div className="flex flex-col gap-[4px]">
            <h2 id="sharing-title" className="font-display text-[22px]">Who owns it, who sees it</h2>
            {data && <p className="text-[15px] leading-relaxed">{headline}</p>}
          </div>
          <button type="button" onClick={onClose} aria-label="Close"
            className="w-[44px] h-[44px] rounded-full hover:bg-line flex items-center justify-center text-[22px]">×</button>
        </div>

        {isLoading && <Skeleton className="h-[120px] rounded-[16px]" />}
        {isError && <ErrorState message="Could not load who sees this account." onRetry={() => refetch()} />}
        {error && <p role="alert" className="text-[14px] text-loss">{error}</p>}

        {data && (
          <>
            <section aria-labelledby="owners-h" className="flex flex-col gap-[8px]">
              <h3 id="owners-h" className="text-[13px] font-semibold text-stone">Owner{data.owners.length > 1 ? 's' : ''}</h3>
              <ul className="border border-line rounded-[16px] divide-y divide-line">
                {data.owners.map((o) => (
                  <li key={o.id} className="px-[16px] min-h-[44px] flex items-center justify-between gap-[12px] text-[15px]">
                    <span>{o.name}</span>
                    {!o.has_login && <span className="text-[13px] text-stone">Cannot sign in yet</span>}
                  </li>
                ))}
              </ul>
              {data.held_for && (
                <p className="text-[14px] text-stone">
                  Held by its custodian for {data.held_for.name}, who does not own it yet. {first(data.held_for.name)} sees it, and changes nothing.
                </p>
              )}
            </section>

            <section aria-labelledby="seen-h" className="flex flex-col gap-[8px]">
              <h3 id="seen-h" className="text-[13px] font-semibold text-stone">Also seen by (view only)</h3>
              {data.shared_with.length === 0 ? <p className="text-[15px] text-stone">Nobody.</p> : (
                <ul className="border border-line rounded-[16px] divide-y divide-line">
                  {data.shared_with.map((s) => (
                    <li key={`${s.kind}-${s.id}`} className="px-[16px] min-h-[44px] flex items-center justify-between gap-[12px] text-[15px]">
                      <span>{s.name}{s.kind === 'advisor' ? <span className="text-stone"> · your advisor</span> : null}</span>
                      {data.can_manage && (
                        <button type="button" disabled={changes.unshare.isPending}
                          onClick={() => run(changes.unshare, s.kind === 'advisor' ? { accountId: data.account_id, advisor: true } : { accountId: data.account_id, personId: s.id })}
                          className="h-[36px] px-[12px] rounded-[18px] text-[14px] text-stone hover:bg-line whitespace-nowrap shrink-0">Stop sharing</button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <p className="text-[13px] text-stone">They see it as it is and change nothing. Nobody can move money through Achalara.</p>
            </section>

            {data.can_manage && (
              <>
                <form className="flex flex-wrap items-end gap-[8px]"
                  onSubmit={(e) => {
                    e.preventDefault()
                    if (!pick) return
                    run(changes.share, pick === 'advisor' ? { accountId: data.account_id, advisor: true } : { accountId: data.account_id, personId: pick }, () => setPick(''))
                  }}>
                  <label className="flex-1 min-w-[200px] flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
                    Share with someone
                    <select value={pick} onChange={(e) => setPick(e.target.value)} className={`${select} font-normal`}>
                      <option value="">Choose a person…</option>
                      {data.advisor && !advisorShared && <option value="advisor">{data.advisor.name} (your advisor)</option>}
                      {canShare.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  </label>
                  <button type="submit" disabled={!pick || changes.share.isPending} className={`${pill} bg-pine text-on-dark`}>
                    {pick === 'advisor' && data.advisor ? `Share with ${first(data.advisor.name)}` : 'Share'}
                  </button>
                </form>
                {canShare.length === 0 && !(data.advisor && !advisorShared) && (
                  <p className="text-[13px] text-stone -mt-[12px]">To share with someone new, add them on the Manage Access page first.</p>
                )}

                {canOwn.length > 0 && (
                  <section aria-labelledby="owner-h" className="border-t border-line pt-[16px] flex flex-col gap-[10px]">
                    <h3 id="owner-h" className="text-[13px] font-semibold text-stone">Change owner</h3>
                    <div className="flex flex-wrap items-end gap-[8px]">
                      <label className="flex-1 min-w-[200px] flex flex-col gap-[6px] text-[13px] font-semibold text-stone">
                        New owner
                        <select value={newOwner} onChange={(e) => setNewOwner(e.target.value)} className={`${select} font-normal`}>
                          <option value="">Choose a person…</option>
                          {canOwn.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                        </select>
                      </label>
                      <button type="button" disabled={!newOwner || changes.setOwners.isPending}
                        onClick={() => run(changes.setOwners, { accountId: data.account_id, ownerIds: [newOwner], keepView }, () => setNewOwner(''))}
                        className={`${pill} border border-stone/30 hover:bg-line`}>
                        Make {newOwner ? first(canOwn.find((p) => p.id === newOwner)?.name ?? '') : 'them'} the owner
                      </button>
                      <button type="button" disabled={!newOwner || changes.setOwners.isPending}
                        onClick={() => run(changes.setOwners, { accountId: data.account_id, ownerIds: [...ownerIds, newOwner], keepView }, () => setNewOwner(''))}
                        className={`${pill} border border-stone/30 hover:bg-line`}>
                        Add as joint owner
                      </button>
                    </div>
                    <label className="min-h-[36px] flex items-center gap-[10px] text-[14px] cursor-pointer">
                      <input type="checkbox" checked={keepView} onChange={(e) => setKeepView(e.target.checked)} className="w-[18px] h-[18px] accent-pine" />
                      Whoever stops owning it keeps view-only access
                    </label>
                    <p className="text-[13px] text-stone">Nothing changes at the institution, and the new owner does not need to accept.</p>
                  </section>
                )}

                {(people?.people ?? []).some((p) => p.is_minor) && (
                  <section aria-labelledby="held-h" className="border-t border-line pt-[16px] flex flex-col gap-[10px]">
                    <h3 id="held-h" className="text-[13px] font-semibold text-stone">Held for a minor</h3>
                    <select aria-label="Held for" value={data.held_for?.id ?? ''} className={`${select} self-start`}
                      onChange={(e) => run(changes.holdFor, { accountId: data.account_id, minorId: e.target.value || null })}>
                      <option value="">Not held for anyone</option>
                      {(people?.people ?? []).filter((p) => p.is_minor).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                    {data.held_for && (
                      <div className="flex flex-col gap-[6px]">
                        <h3 className="text-[13px] font-semibold text-stone">When {first(data.held_for.name)} comes of age</h3>
                        <button type="button" disabled={changes.handOver.isPending}
                          onClick={() => run(changes.handOver, { accountId: data.account_id, keepView })}
                          className="self-start text-[14px] text-pine underline underline-offset-2 min-h-[44px]">
                          Hand over to {first(data.held_for.name)}…
                        </button>
                        <p className="text-[13px] text-stone">{first(data.held_for.name)} needs a sign-in first.</p>
                      </div>
                    )}
                  </section>
                )}
              </>
            )}
          </>
        )}
      </div>
    </dialog>
  )
}
