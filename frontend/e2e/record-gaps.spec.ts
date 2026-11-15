import { test, expect, signedIn, account, BROKERAGE, CHECKING } from './api'
import type { RecordGaps } from '../src/api/types'

const INCOMPLETE = account({
  ...BROKERAGE,
  health: {
    state: 'incomplete',
    reasons: ['Holdings differ from the institution\'s record since 3 Mar 2026.'],
    download_from: '2026-03-02',
  },
})

const GAPS: RecordGaps = {
  account_id: INCOMPLETE.id,
  holdings_as_of: '2026-11-13',
  holdings: [{ symbol: 'AAA', custodian_quantity: 10, our_quantity: 4 }],
  first_differed: '2026-03-03',
  last_agreed: '2026-03-02',
  cash: { last_differed: '2026-06-12', custodian_cash: 500, our_cash: 350, difference: 150 },
  opening: [],
}
const GAPS_CALL = `GET /api/v1/portal/accounts/${INCOMPLETE.id}/record-gaps`

test('the Performance tab says what differs only when asked, and asks nothing before', async ({ page, api }) => {
  signedIn(api, [INCOMPLETE, CHECKING]).on(GAPS_CALL, GAPS)
  await page.goto(`/home?sel=account%3A${INCOMPLETE.id}&view=performance`)

  await expect(page.getByText('Not shown while a record is incomplete')).toBeVisible()
  await expect(page.getByText(/Holdings differ from the institution's record since/)).toBeVisible()
  // Nothing about the gap is fetched until the details are opened.
  expect(api.count(GAPS_CALL)).toBe(0)
  await expect(page.getByRole('cell', { name: 'AAA' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Show what is missing' }).click()
  await expect(page.getByRole('cell', { name: 'AAA' })).toBeVisible()
  await expect(page.getByText('Cash differs on')).toBeVisible()
  await expect(page.getByText(/activity from .*2026 to today/)).toBeVisible()
  expect(api.count(GAPS_CALL)).toBe(1)

  await page.getByRole('button', { name: 'Hide what is missing' }).click()
  await expect(page.getByRole('cell', { name: 'AAA' })).toHaveCount(0)
})

test('only the parts that apply are shown, and a shared account names who repairs it', async ({ page, api }) => {
  const shared = account({ ...INCOMPLETE, shared: true, owner_name: 'Sam Example' })
  signedIn(api, [shared, CHECKING]).on(GAPS_CALL, { ...GAPS, holdings: [], cash: null, first_differed: null, last_agreed: null })
  await page.goto(`/home?sel=account%3A${INCOMPLETE.id}&view=performance`)

  await page.getByRole('button', { name: 'Show what is missing' }).click()
  await expect(page.getByText('Shares that differ')).toHaveCount(0)
  await expect(page.getByText('Cash differs on')).toHaveCount(0)
  await expect(page.getByText(/no single holding or amount to point to/)).toBeVisible()
  await expect(page.getByText('Sam can repair it.')).toBeVisible()
  // Not theirs to upload into.
  await expect(page.getByRole('button', { name: 'Update from a file' })).toHaveCount(0)
})

test('a complete account has no such link', async ({ page, api }) => {
  signedIn(api)
  await page.goto('/home')
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Show what is missing' })).toHaveCount(0)
})
