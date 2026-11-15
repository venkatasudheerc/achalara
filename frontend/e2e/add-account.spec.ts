import { test, expect, signedIn, people } from './api'
import { accountList } from './pages'

test('adding an account offers Plaid and asks nothing of it until chosen', async ({ page, api }) => {
  signedIn(api).on('GET /api/v1/portal/people', people())
  // Plaid's own script is never loaded by a test.
  await page.route('**/cdn.plaid.com/**', (route) => route.abort())
  await page.goto('/home')

  const list = await accountList(page)
  await list.getByRole('button', { name: '+ Add an account' }).click()

  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Link with Plaid/ })).toBeEnabled()
  await expect(dialog.getByText('coming later')).toBeVisible()
  expect(api.count('POST /api/v1/portal/links/plaid/start')).toBe(0)

  await dialog.getByRole('button', { name: 'Close' }).click()
  await expect(dialog).toBeHidden()
})

test('when linking is not set up the dialog says so and the button is off', async ({ page, api }) => {
  signedIn(api)
    .on('GET /api/v1/portal/people', people())
    .on('GET /api/v1/portal/links/plaid', { available: false, logins_left: 0 })
  await page.goto('/home')
  const list = await accountList(page)
  await list.getByRole('button', { name: '+ Add an account' }).click()
  await expect(page.getByRole('dialog').getByRole('button', { name: /Link with Plaid/ })).toBeDisabled()
})
