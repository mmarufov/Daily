# ASCII sharks

Source: https://github.com/stackedlol/ascii-sharks

Pinned revision: `a0074c16a106f0abc665fe9712ca445f8f98ad8e`

The TypeScript modules have a first-line `ts-nocheck` directive because upstream does not enable Daily's unchecked-index diagnostics. The math, species and simulation modules otherwise match the pinned source. Daily owns lifecycle and responsive integration in `web/lib/ocean-controller.ts` and `web/lib/ocean-scene.ts`.

The renderer adds a `sharkGlyphs: false` option for Daily's color cells. It paints partial silhouette cells using their coverage and moves the restrained accent colors into the cell fills. The default retains upstream's ASCII treatment. Both the animated scene and static posters use the color-cell option.

License: MIT, copyright (c) 2026 drewdi. The complete notice is in LICENSE.

SHA-256 hashes of the original upstream bytes. The math, species and world files match after removing the added first line; the renderer also has the patch described above.

- `math.ts`: `3b80e4aab6d370927382cecfa685185bc9d4e00b14a64c99fd472e96d1b75403`
- `species.ts`: `39ca3a6feb31c2cc2a88633ab4b8ae1ee2e8e047a2bcce0c5336e19ca26f80c8`
- `world.ts`: `f2f8f8daf85698fffc7925c8309c1b3a10f5882957b5674fe1858d2ecf534457`
- `renderer.ts`: `1175efcd707292125129bbb1aefcf75768367b75672abf282313746ebabd1f71`
- `LICENSE`: `c5caff4e891468c982ad58d5491fd30631ab9543188407390fa4bfdb711b4718`
