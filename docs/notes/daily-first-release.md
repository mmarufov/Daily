# Daily-first release verification

Verified October 1, 2026 (October 2 UTC) on https://marufov.com.

## Revision and scope

- Product PR: https://github.com/mmarufov/Daily/pull/93
- Branch: `mmarufov/daily-first`; implementation head `b2412f9f`.
- Rebased onto current main `814fac639842b8cf336dbb91ee7acce8e7bc9634` (already up to date).
- Merged application revision: `69e77f97ce5af1f318ccfb185d13b0132a981a51`.
- Verified production deployment: `dpl_C8pv3tYtUk5cKibT8t6EtKKkFmvt`,
  https://daily-gcfazxbn4-mmarufovs-projects.vercel.app.
- Retained rollback: `dpl_9pt5q3K8ej2EkWBwETeHxrACgpaD`,
  https://daily-8555a859v-mmarufovs-projects.vercel.app.

Daily introduces the product with three unchanged headlines from Ray's pinned
edition. The Lab is the first substantial section. Its production timeline was
extracted from `07caa9cc`, without its page, runner or backend. The original raw
record is byte-identical. Its spec 2 execution is explicitly separate from the
published spec 1 result. The hero category eyebrow is removed.

No backend, evaluator, execution or admission-control changes. Shared presentation
changes are the Daily shell/metadata, Reader navigation, status marks, and font
scoping. `globals.css` changes mobile navigation, the fallback editorial token and
pair-title typography. `fonts.ts` retains only Geist; Reader owns Fraunces.
`evidence/page.tsx` changes two error headings to Geist. `engineering/page.tsx`
is unchanged. The original Sydney checkout remains untouched.

## Checks

- TypeScript and production build passed.
- Unit tests: 304 passed, one existing skip, 22 test files.
- Nine evaluation artifacts and 39 published Lab records validated; re-exporting
  artifacts, editions and Lab records produced no diff.
- PR CI passed: web artifacts/build; required deterministic contracts; degradation
  matrix (31 passed); offline backend suite (2,719 passed, 185 skipped,
  239 subtests passed); PostgreSQL contracts (155 passed).
- Production-only Playwright: 259 passed, two intentional mobile keyboard skips,
  across desktop Chromium, mobile Chromium and mobile WebKit. All routine Lab
  endpoints were intercepted, so these tests consumed no Sandbox runs.
- Verified 320-1,920px layouts, unchanged evidence/query links, Reader profiles,
  grayscale/forced-color status distinctions, keyboard controls, reduced motion,
  no-JavaScript content, no hydration/console errors, interruptible disclosures,
  and no horizontal document scrolling.
- Cold homepage requested only Geist Sans and Mono, including after idle and
  exposing footer links. Entering Reader loaded Fraunces and used it for headlines.
- The below-fold sieve remained inactive until reached and paused when hidden or
  offscreen. Returning did not restart playback.

## One real production run

Exactly one default-parser submission was made after deployment:
https://marufov.com/lab?run=wrun_01M3X9RYY80MHVRYFT7GWSWCN0#run

The request returned 202. It reached `completed`, independently graded `rejected`
as expected for `count-guard-v1`: 48 correct, three wrong associations, one
should-have-refused, 12 not applicable, zero crashes/timeouts/missing records.
Criteria generation 2, hash `f027762ab4d08b35`. All four isolation probes held:
DNS, HTTPS, evaluator absence and credential absence. Reloading the shared URL
restored terminal status and all 64 case results without a second submission.

## Performance and visual evidence

Three fresh headless Chromium Pixel 7 contexts, 412x839 CSS pixels, cache disabled,
4x CPU slowdown, 1.6 Mbps down, 750 Kbps up, 150ms latency, macOS host. LCP was
1,068 / 968 / 1,080ms (median 1,068ms); CLS was 0.01555 or less in every sample.
This meets the 2.5s / 0.1 laboratory targets, not a claim about field percentiles.
After scrolling away, all samples reported playback false and zero sieve DOM
mutations over two seconds; total page task time was 5.40 / 0.12 / 0.19ms.

Evidence is saved under the original Sydney workspace's gitignored `.context/`:

- `daily-first-live-desktop.png`, `daily-first-live-mobile.png`
- `daily-first-live-desktop-full.png`, `daily-first-live-mobile-full.png`
- `daily-first-live-desktop-lab-section.png`, `daily-first-live-mobile-lab-section.png`
- `daily-first-real-run.json`, `daily-first-real-summary.json`, `daily-first-real-run.png`
- `daily-first-performance.json`, `daily-first-visual-check.json`
- `daily-first-e2e.log`, `daily-first-final-unit.log`, `daily-first-final-build.log`
- `daily-first-ci-backend.log`, `daily-first-deployment.json`

A documentation-only follow-up records these post-deployment checks; it does not
change the validated application tree or require another Sandbox submission.
