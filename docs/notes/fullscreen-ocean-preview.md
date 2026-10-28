# Full-screen ocean preview

Reviewed October 28, 2026. Runtime revision: `77993282`. Base: `d956b2a9`.

[Open the preview](https://daily-77qaavzia-mmarufovs-projects.vercel.app). Deployment: `dpl_EGVxie2QA6eTjZUUC4yuWHYsW6pP`. Production remains on the base revision.

The hero now fills the desktop opening. Its existing copy, actions and edition sit over the upstream shark renderer, with open water above and below. Mobile keeps the same content order and grows with the text.

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
- Browser suite on the preview: 314 passed, seven skipped. Covers desktop Chromium, mobile Chromium and mobile WebKit with mocked runner endpoints.
- Additional desktop WebKit ocean checks: 10 passed, one existing skip.
- Reviewed 320, 390, 430, 820, 844, 1440 and 1920px widths, light/dark themes and a 390px-high landscape window. No horizontal overflow or page errors appeared.
- Doubling hero text size at 390px kept both Chromium and WebKit within the viewport. The section grew to about 2116px. At 1440px it grew to about 1193px.
- Pause/resume, resize, hidden tabs, printing, reduced motion, unavailable canvas, disabled scripts, forced colors and keyboard actions passed. The ocean stopped drawing while offscreen, including after resize.
- The original renderer and simulation match the pinned source after removing the documented TypeScript directive. The MIT license is retained in the source and public assets.

Cold mobile measurements used Pixel 7 emulation at 412x839, disabled cache, 4x CPU throttling, 1.6Mbps down, 750Kbps up and 150ms latency. The preview toolbar was blocked. Three samples:

| Sample | LCP | CLS | Offscreen draw calls |
| --- | ---: | ---: | ---: |
| 1 | 1080ms | 0.000146 | 0 |
| 2 | 1044ms | 0.000146 | 0 |
| 3 | 1036ms | 0.000146 | 0 |

These are lab measurements. Browser coverage used Playwright engines; physical phone and trackpad checks were unavailable.

## Existing unsupported-browser issue

Removing `IntersectionObserver` still breaks the existing parser story on production. Its browser test remains marked `fixme`; the ocean itself falls back to its poster when observation APIs are missing. The other browser skips are desktop-only checks on mobile projects.

The parser story, evaluator, backend, data, public routes and homepage copy are unchanged. No Sandbox execution was submitted for this presentation pass.
