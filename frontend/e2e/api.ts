/**
 * The API as the tests answer it. Nothing here reaches a backend: each test
 * says what the server would return, in the shapes generated from
 * `openapi.yaml`, so an answer that no longer fits the contract fails the
 * type-check (`npm run build`) before it misleads a test.
 *
 * Every name, account and figure is invented.
 */
import { test as base, expect, type Page, type Route } from '@playwright/test'
import type {
  HoldingsCheck, ImportPreview, ImportResult, MeResponse, PeopleResponse, PlaidLinkAvailability,
  InsightFinding, InsightsResponse, PortalAccount, PortalAccountsResponse, PortalConnectionsResponse, PortalPerformanceResponse,
} from '../src/api/types'

/** What the server would return, or a function that works it out (or answers the route itself). */
type Answer = object | ((route: Route) => unknown)

/** One answer per `METHOD /path` (the query is ignored). */
export class Api {
  private answers = new Map<string, Answer>()
  /** Calls made, as `METHOD /path?query`, in order */
  readonly calls: string[] = []
  /** Calls no test answered: a screen asked for something the test did not expect */
  readonly unanswered: string[] = []

  constructor(private page: Page) {}

  on(call: string, answer: Answer) {
    this.answers.set(call, answer)
    return this
  }

  /** How many times a call was made */
  count(call: string) {
    return this.calls.filter((c) => c.split('?')[0] === call).length
  }

  async start() {
    await this.page.route('**/api/v1/**', async (route) => {
      const url = new URL(route.request().url())
      const call = `${route.request().method()} ${url.pathname}`
      this.calls.push(call + url.search)
      if (!this.answers.has(call)) {
        this.unanswered.push(call)
        return route.fulfill({ status: 500, json: { detail: `The test gave no answer for ${call}` } })
      }
      const answer = this.answers.get(call)
      const body = typeof answer === 'function' ? await answer(route) : answer
      // A handler that answered the route itself returns nothing.
      if (body === undefined) return
      return route.fulfill({ json: body })
    })
  }
}

export const test = base.extend<{ api: Api }>({
  api: async ({ page }, use) => {
    const api = new Api(page)
    await api.start()
    await use(api)
    expect(api.unanswered, 'every API call a screen makes is one the test expected').toEqual([])
  },
})
export { expect }

// ── Invented answers ──

export const ME: MeResponse = {
  id: 'user-1', email: 'pat@example.com', name: 'Pat Example', role: 'client', client_id: 'client-1', accounts: [],
}

export function account(over: Partial<PortalAccount> & Pick<PortalAccount, 'id' | 'name'>): PortalAccount {
  return {
    client_id: 'client-1', number_last4: '1234', shared: false, owner_name: 'Pat Example',
    kind: 'taxable', owed: false, institution: 'Example Brokerage',
    needs_sign_in: false, login_id: null, health: { state: 'complete', reasons: [], download_from: null },
    value: 0, priced_at: '2026-03-02T15:30:00Z', recorded_value: 0, cash: 0, as_of: '2026-02-27',
    source: 'plaid', synced_at: '2026-03-02T11:30:00Z', sleeves: [],
    owners: [{ id: 'client-1', name: 'Pat Example' }], held_for: null, display_name: null, card: null,
    ...over,
  }
}

export const BROKERAGE = account({ id: 'acct-brokerage', name: 'Individual Brokerage Account', number_last4: '4321', value: 150000, recorded_value: 149000, cash: 5000 })
export const CHECKING = account({ id: 'acct-checking', name: 'Everyday Checking', number_last4: '8765', kind: 'checking', institution: 'Example Bank', value: 12000.5, recorded_value: 12000.5, cash: 12000.5 })

export function accounts(list: PortalAccount[]): PortalAccountsResponse {
  return { viewer: { client_id: 'client-1', name: 'Pat Example', preview: false, is_minor: false, not_shared_with_you: 0 }, accounts: list }
}

