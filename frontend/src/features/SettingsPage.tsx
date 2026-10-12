import { useClientsList } from '@/hooks/useClients'

export function SettingsPage() {
  const { data: clients = [], isLoading } = useClientsList()

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="font-display text-2xl text-summit-ink">Settings</h1>
        <p className="text-stone text-sm mt-1">Platform configuration.</p>
      </div>

      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-4">Clients</h2>
        {isLoading ? (
          <p className="text-stone text-sm">Loading…</p>
        ) : clients.length ? (
          <ul className="space-y-2">
            {clients.map((c) => (
              <li key={c.id} className="text-sm font-mono text-stone">
                <span className="text-summit-ink">{c.name}</span> — {c.email}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-stone text-sm">No clients found.</p>
        )}
      </section>

      <section className="border border-stone/20 rounded-card p-6">
        <h2 className="text-sm font-mono uppercase tracking-wide text-stone mb-2">Sign-in</h2>
        <p className="text-sm text-stone">
          Advisors and clients sign in with an email and password. Invite a client, or send a
          password-reset link, from that client's page.
        </p>
      </section>
    </div>
  )
}
