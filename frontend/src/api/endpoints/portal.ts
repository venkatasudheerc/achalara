import { apiClient } from '../client'
import type {
  AccountSharing,
  PeopleResponse,
  PortalAccountsResponse, PortalGrain, PortalHomeResponse, PortalOverviewResponse, PortalPerformanceResponse,
  PortalActivityResponse, PortalPositionsResponse, PortalRealizedResponse, PortalTradesResponse, SecurityGroup,
  AccountGroup, LinkResponse, Relative, RelativeCreate, PortalAccountSettings, PortalConnectionsResponse, InsightsResponse,
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

  /** The viewer's own Plaid logins, and others' that feed an account in view (read-only). */
  connections: (asClient?: string) =>
    apiClient
      .get<PortalConnectionsResponse>(`${base}/connections`, { params: clean({ as_client: asClient }) })
      .then((r) => r.data),

  /** What is worth a look: next best actions and insights for the accounts in view. */
  insights: (params: PortalScope) =>
    apiClient.get<InsightsResponse>(`${base}/insights`, { params: clean(params) }).then((r) => r.data),

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

  /** Gives one of the viewer's own accounts a name of their own; empty clears it. */
  renameAccount: (accountId: string, displayName: string, asClient?: string) =>
    apiClient
      .patch<PortalAccountSettings>(`${base}/accounts/${accountId}`, { display_name: displayName },
        { params: clean({ as_client: asClient }) })
      .then((r) => r.data),

  people: (asClient?: string) =>
    apiClient.get<PeopleResponse>(`${base}/people`, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  dismissNotice: (asClient?: string) =>
    apiClient.post(`${base}/people/notice/dismiss`, null, { params: clean({ as_client: asClient }) }).then(() => undefined),
  makePrivate: (asClient?: string) =>
    apiClient.post(`${base}/people/make-private`, null, { params: clean({ as_client: asClient }) }).then(() => undefined),
  sharing: (accountId: string, asClient?: string) =>
    apiClient.get<AccountSharing>(`${base}/accounts/${accountId}/sharing`, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  share: (accountId: string, who: { personId?: string; advisor?: boolean }, asClient?: string) =>
    apiClient.post<AccountSharing>(`${base}/accounts/${accountId}/shares`,
      { person_id: who.personId ?? null, advisor: !!who.advisor }, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  unshare: (accountId: string, who: { personId?: string; advisor?: boolean }, asClient?: string) =>
    apiClient.delete<AccountSharing>(`${base}/accounts/${accountId}/shares`,
      { params: clean({ as_client: asClient, person_id: who.personId, advisor: who.advisor || undefined }) }).then((r) => r.data),
  setOwners: (accountId: string, ownerIds: string[], keepView: boolean, asClient?: string) =>
    apiClient.put<AccountSharing>(`${base}/accounts/${accountId}/owners`,
      { owner_ids: ownerIds, keep_view: keepView }, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  holdFor: (accountId: string, minorId: string | null, asClient?: string) =>
    apiClient.put<AccountSharing>(`${base}/accounts/${accountId}/held-for`,
      { minor_id: minorId }, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  handOver: (accountId: string, keepView: boolean, asClient?: string) =>
    apiClient.post<AccountSharing>(`${base}/accounts/${accountId}/hand-over`,
      { keep_view: keepView }, { params: clean({ as_client: asClient }) }).then((r) => r.data),
  stopSeeing: (accountId: string, asClient?: string) =>
    apiClient.delete(`${base}/accounts/${accountId}/shared-with-me`, { params: clean({ as_client: asClient }) }).then(() => undefined),

  /** The people the viewer added: spouse, minors, then anyone else. */
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
