import { useNavigate } from 'react-router-dom'
import { useLogout, useMe } from '@/hooks/useAuth'

/** Where a client lands. The portal's own screens replace this list. */
export function PortalHomePage() {
  const navigate = useNavigate()
  const { data: me } = useMe()
  const logout = useLogout()

  const signOut = () => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })

  return (
    <div className="min-h-screen bg-paper text-summit-ink font-sans">
      <header className="bg-summit-ink text-paper">
        <div className="max-w-5xl mx-auto px-8 py-4 flex items-center justify-between">
          <span className="font-display text-xl font-medium">Achalara</span>
          <button onClick={signOut} className="text-sm text-paper/80 underline underline-offset-2 hover:text-paper">
            Sign out
          </button>
        </div>
      </header>
      <main className="max-w-5xl mx-auto px-8 py-10 space-y-6">
        <div>
          <h1 className="font-display text-3xl">Welcome, {me?.name.split(' ')[0]}</h1>
          <p className="text-stone text-sm mt-2">
            You are signed in. Your positions, trades, realised gains and performance will appear here.
          </p>
        </div>
        <section className="border border-stone/20 rounded-card bg-white">
          <h2 className="px-6 pt-5 text-sm font-mono uppercase tracking-wide text-stone">Accounts you can view</h2>
          {me && me.accounts.length > 0 ? (
            <ul className="divide-y divide-stone/10 mt-3">
              {me.accounts.map((a) => (
                <li key={a.id} className="px-6 py-4 flex items-center justify-between">
                  <span className="font-medium">
                    {a.name}{a.number_last4 && <span className="font-mono font-normal text-stone"> ••{a.number_last4}</span>}
                  </span>
                  {a.shared && (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gold/20 text-summit-ink">Shared with you</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="px-6 py-6 text-sm text-stone">No accounts have been set up for you yet.</p>
          )}
        </section>
      </main>
    </div>
  )
}
