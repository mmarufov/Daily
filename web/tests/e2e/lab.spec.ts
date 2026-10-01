import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { expect, test, type Page } from '@playwright/test'

import { decide, PUBLIC_RUN_LIMITS } from '../../lib/lab/public-limits'
import { handleRunRequest } from '../../lib/lab/public-run'
import { finishedRunBody } from '../fixtures/live-outcome'

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
    await expect(page.getByRole('link', { name: 'Run a parser yourself' })).toBeVisible()
    // What is live and what is replayed, said where a reader starts. The
    // execution is live; the model responses it parses are not.
    await expect(page.getByText(/live parser runs against recorded responses/i).first()).toBeVisible()
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

  test('never claims more agent work than the manifest records', async ({ page }) => {
    // This asserted "No agent has run" while that was true. Agents have run
    // since, so the page rightly stopped saying it and the old assertion
    // stopped matching. The claim is now counted from the manifest, and so is
    // what this test expects: how many investigations were published, and how
    // many of them actually proposed a candidate.
    const manifest = JSON.parse(readFileSync(join(__dirname, '..', '..', 'public', 'lab-artifacts', 'manifest.json'), 'utf8')) as {
      entries: { investigated: boolean; runner: string }[]
    }
    const investigated = manifest.entries.filter((e) => e.investigated)
    const proposed = investigated.filter((e) => e.runner !== 'none')
    expect(investigated.length).toBeGreaterThan(0)
    await page.goto('/lab')
    await expect(page.getByText('Agent proposals, graded like any other').first()).toBeVisible()
    await expect(
      page.getByText(new RegExp(`${investigated.length} investigator runs are published\\. ${proposed.length} of them proposed a candidate`)).first(),
    ).toBeAttached()
    await expect(page.getByText(/ended without a proposal and are published\s+anyway/).first()).toBeAttached()
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

/**
 * The live runner, in a browser, without a microVM.
 *
 * These cannot start real runs, so the two API routes are answered from
 * here. Nothing in those answers is typed in: refusals come from the real
 * `decide()` and request handler, and the finished run is a committed record
 * bundle graded by the real evaluator. What is under test is that the page
 * says what the server said.
 */
test.describe('the live runner', () => {
  const T = Date.parse('2026-10-01T10:30:00.000Z')

  async function refuseWith(page: Page, body: unknown, status = 429) {
    await page.route('**/api/lab/run', (route) =>
      route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }),
    )
  }

  test('opens with a committed parser in the editor, so the first click needs no typing', async ({ page }) => {
    await page.goto('/lab')
    const editor = page.locator('#candidate-source')
    await expect(editor).toHaveValue(/VERSION_ID = "count-guard-v1"/)
    await expect(page.getByRole('button', { name: 'Run it in a microVM' })).toBeEnabled()
    // All 64 cases, before anything has run: hollow, and split as the suite is.
    await expect(page.locator('[data-case]')).toHaveCount(64)
    await expect(page.locator('[data-tone="pending"]')).toHaveCount(64)
    await expect(page.getByText('Fault-injected · 22')).toBeVisible()
    await expect(page.getByText(/5 runs an hour from one address, 3 at once/)).toBeVisible()
  })

  test('a refused run says which limit was hit and when it resets', async ({ page }) => {
    const refusal = decide(
      { active: 1, active_earliest_expiry: null, address: 6, address_oldest: T - 40 * 60_000, runs_today: 9, cpu_ms_today: 0 },
      T,
    )
    expect(refusal?.limit).toBe('per-address')
    await refuseWith(page, refusal)
    await page.goto('/lab')
    await page.getByRole('button', { name: 'Run it in a microVM' }).click()
    await expect(page.getByText('Not started: the hourly limit for one address')).toBeVisible()
    await expect(page.getByText(/has started 5 runs in the last hour/)).toBeVisible()
    await expect(page.getByText(/Resets at 10:50 UTC/)).toBeVisible()
    await expect(page.getByText(/A refused request is not counted against you/)).toBeVisible()
  })

  test('a run over the daily cap is refused until midnight UTC', async ({ page }) => {
    const refusal = decide(
      { active: 1, active_earliest_expiry: null, address: 1, address_oldest: T, runs_today: PUBLIC_RUN_LIMITS.runs_per_day + 1, cpu_ms_today: 0 },
      T,
    )
    expect(refusal?.limit).toBe('daily-runs')
    await refuseWith(page, refusal)
    await page.goto('/lab')
    await page.getByRole('button', { name: 'Run it in a microVM' }).click()
    await expect(page.getByText('Not started: the daily run ceiling')).toBeVisible()
    await expect(page.getByText(/50 runs have started today across every visitor/)).toBeVisible()
    await expect(page.getByText(/Resets at 00:00 UTC/)).toBeVisible()
  })

  test('a deployment with no counter says the runner is closed', async ({ page }) => {
    const closed = await handleRunRequest(
      new Request('https://marufov.com/api/lab/run', {
        method: 'POST',
        body: JSON.stringify({ candidate_id: 'visitor', source: 'def parse(a, r):\n    pass\n' }),
      }),
      { gate: null, env: {}, start: async () => ({ runId: 'never' }) },
    )
    expect(closed.status).toBe(503)
    await refuseWith(page, await closed.json(), 503)
    await page.goto('/lab')
    await page.getByRole('button', { name: 'Run it in a microVM' }).click()
    await expect(page.getByText(/public runner is closed on this deployment/)).toBeVisible()
  })

  test('a run a fault-injected case catches names the fault and why', async ({ page }) => {
    const runId = 'wrun_e2e_count_guard'
    await page.route('**/api/lab/run', (route) =>
      route.fulfill({ status: 202, contentType: 'application/json', body: JSON.stringify({ run_id: runId, suspend_seconds: 0, address_runs_left: 4 }) }),
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

    await page.goto('/lab')
    await page.getByRole('button', { name: 'Run it in a microVM' }).click()
    await expect(page.getByText('Caught by a fault-injected case')).toBeVisible()
    const fault = page.locator('li').filter({ hasText: 'syn-positional-reordered' }).first()
    await expect(fault).toContainText('equal length, internally reordered')
    await expect(fault).toContainText('instead of refusing')
    await expect(page.locator('[data-case="syn-positional-reordered"]')).toHaveAttribute('data-tone', 'wrong')
    await expect(page.locator('[data-tone="pending"]')).toHaveCount(0)
    await expect(page.getByText('Rejected').first()).toBeVisible()
    // These bundles ran locally, so there is no microVM to report, and the
    // page must say that rather than show zeros.
    await expect(page.getByText('This run reported no microVM evidence.')).toBeVisible()
    await expect(page).toHaveURL(new RegExp(`\\?run=${runId}`))

    // The fault's description comes from the frozen case suite and contains
    // an em dash; it is marked verbatim, and nothing else on the page is.
    const dashes = await page.evaluate(() => {
      const hits: string[] = []
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
      for (let n = walker.nextNode(); n !== null; n = walker.nextNode()) {
        const parent = n.parentElement
        if (parent === null || parent.closest('script, style, noscript, [data-verbatim]') !== null) continue
        if ((n.textContent ?? '').includes('\u2014')) hits.push((n.textContent ?? '').trim().slice(0, 110))
      }
      return hits
    })
    expect(dashes).toEqual([])
  })

  test('an accepted parser is told no fault caught it, and which fault was not scored', async ({ page }) => {
    const runId = 'wrun_e2e_keyed'
    await page.route(`**/api/lab/run/${runId}`, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(finishedRunBody(runId, 'keyed-v2')) }),
    )
    // Reached by link, the way a shared run is.
    await page.goto(`/lab?run=${runId}#run`)
    await expect(page.getByText('No fault-injected case caught this parser')).toBeVisible()
    await expect(page.getByText(/21 of the 22 faults apply to the protocol it declared/)).toBeVisible()
    await expect(page.getByText(/Not scored is not passed/)).toBeVisible()
    await expect(page.locator('[data-case="syn-positional-reordered"]')).toHaveAttribute('data-tone', 'unscored')
    await expect(page.getByText('Accepted for review').first()).toBeVisible()
  })
})

