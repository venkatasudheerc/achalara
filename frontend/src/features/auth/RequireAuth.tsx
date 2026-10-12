import { Navigate, Outlet } from 'react-router-dom'
import { useMe } from '@/hooks/useAuth'
import type { UserRole } from '@/api/types'

/** Where each role lands after signing in. */
export function homeFor(role: UserRole): string {
  return role === 'advisor' ? '/app' : '/portal'
}

/** Renders its routes only for a signed-in user of the given role. */
export function RequireAuth({ role }: { role: UserRole }) {
  const { data: me, isLoading } = useMe()

  if (isLoading) {
    return <div className="min-h-screen bg-paper flex items-center justify-center text-stone text-sm">Loading…</div>
  }
  if (!me) return <Navigate to="/login" replace />
  if (me.role !== role) return <Navigate to={homeFor(me.role)} replace />
  return <Outlet />
}
