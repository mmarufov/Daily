import type { Locator } from '@playwright/test'

import { expect, test } from './fixtures'

/**
 * Motion is an enhancement. Native disclosure behaviour must survive it,
 * interruption, reduced motion and no JavaScript at all, and an interactive
 * reading must end on the last thing the visitor asked for.
 */
async function expectSettled(details: Locator, open: boolean) {
  await expect(details).toHaveJSProperty('open', open)
  await expect
    .poll(() =>
      details.evaluate((element) => ({
        running: element.getAnimations({ subtree: true }).filter((a) => a.playState === 'running').length,
        height: (element as HTMLElement).style.height,
        overflow: (element as HTMLElement).style.overflow,
      })),
    )
    .toEqual({ running: 0, height: '', overflow: '' })
}

function disclosure(summary: Locator) {
  return summary.locator('xpath=..')
}

const MEASURES = /^What it measures/

test.describe('disclosure motion', () => {
  test('opening renders an actual intermediate height before settling', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/lab')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: MEASURES })
    const details = disclosure(summary)
    await summary.scrollIntoViewIfNeeded()
    const sample = await summary.evaluate((element) => {
      const parent = element.parentElement as HTMLDetailsElement
      const closed = parent.getBoundingClientRect().height
      ;(element as HTMLElement).click()
      const animation = parent.getAnimations().find((candidate) => {
        const effect = candidate.effect as KeyframeEffect | null
        return effect?.getKeyframes().some((frame) => 'height' in frame)
      })
      if (!animation) return { animated: false, closed, middle: closed }
      // A fixed interior frame, so a slow machine cannot skip the animation.
      animation.pause()
      animation.currentTime = Number(animation.effect!.getTiming().duration) / 2
      const middle = parent.getBoundingClientRect().height
      animation.play()
      return { animated: true, closed, middle }
    })
    expect(sample.animated).toBe(true)
    await expectSettled(details, true)
    const expanded = await details.evaluate((element) => element.getBoundingClientRect().height)
    expect(sample.middle).toBeGreaterThan(sample.closed + 1)
    expect(sample.middle).toBeLessThan(expanded - 1)
  })

  test('opens and closes from the keyboard without losing focus or leaving a fixed height', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/lab')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: MEASURES })
    const details = disclosure(summary)
    const first = details.locator('li').first()
    await summary.scrollIntoViewIfNeeded()
    const closedHeight = await details.evaluate((element) => element.getBoundingClientRect().height)
    await summary.focus()
    await summary.press('Enter')
    await expectSettled(details, true)
    await expect(first).toBeVisible()
    await expect(summary).toBeFocused()
    await summary.press('Space')
    await expectSettled(details, false)
    await expect(first).toBeHidden()
    await expect(summary).toBeFocused()
    expect(await details.evaluate((element) => element.getBoundingClientRect().height)).toBeCloseTo(closedHeight, 0)
  })

  test('rapid reversals finish at the last requested state and remain usable', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/lab')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^The cases are public/ })
    const details = disclosure(summary)
    await summary.scrollIntoViewIfNeeded()
    // Dispatched directly: actionability waits would serialise the clicks and
    // hide a real rapid-input regression.
    for (const _ of [0, 1, 2]) {
      await summary.dispatchEvent('click')
      await page.waitForTimeout(60)
    }
    await expectSettled(details, true)
    await expect(details.getByText(/written against them/)).toBeVisible()
    for (const _ of [0, 1, 2]) {
      await summary.dispatchEvent('click')
      await page.waitForTimeout(60)
    }
    await expectSettled(details, false)
    await expect(details.getByText(/written against them/)).toBeHidden()
  })

  test('reduced motion applies state immediately', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/lab')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: MEASURES })
    const details = disclosure(summary)
    await summary.scrollIntoViewIfNeeded()
    for (const open of [true, false]) {
      const state = await summary.evaluate((element) => {
        ;(element as HTMLElement).click()
        const parent = element.parentElement as HTMLDetailsElement
        return {
          open: parent.open,
          running: parent.getAnimations({ subtree: true }).filter((a) => a.playState === 'running').length,
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
    await page.goto('/lab')
    for (const [label, content] of [
      [MEASURES, /association correctness/],
      [/^The cases are public/, /written against them/],
    ] as const) {
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

test.describe('interactive readings', () => {
  test('rapid toggles finish on the last requested reading', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    await page.goto('/')
    const defect = page.locator('section[aria-labelledby="defect"]')
    const production = defect.getByRole('radio', { name: 'What production does' })
    const guard = defect.getByRole('radio', { name: 'With the count guard' })
    await guard.scrollIntoViewIfNeeded()
    for (const button of [guard, production, guard, production, guard]) {
      await button.dispatchEvent('click')
      await page.waitForTimeout(40)
    }
    await expect(guard).toHaveAttribute('aria-checked', 'true')
    await expect(defect.getByText('42.5%')).toBeVisible()
    await expect(defect.getByText('18.7%')).toBeVisible()

    const ranking = page.locator('section[aria-labelledby="ranking"]')
    const toggle = ranking.getByRole('switch')
    await toggle.scrollIntoViewIfNeeded()
    for (const _ of [0, 1, 2]) {
      await toggle.dispatchEvent('click')
      await page.waitForTimeout(40)
    }
    await expect(toggle).toHaveAttribute('aria-checked', 'true')
    await expect(ranking.locator('p.readout')).toContainText('75')
  })

  test('reduced motion shows the new reading at once', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/')
    const defect = page.locator('section[aria-labelledby="defect"]')
    await defect.getByRole('radio', { name: 'With the count guard' }).click()
    // No easing: the final value is on screen in the same frame as the click.
    await expect(defect.getByText('42.5%')).toBeVisible({ timeout: 500 })
  })
})