export const NO_CONNECTIONS: PortalConnectionsResponse = { connections: [], needs_sign_in: 0 }
export const NO_INSIGHTS: InsightsResponse = { nudges: [], insights: [] }

/** A finding with only what a test cares about; the rest as the server fills it. */
export function finding(over: Partial<InsightFinding> & Pick<InsightFinding, 'key' | 'title'>): InsightFinding {
  return {
    rule: 'test_rule', tier: 'nudge', rank: 50, chip: { tone: 'cash', label: 'Cash' }, detail: '', must: false,
    when: null, foot: null, visual: null, action: null, wide: false, account_ids: [], link: null,
    ...over,
  }
}

export const CAN_LINK: PlaidLinkAvailability = { available: true, logins_left: 6 }

/** A record with nothing over time to draw: the Dashboard still gives its headline. */
export const NO_HISTORY: PortalPerformanceResponse = {
  first_date: null, as_of: null, includes_cash: true, benchmark: 'SPY', grain: 'month',
  benchmarks: [{ code: 'SPY', name: 'S&P 500 (SPY)', includes_dividends: true }],
  summary: null, series: [], months: [], years: [], periods: [],
}

export function people(over: Partial<PeopleResponse> = {}): PeopleResponse {
  return {
    people: [{
      id: 'client-2', name: 'Sam Example', relation: 'spouse', group: 'family', has_login: true, is_minor: false,
      you_share: 0, shares_with_you: 0, own_together: 0, you_hold_for: 0,
    }],
    advisor: null, notice: false,
    your_accounts: [
      { id: BROKERAGE.id, name: BROKERAGE.name, owners: ['Pat Example'], owner_ids: ['client-1'], seen_by: [], seen_by_ids: [], advisor_sees: false },
      { id: CHECKING.id, name: CHECKING.name, owners: ['Pat Example'], owner_ids: ['client-1'], seen_by: [], seen_by_ids: [], advisor_sees: false },
    ],
    shared_with_you: [],
    ...over,
  }
}

export const HOLDINGS_DIFFER: HoldingsCheck = {
  as_of: '2026-02-27', matched: 4,
  differences: [{ symbol: 'ZZZT', custodian_quantity: 10, our_quantity: 0 }],
  last_agreed: '2026-01-15', first_differed: '2026-01-16', download_from: '2026-01-15',
}

export const PREVIEW: ImportPreview = {
  account_id: BROKERAGE.id, file_kind: 'template', rows: 2, first_date: '2026-01-20', last_date: '2026-01-21',
  complete_through: null, history_starts: '2025-06-02',
  on_file_trades: 0, on_file_cash: 0, on_file_a_day_later: 0, on_file_other_symbol: 0, set_aside: {},
  to_add_trades: 1, to_add_cash: 1,
  days: [
    { date: '2026-01-20', trades: [{ action: 'BUY', symbol: 'ZZZT', quantity: 10, price: 25 }], cash: [] },
    { date: '2026-01-21', trades: [], cash: [{ type: 'DIVIDEND', symbol: 'ZZZT', amount: 3.5 }] },
  ],
  not_read: [],
}

export const IMPORTED: ImportResult = {
  ...PREVIEW, added_trades: 1, added_cash: 1,
  check: { as_of: '2026-02-27', matched: 5, differences: [], last_agreed: '2026-02-27', first_differed: null, download_from: null },
}

/** The calls every page of the new app makes for a signed-in client. */
export function signedIn(api: Api, list: PortalAccount[] = [BROKERAGE, CHECKING]) {
  return api
    .on('GET /api/v1/auth/me', ME)
    .on('GET /api/v1/portal/accounts', accounts(list))
    .on('GET /api/v1/portal/groups', { groups: [] })
    .on('GET /api/v1/portal/connections', NO_CONNECTIONS)
    .on('GET /api/v1/portal/insights', NO_INSIGHTS)
    .on('GET /api/v1/portal/links/plaid', CAN_LINK)
    .on('GET /api/v1/portal/performance', NO_HISTORY)
}
