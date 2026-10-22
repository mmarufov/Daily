# Controlled chapter transitions

October 22, 2026. Extend draft PR #107 in the isolated motion-hardening worktree. Current main is 02afcabf; synchronize it without modifying the original workspace. Leave the PR unmerged and production unchanged.

## Interaction contract

- Desktop fine-pointer visitors enter at Parser (or Verdict from below). A large incoming wheel delta lands at the entry and discards overshoot.
- Accumulate 160 normalized vertical pixels, resetting on direction reversal, to advance one adjacent chapter. Line deltas use 16px; page deltas use viewport height.
- Each transition lasts 1000ms with a 150ms settled beat. Discard input during both phases, keep no pending steps, and accept only fresh intent afterward.
- At the first/last chapter, qualifying outward input releases native scrolling. Rail buttons select immediately. A visible Skip animation control focuses the run-details summary.
- Use the existing 300svh sticky track with canonical document positions at entry, thirds and exit. Visual progress remains separate. Internal scroll events and incidental caption resizing cannot restart transitions.
- Enforce a 1500ms wall-clock deadline. Settle and bypass on timeout, noncancelable input, explicit navigation, scrollbar movement, lost eligibility or lifecycle suspension.
- Preserve zoom, horizontal gestures, nested scrolling and controls. Handle unmodified page-scroll keys only when the page is the input target. Escape and Tab leaving the section bypass immediately.
- Touch/coarse input and reduced motion use static chapters. Preserve script failures, delayed hydration, enlarged text, focus, history and print fallbacks.

## Verification

- [x] Inspect current branch, root guidelines and deployed behavior; reconcile current main.
- [x] Add a real-wheel regression and observe it fail on deployed baseline before runtime changes.
- [x] Implement the pure chapter state model and controller integration.
- [x] Add Skip control and fine-pointer/touch fallback.
- [ ] Verify thresholds, bursts, momentum, reversals, keyboard, native escape paths and deadline behavior.
- [ ] Run typecheck, unit tests, artifacts, build and deployed Chromium/WebKit acceptance with mocked runner endpoints.
- [ ] Capture desktop/mobile views and a recording; repeat CPU/network profiling and inactive-work checks.
- [ ] Update draft PR #107 and record hardware coverage. Do not merge or release production.

Baseline regression: a 5000px wheel delta 120px before entry placed the sticky panel at -862.578px rather than 96px. Existing animation time continued independently of document scrolling.

References: [GSAP Observer](https://gsap.com/docs/v3/Plugins/Observer/), [Vercel interface guidelines](https://vercel.com/design/guidelines), [MDN wheel events](https://developer.mozilla.org/en-US/docs/Web/API/Element/wheel_event). Timings and thresholds above are Daily decisions.
