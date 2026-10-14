import { useParams, Link } from 'react-router-dom'
import { useConfirmInvitation } from '@/hooks/useInvitations'

/**
 * Where the emailed link lands. Confirming takes a press of the button, not
 * just opening the page, so a mail scanner that fetches the link confirms nothing.
 */
export function ConfirmInvitationPage() {
  const { token = '' } = useParams<{ token: string }>()
  const confirm = useConfirmInvitation()

  return (
    <div className="min-h-screen bg-chrome text-on-dark font-sans flex flex-col">
      <header className="px-8 py-5 border-b border-on-dark/5">
        <Link to="/" className="font-display text-xl text-on-dark no-underline">Achalara</Link>
      </header>
      <main className="flex-1 flex items-center justify-center px-6">
        <div className="max-w-md w-full text-center">
          {confirm.isSuccess ? (
            <>
              <h1 className="font-display text-4xl font-light mb-16">Thank you.</h1>
              <p className="text-on-dark/70">Your request is confirmed. We will be in touch.</p>
            </>
          ) : confirm.isError ? (
            <>
              <h1 className="font-display text-4xl font-light mb-16">This link has expired.</h1>
              <p className="text-on-dark/70 mb-32">
                Links work once and for 48 hours. You can send your request again.
              </p>
              <Link to="/#request-invitation" className="text-gold underline underline-offset-2">Request an invitation</Link>
            </>
          ) : (
            <>
              <h1 className="font-display text-4xl font-light mb-16">Confirm your request</h1>
              <p className="text-on-dark/70 mb-32">
                Press the button to confirm that you asked for an invitation to Achalara.
              </p>
              <button onClick={() => confirm.mutate(token)} disabled={confirm.isPending || !token}
                className="px-10 py-3 rounded-btn bg-gold text-on-gold text-sm font-semibold hover:bg-gold/90 transition-colors disabled:opacity-60">
                {confirm.isPending ? 'Confirming…' : 'Confirm my request'}
              </button>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
