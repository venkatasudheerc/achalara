import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from '@/components/AppShell'
import { HomePage } from '@/features/HomePage'
import { PerformancePage } from '@/features/performance/PerformancePage'
import { ClientsPage } from '@/features/clients/ClientsPage'
import { ClientDetailPage } from '@/features/clients/ClientDetailPage'
import { AccountDetailPage } from '@/features/accounts/AccountDetailPage'
import { SleeveDetailPage } from '@/features/sleeves/SleeveDetailPage'
import { StrategiesPage } from '@/features/strategies/StrategiesPage'
import { ImportsPage } from '@/features/imports/ImportsPage'
import { SettingsPage } from '@/features/SettingsPage'
import { StatusPage } from '@/features/status/StatusPage'
import { PortfolioPage } from '@/features/PortfolioPage'
import { RiskPage } from '@/features/RiskPage'
import { GrowPage } from '@/features/GrowPage'
import { LoginPage } from '@/features/auth/LoginPage'
import { AcceptLinkPage } from '@/features/auth/AcceptLinkPage'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { PortalShell } from '@/features/portal/PortalShell'
import { PortalHomePage } from '@/features/portal/PortalHomePage'
import { PortalHoldingsPage } from '@/features/portal/PortalHoldingsPage'
import { PortalActivityPage } from '@/features/portal/PortalActivityPage'
import { PortalRealizedPage } from '@/features/portal/PortalRealizedPage'
import { PortalPerformancePage } from '@/features/portal/PortalPerformancePage'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/invite/:token" element={<AcceptLinkPage />} />
      <Route path="/reset/:token" element={<AcceptLinkPage />} />
      <Route element={<RequireAuth role="advisor" />}>
        <Route path="/app" element={<AppShell />}>
          <Route index element={<Navigate to="performance" replace />} />
          <Route path="performance" element={<PerformancePage />} />
          <Route path="clients" element={<ClientsPage />} />
          <Route path="clients/:clientId" element={<ClientDetailPage />} />
          <Route path="clients/:clientId/accounts/:accountId" element={<AccountDetailPage />} />
          <Route path="clients/:clientId/accounts/:accountId/sleeves/:sleeveId" element={<SleeveDetailPage />} />
          <Route path="strategies" element={<StrategiesPage />} />
          <Route path="imports" element={<ImportsPage />} />
          <Route path="status" element={<StatusPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="portfolio" element={<PortfolioPage />} />
          <Route path="risk" element={<RiskPage />} />
          <Route path="grow" element={<GrowPage />} />
        </Route>
      </Route>
      <Route element={<RequireAuth role="client" />}>
        <Route path="/portal" element={<PortalShell />}>
          <Route index element={<PortalHomePage />} />
          <Route path="holdings" element={<PortalHoldingsPage />} />
          <Route path="activity" element={<PortalActivityPage />} />
          <Route path="realized" element={<PortalRealizedPage />} />
          <Route path="performance" element={<PortalPerformancePage />} />
        </Route>
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
