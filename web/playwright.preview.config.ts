import { defineConfig, devices } from '@playwright/test'
import production from './playwright.config'

const baseURL = process.env.PREVIEW_URL
if (!baseURL || !/^https:\/\/daily-[a-z0-9-]+\.vercel\.app$/.test(baseURL)) {
  throw new Error('PREVIEW_URL must be the exact HTTPS Vercel deployment URL.')
}

export default defineConfig({
  ...production,
  use: {
    ...production.use,
    baseURL,
    storageState: process.env.PLAYWRIGHT_STORAGE_STATE,
  },
  projects: [
    ...(production.projects ?? []),
    { name: 'desktop-webkit', use: { ...devices['Desktop Safari'], viewport: { width: 1440, height: 1000 } } },
  ],
})
