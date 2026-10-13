import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useLogin, useMe } from '@/hooks/useAuth'
import { homeFor } from '@/features/auth/RequireAuth'
import { AuthFrame, authInput, authLabel, authSubmit } from '@/features/auth/AuthFrame'

export function LoginPage() {
  const navigate = useNavigate()
  const { data: me } = useMe()
  const login = useLogin()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  if (me) return <Navigate to={homeFor(me.role)} replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    try {
      const user = await login.mutateAsync({ email, password })
      navigate(homeFor(user.role), { replace: true })
    } catch {
      // Shown below from login.error; the password stays for a retry.
    }
  }

  return (
    <AuthFrame
      footnote={
        <>
          <p className="text-gold">Achalara Services · Clarity first, ambition next</p>
          <p>Access is by invitation from your Achalara contact</p>
        </>
      }
      aside={
        <>
          {/* Each sentence stays on one line at every width: the size is worked
              out from the room the panel has (half the window beside the form,
              the whole window once the two stack below 840px). */}
          <h1 className="font-display font-light leading-[1.08] whitespace-nowrap text-[clamp(22px,calc((50vw-112px)/10.2),56px)] max-[839px]:text-[clamp(22px,calc((100vw-128px)/10.4),56px)]">
            <span className="block">Know where you stand.</span>
            <span className="block text-gold italic">Then dream bigger.</span>
          </h1>
          <p className="max-w-md text-[17px] leading-relaxed text-on-dark/80">
            Every position, trade, and return across your portfolio, so your next move starts from facts.
          </p>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-6">
        <h2 className="font-display text-[32px]">Sign in</h2>
        {login.isError && (
          <div role="alert" className="px-3.5 py-3 rounded-btn bg-loss/10 text-loss text-sm leading-snug">
            {login.error.message}
          </div>
        )}
        <div>
          <label htmlFor="email" className={authLabel}>Email</label>
          <input id="email" type="email" required autoFocus autoComplete="username"
            value={email} onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com" className={authInput} />
        </div>
        <div>
          <label htmlFor="password" className={authLabel}>Password</label>
          <input id="password" type="password" required autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)} className={authInput} />
        </div>
        <button type="submit" disabled={login.isPending} className={authSubmit}>
          {login.isPending ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="text-sm text-stone leading-relaxed">
          Forgot your password? Ask your Achalara contact for a reset link.
        </p>
      </form>
    </AuthFrame>
  )
}
