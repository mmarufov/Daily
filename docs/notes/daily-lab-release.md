# Daily Lab release verification, October 1, 2026

Public acceptance target: https://marufov.com. No localhost server was used.
Implementation started in an isolated worktree at main `b95a9a63562a6c7b7c36550f1ca7f90ce5e4ceaa`.
The original `mmarufov/sydney-v11` checkout and unrelated changes were preserved.

## Release and rollback

- Runtime revision: `2aab0d75` (headline polish after `7948dfd1`).
- Public deployment: `dpl_9fqqwzF9FQYdm7nPnEyXFq22dZ3W`,
  https://daily-ai3gwqr1z-mmarufovs-projects.vercel.app.
- Previous production, retained for rollback: `dpl_C3iXth1No7VtHRMdGuTLJwv3h82L`,
  https://daily-7xtpnq75o-mmarufovs-projects.vercel.app.
- Source review and CI: https://github.com/mmarufov/Daily/pull/91.

The public custom domain was inspected directly. SSO-gated previews were not used
as acceptance evidence. The APIs, evaluator, admission limits and news backend
were not changed. The evidence exporter now explicitly uses seven-character Git
abbreviations so object counts cannot spuriously rewrite published artifacts.

## Verification

- TypeScript and production build pass.
- Unit tests: 279 passed, one existing skip, across 21 files.
- Nine evaluation artifacts and 39 Lab records validate. Regenerating all exports
  produces no changes to the published evidence or reader data.
- Production Playwright: 202 passed, two intentional mobile keyboard-tab skips.
  Chromium 153.0.8010.12 and WebKit 26.6, desktop plus Pixel 7 and iPhone 14 profiles.
- Layout checks cover 320, 375, 768, 1024, 1280 and 1920 CSS pixels, including the
  evidence tables, Lab records and reader. No document horizontal overflow.
- Coverage includes exact sieve populations and stages, fixture switching,
  pause/replay/scrubbing, hidden/offscreen interruption, reduced motion,
  server-rendered content, accessible summaries and controls, deep links, preserved
  query state, both guard metric states and provenance, missing-data rendering,
  runner validation, quotas, unavailable, rejected, accepted, interrupted and expired
  outcomes. Console and hydration checks pass.
- All routine Lab API requests are intercepted. Unexpected Lab requests fail the
  test instead of consuming production allowance.

## One real default-parser run

https://marufov.com/lab?run=wrun_01M3X2KSBTMEPWJJZT74HCTHX3#run

Started explicitly through the public Run in Sandbox button. HTTP 202 admitted it;
terminal status was `completed`, independently graded `rejected`. Reload restored
both the terminal result and the named fault. Verified at 2026-10-02T01:11:00Z.

- 48 correct, three wrong associations, one case that should have been refused,
  12 not applicable; zero crashes, timeouts or missing records.
- Criteria generation 2, hash `f027762ab4d08b35`.
- Sandbox `chocolate-head-tyrannosaurus-mCMKbR`, `iad1`, Python 3.13, deny-all
  networking. All four reported isolation probes held.
- The event console showed the actual scope, creation, upload, harness, isolation
  and shutdown events. No case grades were simulated during execution.

This rejection is the expected demonstration of the default parser's known gap,
not a failure of the runner. It is separate from the September 21 quality experiment.

## Performance lab

Measured on the public deployment at `7948dfd1`; the final follow-up changes only
headline sizing above mobile widths and deployment exclusions. Full samples are in
[daily-lab-performance.json](daily-lab-performance.json).

Three fresh, cache-disabled Chromium contexts, Pixel 7 at 412 by 839 CSS pixels,
4x CPU slowdown, 1.6 Mbps download, 750 Kbps upload and 150 ms network latency,
on a macOS host. Browser PerformanceObserver measurements, not field data.

- LCP: 1.044, 0.968 and 0.976 seconds; median 0.976 seconds, target <=2.5 seconds.
- CLS: 0.02048 in every sample; target <=0.1.
- Longest observed task: 95 ms under CPU throttling.
- After scrolling away, playback was stopped, with zero sieve DOM mutations in
  each two-second inactive sample. No background replay restarted on return.

## Captured artifacts

Saved under the original workspace's gitignored `.context/`:

- `redesign-desktop.png`, `redesign-mobile.png`: first viewport, CSS-pixel scale.
- `redesign-desktop-full.png`, `redesign-mobile-full.png`: complete homepage.
- `redesign-lab.png`: workspace layout.
- `redesign-real-run.png`, `redesign-real-run.json`: real execution and grading.
- `redesign-e2e-final.log`: complete production browser suite.
- `redesign-polish-checks.log`: final homepage/layout checks after headline polish.
- `redesign-performance.json`, `redesign-profile.cjs`: samples and measurement method.

The historical experiment is published at `/experiments/batch-alignment.json` with
source hashes and explicit limits: the exact historical working-tree guard bytes
are unknown; cache-key sets differ; provisional relevance labels are not human
truth; six historical failures are not presented as current CI status.
