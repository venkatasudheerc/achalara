import { test, expect, signedIn } from './api'

test('a page that cannot be downloaded says so inside the frame, with a way out', async ({ page, api }) => {
  signedIn(api)
  // The page's own file fails to arrive, as it does when the app was updated
  // after this tab was opened or the connection drops.
  await page.route(/features\/home\/AccessPage/, (route) => route.abort())
  await page.goto('/home/access')

  const alert = page.getByRole('alert')
  await expect(alert).toContainText('This page could not be downloaded.')
  await expect(alert.getByRole('button', { name: 'Reload' })).toBeVisible()
  // The frame is still there, so the person can go elsewhere.
  await expect(page.getByRole('link', { name: 'achalara, home' })).toBeVisible()
})
