import { test, expect, signedIn, people, BROKERAGE } from './api'
import type { AccountSharing } from '../src/api/types'

const shared = people()
shared.your_accounts[0] = { ...shared.your_accounts[0], seen_by: ['Sam Example'], seen_by_ids: ['client-2'] }
shared.people[0] = { ...shared.people[0], you_share: 1 }

const sharing: AccountSharing = {
  account_id: BROKERAGE.id, name: BROKERAGE.name, can_manage: true,
  owners: [{ id: 'client-1', name: 'Pat Example', has_login: true }], held_for: null,
  shared_with: [{ kind: 'person', id: 'client-2', name: 'Sam Example', level: 'view' }], advisor: null,
}

test('every account starts private; sharing is one switch, and one button takes it all back', async ({ page, api }) => {
  let now = people()
  signedIn(api)
    .on('GET /api/v1/portal/people', () => now)
    .on(`POST /api/v1/portal/accounts/${BROKERAGE.id}/shares`, (route) => {
      expect(route.request().postDataJSON()).toEqual({ person_id: 'client-2', advisor: false })
      now = shared
      return sharing
    })
    .on('POST /api/v1/portal/people/make-private', () => {
      now = people()
      return {}
    })
  await page.goto('/home/access')

  await expect(page.getByRole('heading', { name: 'Manage Access' })).toBeVisible()
  const mine = page.getByRole('region', { name: 'Your accounts' })
  const brokerage = mine.getByRole('listitem').filter({ hasText: 'Individual Brokerage' })
  await expect(mine.getByText('Private', { exact: true })).toHaveCount(2)
  // Nothing is switched on for the viewer.
  for (const control of await mine.getByRole('switch').all()) await expect(control).not.toBeChecked()
  await expect(page.getByRole('button', { name: 'Make everything private' })).toHaveCount(0)

  await brokerage.getByRole('switch', { name: /Sam/ }).click()
  await expect(brokerage.getByText('Shared with 1')).toBeVisible()
  await expect(brokerage.getByRole('switch', { name: /Sam/ })).toBeChecked()

  await page.getByRole('button', { name: 'Make everything private' }).click()
  const confirm = page.getByRole('alertdialog', { name: 'Make everything private' })
  await expect(confirm).toContainText('Stop sharing all 1 account?')
  await confirm.getByRole('button', { name: 'Yes, make private' }).click()
  await expect(mine.getByText('Private', { exact: true })).toHaveCount(2)
  expect(api.count('POST /api/v1/portal/people/make-private')).toBe(1)
})
