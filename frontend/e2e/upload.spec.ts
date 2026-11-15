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
