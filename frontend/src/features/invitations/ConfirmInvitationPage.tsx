import { useParams, Link } from 'react-router-dom'
import { useConfirmInvitation } from '@/hooks/useInvitations'
import { AuthFrame, authSubmit } from '@/features/auth/AuthFrame'

/**
 * Where the emailed link lands. Confirming takes a press of the button, not
 * just opening the page, so a mail scanner that fetches the link confirms nothing.
 */
export function ConfirmInvitationPage() {
  const { token = '' } = useParams<{ token: string }>()
  const confirm = useConfirmInvitation()

  return (
    <AuthFrame
      footnote={<p className="text-gold">Achalara Services · Clarity first, ambition next</p>}
      aside={
        <h1 className="font-display font-light leading-[1.1] text-[clamp(26px,4vw,48px)]">
          Access is by invitation.
        </h1>
      }
    >
      <div className="space-y-5">
        {confirm.isSuccess ? (
          <>
            <h2 className="font-display text-[32px]">Thank you.</h2>
            <p className="text-[15px] leading-relaxed text-summit-ink/80">Your request is confirmed. We will be in touch.</p>
          </>
        ) : confirm.isError ? (
          <>
            <h2 className="font-display text-[32px]">This link has expired.</h2>
            <p className="text-[15px] leading-relaxed text-summit-ink/80">
              Links work once and for 48 hours. You can send your request again.
            </p>
            <Link to="/request-invitation" className="inline-block text-pine underline underline-offset-2">Request an invitation</Link>
          </>
        ) : (
          <>
            <h2 className="font-display text-[32px]">Confirm your request</h2>
            <p className="text-[15px] leading-relaxed text-summit-ink/80">
              Press the button to confirm that you asked for an invitation to Achalara.
            </p>
            <button onClick={() => confirm.mutate(token)} disabled={confirm.isPending || !token} className={authSubmit}>
              {confirm.isPending ? 'Confirming…' : 'Confirm my request'}
            </button>
          </>
        )}
      </div>
    </AuthFrame>
  )
}
