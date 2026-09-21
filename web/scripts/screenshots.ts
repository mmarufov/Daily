/**
 * Capture desktop and mobile screenshots of the production build.
 *   npx tsx scripts/screenshots.ts  (expects a server on PORT, default 3100)
 */
import { mkdirSync } from 'node:fs'
import { join } from 'node:path'

import { chromium, devices, webkit } from '@playwright/test'

const BASE = `http://127.0.0.1:${process.env.PORT ?? '3100'}`
const OUT = join(process.cwd(), '..', '.context', 'screenshots-web')

const SHOTS = [
  { name: 'home', path: '/' },
  { name: 'reader', path: '/reader?profile=ray' },
  { name: 'evidence-summary', path: '/evidence' },
  { name: 'evidence-funnel', path: '/evidence?persona=ray&view=funnel' },
  {
    name: 'evidence-story',
    path: '/evidence?run=prod-llm__2026-08-31__47edb50&persona=ray&view=stories&story=a00407',
  },
  { name: 'engineering', path: '/engineering' },
] as const

async function main(): Promise<void> {
  mkdirSync(OUT, { recursive: true })

  const desktop = await chromium.launch()
  const desktopPage = await (await desktop.newContext({ viewport: { width: 1280, height: 900 } })).newPage()
  for (const shot of SHOTS) {
    await desktopPage.goto(`${BASE}${shot.path}`, { waitUntil: 'networkidle' })
    await desktopPage.screenshot({ path: join(OUT, `desktop-${shot.name}.png`), fullPage: true })
    console.log(`desktop-${shot.name}.png`)
  }
  await desktop.close()

  const mobile = await webkit.launch()
  const mobilePage = await (await mobile.newContext({ ...devices['iPhone 14'] })).newPage()
  for (const shot of SHOTS) {
    await mobilePage.goto(`${BASE}${shot.path}`, { waitUntil: 'networkidle' })
    await mobilePage.screenshot({ path: join(OUT, `mobile-${shot.name}.png`), fullPage: true })
    console.log(`mobile-${shot.name}.png`)
  }
  await mobile.close()
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
})
