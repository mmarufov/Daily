import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import type { Locator } from '@playwright/test'

import type { DemoBundle } from '../../lib/demo'

import { expect, test } from './fixtures'

const NARRATIVE_RUN = 'prod-llm__2026-09-02__47edb50'
const RECORDED_EXECUTION = 'wrun_01M3WXWPKMF3H8Q66KZA56MZCV'
const RAY_SURVIVORS = [1362, 300, 298, 100, 100, 55, 55, 55, 55, 50] as const
const MILESTONES = ['Parser', 'Sandbox', 'Tests', 'Verdict'] as const
const VISUAL_STOPS = [0.08, 0.32, 0.59, 0.92] as const

async function scrollStory(story: Locator, progress: number) {
  await story.getByTestId('run-story-track').evaluate((element, fraction) => {
    const bounds = element.getBoundingClientRect()
    const sticky = element.querySelector<HTMLElement>('.run-story-sticky')!
    window.scrollTo({ top: window.scrollY + bounds.top - 96 + ((element as HTMLElement).offsetHeight - sticky.offsetHeight) * fraction, behavior: 'instant' })
  }, progress)
}

async function settledStory(story: Locator, stage: number) {
  await expect(story).toHaveAttribute('data-transitioning', 'false')
  await expect.poll(async () => Number(await story.getAttribute('data-visual-progress'))).toBeCloseTo(VISUAL_STOPS[stage]!, 3)
}

function recordedField(story: Locator) {
  return story.locator('[data-testid="recorded-case-field"]:visible')
}

