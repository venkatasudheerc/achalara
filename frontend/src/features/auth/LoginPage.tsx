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
      footnote="Access is by invitation from your advisor"
      aside={
        <>
          <h1 className="font-display font-light text-5xl leading-tight">
            Your portfolio, <span className="text-gold italic">as it stands today.</span>
          </h1>
          <p className="text-[17px] leading-relaxed text-paper/80">
            Positions, trades, realised gains and performance for every account you hold or have
            been given access to.
          </p>
        </>
      }
    >
      <form onSubmit={submit} className="space-y-6">
        <div className="space-y-2">
          <h2 className="font-display text-[32px]">Sign in</h2>
          <p className="text-[15px] text-stone">Clients and advisors use the same sign-in.</p>
        </div>
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
          Forgot your password? Ask your advisor for a reset link.
        </p>
      </form>
    </AuthFrame>
  )
}
