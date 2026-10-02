import { expect, test as base, type Page, type Route } from '@playwright/test'

const LAB_API = /^https?:\/\/[^/]+\/api\/lab(?:\/|$)/

/**
 * Production pages are real; running visitor code is always mocked.
 *
 * A test-specific route registered later takes precedence over this guard.
 * An unexpected endpoint, method, or run ID receives a local refusal and
 * fails the test instead of spending production quota or starting a microVM.
 */
export const test = base.extend({
  page: async ({ context, page }, use) => {
    const unmocked: string[] = []
    // Context routing also covers popups. Service workers are blocked by the
    // config so they cannot bypass this interception.
    await context.route(LAB_API, async (route) => {
      const request = route.request()
      unmocked.push(`${request.method()} ${new URL(request.url()).pathname}`)
      await route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({ error: 'The browser acceptance test did not mock this Lab request.' }),
      })
    })

    await use(page)

    expect(unmocked, 'Every Lab API request must have an explicit test mock').toEqual([])
  },
})

/** A mock only owns the exact endpoint and method it was written to answer. */
export async function mockLabRequest(
  page: Page,
  method: 'GET' | 'POST',
  path: string,
  answer: (route: Route) => Promise<void>,
) {
  if (!path.startsWith('/api/lab/')) throw new Error(`Not a Lab endpoint: ${path}`)
  await page.route((url) => url.pathname === path, async (route) => {
    if (route.request().method() !== method) {
      await route.fallback()
      return
    }
    await answer(route)
  })
}

export async function mockLabJson(page: Page, method: 'GET' | 'POST', path: string, body: unknown, status = 200) {
  await mockLabRequest(page, method, path, (route) => route.fulfill({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  }))
}

export { expect } from '@playwright/test'
