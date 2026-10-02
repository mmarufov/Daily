# Daily Lab motion polish

Implementation is based on main 6bebf9ab. The original Sydney checkout and its
unrelated work remain intact. Source changes are limited to the web presentation,
interaction tests and these notes; evaluator, admission controls and evidence
artifacts are unchanged.

## Interaction contract

- Native details/summary remain usable before hydration and without JavaScript.
- Disclosures animate measured heights in 280ms and reverse from their current
  height. They release constraints on completion, resize, hidden tab or reduced
  motion changes. Nested disclosures keep their own event handling.
- Finding selections ease container height and text in 220-260ms, preserving
  current visual values if interrupted. Initial content is immediately visible.
- The guard selector slides on one track. Exact recorded numbers change directly.
- Press feedback is scoped to controls; hover movement only applies to fine
  pointers. Reduced motion disables movement. No animation dependency was added.

## Verification

- TypeScript and production builds passed.
- Unit suite: 279 passed, one existing skip.
- Artifact validators: nine artifacts and 39 Lab records passed.
- Dedicated motion suite: 24 passed across desktop Chromium, mobile Chromium and
  mobile WebKit. Coverage includes a real intermediate height, rapid reversal,
  keyboard focus, natural resized heights, reduced motion and native no-JS use.
- Full production suite: 226 passed, two existing mobile keyboard skips.
  Covers 320-1920px layouts, runner states with mocked endpoints, deep links,
  console errors, reduced motion and all three browser projects.
- Tests intercept Lab API requests; this presentation release did not consume a
  new Sandbox execution.

## Performance

Three fresh mobile Chromium samples on the public domain, cache disabled,
4x CPU slowdown, 1.6 Mbps down / 750 Kbps up and 150ms latency. Pixel 7 viewport,
412x839 CSS pixels. Median LCP 1,004ms; CLS 0.02048 in every sample. Longest observed
task 82ms. Offscreen sieve: zero DOM mutations over each two-second idle sample,
playback false. This is lab measurement, not field telemetry.

Raw samples: [daily-lab-motion-performance.json](daily-lab-motion-performance.json).
Screenshots were inspected at desktop and mobile widths and saved in the original
workspace's .context/motion-desktop.png and .context/motion-mobile.png.

## Deployment

Verified candidate source: b42ef0f9, identical tree to CLI revision bbdd95fb.
Public domain: https://marufov.com.
Deployment: dpl_Fet7JevFoa7paZkfAYxNRUQjNLf1,
https://daily-azvyiffrj-mmarufovs-projects.vercel.app.
Previous production retained for rollback: dpl_5a13LvnBSByqkFuY6wQajPLiQh8B,
https://daily-by2vjutyl-mmarufovs-projects.vercel.app.
