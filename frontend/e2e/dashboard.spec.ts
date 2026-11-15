import { test, expect, signedIn, account, finding, BROKERAGE, CHECKING } from './api'
import { accountList } from './pages'

test('the Dashboard adds up the accounts in view and follows the account chosen', async ({ page, api }) => {
  signedIn(api)
  await page.goto('/home')

  const headline = page.getByRole('heading', { level: 1 })
  await expect(headline).toContainText('Your net worth is')
  await expect(headline).toContainText('$162,000.50')

  const list = await accountList(page)
  // Two accounts can share a name, so each shows its last four.
  await expect(list.getByText('··4321')).toBeVisible()
  await expect(list.getByText('··8765')).toBeVisible()

  await list.getByText('Everyday Checking').click()
  await expect(page).toHaveURL(new RegExp(`sel=account(:|%3A)${CHECKING.id}`))
  await expect(headline).toContainText('Your Everyday Checking is worth')
  await expect(headline).toContainText('$12,000.50')
  // A bank account has no holdings or cost basis to show.
  const views = page.getByRole('tablist', { name: 'Views of the chosen accounts' })
  await expect(views.getByRole('tab', { name: 'Transactions' })).toBeVisible()
  await expect(views.getByRole('tab', { name: 'Holdings' })).toHaveCount(0)
})