test.describe('recorded parser run', () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
  })

  test('the offscreen story stays inactive and idle time does not advance the recording', async ({ page }) => {
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'scroll')
    await page.getByRole('contentinfo').scrollIntoViewIfNeeded()
    await expect(story).not.toBeInViewport()
    await expect(story).toHaveAttribute('data-active', 'false')
    const stage = await story.getAttribute('data-stage')
    await page.waitForTimeout(700)
    await expect(story).toHaveAttribute('data-stage', stage!)
    expect(await story.evaluate(element => element.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length)).toBe(0)
  })

  test('scrolling forward and backward follows the four recorded moments', async ({ page }) => {
    const story = page.getByTestId('run-story')
    for (const [progress, stage] of [[0.10, 0], [0.30, 1], [0.60, 2], [0.90, 3], [0.60, 2], [0.30, 1], [0.10, 0]] as const) {
      await scrollStory(story, progress)
      await expect(story).toHaveAttribute('data-stage', String(stage))
      await expect(story.getByRole('button', { name: MILESTONES[stage], exact: true })).toHaveAttribute('aria-current', 'step')
      await expect(story).toHaveAttribute('data-active', 'true')
    }
  })

  test('stopping just past a chapter boundary completes the scene without moving the page', async ({ page }) => {
    const story = page.getByTestId('run-story')
    for (const [progress, stage] of [[0.21, 1], [0.46, 2], [0.76, 3]] as const) {
      await scrollStory(story, progress)
      await expect(story).toHaveAttribute('data-stage', String(stage))
      const stoppedAt = await page.evaluate(() => window.scrollY)
      await settledStory(story, stage)
      await page.waitForTimeout(450)
      expect(await page.evaluate(() => window.scrollY)).toBe(stoppedAt)
      const visuals = await story.evaluate(element => {
        const style = getComputedStyle(element)
        return Object.fromEntries(['--run-sandbox', '--run-tests', '--run-checks', '--run-verdict'].map(name => [name, Number(style.getPropertyValue(name))]))
      })
      expect(visuals['--run-sandbox']).toBe(1)
      expect(visuals['--run-tests']).toBe(stage === 2 ? 1 : 0)
      expect(visuals['--run-checks']).toBe(stage === 2 ? 1 : 0)
      expect(visuals['--run-verdict']).toBe(stage === 3 ? 1 : 0)
    }
  })

  test('probe labels clear before the verdict appears during forward and reverse transitions', async ({ page }) => {
    const story = page.getByTestId('run-story')
    await scrollStory(story, 0.59)
    await settledStory(story, 2)
    for (const [progress, stage] of [[0.76, 3], [0.46, 2]] as const) {
      const samples = await story.evaluate(async (element, destination) => {
        const track = element.querySelector<HTMLElement>('[data-testid="run-story-track"]')!
        const sticky = track.querySelector<HTMLElement>('.run-story-sticky')!
        const top = window.scrollY + track.getBoundingClientRect().top - 96 + (track.offsetHeight - sticky.offsetHeight) * destination
        const probes = element.querySelector('.run-scene-checks')!
        const result = element.querySelector('.run-scene-result')!
        const frames: { probes: number; result: number }[] = []
        window.scrollTo({ top, behavior: 'instant' })
        const start = performance.now()
        await new Promise<void>(resolve => {
          const sample = () => {
            frames.push({ probes: Number(getComputedStyle(probes).opacity), result: Number(getComputedStyle(result).opacity) })
            if (performance.now() - start < 550) requestAnimationFrame(sample)
            else resolve()
          }
          requestAnimationFrame(sample)
        })
        return frames
      }, progress)
      expect(samples.length).toBeGreaterThan(3)
      expect(samples.some(sample => sample.probes > 0 || sample.result > 0)).toBe(true)
      expect(samples.filter(sample => sample.probes > 0.01 && sample.result > 0.01)).toEqual([])
      await settledStory(story, stage)
    }
  })

  test('milestones work from the keyboard and keep focus while changing the scene', async ({ page }) => {
    const story = page.getByTestId('run-story')
    for (const [stage, name] of MILESTONES.entries()) {
      const button = story.getByRole('button', { name, exact: true })
      await button.press('Enter')
      await expect(button).toBeFocused()
      await expect(button).toHaveAttribute('aria-current', 'step')
      await expect(story).toHaveAttribute('data-stage', String(stage))
      await settledStory(story, stage)
    }
    await expect(recordedField(story)).toHaveAccessibleName('48 correct, 4 failed, 12 not applicable, out of 64 cases')
  })

  test('rapid direction changes settle at the current position without queued transitions', async ({ page }) => {
    const story = page.getByTestId('run-story')
    for (const progress of [0.90, 0.10, 0.60, 0.30, 0.90]) await scrollStory(story, progress)
    await expect(story).toHaveAttribute('data-stage', '3')
    await expect(story.getByRole('button', { name: 'Verdict', exact: true })).toHaveAttribute('aria-current', 'step')
    await expect.poll(() => story.evaluate(element => element.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length)).toBe(0)
    await settledStory(story, 3)
    await page.waitForTimeout(700)
    await expect(story).toHaveAttribute('data-stage', '3')
    await settledStory(story, 3)
  })

  test('hiding the document suspends the story and returning preserves its scroll position', async ({ page }) => {
    const story = page.getByTestId('run-story')
    await scrollStory(story, 0.60)
    await expect(story).toHaveAttribute('data-stage', '2')
    await expect(story).toHaveAttribute('data-active', 'true')
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await expect(story).toHaveAttribute('data-active', 'false')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    const frozen = await story.getAttribute('data-visual-progress')
    await page.waitForTimeout(400)
    await expect(story).toHaveAttribute('data-visual-progress', frozen!)
    await expect(story).toHaveAttribute('data-stage', '2')
    await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await expect(story).toHaveAttribute('data-active', 'true')
    await expect(story).toHaveAttribute('data-stage', '2')
    await settledStory(story, 2)
  })

  test('every sticky scene fits a 720px-tall desktop viewport', async ({ page }) => {
    const story = page.getByTestId('run-story')
    for (const width of [1024, 1280]) {
      await page.setViewportSize({ width, height: 720 })
      await expect(story).toHaveAttribute('data-mode', 'scroll')
      for (const [stage, progress] of [0.08, 0.32, 0.59, 0.92].entries()) {
        await scrollStory(story, progress)
        await expect(story).toHaveAttribute('data-stage', String(stage))
        await settledStory(story, stage)
        await expect.poll(() => story.evaluate(element => element.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length)).toBe(0)
        const selectors = ['.run-story-heading', '.run-rail', '.run-recording-label', '.run-scene-caption']
        if (stage === 2) selectors.push('.run-scene-checks')
        if (stage === 3) selectors.push('.run-scene-result')
        for (const selector of selectors) {
          const box = await story.locator(selector).boundingBox()
          expect(box, `${selector} is missing at ${width}px, stage ${stage}`).not.toBeNull()
          expect(box!.y, `${selector} is above the scene at ${width}px, stage ${stage}`).toBeGreaterThanOrEqual(95)
          expect(box!.y + box!.height, `${selector} is below the viewport at ${width}px, stage ${stage}`).toBeLessThanOrEqual(720)
          expect(box!.x).toBeGreaterThanOrEqual(0)
          expect(box!.x + box!.width).toBeLessThanOrEqual(width)
        }
      }
    }
  })

  test('resizing to a short window exposes all four static chapters', async ({ page }) => {
    const story = page.getByTestId('run-story')
    await scrollStory(story, 0.60)
    await page.setViewportSize({ width: 1440, height: 650 })
    await expect(story).toHaveAttribute('data-mode', 'static')
    await expect(story).toHaveAttribute('data-active', 'false')
    for (const chapter of ['parser', 'sandbox', 'tests', 'verdict']) {
      await expect(story.locator(`.run-story-chapter[data-chapter="${chapter}"]`)).toBeVisible()
    }
    await expect(recordedField(story)).toBeVisible()
    await page.setViewportSize({ width: 1440, height: 900 })
    await expect(story).toHaveAttribute('data-mode', 'scroll')
  })
})

