import { expect, test } from './fixtures'

/**
 * The main visitor journey: understand Daily, read a real recorded edition,
 * and discover the Lab that tests its parser, with evidence one click away.
 */
test.describe('visitor journey', () => {
  test('home introduces Daily with Reader and Lab in the primary navigation', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Daily makes news personal.')
    await expect(page.getByRole('banner').getByRole('link', { name: 'Daily, home', exact: true })).toHaveAttribute('href', '/')
    const entries = page.getByRole('banner').getByRole('navigation')
    for (const [name, href] of [['Reader', '/reader'], ['Lab', '/lab'], ['Evidence', '/evidence'], ['Findings', '/engineering']] as const) {
      await expect(entries.getByRole('link', { name, exact: true })).toHaveAttribute('href', href)
    }
    await expect(page.getByRole('link', { name: 'Explore the Lab', exact: true }).first()).toHaveAttribute('href', '/lab')
    await expect(page.getByRole('link', { name: 'Read an edition', exact: true }).first()).toHaveAttribute('href', '/reader?profile=ray')
    await expect(page.getByRole('contentinfo').getByRole('link', { name: 'Read an edition', exact: true })).toHaveAttribute('href', '/reader')
  })

  test('both hero actions reach the promised product and engineering workspace', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('link', { name: 'Read an edition', exact: true }).first().click()
    await expect(page).toHaveURL((url) => url.pathname === '/reader' && url.searchParams.get('profile') === 'ray')
    await expect(page.getByRole('heading', { level: 1 })).toContainText('RAY EDITION')
    await page.getByRole('banner').getByRole('link', { name: 'Daily, home', exact: true }).click()
    await page.getByRole('link', { name: 'Explore the Lab', exact: true }).first().click()
    await expect(page).toHaveURL((url) => url.pathname === '/lab')
    await expect(page.getByRole('button', { name: 'Run in Sandbox', exact: true })).toBeEnabled()
  })

  test('reader shows a dated replay, never today’s news', async ({ page }) => {
    await page.goto('/reader')
    await expect(page.getByText('Recorded edition.')).toBeVisible()
    await expect(page.getByText(/Stories were published on or before/)).toBeVisible()
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

  test('explorer view and outcome changes preserve the selected run, comparison and story', async ({ page }) => {
    const run = 'prod-llm__2026-08-31__47edb50'
    const compare = 'proto-hybrid-judge-events__2026-08-31__47edb50'
    await page.goto(`/evidence?run=${run}&compare=${compare}&persona=ray&view=stories&story=a00407`)
    await page.getByRole('navigation', { name: 'Explorer view' }).getByRole('link', { name: 'Funnel', exact: true }).click()
    await expect(page).toHaveURL((url) => url.searchParams.get('view') === 'funnel'
      && url.searchParams.get('run') === run
      && url.searchParams.get('compare') === compare
      && url.searchParams.get('persona') === 'ray'
      && url.searchParams.get('story') === 'a00407')
    await page.getByRole('navigation', { name: 'Explorer view' }).getByRole('link', { name: 'Stories', exact: true }).click()
    await page.getByLabel('Outcome', { exact: true }).selectOption('lost-at-or-after-scorer')
    await expect(page).toHaveURL((url) => url.searchParams.get('outcome') === 'lost-at-or-after-scorer'
      && url.searchParams.get('run') === run
      && url.searchParams.get('compare') === compare
      && url.searchParams.get('story') === 'a00407')
    await page.reload()
    await expect(page.getByLabel('Outcome', { exact: true })).toHaveValue('lost-at-or-after-scorer')
    await expect(page.getByRole('complementary', { name: /^Recorded trace for / })).toContainText('music EP')
  })

  test('the funnel decreases monotonically and explains why', async ({ page }) => {
    await page.goto('/evidence?persona=ray&view=funnel')
    await expect(page.getByText(/furthest stage it reached/)).toBeVisible()
    const cells = await page
      .getByRole('table', { name: 'Candidate funnel: survivors, articles lost entering each stage, and pass rate' })
      .locator('tbody tr')
      .locator('td:first-of-type')
      .allInnerTexts()
    const numbers = cells
      .map((t) => Number(t.replace(/[^0-9]/g, '')))
      .filter((n) => Number.isFinite(n) && n > 0)
    expect(numbers.length).toBeGreaterThan(1)
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
    await expect(page.getByRole('heading', { level: 1 })).toContainText('A safer guard.')
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
    // Maya has no delivered-unwanted stories in this pinned artifact.
    await page.goto('/evidence?run=prod-llm__2026-09-02__47edb50&persona=maya&view=stories&outcome=delivered-unwanted')
    await expect(page.getByText(/No stories for/)).toBeVisible()
    await page.getByRole('link', { name: 'Show every story' }).click()
    await expect(page).toHaveURL((url) => url.searchParams.get('persona') === 'maya' && !url.searchParams.has('outcome'))
    await expect(page.getByRole('table', { name: /Stories for/ })).toBeVisible()
  })

  test('404 route renders', async ({ page }) => {
    const response = await page.goto('/no-such-page')
    expect(response?.status()).toBe(404)
  })
})

test.describe('accessibility basics', () => {
  test('every page exposes a skip link and one h1', async ({ page }) => {
    for (const path of ['/', '/lab', '/reader', '/evidence', '/engineering']) {
      await page.goto(path)
      await expect(page.getByRole('link', { name: 'Skip to content' })).toBeAttached()
      expect(await page.getByRole('heading', { level: 1 }).count()).toBe(1)
    }
  })

  test('the explorer is keyboard operable to the first control', async ({ page, isMobile }) => {
    // WebKit under a touch device profile does not move focus to links on Tab
    // unless full keyboard access is enabled, which is a platform behaviour
    // rather than a property of this page. Asserted on desktop only.
    test.skip(isMobile, 'Tab focus is not meaningful on a touch profile')
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
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      await page.waitForLoadState('networkidle')
    }
    expect(errors).toEqual([])
  })
})
