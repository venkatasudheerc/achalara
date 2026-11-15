import { test, expect, signedIn, BROKERAGE, HOLDINGS_DIFFER, PREVIEW, IMPORTED } from './api'

const imports = `/api/v1/portal/accounts/${BROKERAGE.id}/imports`

test('a file is shown before anything is added, then added once', async ({ page, api }) => {
  signedIn(api)
    .on(`GET ${imports}/check`, HOLDINGS_DIFFER)
    .on(`POST ${imports}/preview`, PREVIEW)
    .on(`POST ${imports}`, IMPORTED)
  await page.goto(`/home?sel=account:${BROKERAGE.id}`)

  await page.getByRole('button', { name: 'Update from a file' }).click()
  const dialog = page.getByRole('dialog', { name: 'Update from a file' })
  // Before a file is chosen: where the download should start.
  await expect(dialog.getByText(/Jan 15, 2026/).first()).toBeVisible()

  await dialog.locator('input[type=file]').setInputFiles({
    name: 'activity.csv', mimeType: 'text/csv',
    buffer: Buffer.from('date,type,symbol,quantity,price,amount\n2026-01-20,BUY,ZZZT,10,25,\n'),
  })
  await expect(dialog.getByText(/Bought 10 ZZZT/)).toBeVisible()
  // A file that does not say how far it is complete says nothing about it.
  await expect(dialog.getByText(/complete through/)).toHaveCount(0)
  expect(api.count(`POST ${imports}`), 'the preview writes nothing').toBe(0)

  await dialog.getByRole('button', { name: 'Add these' }).click()
  await expect(dialog.getByText(/The account’s history has been rebuilt\./)).toBeVisible()
  await expect(dialog.getByText('Holdings match.')).toBeVisible()
  expect(api.count(`POST ${imports}`)).toBe(1)

  await dialog.getByRole('button', { name: 'Done' }).click()
  await expect(dialog).toBeHidden()
})

test('an account shared with the viewer takes no uploads', async ({ page, api }) => {
  signedIn(api, [{ ...BROKERAGE, shared: true, client_id: 'client-2', owner_name: 'Sam Example' }])
  await page.goto(`/home?sel=account:${BROKERAGE.id}`)
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Sam’s')
  await expect(page.getByRole('button', { name: 'Update from a file' })).toHaveCount(0)
})

test('a file that says how far it is complete is shown saying so', async ({ page, api }) => {
  signedIn(api)
    .on(`GET ${imports}/check`, HOLDINGS_DIFFER)
    .on(`POST ${imports}/preview`, { ...PREVIEW, complete_through: '2026-02-20' })
  await page.goto(`/home?sel=account:${BROKERAGE.id}`)
  await page.getByRole('button', { name: 'Update from a file' }).click()
  const dialog = page.getByRole('dialog', { name: 'Update from a file' })
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'activity.csv', mimeType: 'text/csv', buffer: Buffer.from('Date,Type\n2026-01-20,Through\n'),
  })
  await expect(dialog.getByText(/complete through Feb 20, 2026/)).toBeVisible()
})

test('a file with nothing to add but a complete-through date offers to record it', async ({ page, api }) => {
  const nothing = { ...PREVIEW, complete_through: '2026-02-20', to_add_trades: 0, to_add_cash: 0, days: [] }
  signedIn(api)
    .on(`GET ${imports}/check`, HOLDINGS_DIFFER)
    .on(`POST ${imports}/preview`, nothing)
    .on(`POST ${imports}`, { ...IMPORTED, ...nothing, added_trades: 0, added_cash: 0 })
  await page.goto(`/home?sel=account:${BROKERAGE.id}`)
  await page.getByRole('button', { name: 'Update from a file' }).click()
  const dialog = page.getByRole('dialog', { name: 'Update from a file' })
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'activity.csv', mimeType: 'text/csv', buffer: Buffer.from('Date,Type\n2026-01-20,Through\n'),
  })
  await expect(dialog.getByText(/Nothing to add, but the file says it is complete through Feb 20, 2026/)).toBeVisible()
  expect(api.count(`POST ${imports}`), 'the preview writes nothing').toBe(0)
  await dialog.getByRole('button', { name: /Record complete through Feb 20, 2026/ }).click()
  await expect(dialog.getByText(/known to be complete through Feb 20, 2026/)).toBeVisible()
  expect(api.count(`POST ${imports}`)).toBe(1)
})

test('a file with nothing to add and no date just says so', async ({ page, api }) => {
  signedIn(api)
    .on(`GET ${imports}/check`, HOLDINGS_DIFFER)
    .on(`POST ${imports}/preview`, { ...PREVIEW, to_add_trades: 0, to_add_cash: 0, days: [] })
  await page.goto(`/home?sel=account:${BROKERAGE.id}`)
  await page.getByRole('button', { name: 'Update from a file' }).click()
  const dialog = page.getByRole('dialog', { name: 'Update from a file' })
  await dialog.locator('input[type=file]').setInputFiles({
    name: 'activity.csv', mimeType: 'text/csv', buffer: Buffer.from('Date,Type\n2026-01-20,Buy\n'),
  })
  await expect(dialog.getByText('Nothing to add: everything in this file is already here.')).toBeVisible()
  await expect(dialog.getByRole('button', { name: /Record complete through/ })).toHaveCount(0)
})
