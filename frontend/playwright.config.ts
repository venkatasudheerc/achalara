import { defineConfig } from '@playwright/test'

/**
 * Browser checks of the screens people rely on, against the app alone: every
 * API call is answered by the test (`e2e/api.ts`), so no backend, database or
 * outside service is needed and nothing real is read or written.
 *
 * Locally the installed Chrome is used; CI downloads Chromium.
 */
const PORT = 5199

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://localhost:${PORT}`,
    channel: process.env.CI ? undefined : 'chrome',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'laptop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'phone', use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
  webServer: {
    // The API is asked for on the app's own address, where the tests answer it.
    command: `npx vite --port ${PORT} --strictPort`,
    env: { VITE_API_BASE_URL: '' },
    url: `http://localhost:${PORT}/login`,
    reuseExistingServer: !process.env.CI,
  },
})
