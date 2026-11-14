import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { PerformancePage } from '@/features/performance/PerformancePage'
import { ClientsPage } from '@/features/clients/ClientsPage'
import { ClientDetailPage } from '@/features/clients/ClientDetailPage'
import { AccountDetailPage } from '@/features/accounts/AccountDetailPage'
import { SleeveDetailPage } from '@/features/sleeves/SleeveDetailPage'
import { StrategiesPage } from '@/features/strategies/StrategiesPage'
import { ImportsPage } from '@/features/imports/ImportsPage'
import { SettingsPage } from '@/features/SettingsPage'
import { StatusPage } from '@/features/status/StatusPage'
import { MarketDataPage } from '@/features/marketdata/MarketDataPage'
import { ResearchPage } from '@/features/research/ResearchPage'
import { RequestsPage } from '@/features/invitations/RequestsPage'
import { HomePage } from '@/features/HomePage'
import { RequestInvitationPage } from '@/features/invitations/RequestInvitationPage'
import { ConfirmInvitationPage } from '@/features/invitations/ConfirmInvitationPage'
import { PortfolioPage } from '@/features/PortfolioPage'
import { RiskPage } from '@/features/RiskPage'
import { GrowPage } from '@/features/GrowPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { AcceptLinkPage } from '@/features/auth/AcceptLinkPage'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { HomeShell, MorePage } from '@/features/home/HomeShell'
import { LandingPage } from '@/features/home/LandingPage'
import { PlanPage, TaxPage } from '@/features/home/ComingSoonPage'
import { FamilyPage } from '@/features/home/FamilyPage'

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
          <Route index element={<Navigate to="performance" replace />} />
          <Route path="performance" element={<PerformancePage />} />
          <Route path="clients" element={<ClientsPage />} />
          <Route path="clients/:clientId" element={<ClientDetailPage />} />
          <Route path="clients/:clientId/accounts/:accountId" element={<AccountDetailPage />} />
          <Route path="clients/:clientId/accounts/:accountId/sleeves/:sleeveId" element={<SleeveDetailPage />} />
          <Route path="strategies" element={<StrategiesPage />} />
          <Route path="markets" element={<ResearchPage forAdvisor />} />
          <Route path="research" element={<Navigate to="/app/markets" replace />} />
          {/* The platform's own pages: the admin's alone (the API refuses them to an advisor). */}
          <Route element={<RequireAuth role="admin" />}>
            <Route path="imports" element={<ImportsPage />} />
            <Route path="requests" element={<RequestsPage />} />
            <Route path="status" element={<StatusPage />} />
            <Route path="market-data" element={<MarketDataPage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="risk" element={<RiskPage />} />
          <Route path="grow" element={<GrowPage />} />
        </Route>
      </Route>
      <Route element={<RequireAuth role="client" />}>
        <Route path="/home" element={<HomeShell />}>
          <Route index element={<LandingPage />} />
          <Route path="plan" element={<PlanPage />} />
          <Route path="tax" element={<TaxPage />} />
          <Route path="research" element={<HomeResearch />} />
          <Route path="family" element={<FamilyPage />} />
          <Route path="more" element={<MorePage />} />
        </Route>
        {/* The old portal's addresses, kept for bookmarks: each opens the matching place in the new app. */}
        <Route path="/portal/*" element={<OldPortalRedirect />} />
      </Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}
