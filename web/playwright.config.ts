import { defineConfig, devices } from '@playwright/test'

/**
 * Two targets, one suite.
 *
 * By default it runs against a local production build (`next build && next
 * start`), so a change can be checked before it ships. Set E2E_BASE_URL to
 * point the same suite at the public deployment once a revision is live,
 * which is the acceptance that counts:
 *
 *   E2E_BASE_URL=https://marufov.com npx playwright test
 *
 * Either way, `tests/e2e/fixtures.ts` intercepts every Lab API call, so no
 * test can start a real microVM or spend the public run quota.
 */
const remote = process.env.E2E_BASE_URL
const baseURL = remote ?? 'http://127.0.0.1:3100'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  ...(remote === undefined ? {} : { workers: 2 }),
  timeout: 60_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL,
    serviceWorkers: 'block',
    navigationTimeout: 30_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 7'] } },
    { name: 'mobile', use: { ...devices['iPhone 14'] } },
  ],
  ...(remote === undefined
    ? {
        webServer: {
          command: 'npm run build && npm run start -- --port 3100',
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
      }
    : {}),
})
