# Daily composition release verification

Verified October 1, 2026 (October 2 UTC) on https://marufov.com.

## Revision and scope

- Composition PR: https://github.com/mmarufov/Daily/pull/95
- Browser follow-up: https://github.com/mmarufov/Daily/pull/96
- Branch: `mmarufov/daily-composition`, started from `d1ca5383ea3c97c5f20bcce4605c58e19cf71162`.
- Initial application merge: `9f8f48ced99cfca4c74b415f8084b7f58fb71c19`.
- Final application merge: `46e6c16ef3338c24b53925804e6abe400e1f140c`.
- Verified production deployment: `dpl_7nvepyvqQKdVvDFZYw1RLKGJrsYe`,
  https://daily-m8fh4ibff-mmarufovs-projects.vercel.app.
- Retained pre-composition rollback: `dpl_C8pv3tYtUk5cKibT8t6EtKKkFmvt`,
  https://daily-gcfazxbn4-mmarufovs-projects.vercel.app.

The homepage now separates introductions from primary evidence. The Lab has a
full-width execution timeline/result row; guard metrics use an open comparison;
retrieval has a wide chart and paired explanation/story. Supporting pages use
consistent spacing, grouped filters, full-width tables and a clearer completed-run
hierarchy. The Daily-first hero and dark pipeline instrument are preserved.

Shared changes: `globals.css` adds the section-spacing token, applies it to the
footer and raises disclosure body text to 14px. `fonts.ts` is unchanged. Evidence
and Findings page changes are presentation and concise copy; query-state and data
selection logic are unchanged. No backend, API, evaluator, quota, artifact-format,
or execution changes. Sydney's original dirty checkout is preserved.

## Verification

- TypeScript, production build and artifact validation passed.
- Web units: 304 passed, one existing skip across 22 files.
- Nine evidence artifacts and 39 published Lab records validated; all exports
  reproduced committed data without differences.
- PR95 and PR96 CI passed: 31 degradation tests, 2,719 offline backend tests with 185 skips
  and 239 subtests, 155 PostgreSQL contracts, and the mandatory deterministic suites.
- Initial production acceptance: 260 passed, two intentional mobile keyboard skips,
  five failures. Three were the same stale fault-explanation selector after the case
  field moved earlier. Two exposed a 5px Evidence overflow at 320px in WebKit.
- PR96 scopes select styling so long labels stay inside the control and the 44px
  touch height is respected. Native option menus keep complete labels. The fault
  test now selects the exact case identifier instead of relying on list order.
- The select fix passed 40 diagnostic combinations across affected routes, both
  themes, five widths and Chromium/WebKit, including visible forced-color arrows.
- Final production-only Playwright: 265 passed, two intentional mobile keyboard
  skips, in desktop Chromium, mobile Chromium and mobile WebKit. All routine Lab
  APIs intercepted; no Sandbox submissions.
- Existing run wrun_01M3X9RYY80MHVRYFT7GWSWCN0 restored its completed/rejected result
  and all 64 cases after reload. Read-only verification blocked non-GET requests,
  recorded zero submissions and no JavaScript errors.
- The closed guard section is 757.11px at 1,440px in light and dark. Both toggle
  states retain the same natural height; expanded provenance grows without clipping.
- Desktop/mobile captures of all five routes returned HTTP 200 with no JavaScript
  errors or document overflow. Tablet and section captures supplement these.
- Browser checks cover 320-1,920px, evidence URL state, Reader profiles, keyboard and
  touch access, forced-color status marks, reduced motion, no-JavaScript evidence,
  interruptible disclosures and inactive sieve behavior.
- Cold homepage requests only Geist Sans and Mono; entering Reader loads Fraunces.

## Performance and evidence

Three fresh headless Chromium Pixel 7 contexts, 412x839 CSS pixels, disabled
cache, 4x CPU slowdown, 1.6 Mbps down, 750 Kbps up, 150ms latency, macOS host.
LCP: 1,048 / 992 / 984ms, median 992ms. CLS: 0.01555 or less in every sample.
These meet the 2.5s / 0.1 laboratory targets, not a claim about field percentiles.
After scrolling away, all samples reported playback false and zero sieve DOM
mutations over two seconds. Total page task time was 4.51 / 0.15 / 0.10ms.

Evidence is under the original Sydney workspace's gitignored `.context/`:

- `composition-before/`: all five routes, desktop/mobile, light/dark.
- `composition-after/`: corresponding captures plus tablet and section views.
- `composition-existing-run.json`, `composition-existing-run.png`.
- `composition-performance.json`, `composition-deployment.json`.
- `composition-e2e.log`, `composition-e2e-final.log`, `composition-ci-backend.log`.
- `composition-unit.log`, `composition-export.log`, `composition-build.log`.
- `composition-fix-build.log`, `composition-fault-rerun.log`.

The documentation follow-up records post-deployment results without changing the
validated application tree or starting another Sandbox execution.
