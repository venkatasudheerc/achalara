import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useLogout, useMe } from '@/hooks/useAuth'
import { ThemeToggle } from '@/components/ThemeToggle'
import { useDateRange } from '@/context/DateRangeContext'
import { useScope } from '@/context/ScopeContext'
import { useOneAppLook } from '@/context/ThemeContext'
import { useClientsList } from '@/hooks/useClients'
import { staffTitle } from '@/lib/roles'

interface NavItem {
  to: string
  label: string
  /** The label in the phone's bottom bar, where space is short. */
  short?: string
  /** One of the phone's bottom bar; every other page is under More. */
  phone?: boolean
}

/** The day-to-day pages, for an admin and an advisor alike, the admin's Requests aside. */
const workItems: (NavItem & { admin?: boolean })[] = [
  { to: '/app/clients', label: 'People', phone: true },
  { to: '/app/requests', label: 'Requests', admin: true },
  { to: '/app/markets', label: 'Market patterns', short: 'Markets', phone: true },
  { to: '/app/performance', label: 'Performance', phone: true },
  { to: '/app/strategies', label: 'Strategies' },
]

/** The platform's own pages: the admin's alone (an advisor neither sees nor may open them). */
const platformItems: NavItem[] = [
  { to: '/app/imports', label: 'Imports' },
  { to: '/app/status', label: 'System status' },
  { to: '/app/market-data', label: 'Market data' },
  { to: '/app/settings', label: 'Settings' },
]

const sideLink = ({ isActive }: { isActive: boolean }) =>
  `block px-3 py-2 rounded-btn text-sm transition-colors ${
    isActive ? 'bg-pine text-on-dark font-medium' : 'text-on-dark/70 hover:text-on-dark hover:bg-pine/30'
  }`

