import { test, expect, signedIn, account, BROKERAGE, CHECKING } from './api'
import { accountList } from './pages'

test('the Dashboard adds up the accounts in view and follows the account chosen', async ({ page, api }) => {
  signedIn(api)
  await page.goto('/home')

  const headline = page.getByRole('heading', { level: 1 })
  await expect(headline).toContainText('Everything you have is worth')
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

test('an account whose login stopped sharing says who must sign in again', async ({ page, api }) => {
  signedIn(api, [account({ ...BROKERAGE, needs_sign_in: true, login_id: 'login-1' }), CHECKING])
  await page.goto('/home')
  await expect(page.getByText(/has stopped sharing .* until you sign in again\./)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Sign in again' })).toBeVisible()
})

test('with no accounts the page offers to add the first one', async ({ page, api }) => {
  signedIn(api, [])
  await page.goto('/home')
  await expect(page.getByText('No accounts yet')).toBeVisible()
  await expect(page.getByRole('button', { name: '+ Add an account' })).toBeVisible()
})
