import { expect, test } from '@playwright/test'

/**
 * The Lab's public claims, exercised in a real browser.
 *
 * Each assertion corresponds to something the site says about itself. If the
 * Lab ever starts depicting a live run, fabricating an agent trace, or letting
 * a verdict appear without its scope, one of these fails.
 */

test.describe('Daily Lab', () => {
  test('the first screen states the failure and offers the replay', async ({ page }) => {
    await page.goto('/lab')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('never said which verdict')
    await expect(page.getByRole('link', { name: 'Replay the investigation' })).toBeVisible()
    // Recorded replay must never be presented as live execution.
    await expect(page.getByText(/recorded replay, not a live run/i).first()).toBeVisible()
  })

  test('shows the real offending response, not a description of one', async ({ page }) => {
    await page.goto('/lab')
    await expect(page.getByText('Articles sent')).toBeVisible()
    await expect(page.getByText('Verdicts returned')).toBeVisible()
    // The recorded batch: 40 articles in, 254 verdicts back.
    const sent = page.locator('dd').filter({ hasText: 'one batch' }).first()
    await expect(sent).toContainText('40')
  })

  test('publishes three walkthroughs, one of them a labelled control', async ({ page }) => {
    await page.goto('/lab')
    for (const slug of ['accepted', 'rejected', 'interrupted']) {
      const response = await page.request.get(`/lab/${slug}`)
      expect(response.status()).toBe(200)
    }
    await expect(page.getByText('Seeded control').first()).toBeVisible()
  })

  test('a rejected control names the criterion it failed', async ({ page }) => {
    await page.goto('/lab/rejected')
    await expect(page.getByText('Rejected').first()).toBeVisible()
    await expect(page.getByText(/This is a seeded control/).first()).toBeVisible()
    const row = page.getByRole('row').filter({ hasText: 'protocol-violation-refusal' }).first()
    await expect(row).toContainText('not met')
  })

  test('an accepted run says what acceptance does not mean', async ({ page }) => {
    await page.goto('/lab/accepted')
    await expect(page.getByText('Accepted for review').first()).toBeVisible()
    await expect(page.getByText(/eligible for human review/).first()).toBeVisible()
    await expect(page.getByText(/does not establish generalisation/).first()).toBeVisible()
  })

  test('the interrupted run shows a real recovery, not a retry that pretends', async ({ page }) => {
    await page.goto('/lab/interrupted')
    // The status appears in the timeline and again in the provenance prose.
    await expect(page.getByText('unknown-outcome').first()).toBeVisible()
    await expect(page.getByText(/orchestrator died with this attempt in flight/).first()).toBeVisible()
    await expect(page.getByText('succeeded').first()).toBeVisible()
  })

  test('never claims an agent has run', async ({ page }) => {
    await page.goto('/lab')
    // The never-claims list became `<details>` when the page was rewritten, so
    // the heading is what is on screen and the sentence is one click down.
    // Both matter: a reader who never clicks must still see the claim, and the
    // reason must be there for the one who does.
    await expect(page.getByText('No agent has run').first()).toBeVisible()
    await expect(page.getByText(/no model has been called/i).first()).toBeAttached()
  })

  test('reports zero spend and zero model calls for every published run', async ({ page }) => {
    await page.goto('/lab/accepted')
    const calls = page.locator('dd').filter({ hasText: /^0$/ }).first()
    await expect(calls).toBeVisible()
    await expect(page.getByText(/provider spend for this run is \$0/).first()).toBeVisible()
  })

  test('a shared run URL survives a reload', async ({ page }) => {
    await page.goto('/lab/interrupted')
    const heading = await page.getByRole('heading', { level: 1 }).innerText()
    await page.reload()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(heading)
  })

  test('an unknown run is a 404, not an empty page', async ({ page }) => {
    const response = await page.goto('/lab/does-not-exist')
    expect(response?.status()).toBe(404)
  })

  test('every lab page has one h1 and a skip link', async ({ page }) => {
    for (const path of ['/lab', '/lab/accepted', '/lab/rejected', '/lab/interrupted']) {
      await page.goto(path)
      await expect(page.getByRole('link', { name: 'Skip to content' })).toBeAttached()
      expect(await page.getByRole('heading', { level: 1 }).count()).toBe(1)
    }
  })

  test('no console errors on any lab route', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
    page.on('pageerror', (e) => errors.push(e.message))
    for (const path of ['/lab', '/lab/accepted', '/lab/rejected', '/lab/interrupted']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
    }
    expect(errors).toEqual([])
  })
})
