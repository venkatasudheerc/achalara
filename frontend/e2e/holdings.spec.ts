import { test, expect, signedIn, BROKERAGE } from './api'
import type { PortalHomeResponse, PortalPosition, PortalPositionsResponse } from '../src/api/types'

function holding(over: Partial<PortalPosition> & Pick<PortalPosition, 'symbol'>): PortalPosition {
  return {
    account_id: BROKERAGE.id, account_name: BROKERAGE.name, shared: false, sleeve_id: 'sleeve-1',
    strategy_id: 'strategy-1', strategy_name: 'Stocks', security_type: 'stock', name: null,
    quantity: 10, is_short: false, avg_cost: 5, multiplier: 1, price: 6, price_source: 'live',
    day_change: 0.1, day_change_pct: 0.02, cost_basis: 50, market_value: 60, unrealized_gain: 10,
    unrealized_gain_pct: 20, sector_group: 'sector', sector: 'Information Technology', sector_code: 'IT',
    ...over,
  }
}

const POSITIONS: PortalPositionsResponse = {
  as_of: '2026-11-13', live_prices_at: null, count: 2, unpriced_count: 0,
  total_market_value: 120, total_cost_basis: 100, total_unrealized_gain: 20, total_unrealized_gain_pct: 20,
  options: null,
  account_balances: [],
  positions: [
    holding({ symbol: 'AAA', name: 'EXAMPLE HOLDINGS CORP /DE/' }),
    holding({ symbol: 'BBB' }),
  ],
}

// The holdings page reads only a few of Home's figures; the rest are not asked for here.
const HOME = { as_of: '2026-11-13', total_value: 120 } as PortalHomeResponse

test('a holding says what it is called, or its type while no name is known', async ({ page, api }) => {
  signedIn(api).on('GET /api/v1/portal/positions', POSITIONS).on('GET /api/v1/portal/home', HOME)
  await page.goto(`/home?sel=account%3A${BROKERAGE.id}&view=holdings`)
  await page.getByRole('button', { name: 'Expand all' }).click()
  const aaa = page.getByRole('row').filter({ hasText: 'AAA' })
  await expect(aaa.getByText('Example Holdings')).toBeVisible()
  await expect(aaa.getByText('Stock', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('row').filter({ hasText: 'BBB' }).getByText('Stock', { exact: true })).toBeVisible()
})
