import { expect, test } from './fixtures'

const NARRATIVE_RUN = 'prod-llm__2026-09-02__47edb50'
// The pinned Ray recording, independently read from the exported artifact.
const RAY_SURVIVORS = [1362, 300, 298, 100, 100, 55, 55, 55, 55, 50] as const

test.describe('recorded hero instrument', () => {
  test('reduced motion starts with all 1,362 marks and the 50 recorded survivors', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    const hero = page.getByTestId('hero-sieve')
    await expect(hero).toHaveAttribute('data-stage', '9')
    await expect(hero).toHaveAttribute('data-playing', 'false')
    await expect(hero.locator('.sieve-cell')).toHaveCount(1362)
    await expect(hero.locator('.sieve-cell[data-state="delivered"]')).toHaveCount(50)
    await expect(hero.getByRole('img')).toHaveAccessibleName(
      '1,362 candidate articles for reader fixture Ray; 50 remain after Delivered feed.',
    )
    await expect(hero.getByRole('slider', { name: 'Pipeline stage' })).toHaveAttribute('max', '9')
    await expect(hero.getByRole('slider', { name: 'Pipeline stage' })).toHaveAttribute('aria-valuetext', '10 of 10: Delivered feed, 50 remaining')
    await expect(hero.locator('.sieve-cell:not([aria-hidden="true"])')).toHaveCount(0)
    await expect(hero.locator('.sieve-cell[tabindex]')).toHaveCount(0)

    await hero.getByRole('button', { name: 'Replay', exact: true }).click()
    await expect(hero).toHaveAttribute('data-stage', '9')
    await expect(hero).toHaveAttribute('data-playing', 'false')
  })

  test('all ten stages are keyboard operable and report their recorded counts', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    const hero = page.getByTestId('hero-sieve')
    const slider = hero.getByRole('slider', { name: 'Pipeline stage' })
    await expect(hero).toHaveAttribute('data-stage', '9')
    await slider.press('Home')

    for (const [index, survivors] of RAY_SURVIVORS.entries()) {
      if (index > 0) await slider.press('ArrowRight')
      await expect(slider).toBeFocused()
      await expect(hero).toHaveAttribute('data-stage', String(index))
      await expect(hero).toHaveAttribute('data-playing', 'false')
      await expect(slider).toHaveAttribute('aria-valuetext', new RegExp(`^${index + 1} of 10: .*?, ${survivors} remaining$`))
      await expect(hero.locator('.sieve-cell[data-state="alive"], .sieve-cell[data-state="delivered"]')).toHaveCount(survivors)
    }
  })

  test('changing fixtures settles on Tom and preserves the exact evidence destination', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    const hero = page.getByTestId('hero-sieve')
    await hero.getByRole('combobox', { name: 'Reader fixture' }).selectOption('tom')
    await expect(hero).toHaveAttribute('data-stage', '9')
    await expect(hero).toHaveAttribute('data-playing', 'false')
    await expect(hero.locator('.sieve-cell')).toHaveCount(1362)
    await expect(hero.locator('.sieve-cell[data-state="delivered"]')).toHaveCount(9)
    await expect(hero.getByRole('img')).toHaveAccessibleName(/fixture Tom; 9 remain after Delivered feed/)

    await hero.getByText('About this recording', { exact: true }).click()
    await expect(hero.getByText(/positions do not identify articles/)).toBeVisible()
    await hero.getByRole('link', { name: 'Inspect', exact: true }).click()
    await expect(page).toHaveURL((url) => url.pathname === '/evidence'
      && url.searchParams.get('run') === NARRATIVE_RUN
      && url.searchParams.get('persona') === 'tom'
      && url.searchParams.get('view') === 'funnel')
    await expect(page.getByRole('combobox', { name: 'Reader fixture', exact: true })).toHaveValue('tom')
  })

  test('autoplay settles once, while pause and manual scrubbing take control', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    const hero = page.getByTestId('hero-sieve')
    await hero.scrollIntoViewIfNeeded()
    await expect(hero).toHaveAttribute('data-stage', '9', { timeout: 12_000 })
    await expect(hero).toHaveAttribute('data-playing', 'false')

    await hero.getByRole('button', { name: 'Replay', exact: true }).click()
    await expect(hero).toHaveAttribute('data-playing', 'true')
    await hero.getByRole('button', { name: 'Pause', exact: true }).click()
    await expect(hero).toHaveAttribute('data-playing', 'false')
    const stoppedAt = await hero.getAttribute('data-stage')
    // Longer than the recording's longest dwell: a stale timer must not win.
    await page.waitForTimeout(1700)
    await expect(hero).toHaveAttribute('data-stage', stoppedAt as string)

    const slider = hero.getByRole('slider', { name: 'Pipeline stage' })
    await slider.press('Home')
    await slider.press('ArrowRight')
    await expect(hero).toHaveAttribute('data-stage', '1')
    await expect(hero).toHaveAttribute('data-playing', 'false')
    await hero.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(hero).toHaveAttribute('data-playing', 'true')
    await expect(hero).not.toHaveAttribute('data-stage', '1')
  })

  test('scrolling the replay offscreen pauses it and returning does not restart it', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    const hero = page.getByTestId('hero-sieve')
    await hero.scrollIntoViewIfNeeded()
    await hero.getByRole('slider', { name: 'Pipeline stage' }).press('Home')
    await hero.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(hero).toHaveAttribute('data-playing', 'true')
    await page.getByRole('contentinfo').scrollIntoViewIfNeeded()
    await expect(hero).not.toBeInViewport()
    await expect(hero).toHaveAttribute('data-playing', 'false')
    const stoppedAt = await hero.getAttribute('data-stage')
    await page.waitForTimeout(1700)
    await expect(hero).toHaveAttribute('data-stage', stoppedAt as string)
    await hero.scrollIntoViewIfNeeded()
    await expect(hero).toHaveAttribute('data-playing', 'false')
    await expect(hero).toHaveAttribute('data-stage', stoppedAt as string)
  })
  test('hiding the document stops playback without restarting when visible', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    const hero = page.getByTestId('hero-sieve')
    await hero.scrollIntoViewIfNeeded()
    await hero.getByRole('slider').press('Home')
    await hero.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(hero).toHaveAttribute('data-playing', 'true')
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await expect(hero).toHaveAttribute('data-playing', 'false')
    const stopped = await hero.getAttribute('data-stage')
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await page.waitForTimeout(1700)
    await expect(hero).toHaveAttribute('data-stage', stopped!)
    await expect(hero).toHaveAttribute('data-playing', 'false')
  })

})

