# Bundled typefaces

Both files are vendored rather than fetched at build time, so `npm run build`
never needs network access and the bytes that ship are the bytes in this tree.
Each is the Latin subset of the variable font, served self-hosted via
`next/font/local`.

| File | Family | Licence |
|---|---|---|
| `Fraunces-latin.woff2` | Fraunces (Undercase Type — Phaedra Charles, Flavia Zimbardi) | SIL Open Font License 1.1 |
| `GeistMono-latin.woff2` | Geist Mono (Vercel) | SIL Open Font License 1.1 |

The SIL OFL permits bundling and redistribution provided the fonts are not sold
on their own and the licence travels with them. Upstream sources:

- https://github.com/undercasetype/Fraunces
- https://github.com/vercel/geist-font
