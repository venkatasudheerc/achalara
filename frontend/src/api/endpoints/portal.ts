import { apiClient } from '../client'
import type {
  PortalAccountsResponse, PortalGrain, PortalHomeResponse, PortalOverviewResponse, PortalPerformanceResponse,
  PortalActivityResponse, PortalPositionsResponse, PortalRealizedResponse, PortalTradesResponse, SecurityGroup,
  AccountGroup, LinkResponse, Relative, RelativeCreate,
} from '../types'

const base = '/api/v1/portal'

/** Filters shared by the portal's lists. `as_client` is an advisor previewing a client. */
export interface PortalScope {
  as_client?: string
  /** A set of accounts in view; empty or left out means every account */
  account_ids?: string[]
  account_id?: string
  strategy_id?: string
}
export interface PositionFilters extends PortalScope { type?: SecurityGroup; q?: string }
export interface TradeFilters extends PositionFilters {
  start_date?: string; end_date?: string; action?: 'buy' | 'sell'
  skip?: number; limit?: number
}
export type ActivityShow = 'all' | 'trades' | 'money' | 'income' | 'charges'
export interface ActivityFilters extends TradeFilters { show?: ActivityShow }
export interface RealizedFilters extends PositionFilters {
  start_date?: string; end_date?: string; term?: 'short' | 'long'; result?: 'gain' | 'loss'
  /** How the period breakdown is cut */
  grain?: 'month' | 'quarter'
}
export interface PerformanceFilters extends PortalScope {
  start_date?: string; end_date?: string; grain?: PortalGrain
  /** A code from the response's `benchmarks` */
  benchmark?: string
}

/** Drops empty values so they are not sent as blank parameters. */
function clean<T extends object>(params: T): Partial<T> {
  return Object.fromEntries(
    Object.entries(params).filter(
      ([, v]) => v !== undefined && v !== '' && v !== null && !(Array.isArray(v) && v.length === 0),
    ),
  ) as Partial<T>
}

export const portalApi = {
  accounts: (asClient?: string) =>
    apiClient
      .get<PortalAccountsResponse>(`${base}/accounts`, { params: clean({ as_client: asClient }) })
      .then((r) => r.data),

  home: (params: PortalScope) =>
    apiClient.get<PortalHomeResponse>(`${base}/home`, { params: clean(params) }).then((r) => r.data),

  overview: (params: PortalScope) =>
    apiClient.get<PortalOverviewResponse>(`${base}/overview`, { params: clean(params) }).then((r) => r.data),

  positions: (params: PositionFilters) =>
    apiClient.get<PortalPositionsResponse>(`${base}/positions`, { params: clean(params) }).then((r) => r.data),

  trades: (params: TradeFilters) =>
    apiClient.get<PortalTradesResponse>(`${base}/trades`, { params: clean(params) }).then((r) => r.data),

  activity: (params: ActivityFilters) =>
    apiClient.get<PortalActivityResponse>(`${base}/activity`, { params: clean(params) }).then((r) => r.data),

  realized: (params: RealizedFilters) =>
    apiClient.get<PortalRealizedResponse>(`${base}/realized`, { params: clean(params) }).then((r) => r.data),

  performance: (params: PerformanceFilters) =>
    apiClient
      .get<PortalPerformanceResponse>(`${base}/performance`, { params: clean(params) })
      .then((r) => r.data),

  groups: (asClient?: string) =>
    apiClient
      .get<{ groups: AccountGroup[] }>(`${base}/groups`, { params: clean({ as_client: asClient }) })
      .then((r) => r.data.groups),
  createGroup: (name: string, accountIds: string[] = [], asClient?: string) =>
    apiClient.post<AccountGroup>(`${base}/groups`, { name, account_ids: accountIds },
      { params: clean({ as_client: asClient }) }).then((r) => r.data),
  updateGroup: (id: string, body: { name?: string; position?: number }, asClient?: string) =>
    apiClient.patch<AccountGroup>(`${base}/groups/${id}`, body,
      { params: clean({ as_client: asClient }) }).then((r) => r.data),
  setGroupAccounts: (id: string, accountIds: string[], asClient?: string) =>
    apiClient.put<AccountGroup>(`${base}/groups/${id}/accounts`, { account_ids: accountIds },
      { params: clean({ as_client: asClient }) }).then((r) => r.data),
  deleteGroup: (id: string, asClient?: string) =>
    apiClient.delete(`${base}/groups/${id}`, { params: clean({ as_client: asClient }) }).then(() => undefined),

  /** Keeps one of the viewer's own accounts from their spouse, or stops keeping it. */
  setAccountPrivate: (accountId: string, isPrivate: boolean, asClient?: string) =>
    apiClient
      .patch<{ is_private: boolean }>(`${base}/accounts/${accountId}`, { is_private: isPrivate },
        { params: clean({ as_client: asClient }) })
      .then((r) => r.data),

  /** The viewer's spouse first, then their minors. */
  relatives: (asClient?: string) =>
    apiClient.get<Relative[]>(`${base}/relatives`, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  addRelative: (body: RelativeCreate, asClient?: string) =>
    apiClient
      .post<Relative>(`${base}/relatives`, body, { params: clean({ as_client: asClient }) })
      .then((r) => r.data),
  /** A one-time sign-in link for the viewer's spouse or minor; `email` is their own when left out. */
  inviteRelative: (relativeId: string, email?: string, asClient?: string) =>
    apiClient
      .post<LinkResponse>(`${base}/relatives/${relativeId}/invite`, { email: email || null },
        { params: clean({ as_client: asClient }) })
      .then((r) => r.data),

  /** A link that downloads what the filters match as CSV (the session cookie rides along). */
  csvUrl: (list: 'positions' | 'trades' | 'activity' | 'realized', params: object) =>
    apiClient.getUri({ url: `${base}/${list}`, params: { ...clean(params), format: 'csv' } }),
}
