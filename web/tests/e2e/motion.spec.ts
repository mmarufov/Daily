import type { Locator } from '@playwright/test'

import { expect, test } from './fixtures'

/** Native disclosure behavior must survive enhancement, interruption, and no JS. */
async function expectSettled(details: Locator, open: boolean) {
  await expect(details).toHaveJSProperty('open', open)
  await expect.poll(() => details.evaluate((element) => ({
    running: element.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length,
    height: (element as HTMLElement).style.height,
    overflow: (element as HTMLElement).style.overflow,
  }))).toEqual({ running: 0, height: '', overflow: '' })
}

function disclosure(summary: Locator) {
  return summary.locator('xpath=..')
}

test.describe('disclosure motion', () => {
  test('opening renders an actual intermediate height before settling', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Experiment provenance$/ })
    const details = disclosure(summary)
    await summary.scrollIntoViewIfNeeded()
    const sample = await summary.evaluate(element => {
      const parent = element.parentElement as HTMLDetailsElement
      const closed = parent.getBoundingClientRect().height
      ;(element as HTMLElement).click()
      const animation = parent.getAnimations().find(candidate => {
        const effect = candidate.effect as KeyframeEffect | null
        return effect?.getKeyframes().some(frame => 'height' in frame)
      })
      if (!animation) return { animated: false, closed, middle: closed }
      // Sample a deterministic interior frame so a slow CI machine cannot
      // skip the entire animation between two Playwright commands.
      animation.pause()
      animation.currentTime = Number(animation.effect!.getTiming().duration) / 2
      const middle = parent.getBoundingClientRect().height
      animation.play()
      return { animated: true, closed, middle }
    })
    expect(sample.animated).toBe(true)
    await expectSettled(details, true)
    const expanded = await details.evaluate(element => element.getBoundingClientRect().height)
    expect(sample.middle).toBeGreaterThan(sample.closed + 1)
    expect(sample.middle).toBeLessThan(expanded - 1)
  })

  test('provenance opens and closes from the keyboard without losing focus or leaving a fixed height', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Experiment provenance$/ })
    const details = disclosure(summary)
    const sourceLink = details.getByRole('link', { name: /Inspect summary and source hashes/ })
    await summary.scrollIntoViewIfNeeded()
    const closedHeight = await details.evaluate(element => element.getBoundingClientRect().height)

    await summary.press('Enter')
    await expectSettled(details, true)
    await expect(sourceLink).toBeVisible()
    await expect(summary).toBeFocused()
    expect(await details.evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThan(closedHeight)

    await summary.press('Space')
    await expectSettled(details, false)
    await expect(sourceLink).toBeHidden()
    await expect(summary).toBeFocused()
    expect(await details.evaluate(element => element.getBoundingClientRect().height)).toBeCloseTo(closedHeight, 0)
  })

  test('rapid reversals finish at the last requested state and remain usable', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/lab')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Limits of this evidence$/ })
    const details = disclosure(summary)
    await summary.scrollIntoViewIfNeeded()
    // Dispatch directly because actionability's stability wait would serialize
    // clicks until the animation stops, masking a real rapid-input regression.
    await summary.dispatchEvent('click')
    await page.waitForTimeout(60)
    await summary.dispatchEvent('click')
    await page.waitForTimeout(60)
    await summary.dispatchEvent('click')
    await expectSettled(details, true)
    await expect(details.getByText(/The cases are public/)).toBeVisible()

    await summary.dispatchEvent('click')
    await page.waitForTimeout(60)
    await summary.dispatchEvent('click')
    await page.waitForTimeout(60)
    await summary.dispatchEvent('click')
    await expectSettled(details, false)
    await expect(details.getByText(/The cases are public/)).toBeHidden()
    await summary.click()
    await expectSettled(details, true)
  })

  test('large Lab sections return to their natural height after opening and resizing', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/lab')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Every published run/ })
    const details = disclosure(summary)
    await summary.click()
    await expectSettled(details, true)
    await expect(details.getByRole('link')).toHaveCount(39)
    const viewport = page.viewportSize()!
    await page.setViewportSize({ width: viewport.width > 600 ? 375 : 768, height: viewport.height })
    await expectSettled(details, true)
    // The final inventory link must stay inside the expanded disclosure after
    // text reflows; a stale pixel height clips it at narrow widths.
    const lastLinkBottom = await details.getByRole('link').last().evaluate(element => element.getBoundingClientRect().bottom)
    const detailsBottom = await details.evaluate(element => element.getBoundingClientRect().bottom)
    expect(lastLinkBottom).toBeLessThanOrEqual(detailsBottom + 1)
    await summary.click()
    await expectSettled(details, false)
  })

  test('reduced motion applies state immediately without a running disclosure animation', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Experiment provenance$/ })
    const details = disclosure(summary)
    await summary.scrollIntoViewIfNeeded()
    for (const open of [true, false]) {
      const state = await summary.evaluate(element => {
        (element as HTMLElement).click()
        const parent = element.parentElement as HTMLDetailsElement
        return {
          open: parent.open,
          running: parent.getAnimations({ subtree: true }).filter(animation => animation.playState === 'running').length,
          height: parent.style.height,
        }
      })
      expect(state).toEqual({ open, running: 0, height: '' })
      await expectSettled(details, open)
    }
  })
})

