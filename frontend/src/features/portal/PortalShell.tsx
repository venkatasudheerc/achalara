import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useLogout, useMe } from '@/hooks/useAuth'
import { usePortalAccounts, usePreviewClient } from '@/hooks/usePortal'
import { ThemeToggle } from '@/components/ThemeToggle'

const NAV = [
  { to: '/portal', label: 'Home', end: true },
  { to: '/portal/holdings', label: 'Holdings' },
  { to: '/portal/activity', label: 'Activity' },
  { to: '/portal/realized', label: 'Realised gains' },
  { to: '/portal/performance', label: 'Performance' },
]

/** The client portal's frame: a slim bar with the menu behind one button, and the page at full width. */
export function PortalShell() {
  const navigate = useNavigate()
  const { pathname, search } = useLocation()
  const { data: me } = useMe()
  const { data: portal } = usePortalAccounts()
  const preview = usePreviewClient()
  const logout = useLogout()
  const signOut = () => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })
  const name = portal?.viewer.name ?? me?.name ?? ''

  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  // The menu closes when a page is chosen, on Escape, and on a click elsewhere.
  useEffect(() => setOpen(false), [pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onClick = (e: MouseEvent) => {
      if (menu.current && !menu.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  return (
    <div className="min-h-screen bg-paper text-summit-ink font-sans text-[17px]">
      {preview && (
        <div className="bg-gold text-on-gold text-[15px]">
          <div className="px-[20px] md:px-[40px] py-2 flex flex-wrap items-center justify-between gap-3">
            <span>Advisor preview: this is the portal as <strong>{name}</strong> sees it.</span>
            <NavLink to={`/app/clients/${preview}`} className="underline underline-offset-2 font-medium">
              Back to the client
            </NavLink>
          </div>
        </div>
      )}
      <header className="bg-chrome text-on-dark">
        <div className="px-[20px] md:px-[40px] py-[12px] flex flex-wrap items-center gap-[16px]">
          <div ref={menu} className="relative">
            <button type="button" aria-label="Menu" aria-expanded={open} aria-controls="portal-menu"
              onClick={() => setOpen(!open)}
              className="flex items-center justify-center w-[48px] h-[48px] rounded-btn border border-on-dark/30 text-on-dark hover:border-on-dark/60 transition-colors">
              <svg aria-hidden width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="4" y1="7" x2="20" y2="7" /><line x1="4" y1="12" x2="20" y2="12" /><line x1="4" y1="17" x2="20" y2="17" />
              </svg>
            </button>
            {open && (
              <nav id="portal-menu" aria-label="Main"
                className="absolute left-0 top-[60px] z-20 w-[264px] p-[12px] rounded-card bg-chrome border border-on-dark/15 shadow-[0_16px_36px_rgba(0,0,0,0.28)] flex flex-col gap-[4px]">
                {NAV.map((item) => (
                  // The query string carries an advisor's preview from page to page.
                  <NavLink key={item.to} to={{ pathname: item.to, search }} end={item.end}
                    className={({ isActive }) =>
                      `px-[14px] py-[13px] rounded-btn no-underline ${
                        isActive ? 'bg-pine text-on-dark font-semibold' : 'text-on-dark/80 hover:text-on-dark hover:bg-on-dark/10'
                      }`}>
                    {item.label}
                  </NavLink>
                ))}
              </nav>
            )}
          </div>
          <span className="font-display text-[26px] font-medium">Achalara</span>
          <div className="ml-auto flex items-center gap-[12px]">
            <ThemeToggle />
            <div className="text-right text-[16px] leading-tight">
              <div>{name}</div>
              <button onClick={signOut} className="text-on-dark/80 underline underline-offset-2 hover:text-on-dark">
                Sign out
              </button>
            </div>
          </div>
        </div>
      </header>
      <main className="px-[20px] md:px-[40px] pt-[36px] pb-[64px] flex flex-col gap-[24px]">
        <Outlet />
      </main>
    </div>
  )
}
