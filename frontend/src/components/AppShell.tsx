import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useLogout, useMe } from '@/hooks/useAuth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useDateRange } from '@/context/DateRangeContext'
import { useScope } from '@/context/ScopeContext'

const navItems = [
  { to: '/app/performance', label: 'Performance' },
  { to: '/app/clients', label: 'Clients' },
  { to: '/app/strategies', label: 'Strategies' },
  { to: '/app/imports', label: 'Imports' },
  { to: '/app/status', label: 'System status' },
]

const fastFollowers = [
  { to: '/app/portfolio', label: 'Portfolio' },
  { to: '/app/risk', label: 'Risk' },
  { to: '/app/grow', label: 'Grow' },
]

export function AppShell() {
  const { startDate, endDate, setDateRange } = useDateRange()
  const { scope, clearScope } = useScope()
  const navigate = useNavigate()
  const { data: me } = useMe()
  const logout = useLogout()
  const signOut = () => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })

  return (
    <div className="min-h-screen bg-paper flex">
      {/* Sidebar */}
      <aside className="hidden md:flex flex-col w-56 bg-chrome text-on-dark shrink-0 fixed top-0 left-0 h-full z-10">
        <div className="px-6 py-6 border-b border-on-dark/15">
          <span className="font-display text-lg text-on-dark tracking-tight">Achalara</span>
          <p className="text-xs text-stone mt-0.5">Performance Platform</p>
        </div>

        <nav className="flex-1 px-4 py-6 space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-btn text-sm transition-colors ${
                  isActive
                    ? 'bg-pine text-on-dark font-medium'
                    : 'text-on-dark/70 hover:text-on-dark hover:bg-pine/30'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}

          <div className="pt-4 mt-4 border-t border-on-dark/15">
            <p className="text-xs text-stone px-3 mb-2 uppercase tracking-wide">Coming soon</p>
            {fastFollowers.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className="block px-3 py-2 rounded-btn text-sm text-stone/60 hover:text-stone transition-colors"
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>

        <div className="px-4 py-4 border-t border-on-dark/15">
          <NavLink
            to="/app/settings"
            className="block px-3 py-2 rounded-btn text-sm text-stone/60 hover:text-on-dark transition-colors"
          >
            Settings
          </NavLink>
          <div className="px-3 pt-3 mt-2 border-t border-on-dark/15">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs text-on-dark/80 truncate">{me?.name}</p>
              <ThemeToggle className="-mr-2 shrink-0" />
            </div>
            <button onClick={signOut} className="text-xs text-stone hover:text-on-dark underline underline-offset-2 mt-1">
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 md:ml-56 flex flex-col min-h-screen">
        {/* Top bar */}
        <header className="sticky top-0 z-10 bg-paper/95 backdrop-blur border-b border-stone/20 px-6 py-3 flex items-center gap-4">
          {/* Scope breadcrumb */}
          <div className="flex-1 flex items-center gap-2 text-sm text-stone font-mono overflow-x-auto">
            {scope.clientName && (
              <>
                <button
                  onClick={clearScope}
                  className="hover:text-summit-ink transition-colors"
                >
                  {scope.clientName}
                </button>
              </>
            )}
            {scope.accountName && (
              <>
                <span>/</span>
                <span className="text-summit-ink">{scope.accountName}</span>
              </>
            )}
            {scope.sleeveName && (
              <>
                <span>/</span>
                <span className="text-summit-ink">{scope.sleeveName}</span>
              </>
            )}
            {scope.strategyName && (
              <span className="text-summit-ink">{scope.strategyName}</span>
            )}
            {!scope.clientId && !scope.strategyId && (
              <span className="text-stone/50 text-xs">Select a client to begin</span>
            )}
          </div>

          {/* Date range */}
          <div className="flex items-center gap-2 shrink-0">
            <input
              type="date"
              value={startDate ?? ''}
              onChange={(e) => setDateRange(e.target.value || undefined, endDate)}
              className="border border-stone/30 rounded-btn px-2 py-1 text-xs font-mono text-summit-ink focus:outline-none focus:border-pine"
            />
            <span className="text-stone text-xs">to</span>
            <input
              type="date"
              value={endDate ?? ''}
              onChange={(e) => setDateRange(startDate, e.target.value || undefined)}
              className="border border-stone/30 rounded-btn px-2 py-1 text-xs font-mono text-summit-ink focus:outline-none focus:border-pine"
            />
            {(startDate || endDate) && (
              <button
                onClick={() => setDateRange(undefined, undefined)}
                className="text-stone hover:text-loss text-xs"
                title="Clear date range"
              >
                ✕
              </button>
            )}
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 px-6 py-8">
          <Outlet />
        </main>
      </div>

      {/* Mobile bottom nav */}
      <nav className="fixed bottom-0 left-0 right-0 md:hidden bg-chrome border-t border-on-dark/15 flex z-20">
        {navItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex-1 py-3 text-center text-xs transition-colors ${
                isActive ? 'text-gold font-medium' : 'text-on-dark/60'
              }`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
