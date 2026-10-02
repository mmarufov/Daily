import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import type { DemoBundle } from '../../lib/demo'

import { expect, test } from './fixtures'

const NARRATIVE_RUN = 'prod-llm__2026-09-02__47edb50'
const RECORDED_EXECUTION = 'wrun_01M3WXWPKMF3H8Q66KZA56MZCV'
// The pinned Ray recording, independently read from the exported artifact.
const RAY_SURVIVORS = [1362, 300, 298, 100, 100, 55, 55, 55, 55, 50] as const

test.describe('recorded pipeline instrument', () => {
  test('the below-fold replay does no work before the visitor reaches it', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    const sieve = page.getByTestId('hero-sieve')
    await expect(sieve).not.toBeInViewport()
    await expect(sieve).toHaveAttribute('data-stage', '0')
    await expect(sieve).toHaveAttribute('data-playing', 'false')
    await page.waitForTimeout(1700)
    await expect(sieve).toHaveAttribute('data-stage', '0')
    await expect(sieve).toHaveAttribute('data-playing', 'false')

    await sieve.scrollIntoViewIfNeeded()
    await expect(sieve).toHaveAttribute('data-playing', 'true')
    await expect(sieve).not.toHaveAttribute('data-stage', '0')
  })

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
  test('Daily opens with the unchanged first three stories of the pinned Ray edition', async ({ page }) => {
    const bundle = JSON.parse(readFileSync(join(__dirname, '..', '..', 'public', 'demo', 'editions.json'), 'utf8')) as DemoBundle
    const stories = bundle.editions.find((edition) => edition.persona === 'ray')!.stories.slice(0, 3)
    expect(bundle.run_id).toBe(NARRATIVE_RUN)
    expect(bundle.snapshot).toBe('2026-09-02')
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Daily makes news personal.')
    await expect(page.getByText('A personalized news app', { exact: true })).toHaveCount(0)
    const preview = page.getByTestId('edition-preview')
    await expect(preview).toContainText('Recorded edition')
    await expect(preview).toContainText('September 2, 2026')
    await expect(preview).toContainText('Reader fixture: Ray')
    await expect(preview.locator('[data-verbatim]')).toHaveText(stories.map((story) => story.headline))
    const rows = preview.locator('li')
    await expect(rows).toHaveCount(3)
    for (const [index, story] of stories.entries()) {
      await expect(rows.nth(index)).toContainText(story.publication ?? 'Publication not recorded')
      if (story.synthetic) await expect(rows.nth(index)).toContainText(/authored test story/i)
    }
  })

  test('the first invitation connects the news product, parser failure and a runnable fix', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByText("Daily builds a news edition around a reader's interests.", { exact: false })).toBeVisible()
    const invitation = page.getByRole('heading', { name: 'Does the fix actually work?', exact: true })
      .locator('xpath=ancestor::section[1]')
    await expect(invitation).toContainText(/parser/i)
    await expect(invitation).toContainText(/40 articles/)
    await expect(invitation).toContainText(/254 verdicts/)
    await expect(invitation.getByRole('link', { name: 'Run the default parser', exact: true })).toHaveAttribute('href', '/lab#run')
    const order = await page.locator('.lab-landing > section[id]').evaluateAll((sections) => sections.map((section) => section.id))
    expect(order).toEqual(['daily-lab', 'experiment', 'pipeline', 'retrieval'])
    await expect(page.locator('#pipeline').getByTestId('hero-sieve')).toHaveCount(1)
  })

  test('the recorded result identifies every outcome with a shape and a counted text legend', async ({ page }) => {
    await page.goto('/')
    const field = page.getByTestId('recorded-case-field')
    await expect(field).toHaveAccessibleName('48 correct, 4 failed, 12 not applicable, out of 64 cases')
    await expect(field.locator('[data-case-mark="correct"]')).toHaveCount(48)
    await expect(field.locator('[data-case-mark="wrong"]')).toHaveCount(4)
    await expect(field.locator('[data-case-mark="unscored"]')).toHaveCount(12)
    const result = field.locator('xpath=..')
    for (const text of ['48 correct', '4 failed', '12 not applicable']) {
      await expect(result.getByText(text, { exact: true })).toBeVisible()
    }
    await expect(field.locator('[tabindex], button, a')).toHaveCount(0)
    const marks = await field.locator('[data-case-mark]').evaluateAll((elements) => elements.map((element) => ({
      tag: element.tagName.toLowerCase(),
      hidden: element.getAttribute('aria-hidden'),
      size: Math.min(element.parentElement!.getBoundingClientRect().width, element.parentElement!.getBoundingClientRect().height),
    })))
    expect(marks.every((mark) => mark.tag === 'svg' && mark.hidden === 'true' && mark.size >= 20)).toBe(true)
  })

  test('all 97 retrieval losses have a selectable explanation and a real story trace', async ({ page }) => {
    await page.goto('/')
    const panel = page.getByTestId('retrieval-loss-panel')
    await expect(panel.locator('.retrieval-total')).toHaveText(/75\s*\/\s*97/)
    await expect(panel.locator('.retrieval-summary')).toContainText('Lost at the lookback window')
    await expect(panel.locator('.retrieval-summary')).toContainText('84 were lost before scoring')
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

  test('section 01 exposes the real execution sequence and isolation evidence without JavaScript', async ({ page }) => {
    await page.goto('/')
    const timeline = page.locator('#daily-lab').getByTestId('recorded-run-timeline')
    await expect(timeline).toHaveAttribute('data-run-id', RECORDED_EXECUTION)
    await expect(timeline).toContainText('Recorded production execution')
    await expect(timeline).toContainText('count-guard-v1')
    const rows = timeline.locator('ol.recorded-timeline > li')
    const expected = [
      ['0.00', 'scope checked: only candidate.py is written'],
      ['0.84', 'creating microVM'],
      ['1.07', 'uploading 5 files'],
      ['1.20', 'running the harness'],
      ['1.74', 'probing isolation'],
      ['2.61', 'stopping the microVM'],
      ['6.77', 'microVM stopped'],
    ] as const
    await expect(rows).toHaveCount(expected.length + 1)
    for (const [index, [elapsed, stage]] of expected.entries()) {
      await expect(rows.nth(index).locator('.recorded-timeline-time')).toHaveText(elapsed)
      await expect(rows.nth(index)).toContainText(stage)
    }
    await expect(rows.last()).toContainText('graded outside the microVM')
    // Grading is a terminal fact, not a made-up timestamp in the progress feed.
    await expect(rows.last().locator('.recorded-timeline-time')).toHaveText('')
    const probes = rows.nth(4).getByRole('list', { name: 'Recorded isolation checks' })
    for (const label of ['DNS lookup fails', 'HTTPS request fails', 'Grader not on disk', 'No credentials in env']) {
      const probe = probes.getByRole('listitem').filter({ hasText: label })
      await expect(probe).toBeVisible()
      await expect(probe).toHaveAttribute('data-held', 'true')
      await expect(probe).toContainText('passed')
    }
    await expect(probes.getByRole('listitem')).toHaveCount(4)
    await expect(timeline).toContainText('f027762ab4d08b35')
    await expect(timeline).toContainText(/separate execution from the published spec 1 result/i)
    await expect(timeline).not.toContainText('result above')
    await expect(timeline.locator(`a[href="/runs/${RECORDED_EXECUTION}.json"]`)).toBeVisible()
  })

  test('the product, recorded headlines and both destinations render before JavaScript runs', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Daily makes news personal.')
    await expect(page.getByText('A personalized news app', { exact: true })).toHaveCount(0)
    await expect(page.getByRole('link', { name: 'Explore the Lab', exact: true }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: 'Read an edition', exact: true }).first()).toBeVisible()
    await expect(page.getByTestId('edition-preview').locator('[data-verbatim]')).toHaveCount(3)
  })
})
