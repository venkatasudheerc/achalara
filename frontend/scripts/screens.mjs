// Screenshots of the new app at phone and laptop width, light and dark, for review.
//
//   ACHALARA_SESSION=<a session token> node scripts/screens.mjs [out-dir] [route ...]
//
// The token is a signed-in session for the local API (the `achalara_session`
// cookie). Uses the Chrome already installed; set CHROME_PATH if it is elsewhere.
// Routes default to the new app's pages; an advisor's token needs `?as=<client>`.
import { chromium } from 'playwright-core'
import { mkdirSync } from 'node:fs'

const base = process.env.APP_URL ?? 'http://localhost:5173'
const session = process.env.ACHALARA_SESSION
const chrome = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
const [out = 'screens', ...given] = process.argv.slice(2)
const routes = given.length ? given : ['/home', '/home?view=performance', '/home/research', '/home/plan', '/login']
const widths = { phone: 390, laptop: 1440 }

if (!session) {
  console.error('Set ACHALARA_SESSION to a signed-in session token.')
  process.exit(1)
}
mkdirSync(out, { recursive: true })
const browser = await chromium.launch({ executablePath: chrome })
for (const theme of ['light', 'dark']) {
  for (const [device, width] of Object.entries(widths)) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1 })
    await context.addCookies([{ name: 'achalara_session', value: session, domain: 'localhost', path: '/' }])
    await context.addInitScript((t) => localStorage.setItem('achalara-theme', t), theme)
    const page = await context.newPage()
    for (const route of routes) {
      // The dev server keeps a live connection open, so wait for the page itself.
      await page.goto(base + route, { waitUntil: 'load' })
      await page.waitForSelector('main, form', { timeout: 20000 }).catch(() => {})
      await page.waitForTimeout(2500)
      const name = route.replace(/^\//, '').replace(/[^a-z0-9]+/gi, '-') || 'root'
      await page.screenshot({ path: `${out}/${name}-${device}-${theme}.png`, fullPage: true })
    }
    await context.close()
  }
}
await browser.close()
console.log(`Saved to ${out}/`)
