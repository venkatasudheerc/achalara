import type { UserRole } from '@/api/types'

/**
 * Staff run the workspace at `/app`: an admin (the platform's super user, everything)
 * or an advisor (only the clients assigned to them). A client uses the new app.
 */
export function isStaff(role: UserRole | undefined): boolean {
  return role === 'admin' || role === 'advisor'
}

/** What a staff member is called on screen. */
export function staffTitle(role: UserRole | undefined): string {
  return role === 'admin' ? 'Admin' : 'Advisor'
}