export function AppShell() {
  // The staff workspace wears the same look as the client app, light or dark.
  useOneAppLook()
  const { scope, clearScope } = useScope()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { data: me } = useMe()
  const logout = useLogout()
  const isAdmin = me?.role === 'admin'
  const work = workItems.filter((item) => isAdmin || !item.admin)
  const platform = isAdmin ? platformItems : []
  const signOut = () => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })
  // The scope is remembered in the tab; a client this login cannot see (removed,
  // or another login's) is forgotten once the list of clients says so.
  const { data: clients } = useClientsList()
  const staleClient = !!scope.clientId && !!clients && !clients.some((c) => c.id === scope.clientId)
  useEffect(() => {
    if (staleClient) clearScope()
  }, [staleClient, clearScope])

  // The phone's More sheet closes whenever the page changes.
  const [moreOpen, setMoreOpen] = useState(false)
  useEffect(() => setMoreOpen(false), [pathname])
  useEffect(() => {
    if (!moreOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMoreOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [moreOpen])

  // The date range and the scope's trail matter only to Performance and the pages under a person.
  const onPerformance = pathname.startsWith('/app/performance')
  const underAccount = /^\/app\/clients\/[^/]+\/accounts\//.test(pathname)
  const phoneItems = work.filter((item) => item.phone)
  const moreItems = [...work.filter((item) => !item.phone), ...platform]
  const moreActive = moreItems.some((item) => pathname.startsWith(item.to))

  const person = (
    <div className="flex items-center justify-between gap-2">
      <p className="text-xs text-on-dark/80 truncate">
        {me?.name}
        {me && <span className="text-stone"> · {staffTitle(me.role)}</span>}
      </p>
      <ThemeToggle className="-mr-2 shrink-0" />
    </div>
  )

  return (
    <div className="min-h-screen bg-paper flex">
      {/* Sidebar (laptop) */}
      <aside className="hidden md:flex flex-col w-56 bg-chrome text-on-dark shrink-0 fixed top-0 left-0 h-full z-10">
        <div className="px-6 py-6 border-b border-on-dark/15">
          <NavLink to="/app" className="font-display text-lg text-on-dark tracking-tight no-underline hover:text-on-dark/80">Achalara</NavLink>
        </div>

        <nav aria-label="Main" className="flex-1 overflow-y-auto px-4 py-6 space-y-1">
          {work.map((item) => (
            <NavLink key={item.to} to={item.to} className={sideLink}>{item.label}</NavLink>
          ))}
          {platform.length > 0 && (
            <div className="pt-4 mt-4 border-t border-on-dark/15 space-y-1">
              <p className="text-xs text-stone px-3 mb-2 uppercase tracking-wide">Platform</p>
              {platform.map((item) => (
                <NavLink key={item.to} to={item.to} className={sideLink}>{item.label}</NavLink>
              ))}
            </div>
          )}
        </nav>

        <div className="px-4 py-4 border-t border-on-dark/15">
          <div className="px-3">
            {person}
            <button onClick={signOut} className="text-xs text-stone hover:text-on-dark underline underline-offset-2 mt-1">
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <div className="flex-1 min-w-0 md:ml-56 flex flex-col min-h-screen pb-[64px] md:pb-0">
        {/* Top bar: the wordmark on a phone; the scope's trail and the dates where they apply. */}
        {(onPerformance || underAccount) ? (
          <header className="sticky top-0 z-10 bg-paper/95 backdrop-blur border-b border-stone/20 px-16 md:px-6 py-3 flex flex-wrap items-center gap-x-16 gap-y-2">
            <Link to="/app" className="md:hidden font-display text-base text-summit-ink no-underline">Achalara</Link>
            <ScopeTrail />
            {onPerformance && <DateRangeBar />}
          </header>
        ) : (
          <header className="md:hidden sticky top-0 z-10 bg-paper/95 backdrop-blur border-b border-stone/20 px-16 py-3">
            <Link to="/app" className="font-display text-base text-summit-ink no-underline">Achalara</Link>
          </header>
        )}

        {/* Page content */}
        <main className="flex-1 px-16 md:px-6 py-8 min-w-0">
          <Outlet />
        </main>
      </div>

      {/* Phone: More, a sheet above the bottom bar with every other page, the person and Sign out. */}
      {moreOpen && (
        <div className="md:hidden fixed inset-0 z-20" onClick={() => setMoreOpen(false)}>
          <div className="absolute inset-0 bg-chrome/40" />
          <div
            id="staff-more"
            role="dialog"
            aria-label="More"
            onClick={(e) => e.stopPropagation()}
            className="absolute left-0 right-0 bottom-[56px] bg-chrome text-on-dark border-t border-on-dark/15 px-16 pt-16 pb-16 space-y-1 max-h-[70vh] overflow-y-auto"
          >
            {moreItems.map((item) => (
              <NavLink key={item.to} to={item.to} className={sideLink}>{item.label}</NavLink>
            ))}
            <div className="px-3 pt-3 mt-2 border-t border-on-dark/15">
              {person}
              <button onClick={signOut}
                className="mt-2 w-full h-11 border border-on-dark/30 rounded-btn text-sm text-on-dark hover:bg-pine/30">
                Sign out
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Phone: the bottom bar, three pages and More. */}
      <nav aria-label="Main" className="fixed bottom-0 left-0 right-0 md:hidden bg-chrome border-t border-on-dark/15 flex z-30 h-[56px]">
        {phoneItems.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex-1 flex items-center justify-center text-center text-xs transition-colors ${
                isActive && !moreOpen ? 'text-gold font-medium' : 'text-on-dark/60'
              }`
            }
          >
            {item.short ?? item.label}
          </NavLink>
        ))}
        <button
          type="button"
          onClick={() => setMoreOpen((open) => !open)}
          aria-expanded={moreOpen}
          aria-controls="staff-more"
          className={`flex-1 text-xs transition-colors ${moreOpen || moreActive ? 'text-gold font-medium' : 'text-on-dark/60'}`}
        >
          More
        </button>
      </nav>
    </div>
  )
}

/** Where the page stands: person, account, strategy. Each part opens its own page. */
function ScopeTrail() {
  const { scope } = useScope()
  const crumb = 'hover:text-pine no-underline'
  if (!scope.clientId && !scope.strategyId) {
    return <span className="flex-1 text-stone text-xs">Choose a person or a strategy</span>
  }
  return (
    <div className="flex-1 min-w-0 flex items-center gap-2 text-sm text-stone font-mono overflow-x-auto whitespace-nowrap">
      {scope.clientId && scope.clientName && (
        <Link to={`/app/clients/${scope.clientId}`} className={crumb}>{scope.clientName}</Link>
      )}
      {scope.clientId && scope.accountId && scope.accountName && (
        <>
          <span>/</span>
          <Link to={`/app/clients/${scope.clientId}/accounts/${scope.accountId}`} className={`text-summit-ink ${crumb}`}>
            {scope.accountName}
          </Link>
        </>
      )}
      {scope.sleeveName && (
        <>
          <span>/</span>
          <span className="text-summit-ink">{scope.sleeveName}</span>
        </>
      )}
      {scope.strategyName && <Link to="/app/strategies" className={`text-summit-ink ${crumb}`}>{scope.strategyName}</Link>}
    </div>
  )
}

/** The dates Performance reads. Shown only there. */
function DateRangeBar() {
  const { startDate, endDate, setDateRange } = useDateRange()
  const field = 'border border-stone/30 rounded-btn px-2 py-1 text-xs font-mono text-summit-ink bg-surface focus:outline-none focus:border-pine'
  return (
    <div className="flex items-center gap-2 shrink-0">
      <input type="date" aria-label="From" value={startDate ?? ''}
        onChange={(e) => setDateRange(e.target.value || undefined, endDate)} className={field} />
      <span className="text-stone text-xs">to</span>
      <input type="date" aria-label="To" value={endDate ?? ''}
        onChange={(e) => setDateRange(startDate, e.target.value || undefined)} className={field} />
      {(startDate || endDate) && (
        <button onClick={() => setDateRange(undefined, undefined)} className="text-stone hover:text-loss text-xs" title="Clear the dates">
          ✕
        </button>
      )}
    </div>
  )
}
