import { Suspense, lazy, type ComponentType } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { SkeletonCard } from '@/components/Skeleton'
import { LoginPage } from '@/features/auth/LoginPage'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { HomeShell, MorePage } from '@/features/home/HomeShell'
import { PlanPage, TaxPage } from '@/features/home/ComingSoonPage'

/**
 * A page fetched when it is first opened, so signing in does not download every
 * page of both apps. The frame (sign-in, the two shells) stays in the first
 * file; while a page arrives its place shows a skeleton inside the frame.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- any page's own props
function page<P extends Record<string, any>>(load: () => Promise<ComponentType<P>>) {
  const Loaded = lazy(() => load().then((component) => ({ default: component }))) as unknown as ComponentType<P>
  return function Page(props: P) {
    return (
      <Suspense fallback={<div className="p-[24px] grid gap-[20px]"><SkeletonCard /><SkeletonCard /></div>}>
        <Loaded {...props} />
      </Suspense>
    )
  }
}

const PerformancePage = page(() => import('@/features/performance/PerformancePage').then((m) => m.PerformancePage))
const ClientsPage = page(() => import('@/features/clients/ClientsPage').then((m) => m.ClientsPage))
const ClientDetailPage = page(() => import('@/features/clients/ClientDetailPage').then((m) => m.ClientDetailPage))
const AccountDetailPage = page(() => import('@/features/accounts/AccountDetailPage').then((m) => m.AccountDetailPage))
const SleeveDetailPage = page(() => import('@/features/sleeves/SleeveDetailPage').then((m) => m.SleeveDetailPage))
const StrategiesPage = page(() => import('@/features/strategies/StrategiesPage').then((m) => m.StrategiesPage))
const SettingsPage = page(() => import('@/features/SettingsPage').then((m) => m.SettingsPage))
const StatusPage = page(() => import('@/features/status/StatusPage').then((m) => m.StatusPage))
const MarketDataPage = page(() => import('@/features/marketdata/MarketDataPage').then((m) => m.MarketDataPage))
const ResearchPage = page(() => import('@/features/research/ResearchPage').then((m) => m.ResearchPage))
const RequestsPage = page(() => import('@/features/invitations/RequestsPage').then((m) => m.RequestsPage))
const HomePage = page(() => import('@/features/HomePage').then((m) => m.HomePage))
const RequestInvitationPage = page(() => import('@/features/invitations/RequestInvitationPage').then((m) => m.RequestInvitationPage))
const ConfirmInvitationPage = page(() => import('@/features/invitations/ConfirmInvitationPage').then((m) => m.ConfirmInvitationPage))
const AcceptLinkPage = page(() => import('@/features/auth/AcceptLinkPage').then((m) => m.AcceptLinkPage))
const LandingPage = page(() => import('@/features/home/LandingPage').then((m) => m.LandingPage))
const AccessPage = page(() => import('@/features/home/AccessPage').then((m) => m.AccessPage))
const ConnectionsPage = page(() => import('@/features/home/ConnectionsPage').then((m) => m.ConnectionsPage))

/** Where each of the old portal's pages now lives in the new app. */
const OLD_PORTAL: Record<string, string> = {
  '': '/home', holdings: '/home?view=holdings', activity: '/home?view=transactions',
  realized: '/home?view=cost-basis', performance: '/home?view=performance',
  markets: '/home/research', research: '/home/research',
}

/** An old `/portal/...` address: the same page in the new app, keeping a staff preview's `?as=`. */
function OldPortalRedirect() {
  const { pathname, search } = useLocation()
  const page = pathname.replace(/^\/portal\/?/, '').split('/')[0]
  const to = OLD_PORTAL[page] ?? '/home'
  const as = new URLSearchParams(search).get('as')
  return <Navigate to={as ? `${to}${to.includes('?') ? '&' : '?'}as=${as}` : to} replace />
}

/** Research (Market patterns, as built) inside the new app's frame. */
function HomeResearch() {
  return (
    <main className="w-full px-[20px] md:px-[40px] pt-[32px] pb-[64px]">
      <ResearchPage />
    </main>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      {/* No public front page: the way in is sign-in, or a request for an invitation. */}
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/request-invitation" element={<RequestInvitationPage />} />
      {/* The old marketing page, kept at an address nothing links to. */}
      <Route path="/about" element={<HomePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite/:token" element={<AcceptLinkPage />} />
      <Route path="/reset/:token" element={<AcceptLinkPage />} />
      <Route path="/request-invitation/confirm/:token" element={<ConfirmInvitationPage />} />
      {/* The workspace: an admin sees everything, an advisor their own clients. */}
      <Route element={<RequireAuth role="staff" />}>
        <Route path="/app" element={<AppShell />}>
          {/* Staff start where the work starts: the list of people they look after. */}
          <Route index element={<Navigate to="clients" replace />} />
          <Route path="performance" element={<PerformancePage />} />
          <Route path="clients" element={<ClientsPage />} />
          <Route path="clients/:clientId" element={<ClientDetailPage />} />
          <Route path="clients/:clientId/accounts/:accountId" element={<AccountDetailPage />} />
          <Route path="clients/:clientId/accounts/:accountId/sleeves/:sleeveId" element={<SleeveDetailPage />} />
          <Route path="strategies" element={<StrategiesPage />} />
          <Route path="markets" element={<ResearchPage forAdvisor />} />
          <Route path="research" element={<Navigate to="/app/markets" replace />} />
          {/* The Imports page is retired: files go through each account's "Update from a file". */}
          <Route path="imports" element={<Navigate to="/app" replace />} />
          {/* The platform's own pages: the admin's alone (the API refuses them to an advisor). */}
          <Route element={<RequireAuth role="admin" />}>
            <Route path="requests" element={<RequestsPage />} />
            <Route path="status" element={<StatusPage />} />
            <Route path="market-data" element={<MarketDataPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          {/* Retired "coming soon" pages: their old addresses open the workspace. */}
          <Route path="portfolio" element={<Navigate to="/app" replace />} />
          <Route path="risk" element={<Navigate to="/app" replace />} />
          <Route path="grow" element={<Navigate to="/app" replace />} />
        </Route>
      </Route>
      <Route element={<RequireAuth role="client" />}>
        <Route path="/home" element={<HomeShell />}>
          <Route index element={<LandingPage />} />
          <Route path="plan" element={<PlanPage />} />
          <Route path="tax" element={<TaxPage />} />
          <Route path="research" element={<HomeResearch />} />
          <Route path="access" element={<AccessPage />} />
          <Route path="people" element={<Navigate to="/home/access" replace />} />
          <Route path="family" element={<Navigate to="/home/access" replace />} />
          <Route path="connections" element={<ConnectionsPage />} />
          <Route path="more" element={<MorePage />} />
        </Route>
        {/* The old portal's addresses, kept for bookmarks: each opens the matching place in the new app. */}
        <Route path="/portal/*" element={<OldPortalRedirect />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
