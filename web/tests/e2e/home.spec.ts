import { expect, test } from '@playwright/test'

import { finishedRunBody } from '../fixtures/live-outcome'

/**
 * The homepage's claims, exercised in a browser.
 *
 * The page opens on a recorded production run and two interactive readings.
 * Each assertion here is something a visitor is told: that the run on screen
 * is recorded and real, that pressing Run starts a different, live one, and
 * that the two switches change what the data says they change, no more.
 */
test.describe('homepage', () => {
  test('opens on a recorded production run, labelled as recorded', async ({ page }) => {
    await page.goto('/')
    const panel = page.locator('.console')
    await expect(panel.getByText('Recorded', { exact: true })).toBeVisible()
    await expect(panel.getByText(/A real run on production, 2026-10-01 23:48 UTC/)).toBeVisible()
    await expect(panel.locator('[data-case]')).toHaveCount(64)
    await expect(panel.locator('[data-case="syn-positional-reordered"]')).toHaveAttribute('data-tone', 'wrong')
    await expect(panel.getByText('Rejected', { exact: true })).toBeVisible()
    await expect(panel.getByText('Caught by a fault-injected case')).toBeVisible()
    await expect(panel.getByText('deny-all')).toBeVisible()
    // The run on screen is the stored response, and it is one click away.
    const href = await panel.getByRole('link', { name: 'wrun_01M3WXWPKMF3H8Q66KZA56MZCV' }).getAttribute('href')
    expect(href).toBe('/runs/wrun_01M3WXWPKMF3H8Q66KZA56MZCV.json')
    expect((await page.request.get(href as string)).status()).toBe(200)
  })

  test('Run starts a live run and replaces the recorded one', async ({ page }) => {
    const runId = 'wrun_e2e_home'
    await page.route('**/api/lab/run', (route) =>
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ run_id: runId, suspend_seconds: 0, address_runs_left: 4 }),
      }),
    )
    let polls = 0
    await page.route(`**/api/lab/run/${runId}`, (route) => {
      polls += 1
      const body =
        polls === 1
          ? { run_id: runId, status: 'running', finished: false, outcome: null, progress: [] }
          : finishedRunBody(runId, 'count-guard-v1')
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
    })

    await page.goto('/')
    const panel = page.locator('.console')
    await panel.getByRole('button', { name: /Run it live/ }).click()
    await expect(panel.getByText('Recorded', { exact: true })).toHaveCount(0)
    await expect(panel.getByText('Finished')).toBeVisible()
    await expect(panel.getByText(/from the click to the verdict/)).toBeVisible()
    await expect(panel.getByText('Rejected', { exact: true })).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`\\?run=${runId}`))
  })

  test('choosing another parser clears a verdict it never got', async ({ page }) => {
    await page.goto('/')
    const panel = page.locator('.console')
    await panel.getByRole('button', { name: 'positional-v0' }).click()
    await expect(panel.getByText('No verdict yet')).toBeVisible()
    await expect(panel.locator('[data-tone="pending"]')).toHaveCount(64)
  })

  test('perfect ranking brings back only what was lost after the window', async ({ page }) => {
    await page.goto('/')
    const section = page.locator('section[aria-labelledby="ranking"]')
    await expect(section.getByText('needed stories that never arrived')).toBeVisible()
    await section.getByRole('switch').click()
    await expect(section.getByText('still missing with every later stage perfect')).toBeVisible()
    await expect(section.getByText('At most 22 come back.')).toBeVisible()
    await expect(section.locator('p.readout')).toContainText('75')
  })

  test('the reader at zero is named, not averaged away', async ({ page }) => {
    await page.goto('/')
    const section = page.locator('section[aria-labelledby="ranking"]')
    await expect(section.getByText(/for Will, who received none/)).toBeVisible()
    await expect(section.getByText('22.1%')).toBeVisible()
    await expect(section.getByText('32.1%')).toBeVisible()
  })

  test('turning the fix on makes the measured numbers worse', async ({ page }) => {
    await page.goto('/')
    const section = page.locator('section[aria-labelledby="defect"]')
    await expect(section.getByText('254 verdicts returned')).toBeVisible()
    await section.getByRole('radio', { name: 'With the count guard' }).click()
    await expect(section.getByText('42.5%')).toBeVisible()
    await expect(section.getByText('+15.6 pts')).toBeVisible()
    await expect(section.getByText('−3.4 pts')).toBeVisible()
    await expect(section.getByRole('link', { name: /Failing/ })).toHaveAttribute(
      'href',
      'https://github.com/mmarufov/Daily/pull/59/checks',
    )
    const scorecard = await section.getByRole('link', { name: 'The scorecard' }).getAttribute('href')
    expect((await page.request.get(scorecard as string)).status()).toBe(200)
  })

  test('reduced motion gets the answer, not the performance', async ({ browser }) => {
    const context = await browser.newContext({ reducedMotion: 'reduce' })
    const page = await context.newPage()
    await page.goto('/')
    const section = page.locator('section[aria-labelledby="subject"]')
    await expect(section.getByText('of 1,362 delivered')).toBeVisible()
    await context.close()
  })
})
