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
- [ ] Run typecheck, unit tests, artifact validation, build and preview browser suite.
- [ ] Review desktop/mobile/print evidence, profile inactive work and document measured limits.
- [ ] Commit and publish an unmerged review PR with preview evidence.