test.describe('homepage evidence', () => {
  test('all 97 retrieval losses have a selectable explanation and a real story trace', async ({ page }) => {
    await page.goto('/')
    const panel = page.getByTestId('retrieval-loss-panel')
    const segments = [
      ['Lookback', 75],
      ['Prefilter cap', 9],
      ['Scoring', 9],
      ['Rank cutoff', 4],
    ] as const
    for (const [name, count] of segments) {
      const button = panel.getByRole('button', { name: `${name}: ${count} of 97 losses`, exact: true })
      await button.click()
      await expect(button).toHaveAttribute('aria-pressed', 'true')
      await expect(panel.locator('button[aria-pressed="true"]')).toHaveCount(1)
      const story = panel.getByTestId('retrieval-story-link')
      await expect(story).toBeVisible()
      const href = await story.getAttribute('href')
      const url = new URL(href as string, 'https://marufov.com')
      expect(url.pathname).toBe('/evidence')
      expect(url.searchParams.get('run')).toBe(NARRATIVE_RUN)
      expect(url.searchParams.get('view')).toBe('stories')
      expect(url.searchParams.get('persona')).toBeTruthy()
      expect(url.searchParams.get('story')).toBeTruthy()
    }
    const lastStory = new URL(await panel.getByTestId('retrieval-story-link').getAttribute('href') as string, 'https://marufov.com')
    await panel.getByTestId('retrieval-story-link').click()
    await expect(page).toHaveURL(lastStory.href)
    await expect(page.getByRole('complementary', { name: /^Recorded trace for / })).toContainText(lastStory.searchParams.get('story') as string)
  })

  test('the historical guard comparison keeps its measured regression visible in both directions', async ({ page }) => {
    await page.goto('/')
    const panel = page.getByTestId('guard-experiment-panel')
    const original = panel.getByRole('button', { name: 'Original', exact: true })
    const experiment = panel.getByRole('button', { name: 'Guard experiment', exact: true })
    await original.click()
    await expect(original).toHaveAttribute('aria-pressed', 'true')
    await expect(panel.getByTestId('guard-metric-recall')).toContainText('22.1%')
    await expect(panel.getByTestId('guard-metric-unwanted')).toContainText('26.9%')
    await experiment.click()
    await expect(experiment).toHaveAttribute('aria-pressed', 'true')
    await expect(original).toHaveAttribute('aria-pressed', 'false')
    await expect(panel.getByTestId('guard-metric-recall')).toContainText('18.7%')
    await expect(panel.getByTestId('guard-metric-unwanted')).toContainText('42.5%')
    await expect(panel).toContainText(/September 21|2026-09-21/)
    await expect(panel).toContainText(/historical|experiment/i)
    await original.click()
    await expect(panel.getByTestId('guard-metric-recall')).toContainText('22.1%')
    await expect(panel.getByTestId('guard-metric-unwanted')).toContainText('26.9%')
  })
})

test.describe('server-rendered opening', () => {
  test.use({ javaScriptEnabled: false })

  test('the question and both destinations are visible before JavaScript runs', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Does the fix actually work?')
    await expect(page.getByRole('link', { name: 'Run a parser', exact: true }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: 'Explore the evidence', exact: true })).toBeVisible()
  })
})
