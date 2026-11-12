import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useLogout, useMe } from '@/hooks/useAuth'
import { usePortalAccounts, usePreviewClient } from '@/hooks/usePortal'
import { useOneAppLook, useTheme, type ThemeChoice } from '@/context/ThemeContext'

/** The places in the menu bar. The wordmark is the way home. */
const PLACES = [
  { to: '/home/plan', label: 'Plan' },
  { to: '/home/tax', label: 'Tax' },
  { to: '/home/research', label: 'Research' },
]

/** Keeps an advisor's `?as=` on every link, so the preview carries on. */
function useWithPreview() {
  const preview = usePreviewClient()
  return (to: string) => (preview ? `${to}${to.includes('?') ? '&' : '?'}as=${preview}` : to)
}

function Icon({ d }: { d: ReactNode }) {
  return (
    <svg aria-hidden="true" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{d}</svg>
  )
}
const ICONS = {
  home: <path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" />,
  plan: <><circle cx="12" cy="12" r="9" /><path d="M8.5 12.5l2.5 2.5 4.5-5" /></>,
  tax: <><path d="M7 3h7l4 4v14H7z" /><path d="M14 3v4h4" /><path d="M10 12h5M10 16h5" /></>,
  research: <><path d="M4 19h16" /><path d="M5 15l4-5 4 3 6-8" /></>,
  more: <path d="M4 7h16M4 12h16M4 17h16" />,
}

export function AppearanceChoice({ label = 'Appearance' }: { label?: string }) {
  const { choice, setChoice } = useTheme()
  const options: { value: ThemeChoice; label: string }[] = [
    { value: 'light', label: 'Light' }, { value: 'dark', label: 'Dark' }, { value: 'system', label: 'Auto' },
  ]
  return (
    <div className="flex flex-col gap-[8px]">
      <span id="appearance-label" className="text-[15px]">{label}</span>
      <div role="group" aria-labelledby="appearance-label" className="flex border border-stone/30 rounded-[24px] p-[3px] gap-[2px]">
        {options.map((o) => (
          <button key={o.value} type="button" aria-pressed={choice === o.value} onClick={() => setChoice(o.value)}
            className={`flex-1 h-[40px] px-[10px] rounded-[20px] text-[14px] ${
              choice === o.value ? 'bg-summit-ink text-paper font-semibold' : 'text-summit-ink/80 hover:bg-line'
            }`}>
            {o.label}
          </button>
        ))}
      </div>
      <span className="text-[13px] text-stone">Auto follows your device's own setting.</span>
    </div>
  )
}

/** The person menu's rows; on a phone the same list is the More page. */
function PersonMenu({ name, household, onSignOut }: { name: string; household: string; onSignOut: () => void }) {
  const { data: me } = useMe()
  const preview = usePreviewClient()
  const row = 'min-h-[44px] px-[12px] flex items-center rounded-[12px] text-[15px] text-summit-ink no-underline hover:bg-line'
  return (
    <>
      <div className="px-[12px] pt-[6px] pb-[10px] border-b border-line">
        <div className="font-display text-[17px]">{name}</div>
        <div className="text-[13px] text-stone">{household}</div>
      </div>
      <div className="px-[12px] py-[10px]"><AppearanceChoice /></div>
      {me?.role === 'advisor' && (
        <Link to={preview ? `/app/clients/${preview}` : '/app'} className={`${row} flex-col !items-start justify-center py-[6px] border-t border-line`}>
          <span>Manage</span>
          <span className="text-[13px] text-stone">Clients, strategies, imports, system status</span>
        </Link>
      )}
      <button type="button" onClick={onSignOut} className={`${row} w-full text-left`}>Sign out</button>
    </>
  )
}

/**
 * The new app's frame: a menu bar (the wordmark is home; Plan, Tax, Research),
 * the person menu with Appearance, and on a phone a bar of five at the foot.
 */