test('a login that stopped sharing is a must-do: it stays, with its button, and the Dashboard has no empty sections', async ({ page, api }) => {
  signedIn(api, [account({ ...BROKERAGE, needs_sign_in: true, login_id: 'login-1' }), CHECKING])
  api.on('GET /api/v1/portal/insights', {
    nudges: [finding({
      key: 'login_needs_sign_in:login-1', rule: 'login_needs_sign_in', must: true,
      chip: { tone: 'link', label: 'Connection' }, title: 'Example Brokerage has stopped sharing 1 account',
      detail: 'Individual Brokerage ··4321 stay as they were on 11 Nov until you sign in again.',
      action: { kind: 'repair_login', label: 'Sign in again', login_id: 'login-1', view: null, sel: null, account_id: null },
    })],
    insights: [],
  })
  await page.goto('/home')
  await expect(page.getByRole('heading', { name: 'Next best action' })).toBeVisible()
  await expect(page.getByText(/has stopped sharing 1 account/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in again' })).toBeVisible()
  // Nothing to say in Insights: no section, and no line saying there is nothing.
  await expect(page.getByRole('heading', { name: 'Insights' })).toHaveCount(0)
})

test('with nothing to say there are no Next best action or Insights sections', async ({ page, api }) => {
  signedIn(api)
  await page.goto('/home')
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Your net worth is')
  await expect(page.getByRole('heading', { name: 'Next best action' })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Insights' })).toHaveCount(0)
})

test('nudges take turns in one slot, a dot shows any of them, and a button goes where it says', async ({ page, api }) => {
  signedIn(api)
  // No rolling here: this check is about choosing and going.
  await page.emulateMedia({ reducedMotion: 'reduce' })
  api.on('GET /api/v1/portal/insights', {
    nudges: [
      finding({ key: 'a', title: 'A card payment is due in 4 days', rank: 30,
        action: { kind: 'view', label: 'See the card', view: 'dashboard', sel: `account:${CHECKING.id}`, login_id: null, account_id: null } }),
      finding({ key: 'b', title: '$24,000 is in cash: 13% of what you own', rank: 60,
        action: { kind: 'view', label: 'See accounts', view: 'accounts', sel: null, login_id: null, account_id: null } }),
    ],
    insights: [
      finding({ key: 'i1', tier: 'insight', title: 'One holding, NVDA, is 21% of what you hold', detail: 'The next largest is 7%.',
        visual: { type: 'meter', part: 21, whole: 100, left: 'NVDA $21', right: 'of $100', warn: false, parts: null, days: null, note: null, rows: null, text: null, spans: null } }),
    ],
  })
  await page.goto('/home')
  await expect(page.getByText('1 of 2')).toBeVisible()
  await expect(page.getByText('A card payment is due in 4 days')).toBeVisible()
  await expect(page.getByText('$24,000 is in cash: 13% of what you own')).toHaveCount(0)

  await page.getByRole('button', { name: 'Show 2 of 2' }).click()
  await expect(page.getByText('2 of 2')).toBeVisible()
  await expect(page.getByText('$24,000 is in cash: 13% of what you own')).toBeVisible()
  await expect(page.getByText('A card payment is due in 4 days')).toHaveCount(0)

  await expect(page.getByRole('heading', { name: 'Insights' })).toBeVisible()
  await expect(page.getByText('One holding, NVDA, is 21% of what you hold')).toBeVisible()
  await expect(page.getByText('These describe what is on record. They are not advice.')).toBeVisible()

  await page.getByRole('button', { name: 'Show 1 of 2' }).click()
  await page.getByRole('button', { name: 'See the card' }).click()
  await expect(page).toHaveURL(new RegExp(`sel=account(:|%3A)${CHECKING.id}`))
  await expect(page).not.toHaveURL(/view=/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Your Everyday Checking is worth')
})

test('the slot rolls to the next nudge by itself', async ({ page, api }) => {
  test.setTimeout(30_000)
  signedIn(api)
  api.on('GET /api/v1/portal/insights', {
    nudges: [finding({ key: 'a', title: 'First nudge', rank: 30 }), finding({ key: 'b', title: 'Second nudge', rank: 60 })],
    insights: [],
  })
  await page.goto('/home')
  await expect(page.getByText('First nudge')).toBeVisible()
  await expect(page.getByText('Second nudge')).toBeVisible({ timeout: 12_000 })
  await expect(page.getByText('2 of 2')).toBeVisible()
})

test('with no accounts the page offers to add the first one', async ({ page, api }) => {
  signedIn(api, [])
  await page.goto('/home')
  await expect(page.getByText('No accounts yet')).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Add an account' })).toBeVisible()
})

test('the market tile sets cash beside what the market did in past years, and its link opens Research', async ({ page, api }) => {
  signedIn(api)
  api.on('GET /api/v1/portal/insights', {
    nudges: [],
    insights: [finding({
      key: 'cash_and_market_pattern', tier: 'insight', wide: true, chip: { tone: 'all', label: 'Markets' },
      title: 'You hold 12% in cash. The S&P 500 rose in 15 of the last 20 Novembers.',
      visual: {
        type: 'record', part: null, whole: null, left: null, right: null, warn: null, parts: null, days: null, note: null, rows: null, text: null,
        spans: [
          { when: 'This week · 9 to 13 Nov', said: 'Up in 11 of the last 20 years', years: [true, false, true, true, false], nums: 'Typical week +0.3% · best +3.1% · worst −4.2%' },
          { when: 'This month · November', said: 'Up in 15 of the last 20 years', years: [true, true, false, true, true], nums: 'Typical month +1.9% · best +10.8% · worst −7.5%' },
        ],
      },
      detail: 'This is what happened in past years, not what this year will do.',
      link: { kind: 'view', label: 'See the pattern in Research', view: 'research', sel: null, login_id: null, account_id: null },
    })],
  })
  api.on('GET /api/v1/research/indices', { indices: [] })
  await page.goto('/home')
  await expect(page.getByText('You hold 12% in cash. The S&P 500 rose in 15 of the last 20 Novembers.')).toBeVisible()
  await expect(page.getByRole('img', { name: /Up in 15 of the last 20 years/ })).toBeVisible()
  await expect(page.getByText('not what this year will do')).toBeVisible()
  // A fact, not a nudge: no Next best action section came with it.
  await expect(page.getByRole('heading', { name: 'Next best action' })).toHaveCount(0)
  await page.getByRole('button', { name: /See the pattern in Research/ }).click()
  await expect(page).toHaveURL(/\/home\/research/)
})
