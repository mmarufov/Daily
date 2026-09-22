import { expect, test } from '@playwright/test'

/**
 * The main visitor journey: understand the product, read an edition, then
 * follow one story from a summary metric down to its recorded trace.
 */
test.describe('visitor journey', () => {
  test('home explains the product and routes to all three surfaces', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('daily edition')
    // The three entry points are labelled and described, not three bare buttons.
    const entries = page.getByRole('navigation', { name: 'Main' })
    for (const name of ['Reader', 'Evidence', 'Defect report']) {
      await expect(entries.getByRole('link', { name: new RegExp(name, 'i') })).toBeVisible()
    }
    // The demo must never be presented as real readership.
    await expect(page.getByText(/adversarial test\s+fixtures, not users/i)).toBeVisible()
  })

  test('reader shows a dated replay, never today’s news', async ({ page }) => {
    await page.goto('/reader')
    await expect(page.getByText('This is a replay, not today’s news.')).toBeVisible()
    await expect(page.getByText(/Every story below was published on or before/)).toBeVisible()
    // The edition stamp from DESIGN.md.
    await expect(page.getByText(/· [A-Z]+ EDITION/)).toBeVisible()
    // Live mode is explicitly not claimed.
    await expect(page.getByText(/not implemented here/)).toBeVisible()
  })

  test('reader switches profile and keeps it in the URL', async ({ page }) => {
    await page.goto('/reader')
    // The chip shows the display name; the URL keeps the fixture key, which is
    // the identifier the artifacts and labels are stored under.
    await page.getByRole('link', { name: 'Ray', exact: true }).click()
    await expect(page).toHaveURL(/profile=ray/)
    await expect(page.getByText('RAY EDITION')).toBeVisible()
  })

  test('reader shows no scores or match labels in the reading flow', async ({ page }) => {
    await page.goto('/reader?profile=ray')
    const article = page.getByRole('article')
    await expect(article).toBeVisible()
    // Daily's design rule: personalization is felt, not displayed.
    await expect(article).not.toContainText(/relevance|match score|never|must[_ ]see/i)
  })

  test('evidence opens on a useful preselected run with a comparison', async ({ page }) => {
    await page.goto('/evidence')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Evaluation evidence')
    await expect(page.getByLabel('Run')).toBeVisible()
    // The default pairing is same-corpus, different-pipeline, and says so.
    await expect(page.getByText(/Algorithm comparison/)).toBeVisible()
    await expect(page.getByRole('table').first()).toBeVisible()
  })

  test('evidence states that protocol equality cannot be verified', async ({ page }) => {
    await page.goto('/evidence')
    await expect(page.getByText(/Protocol equality therefore cannot be verified/)).toBeVisible()
  })

  test('a missing metric renders as absent, not as zero', async ({ page }) => {
    await page.goto('/evidence?persona=ray')
    const row = page.getByRole('row').filter({ hasText: 'Judge precision' }).first()
    await expect(row).toContainText('—')
    await expect(row).not.toContainText('0.0%')
  })

  test('deep link into a story trace survives a reload', async ({ page }) => {
    const url = '/evidence?run=prod-llm__2026-08-31__47edb50&persona=ray&view=stories&story=a00407'
    await page.goto(url)
    const detail = page.getByRole('complementary')
    await expect(detail).toContainText('Odell Beckham')
    await expect(detail).toContainText('music EP')
    await expect(detail).toContainText('blended')
    await page.reload()
    await expect(page.getByRole('complementary')).toContainText('music EP')
  })

  test('the funnel decreases monotonically and explains why', async ({ page }) => {
    await page.goto('/evidence?persona=ray&view=funnel')
    await expect(page.getByText(/furthest stage it reached/)).toBeVisible()
    const cells = await page
      .getByRole('row')
      .filter({ hasNotText: 'Stage' })
      .locator('td')
      .nth(0)
      .allInnerTexts()
    const numbers = cells
      .map((t) => Number(t.replace(/[^0-9]/g, '')))
      .filter((n) => Number.isFinite(n) && n > 0)
    for (let i = 1; i < numbers.length; i += 1) {
      expect(numbers[i]).toBeLessThanOrEqual(numbers[i - 1] as number)
    }
  })

  test('provenance discloses the three revisions and the contradicted baseline', async ({ page }) => {
    await page.goto('/evidence')
    await page.getByRole('group').filter({ hasText: 'Provenance' }).first().locator('summary').click()
    await expect(page.getByText('Executed the evaluation').first()).toBeVisible()
    await expect(page.getByText('not reachable from the default branch').first()).toBeVisible()
  })

  test('engineering links back into the exact explorer state', async ({ page }) => {
    await page.goto('/engineering')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('rejected for discussing')
    const link = page.getByRole('link', { name: /open this story’s recorded trace/ }).first()
    await link.click()
    await expect(page).toHaveURL(/story=a00407/)
    await expect(page.getByRole('complementary')).toContainText('music EP')
  })

  test('an unknown run reports itself instead of silently showing another', async ({ page }) => {
    await page.goto('/evidence?run=does-not-exist')
    // Next injects its own role="alert" route announcer, so scope to the page's.
    await expect(
      page.getByRole('alert').filter({ hasText: 'does-not-exist' }),
    ).toContainText('not in the current manifest')
  })
})

test.describe('failure and edge states', () => {
  test('an outcome filter with no matches offers a way back', async ({ page }) => {
    await page.goto('/evidence?persona=cold&view=stories&outcome=delivered-unwanted')
    const empty = page.getByText(/No stories for/)
    if (await empty.isVisible()) {
      await expect(page.getByRole('link', { name: 'Show every story' })).toBeVisible()
    }
  })

  test('404 route renders', async ({ page }) => {
    const response = await page.goto('/no-such-page')
    expect(response?.status()).toBe(404)
  })
})

test.describe('accessibility basics', () => {
  test('every page exposes a skip link and one h1', async ({ page }) => {
    for (const path of ['/', '/reader', '/evidence', '/engineering']) {
      await page.goto(path)
      await expect(page.getByRole('link', { name: 'Skip to content' })).toBeAttached()
      expect(await page.getByRole('heading', { level: 1 }).count()).toBe(1)
    }
  })

  test('the explorer is keyboard operable to the first control', async ({ page }, testInfo) => {
    // WebKit under a touch device profile does not move focus to links on Tab
    // unless full keyboard access is enabled, which is a platform behaviour
    // rather than a property of this page. Asserted on desktop only.
    test.skip(testInfo.project.name === 'mobile', 'Tab focus is not meaningful on a touch profile')
    await page.goto('/evidence')
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Skip to content' })).toBeFocused()
  })

  test('data tables have captions for screen readers', async ({ page }) => {
    await page.goto('/evidence?persona=ray&view=funnel')
    const captions = page.locator('table caption')
    expect(await captions.count()).toBeGreaterThan(0)
  })

  test('no console errors on any route', async ({ page }) => {
    const errors: string[] = []
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text())
    })
    page.on('pageerror', (error) => errors.push(error.message))
    for (const path of ['/', '/reader?profile=ray', '/evidence?persona=ray&view=stories', '/engineering']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
    }
    expect(errors).toEqual([])
  })
})