export function HomeShell() {
  useOneAppLook()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const withPreview = useWithPreview()
  const preview = usePreviewClient()
  const { data: me } = useMe()
  const { data: portal } = usePortalAccounts()
  const logout = useLogout()
  const signOut = () => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })
  const name = portal?.viewer.name ?? me?.name ?? ''
  const household = preview ? 'Viewed by your advisor' : me?.role === 'advisor' ? 'Advisor' : 'Your accounts'

  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  useEffect(() => setOpen(false), [pathname])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onClick = (e: MouseEvent) => { if (menu.current && !menu.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('keydown', onKey)
    document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [open])

  const atHome = pathname === '/home'
  const initial = (name.trim()[0] ?? '?').toUpperCase()

  return (
    <div className="min-h-screen bg-paper text-summit-ink font-sans text-[16px] flex flex-col">
      {preview && (
        <div className="bg-pine text-on-dark text-[14px]">
          <div className="px-[20px] md:px-[24px] py-[8px] flex flex-wrap items-center justify-between gap-3">
            <span>Advisor preview: this is what <strong>{name}</strong> sees.</span>
            <Link to={`/app/clients/${preview}`} className="underline underline-offset-2 font-medium text-on-dark">Back to the client</Link>
          </div>
        </div>
      )}
      <header className="border-b border-line shrink-0">
        <div className="px-[20px] md:px-[24px] min-h-[64px] flex items-center gap-[32px]">
          <Link to={withPreview('/home')} aria-label="achalara, home" aria-current={atHome ? 'page' : undefined}
            className="font-display text-[23px] text-pine no-underline">achalara</Link>
          <nav aria-label="Site" className="hidden md:flex gap-[26px] text-[15px]">
            {PLACES.map((p) => (
              <NavLink key={p.to} to={withPreview(p.to)}
                className={({ isActive }) => `py-[20px] no-underline border-b-[3px] ${
                  isActive ? 'border-pine text-summit-ink font-semibold' : 'border-transparent text-stone hover:text-summit-ink'
                }`}>
                {p.label}
              </NavLink>
            ))}
          </nav>
          <div ref={menu} className="ml-auto relative">
            <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-controls="person-menu"
              aria-label={`${name}: open menu`}
              className="h-[44px] px-[6px] flex items-center gap-[8px] border border-stone/30 rounded-[22px] bg-paper text-[14px] font-medium">
              <span className="w-[32px] h-[32px] rounded-full bg-accent-soft text-pine flex items-center justify-center font-bold">{initial}</span>
              <span className="hidden md:inline pr-[8px]">{name.split(' ')[0]}</span>
            </button>
            {open && (
              <div id="person-menu" className="absolute right-0 top-[54px] w-[320px] p-[12px] flex flex-col gap-[4px] bg-paper border border-stone/30 rounded-[18px] shadow-[0_16px_40px_rgba(0,0,0,0.18)] z-30">
                <PersonMenu name={name} household={household} onSignOut={signOut} />
              </div>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 flex flex-col pb-[68px] md:pb-0">
        <Outlet />
      </div>

      <nav aria-label="Site" className="md:hidden fixed bottom-0 inset-x-0 h-[68px] border-t border-line bg-paper grid grid-cols-5 z-20">
        {[
          { to: '/home', label: 'Home', icon: ICONS.home, end: true },
          { to: '/home/plan', label: 'Plan', icon: ICONS.plan },
          { to: '/home/tax', label: 'Tax', icon: ICONS.tax },
          { to: '/home/research', label: 'Research', icon: ICONS.research },
          { to: '/home/more', label: 'More', icon: ICONS.more },
        ].map((t) => (
          <NavLink key={t.to} to={withPreview(t.to)} end={t.end}
            className={({ isActive }) => `flex flex-col items-center justify-center gap-[4px] text-[11px] no-underline ${
              isActive ? 'text-pine font-bold' : 'text-stone font-medium'
            }`}>
            <Icon d={t.icon} />{t.label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

/** The phone's More page: the person menu as a page. */
export function MorePage() {
  const navigate = useNavigate()
  const preview = usePreviewClient()
  const { data: me } = useMe()
  const { data: portal } = usePortalAccounts()
  const logout = useLogout()
  const name = portal?.viewer.name ?? me?.name ?? ''
  return (
    <main className="px-[20px] py-[24px] flex flex-col gap-[16px] max-w-[520px] w-full mx-auto">
      <div className="border border-line rounded-[18px] p-[12px] flex flex-col gap-[4px]">
        <PersonMenu name={name} household={preview ? 'Viewed by your advisor' : 'Your accounts'}
          onSignOut={() => logout.mutate(undefined, { onSettled: () => navigate('/login', { replace: true }) })} />
      </div>
    </main>
  )
}
