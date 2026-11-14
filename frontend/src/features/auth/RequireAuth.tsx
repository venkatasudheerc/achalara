import { Navigate, Outlet, useSearchParams } from 'react-router-dom'
import { useMe } from '@/hooks/useAuth'
import { isStaff } from '@/lib/roles'
import type { UserRole } from '@/api/types'

/** Where each role lands after signing in: staff in the workspace, a client in the new app. */
export function homeFor(role: UserRole): string {
  return isStaff(role) ? '/app' : '/home'
}

/**
 * Who may open a set of routes: `staff` (an admin or an advisor: the workspace),
 * `admin` alone (the platform's own pages), or `client` (the new app).
 */
export type Audience = 'staff' | 'admin' | 'client'

function admits(audience: Audience, role: UserRole): boolean {
  if (audience === 'staff') return isStaff(role)
  return role === audience
}

/**
 * Renders its routes only for a signed-in user the audience admits. An admin or
 * advisor may also open the client routes when previewing a client
 * (`?as=<clientId>`); the API decides which clients that preview may read.
 */
export function RequireAuth({ role }: { role: Audience }) {
  const { data: me, isLoading } = useMe()
  const [params] = useSearchParams()

  if (isLoading) {
    return <div className="min-h-screen bg-paper flex items-center justify-center text-stone text-sm">Loading…</div>
  }
  if (!me) return <Navigate to="/login" replace />
  const previewing = role === 'client' && isStaff(me.role) && params.has('as')
  if (!admits(role, me.role) && !previewing) return <Navigate to={homeFor(me.role)} replace />
  return <Outlet />
}
