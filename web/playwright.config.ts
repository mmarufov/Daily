import { defineConfig, devices } from '@playwright/test'

/**
 * Browser acceptance is about the public deployment. Run only after the
 * matching revision reaches marufov.com; this configuration never starts a
 * local server. Tests intercept every Lab API call so acceptance checks
 * cannot start a real microVM or investigation.
 */
export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  workers: 2,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: 'https://marufov.com',
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
})
