import { useState, type FormEvent } from 'react'
import { useRequestInvitation } from '@/hooks/useInvitations'
import { authInput as field, authLabel as label, authSubmit } from '@/features/auth/AuthFrame'
// Kept in step with the server's rules (backend/app/api/schemas/invitation.py).
const MIN_NOTE = 50

/** The server's reasons, without the "Value error, " it puts in front of each. */
function reasons(error: Error | null): string {
  return (error?.message ?? '').replace(/Value error, /g, '').replace(/value is not a valid email address: /g, '')
}

/** A visitor asks for an invitation. Shown on its own page, in the sign-in look. */
export function RequestInvitationForm() {
  const request = useRequestInvitation()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [note, setNote] = useState('')
  // Hidden from people; a script that fills every field gives itself away here.
  const [website, setWebsite] = useState('')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    request.mutate({ name, email, phone, note, website: website || undefined })
  }

  if (request.isSuccess) {
    return (
      <div role="status" className="space-y-3">
        {request.data.confirm_by_email ? (
          <>
            <p className="font-display text-[26px]">Check your email.</p>
            <p className="text-[15px] leading-relaxed text-summit-ink/80">
              We have sent a link to <strong>{email.trim()}</strong>. Open it within 48 hours to
              confirm your request; we see it once you have.
            </p>
          </>
        ) : (
          <>
            <p className="font-display text-[26px]">Thank you.</p>
            <p className="text-[15px] leading-relaxed text-summit-ink/80">We have your request and will be in touch.</p>
          </>
        )}
      </div>
    )
  }
  const noteLength = note.trim().replace(/\s+/g, ' ').length

  return (
    <form onSubmit={submit} className="space-y-5">
      <div className="space-y-5">
        <div>
          <label htmlFor="invite-name" className={label}>Name</label>
          <input id="invite-name" required minLength={2} maxLength={120} autoComplete="name"
            pattern="[\p{L} \.'\-]{2,120}" title="Letters, with spaces, dots, apostrophes or hyphens"
            value={name} onChange={(e) => setName(e.target.value)} className={field} />
        </div>
        <div>
          <label htmlFor="invite-phone" className={label}>Phone number</label>
          <input id="invite-phone" type="tel" required maxLength={40} autoComplete="tel"
            pattern="[0-9+\(\)\.\- ]{10,40}" title="At least 10 digits, with spaces, dashes, brackets or a leading +"
            value={phone} onChange={(e) => setPhone(e.target.value)} className={field} />
        </div>
      </div>
      <div>
        <label htmlFor="invite-email" className={label}>Email</label>
        <input id="invite-email" type="email" required maxLength={255} autoComplete="email"
          value={email} onChange={(e) => setEmail(e.target.value)} className={field} />
      </div>
      <div>
        <label htmlFor="invite-note" className={label}>Why are you interested, and how did you hear about us?</label>
        <textarea id="invite-note" required minLength={MIN_NOTE} maxLength={1000} rows={5}
          aria-describedby="invite-note-count"
          value={note} onChange={(e) => setNote(e.target.value)} className={`${field} h-auto py-[12px] resize-y`} />
        <p id="invite-note-count" className="text-right text-[13px] mt-1 tabular-nums text-stone">
          {noteLength < MIN_NOTE ? `${MIN_NOTE - noteLength} more characters needed` : `${noteLength} / 1000`}
        </p>
      </div>
      <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label htmlFor="invite-website">Website</label>
        <input id="invite-website" tabIndex={-1} autoComplete="off"
          value={website} onChange={(e) => setWebsite(e.target.value)} />
      </div>

      {request.isError && (
        <p className="px-3.5 py-3 rounded-btn bg-loss/10 text-loss text-sm leading-snug" role="alert">
          That could not be sent. {reasons(request.error) || 'Check each field and try again.'}
        </p>
      )}
      <button type="submit" disabled={request.isPending} className={authSubmit}>
        {request.isPending ? 'Sending…' : 'Request an invitation'}
      </button>
      <p className="text-[13px] text-stone">All fields are needed. We use them only to reply to you.</p>
    </form>
  )
}
