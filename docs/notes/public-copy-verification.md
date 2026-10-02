# Public copy and source comments

Base: `a30f7992` (main). Branch: `mmarufov/daily-copy`. Review: [PR 101](https://github.com/mmarufov/Daily/pull/101).

The site-copy commit shortens the five main routes and shared findings, with every
changed sentence listed before and after in the PR. The separate comment commit
removes debugging history and repetitive explanations from README-linked sources.
No CSS, fonts, routes, public data, execution behavior or quotas changed. Provenance
paragraphs were removed where the existing Inspect link supplies the same detail.

## Validation

- Typecheck: passed.
- Unit tests: 304 passed, one existing skip.
- Artifact checks and full export: passed; committed artifacts remain unchanged.
- Production build: passed.
- HTTPS preview browser suite: 259 passed, two existing touch-profile keyboard skips.
- Screenshots: all five routes at both widths in both themes; no clipping or overflow.

Screenshots cover all five routes at 1440px and 390px, in light and dark themes.
The capture blocks Lab endpoints. Browser tests mock execution; no Sandbox runs
are submitted. Production remains unchanged.

## Rendered copy and screenshots

The preview was built from `20521e4e`:
`https://daily-basysu4i8-mmarufovs-projects.vercel.app`, deployment
`dpl_4MuV6VidfXL5FBW32BsPgo8R4nHZ`.
The final documentation amendment leaves that tested web/backend tree unchanged.

All 20 screenshots returned HTTP 200 with no JavaScript errors or horizontal
page overflow. Desktop and mobile review found no clipped text or overlapping
headings in either theme. Artifacts are saved under `copy-before/` and
`copy-after/` in the original Sydney workspace's ignored `.context/` directory.

The same text collector measured both revisions at 1440px. It excludes editor
code, tables, frozen quoted data, hidden text and standalone numeric text.
Collapsed copy is counted separately. These are explanatory-copy counts, not
counts of the full evidence corpus.

| Route | Visible before | Visible after | Including collapsed before | Including collapsed after |
| --- | ---: | ---: | ---: | ---: |
| `/` | 574 | 405 | 585 | 416 |
| `/lab` | 960 | 862 | 960 | 862 |
| `/evidence` | 1631 | 1540 | 1676 | 1585 |
| `/engineering` | 608 | 350 | 608 | 350 |
| `/reader?profile=ray` | 351 | 246 | 351 | 246 |

## Comment-only comparison

Compared each file with the base using two independent representations:
TypeScript AST output and emitted JavaScript with comments removed; Python
non-comment tokens and ASTs including docstrings. The Vercel ignore patterns are
compared in order after removing comments and blank lines. Every comparison is
identical. The hash below is shared by the before and after normalized source.

| File | Matching SHA-256 |
| --- | --- |
| `web/lib/lab/sandbox.ts` | `06a3b99562b72c24f8e831ff1e25bbf26866ca0630bea6224583a2ee4eb45fac` |
| `web/lib/lab/orchestration.ts` | `a35f8dab08ff28955dfa4465b6fd48867606e3cd4844fd0089b504060c4b77a6` |
| `web/lib/lab/public-run.ts` | `90774b5473e71417aaa2bcf92d5c8f45d2ff3889d82cb1c4a59c5fe06ec8c342` |
| `web/lib/lab/public-limits.ts` | `cd45802420e4c69a60416a60eb445046b1278a07af302a77038940438947d64a` |
| `backend/app/services/article_content.py` | `e7ba44dcacb8f33f220a6648cf34213f356978c30846f5490469560bb89e3f1d` |
| `backend/app/services/ranking_repository.py` | `23be1cfa0d0ddf177751782ced0ba688f2acd556c004854b5f3c5bbc74b99660` |
| `backend/app/services/ranking_service.py` | `8fa12182c409401119fd138ee169cd70e49ed309f5d8d0e2b618ebbcc27f663c` |
| `backend/app/services/safe_http.py` | `36bdf89d1fea74a328420840b81ece1ddf8cfd2c1db7ab88d9c15d91b0ee41b7` |
| `backend/evals/degrade.py` | `04f3e52ca20cee6ce247c2dbc3b5e556e1e5c3404aa42f7ff59957b808586d3e` |
| `backend/evals/metrics.py` | `9f9b2fdeef7420d3a1e94eac3003f6e697985696bf55dbb87c05593a648cee08` |
| `backend/evals/runners.py` | `764ff10b89f65865433a643e41f4d63e58c22d405a662d2ebb6441162eedc63c` |
| `backend/tests/test_eval_degradation.py` | `4faf910de8ea70214d37aeb195bc9d4782647c3f9ed5282d556a219138974ef9` |
| `.vercelignore` | `c147095c91fe98feed15e978c00137f12bfe273604b98a82d0c0edcad8a7901d` |

`web/lib/lab/evaluator.ts` is preserved byte-for-byte. The export hashes its full
source, including comments; trimming those comments changed recorded evaluator
identities and failed the staleness test. The recorded candidate source
`backend/lab/contract/versions/keyed_v2.py` is also preserved.
