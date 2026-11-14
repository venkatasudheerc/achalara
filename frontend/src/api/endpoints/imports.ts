import { apiClient } from '../client'
import type { ImportPreview, ImportResult } from '../types'

/**
 * Where an upload goes. A client imports into an account they own through the
 * portal; the advisor imports into any client's account from its page.
 */
export type ImportDoor =
  | { kind: 'portal'; accountId: string; /** An advisor previewing this client */ asClient?: string }
  | { kind: 'advisor'; clientId: string; accountId: string }

const path = (door: ImportDoor) =>
  door.kind === 'portal'
    ? `/api/v1/portal/accounts/${door.accountId}/imports`
    : `/api/v1/clients/${door.clientId}/accounts/${door.accountId}/imports`

const form = (file: File) => {
  const body = new FormData()
  body.append('file', file)
  return body
}

const params = (door: ImportDoor) =>
  door.kind === 'portal' && door.asClient ? { as_client: door.asClient } : undefined

export const importsApi = {
  /** What the file would add. Nothing is written. */
  preview: (door: ImportDoor, file: File) =>
    apiClient.post<ImportPreview>(`${path(door)}/preview`, form(file), { params: params(door) }).then((r) => r.data),
  /** Add what is not on file, rebuild the account's history, check its holdings. */
  apply: (door: ImportDoor, file: File) =>
    apiClient.post<ImportResult>(path(door), form(file), { params: params(door) }).then((r) => r.data),
}
