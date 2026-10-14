import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useInvitationRequests, useSetInvitationStatus } from '@/hooks/useInvitations'
import { useCreateClient } from '@/hooks/useClients'
import { EmptyState } from '@/components/EmptyState'
import { ErrorState } from '@/components/ErrorState'
import { SkeletonCard } from '@/components/Skeleton'
import { formatDate } from '@/lib/formatters'
import type { InvitationRequest, InvitationStatus } from '@/api/types'

const STATUS_LABEL: Record<InvitationStatus, string> = {
  new: 'Waiting', contacted: 'Contacted', dismissed: 'Dismissed',
}
const quiet = 'text-xs text-stone hover:text-summit-ink disabled:opacity-50'

/** People who asked for an invitation on the public page, for the adviser to act on. */
export function RequestsPage() {
  const { data: requests, isLoading, isError, refetch } = useInvitationRequests()
  const setStatus = useSetInvitationStatus()
  const createClient = useCreateClient()
  const navigate = useNavigate()
  const [error, setError] = useState('')

  // The request becomes a client record; inviting them to sign in is the next step, on that page.
  const makeClient = async (request: InvitationRequest) => {
    setError('')
    try {
      const client = await createClient.mutateAsync({ name: request.name, email: request.email })
      await setStatus.mutateAsync({ id: request.id, status: 'contacted' })
      navigate(`/app/clients/${client.id}`)
    } catch {
      setError(`Could not create a client for ${request.name}. A client with that email may already exist.`)
    }
  }

  if (isLoading) return <SkeletonCard />
  if (isError || !requests) return <ErrorState message="Could not load the requests." onRetry={() => refetch()} />

  const waiting = requests.filter((r) => r.status === 'new').length
  const busy = setStatus.isPending || createClient.isPending

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      <div>
        <h1 className="font-display text-3xl text-summit-ink">Requests</h1>
        <p className="text-stone text-sm mt-1">
          People who asked for an invitation on the public page.{' '}
          {waiting > 0 ? <span className="font-mono text-summit-ink">{waiting} waiting.</span> : 'None waiting.'}
        </p>
      </div>
      {error && <p className="text-loss text-sm">{error}</p>}

      {requests.length === 0 ? (
        <EmptyState title="No requests yet" message="When someone asks for an invitation, they appear here." />
      ) : (
        <div className="space-y-16">
          {requests.map((request) => (
            <section key={request.id}
              className={`border rounded-card p-6 bg-surface ${request.status === 'new' ? 'border-gold/60' : 'border-stone/20'}`}>
              <div className="flex flex-wrap items-start justify-between gap-16">
                <div className="min-w-0">
                  <p className="text-summit-ink font-medium">{request.name}</p>
                  <p className="text-sm font-mono text-stone mt-1 break-all">
                    <a href={`mailto:${request.email}`} className="hover:text-pine">{request.email}</a>
                    {' · '}
                    <a href={`tel:${request.phone.replace(/[^0-9+]/g, '')}`} className="hover:text-pine">{request.phone}</a>
                  </p>
                </div>
                <p className="text-xs text-stone font-mono shrink-0">
                  {STATUS_LABEL[request.status]} · asked {formatDate(request.created_at)}
                </p>
              </div>
              <p className="text-sm text-summit-ink mt-3 whitespace-pre-wrap break-words">{request.note}</p>
              <div className="flex flex-wrap items-center gap-16 mt-5">
                {request.status === 'new' ? (
                  <>
                    <button onClick={() => makeClient(request)} disabled={busy}
                      className="text-xs bg-pine text-on-dark px-3 py-1.5 rounded-btn hover:bg-pine-deep disabled:opacity-50">
                      Create client
                    </button>
                    <button onClick={() => setStatus.mutate({ id: request.id, status: 'contacted' })} disabled={busy} className={quiet}>
                      Mark contacted
                    </button>
                    <button onClick={() => setStatus.mutate({ id: request.id, status: 'dismissed' })} disabled={busy} className={quiet}>
                      Dismiss
                    </button>
                  </>
                ) : (
                  <button onClick={() => setStatus.mutate({ id: request.id, status: 'new' })} disabled={busy} className={quiet}>
                    Put back as waiting
                  </button>
                )}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  )
}
