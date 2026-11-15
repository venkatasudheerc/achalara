import { test, expect, signedIn, ME } from './api'

test('the front door is sign-in, and signing in opens the person\'s own page', async ({ page, api }) => {
  let signedInNow = false
  signedIn(api)
    .on('GET /api/v1/auth/me', (route) =>
      signedInNow ? ME : route.fulfill({ status: 401, json: { detail: 'Not signed in' } }))
    .on('POST /api/v1/auth/login', (route) => {
      const sent = route.request().postDataJSON() as { email: string; password: string }
      if (sent.password !== 'a long invented phrase') {
        return route.fulfill({ status: 401, json: { detail: 'That email and password do not match.' } })
      }
      signedInNow = true
      return ME
    })

  await page.goto('/')
  await expect(page).toHaveURL(/\/login$/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  await page.getByLabel('Email').fill('pat@example.com')
  await page.getByLabel('Password', { exact: true }).fill('not the password')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByText('That email and password do not match.')).toBeVisible()
  await expect(page).toHaveURL(/\/login$/)

  await page.getByLabel('Password', { exact: true }).fill('a long invented phrase')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page).toHaveURL(/\/home/)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Everything you have is worth')
})

test('a page behind sign-in sends a visitor to sign in', async ({ page, api }) => {
  api.on('GET /api/v1/auth/me', (route) => route.fulfill({ status: 401, json: { detail: 'Not signed in' } }))
  await page.goto('/home/access')
  await expect(page).toHaveURL(/\/login/)
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
})
