import { useState, type InputHTMLAttributes } from 'react'
import { authInput } from '@/features/auth/AuthFrame'

/**
 * A password field with an eye button that shows what was typed, and hides it
 * again. The button is not a submit, and says what it will do for screen readers.
 */
export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'className'>) {
  const [shown, setShown] = useState(false)
  return (
    <div className="relative">
      <input {...props} type={shown ? 'text' : 'password'} className={`${authInput} pr-[48px]`} />
      <button type="button" onClick={() => setShown(!shown)}
        aria-label={shown ? 'Hide password' : 'Show password'} aria-pressed={shown}
        aria-controls={props.id} title={shown ? 'Hide password' : 'Show password'}
        className="absolute inset-y-0 right-0 flex items-center justify-center w-[44px] text-stone hover:text-summit-ink focus:outline-none focus-visible:text-summit-ink">
        <svg aria-hidden width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
          <circle cx="12" cy="12" r="3" />
          {shown && <line x1="3" y1="3" x2="21" y2="21" />}
        </svg>
      </button>
    </div>
  )
}
