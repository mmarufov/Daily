# Motion resilience

Base: bda6b69c, October 2, 2026. Work stays on a review branch. No merge or production deployment.

## References

- [Vercel interface guidelines](https://vercel.com/design/guidelines): preserve native scrolling, keyboard alternatives, visible focus, reduced motion, interruptible transitions, and low-cost rendering. Test zoom, throttled devices and multiple browser engines.
- [WCAG animation from interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html): allow interaction-triggered motion to be disabled while keeping the content usable.
- [MDN pageshow](https://developer.mozilla.org/en-US/docs/Web/API/Window/pageshow_event): refresh position-dependent state when a frozen document returns from browser history; visibility needs separate handling.
- [web.dev animation performance](https://web.dev/articles/animations-guide): keep frame work small, prefer transforms and opacity, and measure rendering under load.

## Requirements

- Complete server-rendered content is usable with JavaScript disabled, delayed or blocked, and with unavailable animation capabilities.
- Scroll enhancement requires supported APIs, suitable viewport size, readable content that fits, and no reduced-motion preference.
- Keep the current pacing and native wheel/touch/keyboard scrolling. Add no interception, scroll locks, or continuous background work.
- Preserve the reader's place and keyboard focus when switching layouts, changing text size, printing or restoring browser history.
- Keep every phase readable in print and accessible without relying on motion.
- Reconcile restored/re-entered geometry, font/layout changes and visibility without stale frames or leaked listeners.
- Verify fast reversals, skipped stages, threshold holds, browser navigation, resize, reduced motion changes, script failure, enlarged text, forced colors, print and CPU throttling.
- Preserve all recorded data, controls, source links and runner behavior. Add no new disclaimers.

## Checklist

- [x] Establish clean isolated checkout and inspect current code.
- [x] Research primary guidance and record scope.
- [x] Reproduce edge failures in deployed browsers.
- [x] Implement targeted fixes with regression tests.
- [x] Run typecheck, unit tests, artifact validation, build and preview browser suite.
- [x] Review desktop/mobile/print evidence, profile inactive work and document measured limits.
- [x] Commit and publish an unmerged review PR with preview evidence.

## Verified behavior

| Condition | Result |
| --- | --- |
| JavaScript disabled, blocked or delayed | Complete server-rendered chapters stay readable. Late hydration preserves the chapter already being read. |
| Missing intersection or resize observers | Static chapters remain usable without a page error. |
| Reduced motion, narrow or short viewport | Static chapters replace the sticky scene. Live changes preserve the reading stage and keyboard focus. |
| Enlarged text or spacing overrides | Content-fit checks switch to the static layout before the verdict overflows. |
| Font requests fail | The recording remains readable with fallback fonts. |
| Page hidden, offscreen or suspended | Scroll listening and frame work stop. Returning reconciles the current position. |
| Back, Forward and reload | Static content or the settled scene matches the position the browser restores. |
| Fast reversals and skipped stages | Existing thresholds and reverse buffer hold; transitions finish at the selected stage. |
| A 500ms main-thread stall | The animation resumes without jumping through the remaining phases. |
| Disclosure closes while its content has focus | Focus returns to its summary. Focus elsewhere stays there. |
| Landscape print | All four chapters appear in normal document flow. |

Application revision: `3e4a6e52`. Preview: <https://daily-a5leh29s8-mmarufovs-projects.vercel.app>, deployment `dpl_3La9MnvGrPGsydmWdHJvLYe33P4v`.

Local typecheck, 337 unit tests (one existing skip), both artifact validation commands and production build passed. The artifact checks validated 9 evaluation artifacts and 39 published Lab runs without writing files.

Screenshots cover 1440px light/dark at every stage, 320/390/430/800/1024/1920px layouts, reduced motion and enlarged text. Captured layouts had no horizontal overflow or page errors. The actual A4 landscape PDF contains all four chapter headings. Local evidence is under `.context/motion-hardening/` in the original workspace.

Rapid Back/Forward navigation in WebKit can report an access-control error for an interrupted same-origin Next.js `_rsc` prefetch. The same history test reproduced it on current production in two of three runs, with usable restored content. The regression test retains these errors as an attachment and distinguishes them from other page errors. Preview feedback scripts are blocked during browser verification.

Browser automation uses Chromium and WebKit on macOS with emulated mobile profiles. Physical-device coverage remains a separate check. Lab endpoints are mocked throughout; no Sandbox run was submitted.

## Verification results

- Browser suite: 337 passed, 2 skipped, 0 failures across desktop Chromium, mobile Chromium and WebKit. The existing Evidence first-Tab-focus check skips the two touch profiles and runs on desktop. All 45 resilience cases passed. The stall test also passed nine repeated runs.
- Application-revision CI: artifact export/staleness checks, backend/evaluation tests and PostgreSQL contracts passed.
- Mobile lab performance: three cold samples at 412×839, cache disabled, 4× CPU slowdown, 1.6Mbps download, 750Kbps upload and 150ms latency. LCP was 1052/1024/980ms; CLS was 0.000146 in each sample. Preview feedback scripts were blocked. These are local lab measurements.
- Desktop animation at 1440×900 and 4× CPU slowdown: 62 sampled frames over 1029ms; maximum and 95th-percentile frame gaps were 16.8ms. The transition reached its settled stage.
- Two-second inactive and visible-idle samples each recorded zero story mutations. The offscreen controller reported inactive.

Evidence in the original workspace: `.context/hardening-verified-e2e.log`, `.context/hardening-verified-test-results/`, `.context/hardening-performance.json`, and `.context/motion-hardening/`.

[Draft PR #107](https://github.com/mmarufov/Daily/pull/107) remains unmerged with automatic merging disabled. No production deployment was made by this branch. The final test/documentation commit leaves application files identical to the verified preview revision.
