# Full-screen ocean preview

Current preview: [adaptive paragraph contrast](https://daily-jwblgdw5u-mmarufovs-projects.vercel.app), runtime `caaac412`, deployment `dpl_BGsJQsjmDVZEjbELTpR16xZnC2YZ`. The owner accepted the unbacked composition. Only the paragraph beginning "Daily builds news editions" changes color over the swimming scene. The headline, actions, shark sizes and layout remain unchanged.

The original text color stays where contrast is sufficient. Small clipped overlays supply black or white lettering over difficult cells. They preserve native text rendering, selection and a single screen-reader copy. Sampling covers the paragraph only and runs with the existing scene paint. Pause, hidden tabs and offscreen playback stop the work; reduced motion uses the poster.

![Paragraph during a shark pass](assets/fullscreen-ocean/adaptive-desktop.png)

[Desktop recording](assets/fullscreen-ocean/adaptive-desktop-motion.mp4) · [Mobile recording](assets/fullscreen-ocean/adaptive-mobile-motion.mp4)

Typecheck, production build and 356 unit tests passed, with one existing skip. Preview browser checks: 43 passed across desktop Chromium, mobile Chromium and mobile WebKit; 15 passed in additional desktop WebKit coverage. Six existing skips cover the unsupported observation API and desktop-only layout tests. Checks include light/dark/gray cells, selection, accessibility tree, sampling failure, pause, print and forced colors. Layouts from 320px through 1920px had no horizontal overflow or page errors.

Three cold mobile samples with the conditions below produced LCP of 1080, 1088 and 1024ms; CLS was 0.000146 in each. Offscreen drawing and text sampling both stayed at zero. The contrast model checks all 256 gray levels in both themes. Those checks describe solid samples; the rendered edges also depend on antialiasing and the two-pixel sampling grid.

With 4x CPU throttling over five seconds, the sampler followed 28.9 scene frames per second on desktop and 29.4 on mobile. Pixel readback alone took 0.7ms and 0.6ms at p95, respectively.

The exact preceding unbacked version is saved at `26e11fd2`. PR #112 remains draft, with production unchanged.

## Earlier comparisons

[Text backing removed](https://daily-h8my0p4l7-mmarufovs-projects.vercel.app), runtime `9eee51b2`. The only site change from `653be1b0` is deletion of the `.hero-copy::before` rule. Build and light/dark desktop/mobile checks passed; the original CSS remains in that baseline commit for exact restoration.

![Text backing removed](assets/fullscreen-ocean/no-backing-desktop.png)

The backed version and its checks follow.

Reviewed October 28, 2026. Runtime revision: `48b2f335`. Base: `d956b2a9`.

[Open the preview](https://daily-3uzd39yjz-mmarufovs-projects.vercel.app). Deployment: `dpl_HGYinuEqzAgGN21cFi5Pe889k6VF`. Production remains on the base revision.

The hero now fills the desktop opening. Its existing copy, actions and edition sit over the upstream shark renderer, with open water above and below. Mobile keeps the same content order and grows with the text. The sharks use shaded color cells without letters or symbols; swimming and fish are unchanged.

## Recordings

| Daily | Reference |
| --- | --- |
| [Desktop, 15 seconds](assets/fullscreen-ocean/desktop-motion.mp4) | [Creator's original recording](https://designeer.xyz/finds/stackedlol-2112257760628986188) |
| [Mobile, 15 seconds](assets/fullscreen-ocean/mobile-motion.mp4) | [Source at the pinned revision](https://github.com/stackedlol/ascii-sharks/tree/a0074c16a106f0abc665fe9712ca445f8f98ad8e) |

![Desktop](assets/fullscreen-ocean/desktop.png)

![Desktop dark theme](assets/fullscreen-ocean/desktop-dark.png)

| Mobile | Mobile dark theme |
| --- | --- |
| ![Mobile](assets/fullscreen-ocean/mobile.png) | ![Mobile dark theme](assets/fullscreen-ocean/mobile-dark.png) |

## Checks

- Typecheck, production build and artifact validation passed. Re-exporting all artifacts left the committed data unchanged.
- Unit tests: 346 passed, one existing skip.
- Full browser suite on `60d1e340`: 314 passed, seven skipped. Covers desktop Chromium, mobile Chromium and mobile WebKit with mocked runner endpoints.
- Color-cell update on `48b2f335`: 28 ocean checks passed across the default projects, five skipped. Additional desktop WebKit ocean checks: 10 passed, one existing skip. The browser check rejects text glyphs in shark rendering. Chromium and WebKit captures confirm the color tiles, pause/resume and static fallback.
- Reviewed 320, 390, 430, 820, 844, 1440 and 1920px widths, light/dark themes and a 390px-high landscape window. No horizontal overflow or page errors appeared.
- Doubling hero text size at 390px kept both Chromium and WebKit within the viewport. The section grew to about 2116px. At 1440px it grew to about 1193px.
- Pause/resume, resize, hidden tabs, printing, reduced motion, unavailable canvas, disabled scripts, forced colors and keyboard actions passed. The ocean stopped drawing while offscreen, including after resize.
- The math, species and simulation modules match the pinned source after removing the documented TypeScript directive. The renderer has a documented color-cell option. The MIT license is retained in the source and public assets.

Cold mobile measurements used Pixel 7 emulation at 412x839, disabled cache, 4x CPU throttling, 1.6Mbps down, 750Kbps up and 150ms latency. The preview toolbar was blocked. Three samples on `60d1e340`:

| Sample | LCP | CLS | Offscreen draw calls |
| --- | ---: | ---: | ---: |
| 1 | 1080ms | 0.000146 | 0 |
| 2 | 1124ms | 0.000146 | 0 |
| 3 | 1064ms | 0.000146 | 0 |

These are lab measurements. Browser coverage used Playwright engines; physical phone and trackpad checks were unavailable.

![Mobile reduced-motion fallback](assets/fullscreen-ocean/mobile-reduced.png)

## Existing unsupported-browser issue

Removing `IntersectionObserver` still breaks the existing parser story on production. Its browser test remains marked `fixme`; the ocean itself falls back to its poster when observation APIs are missing. The other browser skips are desktop-only checks on mobile projects.

The parser story, evaluator, backend, data, public routes and homepage copy are unchanged. No Sandbox execution was submitted for this presentation pass.
