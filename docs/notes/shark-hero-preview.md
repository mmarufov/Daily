# ASCII shark hero preview

Original drawing inspired by [stacked on Designeer](https://designeer.xyz/finds/stackedlol-2112257760628986188). The reference media is used only for visual inspection and is absent from the application.

The hero keeps Daily's copy, edition and actions. Three low-contrast sharks drift around the desktop composition; mobile uses two. The drawing uses up to 792 glyphs, a 24fps cap and capped canvas resolution. A pause control, hidden-tab/offscreen suspension and a still SVG cover ordinary motion preferences and missing canvas. Existing RunStory code and backend files match main.

Verified application: 7587945b. Preview: https://daily-d3edscc70-mmarufovs-projects.vercel.app

- Typecheck, 342 unit tests (one existing skip), production build passed.
- Full deployed browser suite: 304 passed, 5 skipped. Two skips are existing device cases; three document the existing unsupported IntersectionObserver case.
- Desktop WebKit background checks: 6 passed, 1 skipped for that same API case.
- The unsupported API case was reproduced independently on marufov.com: removing IntersectionObserver causes the existing RunStory to throw. The test remains marked fixme; this preview leaves that restored component unchanged.
- Three cold Pixel 7 measurements with 4x CPU slowdown, 1.6Mbps down, 750Kbps up and 150ms latency measured LCP 980, 1052 and 1100ms. CLS was 0.000146 in each sample. Cache was disabled and the preview feedback toolbar was excluded.
- Each offscreen sample recorded zero canvas glyph draws.
- Desktop, mobile and dark-theme captures produced no page errors. Images are saved in the workspace .context directory as shark-desktop.png, shark-mobile.png and shark-dark.png.

Draft PR #111 stays unmerged. Production remains on the restored animation. Physical-device visual approval remains with the owner.