test.describe('static parser run', () => {
  test('reduced motion keeps every step readable with no animated scene', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'static')
    for (const chapter of ['parser', 'sandbox', 'tests', 'verdict']) {
      await expect(story.locator(`.run-story-chapter[data-chapter="${chapter}"]`)).toBeVisible()
    }
    await expect(story).toHaveAttribute('data-active', 'false')
    expect(await story.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
  })

  test('a phone keeps the sequence in document flow and exposes the run action', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'static')
    const chapters = story.locator('.run-story-chapter')
    await expect(chapters).toHaveCount(4)
    let previousBottom = 0
    for (const chapter of await chapters.all()) {
      await chapter.scrollIntoViewIfNeeded()
      const box = await chapter.boundingBox()
      expect(box).not.toBeNull()
      const documentTop = box!.y + await page.evaluate(() => window.scrollY)
      expect(documentTop).toBeGreaterThanOrEqual(previousBottom - 1)
      previousBottom = documentTop + box!.height
    }
    await expect(story.getByRole('link', { name: 'Run the default parser', exact: true }).last()).toHaveAttribute('href', '/lab#run')
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

  test('the Lab story connects Daily to a real parser execution', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    await expect(page.getByText("Daily builds news editions around a reader's interests.", { exact: false })).toBeVisible()
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-run-id', RECORDED_EXECUTION)
    await expect(story).toContainText('count-guard-v1')
    await expect(story).toContainText('October 1, 2026')
    await expect(story).toContainText('64 cases')
    await expect(story).toContainText('22 fault-injected')
    await expect(story.getByRole('link', { name: 'Run the default parser', exact: true }).first()).toHaveAttribute('href', '/lab#run')
    await expect(page.getByTestId('hero-sieve')).toHaveCount(0)
    await expect(page.getByTestId('retrieval-loss-panel')).toHaveCount(0)
  })

  test('the recorded verdict identifies every outcome with a shape and counted legend', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    const field = recordedField(page.getByTestId('run-story'))
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

  test('the compact historical finding shows both measured outcomes at once', async ({ page }) => {
    await page.goto('/')
    const finding = page.locator('#experiment')
    for (const value of ['22.1%', '18.7%', '26.9%', '42.5%']) await expect(finding.getByText(value, { exact: true })).toBeVisible()
    await expect(finding).toContainText(/September 21|2026-09-21/)
    await expect(finding).toContainText(/historical working-tree experiment/i)
    await expect(finding.getByRole('link', { name: /finding|investigation/i })).toHaveAttribute('href', '/engineering')
    await expect(finding.getByRole('button', { name: 'Guard experiment', exact: true })).toHaveCount(0)
  })

  test('old section anchors still lead into the pinned evidence views', async ({ page }) => {
    await page.goto('/#pipeline')
    const pipeline = page.locator('#pipeline')
    await expect(pipeline).toBeInViewport()
    await expect(pipeline).toHaveAttribute('href', new RegExp(`^/evidence\\?run=${NARRATIVE_RUN}.*view=funnel`))
    await pipeline.click()
    await expect(page).toHaveURL((url) => url.pathname === '/evidence' && url.searchParams.get('run') === NARRATIVE_RUN && url.searchParams.get('view') === 'funnel')
    await page.goto('/#retrieval')
    const retrieval = page.locator('#retrieval')
    await expect(retrieval).toBeInViewport()
    await expect(retrieval).toHaveAttribute('href', new RegExp(`^/evidence\\?run=${NARRATIVE_RUN}.*view=stories.*outcome=lost-before-scorer`))
    await retrieval.click()
    await expect(page).toHaveURL((url) => url.searchParams.get('view') === 'stories' && url.searchParams.get('outcome') === 'lost-before-scorer')
  })
})

