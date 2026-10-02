# Daily-first restoration and restrained polish

The owner preferred the pre-composition version. This release restores the web
presentation from d1ca5383 and limits new polish to the guard comparison card.

- Product PR: https://github.com/mmarufov/Daily/pull/98
- Branch: mmarufov/daily-subtle-polish
- Application revision: 50f8cfee9147c0e17f04dc03fe23a32370d11059
- Production deployment: dpl_9byHrzi5cKfpYpNDB9xSoimSxMsm,
  https://daily-qdtvs7urg-mmarufovs-projects.vercel.app.
- Previous deployment retained: dpl_7nvepyvqQKdVvDFZYw1RLKGJrsYe,
  https://daily-m8fh4ibff-mmarufovs-projects.vercel.app.

Compared with d1ca5383, only web/app/findings.css differs at runtime: guard-card
padding is capped at 32px, metric numerals at 64px, chart bars at 28px and a few
internal gaps are reduced. All component/page code, copy, recorded data, animation
behavior, font loading, navigation, editor and execution logic match the earlier
version. The superseded composition release reports remain historical records.
The original dirty Sydney checkout is untouched.

Validation:

- TypeScript, 304 unit tests (one existing skip), artifact regeneration with no
  data differences, and production build passed.
- PR CI passed: artifact build, mandatory deterministic contracts, 31 degradation
  tests, 2,719 offline backend tests (185 skips, 239 subtests) and 155 PostgreSQL
  contracts.
- Production Chromium/WebKit acceptance: 259 passed, two intentional mobile
  keyboard skips. Lab requests mocked; no Sandbox allowance consumed.
- Reused completed run wrun_01M3X9RYY80MHVRYFT7GWSWCN0 via GET/reload only:
  completed/rejected result and 64 cases restored after reload, zero page errors
  and zero submissions. No new Sandbox submission.
- Desktop/tablet/390px/320px static renders fit both themes without overflow.
- Final production screenshots: .context/subtle-after/ in the original Sydney
  workspace. Tests/logs: subtle-unit.log, subtle-export.log, subtle-build.log,
  subtle-e2e.log, subtle-existing-run.json and subtle-deployment.json.
- Mobile performance: LCP 1,052 / 1,004 / 996ms (median 1,004ms), CLS 0.01555 or
  less. Three fresh cache-disabled headless Chromium Pixel 7 contexts, 412x839,
  4x CPU slowdown, 1.6 Mbps down, 750 Kbps up, 150ms latency on macOS. Laboratory
  results, not field percentiles. Inactive sieve: playback false and zero DOM
  mutations over two seconds in all samples.