test.describe('disclosures without JavaScript', () => {
  test.use({ javaScriptEnabled: false })

  test('native summaries expose and hide evidence without hydration', async ({ page }) => {
    for (const [path, label, content] of [
      ['/', /^Experiment provenance$/, /Exact working-tree implementation bytes remain unknown/],
      ['/lab', /^Limits of this evidence$/, /The cases are public/],
    ] as const) {
      await page.goto(path)
      const summary = page.locator('summary').filter({ hasText: label })
      const details = disclosure(summary)
      await summary.click()
      await expect(details).toHaveAttribute('open', '')
      await expect(details.getByText(content)).toBeVisible()
      await summary.click()
      await expect(details).not.toHaveAttribute('open', '')
      await expect(details.getByText(content)).toBeHidden()
    }
  })
})


test.describe('finding selection motion', () => {
  test('rapid selection changes finish on the exact last requested evidence', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const guard = page.getByTestId('guard-experiment-panel')
    const original = guard.getByRole('button', { name: 'Original', exact: true })
    const experiment = guard.getByRole('button', { name: 'Guard experiment', exact: true })
    await experiment.scrollIntoViewIfNeeded()
    for (const button of [experiment, original, experiment, original, experiment]) {
      await button.dispatchEvent('click')
      await page.waitForTimeout(40)
    }
    await expect(experiment).toHaveAttribute('aria-pressed', 'true')
    await expect(original).toHaveAttribute('aria-pressed', 'false')
    await expect(guard.getByTestId('guard-metric-recall')).toContainText('18.7%')
    await expect(guard.getByTestId('guard-metric-unwanted')).toContainText('42.5%')
    await expect(guard.getByText('Refusing the mismatch exposed the cost.')).toBeVisible()
    await expect.poll(() => guard.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)

    const retrieval = page.getByTestId('retrieval-loss-panel')
    const stages = ['Rank cutoff: 4 of 97 losses', 'Lookback: 75 of 97 losses', 'Scoring: 9 of 97 losses']
    await retrieval.scrollIntoViewIfNeeded()
    for (const name of stages) {
      await retrieval.getByRole('button', { name, exact: true }).dispatchEvent('click')
      await page.waitForTimeout(40)
    }
    await expect(retrieval.getByRole('heading', { name: 'Scoring removed 9' })).toBeVisible()
    await expect(retrieval.locator('button[aria-pressed="true"]')).toHaveCount(1)
    await expect(retrieval.getByRole('button', { name: stages[2], exact: true })).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(() => retrieval.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
  })

  test('reduced motion keeps finding changes immediate and animation free', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const guard = page.getByTestId('guard-experiment-panel')
    await guard.getByRole('button', { name: 'Guard experiment', exact: true }).click()
    await expect(guard.getByTestId('guard-metric-recall')).toContainText('18.7%')
    expect(await guard.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
    const retrieval = page.getByTestId('retrieval-loss-panel')
    await retrieval.getByRole('button', { name: 'Rank cutoff: 4 of 97 losses', exact: true }).click()
    await expect(retrieval.getByRole('heading', { name: 'Rank cutoff removed 4' })).toBeVisible()
    expect(await retrieval.evaluate(element => element.getAnimations({ subtree: true }).length)).toBe(0)
  })
})