test.describe('pipeline evidence', () => {
  test('the pinned Ray funnel retains all ten exact populations', async ({ page }) => {
    await page.goto(`/evidence?run=${NARRATIVE_RUN}&persona=ray&view=funnel`)
    const table = page.getByRole('table', { name: 'Candidate funnel: survivors, articles lost entering each stage, and pass rate' })
    const counts = await table.locator('tbody tr td:first-of-type').allInnerTexts()
    expect(counts.map(count => Number(count.replaceAll(',', '')))).toEqual(RAY_SURVIVORS)
    await page.getByRole('combobox', { name: 'Reader fixture', exact: true }).selectOption('tom')
    await expect(page).toHaveURL((url) => url.searchParams.get('run') === NARRATIVE_RUN && url.searchParams.get('persona') === 'tom' && url.searchParams.get('view') === 'funnel')
    await expect(table.locator('tbody tr td:first-of-type').first()).toHaveText('1,362')
    await expect(table.locator('tbody tr td:first-of-type').last()).toHaveText('9')
  })

  test('all 97 losses remain inspectable in the recorded aggregate funnel', async ({ page }) => {
    await page.goto(`/evidence?run=${NARRATIVE_RUN}&view=funnel`)
    const rows = page.getByRole('table', { name: 'Must-see losses attributed by stage or mechanism' }).locator('tbody tr')
    for (const [stage, count] of [['lookback', 75], ['prefilter:cap', 9], ['blended', 9], ['rank', 4]] as const) {
      await expect(rows.filter({ hasText: stage }).getByRole('cell')).toHaveText(String(count))
    }
  })

  test('the full historical comparison remains interactive in Findings', async ({ page }) => {
    await page.goto('/engineering')
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
    await expect(panel).toContainText(/historical working-tree experiment/i)
    await original.click()
    await expect(panel.getByTestId('guard-metric-recall')).toContainText('22.1%')
    await expect(panel.getByTestId('guard-metric-unwanted')).toContainText('26.9%')
  })
})

test.describe('server-rendered opening', () => {
  test.use({ javaScriptEnabled: false })

  test('the four-step story and complete execution transcript work without JavaScript', async ({ page }) => {
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'static')
    for (const chapter of ['parser', 'sandbox', 'tests', 'verdict']) await expect(story.locator(`.run-story-chapter[data-chapter="${chapter}"]`)).toBeVisible()
    await expect(recordedField(story)).toHaveAccessibleName('48 correct, 4 failed, 12 not applicable, out of 64 cases')
    const summary = page.locator('summary').filter({ hasText: /^Inspect this recorded run/ })
    const timeline = page.getByTestId('recorded-run-timeline')
    await expect(timeline).toBeHidden()
    await summary.click()
    await expect(timeline).toHaveAttribute('data-run-id', RECORDED_EXECUTION)
    await expect(timeline.getByRole('list', { name: 'Recorded production execution timeline', exact: true })).toBeVisible()
    await expect(story).toContainText('count-guard-v1')
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
    await expect(rows.last().locator(':scope > span').first()).toHaveText('')
    const probes = rows.nth(4).getByRole('list', { name: 'Recorded isolation checks' })
    for (const label of ['DNS lookup fails', 'HTTPS request fails', 'Grader not on disk', 'No credentials in env']) {
      const probe = probes.getByRole('listitem').filter({ hasText: label })
      await expect(probe).toBeVisible()
      await expect(probe).toHaveAttribute('data-held', 'true')
      await expect(probe).toContainText('passed')
    }
    await expect(probes.getByRole('listitem')).toHaveCount(4)
    await expect(timeline).toContainText('f027762ab4d08b35')
    await expect(timeline).not.toContainText('A separate execution')
    await expect(timeline.locator(`a[href="/runs/${RECORDED_EXECUTION}.json"]`)).toBeVisible()
    await summary.click()
    await expect(timeline).toBeHidden()
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
