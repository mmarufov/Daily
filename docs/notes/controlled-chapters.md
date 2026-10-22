# Controlled chapter transitions

October 22, 2026. Extend draft PR #107 in the isolated motion-hardening worktree. Current main is 02afcabf; synchronize it without modifying the original workspace. Leave the PR unmerged and production unchanged.

## Interaction contract

- Desktop fine-pointer visitors enter at Parser (or Verdict from below). A large incoming wheel delta lands at the entry and discards overshoot.
- Accumulate 160 normalized vertical pixels, resetting on direction reversal, to advance one adjacent chapter. Line deltas use 16px; page deltas use viewport height.
- Each transition lasts 1000ms with a 150ms settled beat. Discard input during both phases, keep no pending steps, and accept only fresh intent afterward.
- At the first/last chapter, qualifying outward input releases native scrolling. Rail buttons select immediately. A visible Skip animation control focuses the run-details summary.
- Use the existing 300svh sticky track with canonical document positions at entry, thirds and exit. Visual progress remains separate. Internal scroll events and incidental caption resizing cannot restart transitions.
- Enforce a 1500ms wall-clock deadline. Settle and bypass on timeout, noncancelable input, explicit navigation, scrollbar movement, lost eligibility or lifecycle suspension.
- Preserve zoom, horizontal gestures, editable controls and nested scrolling. Hovering a chapter button or link keeps wheel control; clicking still invokes its action. Handle page-scroll keys only when the page is the input target. Escape and Tab leaving the section bypass immediately.
- Touch/coarse input, pinch zoom and reduced motion use static chapters. Preserve script failures, delayed hydration, enlarged text, focus, history and print fallbacks.

## Verification

- [x] Inspect current branch, root guidelines and deployed behavior; reconcile current main.
- [x] Add a real-wheel regression and observe it fail on deployed baseline before runtime changes.
- [x] Implement the pure chapter state model and controller integration.
- [x] Add Skip control and fine-pointer/touch fallback.
- [x] Verify thresholds, bursts, momentum, reversals, keyboard, native escape paths and deadline behavior.
- [x] Run typecheck, unit tests, artifacts, build and deployed Chromium/WebKit acceptance with mocked runner endpoints.
- [x] Capture desktop/mobile views and a recording; repeat CPU/network profiling and inactive-work checks.
- [x] Update draft PR #107 and record hardware coverage. Do not merge or release production.

Baseline regression: a 5000px wheel delta 120px before entry placed the sticky panel at -862.578px rather than 96px. Existing animation time continued independently of document scrolling.

References: [GSAP Observer](https://gsap.com/docs/v3/Plugins/Observer/), [Vercel interface guidelines](https://vercel.com/design/guidelines), [MDN wheel events](https://developer.mozilla.org/en-US/docs/Web/API/Element/wheel_event). Timings and thresholds above are Daily decisions.

## Preview verification

Application revision: `e39cfecf05cf3ae7460c0458242618356943bbc0`, based on main `02afcabf`. Deployment: `dpl_4PR8yVJ21Y1p83oMqJAHDAigRLkL`, [authenticated preview](https://daily-kw7b6ehwl-mmarufovs-projects.vercel.app). No production deployment or Sandbox execution was submitted.

Typecheck, 353 unit tests (one existing skip), the production build, artifact validation and export staleness checks passed. The exports still contain nine evaluation artifacts and 39 Lab records. Browser acceptance uses mocked Lab endpoints.

Browser acceptance finished with 477 passed, 99 device/API-specific skips and zero failures across desktop Chromium, desktop WebKit, Pixel 7 Chromium and iPhone 14 WebKit. Skips cover fine-pointer scenarios on touch profiles, coarse-pointer scenarios on desktop, and Chromium-only visual viewport emulation. Artifact, backend/evaluation and PostgreSQL CI checks passed for the application revision.

The new tests reproduced large entry overshoot, held-key suppression after settlement, pinch-zoom overflow and wheel escape over hovered controls before their fixes. Sampling verifies panel position throughout transitions. The final suite also covers reverse entry, caption reflow, continuous and decaying input, direct selection, navigation, lifecycle changes, a 1650ms main-thread stall and controller failure.

The browser fixture replaces only Vercel's preview feedback script with empty JavaScript. That iframe could hold the load event after the application had rendered. Application assets, errors and Lab mocks remain checked. Safari's link-navigation test uses its native Option+Tab shortcut; Home/End waits for the first native scroll to settle before reversing it.

## Performance

[Raw measurements](controlled-chapters/performance.json), October 22, 2026. Three cold Chromium runs used a 412×839 Pixel 7 profile, disabled cache, 4× CPU slowdown, 1.6Mbps download, 750Kbps upload and 150ms latency. The preview feedback toolbar was excluded. LCP was 1004–1060ms; CLS was 0.000146 in every sample.

At 4× CPU slowdown, all 70 sampled transition/settlement frames kept the panel at 96px. The maximum frame gap was 16.8ms. Two-second offscreen and visible-idle samples each recorded zero story mutations. These are laboratory measurements on the macOS host.

## Review assets and coverage

[Scroll recording](controlled-chapters/scroll-sequence.mp4) · [Desktop](controlled-chapters/desktop.png) · [Mobile](controlled-chapters/mobile.png)

The recording uses actual Playwright wheel events, including 2000px bursts during each transition. Screenshots cover 320, 390, 430, 800, 1024 and 1920px widths, all four chapters in both desktop themes, reduced motion and 200% text. A landscape PDF keeps every chapter. The expanded capture set and browser logs are under the original workspace's `.context/controlled-chapters/` and `.context/controlled-release-e2e.log`.

Automated Chromium and WebKit ran on macOS. Physical Mac trackpad, mouse and touch-device checks were unavailable. Pinch zoom was exercised through Chromium's visual viewport emulation; WebKit received text enlargement and layout-resize checks.
