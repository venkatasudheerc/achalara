import type { Page } from '@playwright/test'

/** The account list: beside the page on a laptop, behind "Choose accounts" on a phone. */
export async function accountList(page: Page) {
  const list = page.getByRole('complementary', { name: 'Accounts' })
  await list.or(page.getByRole('button', { name: 'Choose accounts' })).first().waitFor()
  if (!(await list.isVisible())) await page.getByRole('button', { name: 'Choose accounts' }).click()
  return list
}
