import { test, expect, ME } from './api'
import type { MeResponse, SystemStatusResponse } from '../src/api/types'

const ADMIN: MeResponse = { ...ME, id: 'user-admin', name: 'Admin', email: 'admin@example.com', role: 'admin', client_id: null }

const STATUS: SystemStatusResponse = {
  generated_at: '2026-03-02T15:01:00Z',
  attention: [],
  alerts: { telegram: true },
  app: { environment: 'production', started_at: '2026-03-02T13:14:00Z', scheduler_enabled: true },
  database: { ok: true, size_bytes: 1_300_000_000, migration: 'abc123' },
  disk: { total_bytes: 100_000_000_000, free_bytes: 80_000_000_000 },
  jobs: [
    {
      id: 'plaid_refresh', label: 'Plaid refresh', schedule: 'Tuesday to Saturday, 6:30 AM (records the day before)',
      next_run_at: '2026-03-03T11:30:00Z', last_started_at: null, last_finished_at: null, last_ok: null, last_error: null, last_skipped: null,
    },
    {
      id: 'ticker_changes', label: 'Ticker changes', schedule: 'Every day, 6:15 AM',
      next_run_at: '2026-03-03T11:15:00Z', last_started_at: '2026-03-02T11:15:00Z', last_finished_at: '2026-03-02T11:15:05Z',
      last_ok: true, last_error: null, last_skipped: null,
    },
  ],
  brokerage_links: [
    { id: 'link-1', institution: 'Example Bank', source: 'plaid', status: 'active', checked_at: '2026-03-02T12:16:00Z', disabled_at: null, client_id: 'client-1', client: 'Pat Example', accounts: 4 },
    { id: 'link-2', institution: 'Example Brokerage', source: 'plaid', status: 'broken', checked_at: '2026-03-02T12:16:00Z', disabled_at: '2026-03-01T12:00:00Z', client_id: 'client-1', client: 'Pat Example', accounts: 2 },
  ],
  brokerage_accounts: [],
  capture: { market_day: '2026-02-27', accounts: 6, missing: [] },
  data: { clients: 1, accounts: 6, trades: 120, latest_trade_date: '2026-02-27', priced_symbols: 10, latest_price_date: '2026-02-27', indices: [] },
  backup: { known: true, at: '2026-03-02T08:15:00Z', file: 'achalara-2026-03-02.dump', size_bytes: 46_000_000 },
  webhooks: [],
  recent_log: [],
}

test('System status names where each login comes from and when each job runs', async ({ page, api }) => {
  api
    .on('GET /api/v1/auth/me', ADMIN)
    .on('GET /api/v1/clients/', [])
    .on('GET /api/v1/admin/status', STATUS)
    .on('GET /api/v1/admin/ticker-changes', [])
  await page.goto('/app/status')

  const connections = page.locator('section', { has: page.getByRole('heading', { name: 'External connections' }) })
  await expect(connections.getByRole('columnheader', { name: 'Source' })).toBeVisible()
  const bank = connections.getByRole('row', { name: /Example Bank/ })
  await expect(bank.getByRole('cell', { name: 'Plaid' })).toBeVisible()
  await expect(bank).toContainText('Sharing data')
  await expect(connections.getByRole('row', { name: /Example Brokerage/ })).toContainText('Stopped sharing')

  const jobs = page.locator('section', { has: page.getByRole('heading', { name: 'Daily jobs' }) })
  const plaid = jobs.getByRole('row', { name: /Plaid refresh/ })
  await expect(plaid).toContainText('Tuesday to Saturday, 6:30 AM')
  await expect(plaid).toContainText('No run on record yet')
  await expect(jobs.getByRole('row', { name: /Ticker changes/ })).toContainText('Completed')
})
