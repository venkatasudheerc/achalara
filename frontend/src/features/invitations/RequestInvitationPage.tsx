import { Link, Navigate } from 'react-router-dom'
import { useMe } from '@/hooks/useAuth'
import { homeFor } from '@/features/auth/RequireAuth'
import { AuthFrame } from '@/features/auth/AuthFrame'
import { RequestInvitationForm } from './RequestInvitationForm'

/** Where someone without a login asks for one: beside sign-in, in the same look. */
export function RequestInvitationPage() {
  const { data: me } = useMe()
  if (me) return <Navigate to={homeFor(me.role)} replace />
  return (
    <AuthFrame
      footnote={<p className="text-gold">Achalara Services · Clarity first, ambition next</p>}
      aside={
        <>
          <h1 className="font-display font-light leading-[1.1] text-[clamp(26px,4vw,48px)]">
            Access is by invitation.
          </h1>
          <p className="max-w-md text-[17px] leading-relaxed text-on-dark/80 dark:text-summit-ink/80">
            Tell us a little about yourself and how you heard of Achalara. We read every request and
            reply by email.
          </p>
        </>
      }
    >
      <div className="space-y-6">
        <h2 className="font-display text-[32px]">Request an invitation</h2>
        <RequestInvitationForm />
        <p className="text-sm text-stone">
          Already have a login? <Link to="/login" className="text-pine underline underline-offset-2">Sign in</Link>
        </p>
      </div>
    </AuthFrame>
  )
}
