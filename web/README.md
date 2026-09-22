# Daily — web companion

A read-only web tier for [Daily](../README.md): a reader demo, an interactive explorer for the
evaluation harness's results, and one worked debugging case study.

It does not reimplement ranking. Nothing here scores an article. The reader replays an edition
the pipeline already assembled; the explorer renders artifacts exported from the harness's own
scorecards.

Every figure on the site is drawn from those committed artifacts at render time. There are no
illustrations, no placeholder data, and no hardcoded numbers in any chart — see
[The visual system](#the-visual-system).

## Setup

```bash
cd web
npm ci
npm run export:all     # build the committed artifact + demo export
npm run dev            # http://localhost:3000
```

No credentials, no database and no provider key are needed for any of that. The export reads
`backend/evals/results/`, `backend/evals/snapshots/` and `backend/evals/labels/`, all of which
are committed.

### Commands

| Command | What it does |
|---|---|
| `npm run dev` | Development server |
| `npm run build` / `npm run start` | Production build and server |
| `npm run typecheck` | `tsc --noEmit`, strict |
| `npm run test` | Vitest unit tests, including the sieve and funnel arithmetic |
| `npm run test:e2e` | Playwright, desktop + mobile, against the production build |
| `npm run export:artifacts` | Rebuild `public/artifacts/` from the harness's scorecards |
| `npm run export:artifacts -- --check` | Validate without writing |
| `npm run export:demo` | Rebuild `public/demo/editions.json` |
| `npm run export:lab` | Rebuild `public/lab-artifacts/` from `backend/lab/` |
| `npm run export:all` | All three exports |
| `npm run summarise` | Markdown comparison summary (used for the CI step summary) |
| `npm run publish:artifacts` | Upload validated artifacts to Vercel Blob |

### Environment variables

| Variable | Required | Meaning |
|---|---|---|
| `ARTIFACTS_BLOB_BASE_URL` | no | Base URL of a published artifact set. When unset — or unreachable — the app falls back to the committed export under `public/artifacts/` and says so in the UI. |
| `BLOB_READ_WRITE_TOKEN` | publish only | Vercel Blob write token. Absent, `publish:artifacts` exits 0 without uploading, so fork pull requests run the same pipeline with no secrets. |
| `PUBLISH_AS_LATEST` | publish only | `true` moves the mutable `evidence/latest/` pointer. The trusted workflow sets it only for the default branch. |
| `DEMO_RUN_ID` | no | Which exported run the reader demo replays. Defaults to `prod-llm__2026-09-02__47edb50`. |

There is deliberately no backend URL here. See [Live mode](#live-mode-is-not-built).

## The boundary between this tier and the backend

Daily's backend is a **stateful process**, not a set of functions. Its startup path launches
seven background loops — ingestion, prewarm, source quality, interest evolution, per-user
refresh, account maintenance, ranking refresh — applies schema, and elects a leader with a
Postgres advisory lock. It stays where it runs today. Nothing about this web tier moves it, and
moving it would trade a working system for a demo.

```
  browser
     │
     ├── /            static           product introduction
     ├── /reader      committed JSON   a replay of one assembled edition
     ├── /evidence    artifacts        validated exports, immutable, cacheable
     └── /engineering static           one case study
                          ▲
                          │  export (offline, reproducible, no credentials)
                          │
          backend/evals/{results,snapshots,labels}   ← committed evidence base
                          ▲
                          │  the harness, run separately
                          │
          FastAPI + Postgres daemon on its own host  ← untouched
```

The only backend change this work made is a scoped correctness fix in the batch relevance
scorer, described in [the case study](#the-case-study) and in
[`.context/batch-alignment-fix/FINDING.md`](../.context/batch-alignment-fix/FINDING.md). No
endpoint was added, no contract changed, and every feature gate keeps its existing default.

## Artifact provenance

The harness's scorecards are an internal format. The web tier consumes a separate **versioned
public artifact**, and the export step establishes what can actually be known rather than
assuming it. Three rules are enforced by construction:

1. **Three revisions are kept apart.** The revision that *executed* an evaluation, the revision
   that *stores* the scorecard, and the revision that *built* the artifact are three different
   fields. None of them is allowed to stand in for another, so today's commit is never stamped
   onto an old measurement.
2. **Importing is not executing.** Every artifact records `origin`. All nine currently exported
   artifacts are `imported-historical`; none was produced by a run this pipeline executed.
3. **Unknown is written as `unknown`.** Never `null`, never `0`, never inferred from a sibling
   field.

What that surfaces about the committed evidence, all of it computed rather than hardcoded:

- The revision that executed every stored run is **not reachable from the default branch**, so
  "this result came from that code" cannot be verified by checking the revision out.
- **No stored scorecard records an evaluation protocol** — the harness began emitting one later.
  Protocol equality between two runs therefore cannot be verified, only assumed from the runner
  name, and the explorer says so instead of showing a clean regression claim.
- `execution_mode` is `unknown` for every run. A zero cache-miss total cannot stand in for it,
  because the harness only counts a miss on the live network path, making the counter
  structurally zero whenever offline replay is active.
- One baseline file, `baseline-prod-llm.json`, carries thresholds for `2026-09-02` that
  **disagree with the committed run scorecard** for the same runner and snapshot. It was
  re-recorded after the timestamps embedded in it. The export detects this by comparing the two
  documents and marks `timestamps_trustworthy: false`.
- Runs named `proto-hybrid-judge-events` carry a warning: that name belongs to the corrected
  default prototype pipeline, but the repository's own regression gate maps the runner key to a
  historical legacy adapter whose protocol reproduces known defects. They are evidence about
  that historical protocol, not validation of the corrected one.

### Comparison compatibility

A delta only means something if you can say what was held fixed, so comparisons are classified:

| Kind | Requires | Shown |
|---|---|---|
| `code-regression` | same corpus, same k, same runner | directional deltas |
| `algorithm` | same corpus, same k, different runner | directional deltas, labelled as an algorithm comparison |
| `incompatible` | anything else | the reason, and **no** improvement arrows |

Differences on fractions are expressed in **percentage points**. "Material" means the harness's
fixed ±0.02 cutoff, which is a threshold its author chose — ten fixtures with no variance
estimate cannot support a significance claim, and the UI never makes one.

### Metric semantics

Capped recall (`must_see_in_top_k / min(n_must_see, k)`) and raw recall
(`must_see_in_top_k / n_must_see`) are different metrics and are shown separately. Direction is
read from an explicit map: an unrecognised metric is rendered with **no** direction rather than
assumed to be better when it rises. Lower is better for the unwanted rate, the lookalike rate,
the false-major rate, cost and latency.

### The funnel is reconstructed, not read

`stage_counts` in a scorecard records each article **once, at the furthest stage it reached**.
Rendering those tallies as survivorship produces a funnel that grows: for fixture `ray` it would
show `scored` at 45 and `feed` at 50. Survivors at a stage are the sum of that stage's tally and
every later one. That reconstruction is validated against three facts recorded independently in
the same scorecard — survivors at `feed` equals the reported feed size (50), survivors at
`loaded_rows` equals the recorded recency window (300), and survivors at `scored` equals the
documented 100-candidate cap — and the total exceeds the 1,358-article corpus by exactly four,
the planted needles. `tests/unit/funnel.test.ts` asserts all of it.

## Preview and publication

```
pull request ──▶ evaluation artifacts   (no secrets, runs on forks)
                 ├─ typecheck, unit tests, production build
                 ├─ export + validate, and fail if the committed export is stale
                 ├─ comparison summary  → job summary, written even on failure
                 └─ upload GitHub artifact (always, so a red gate still yields diagnostics)
                        │
                        ▼  workflow_run, only when the run concluded success
             publish evidence            (trusted, holds the Blob token)
                 ├─ re-validate everything it downloaded
                 └─ upload under evidence/<revision>/, manifest LAST
                        └─ evidence/latest/ only when head branch is main
```

- The pull-request job never holds publishing credentials. Publication happens in a separate
  trusted workflow, which refuses to run unless the triggering run succeeded — so a failed run
  is never published as if it had passed.
- The manifest is uploaded **last**, because it asserts completeness. A reader that sees the
  manifest can rely on every artifact it lists being present and validated.
- Artifacts are published under a **revision-scoped prefix**. The mutable `latest` pointer moves
  only for the default branch, so a preview deployment cannot silently consume an unrelated run.
- There is deliberately **no schedule**. Replaying identical frozen inputs on a timer produces
  identical numbers; the useful triggers are a change to the harness, the pipeline or this tier,
  plus manual dispatch.
- The export is **reproducible**: timestamps come from the HEAD commit, not the wall clock, so
  the same tree always produces byte-identical artifacts. That is what makes the staleness check
  meaningful.

### Caching

| Content | Policy | Why |
|---|---|---|
| `/artifacts/*` | `public, max-age=31536000, immutable` | Content is fixed for a given run id |
| Published artifacts on Blob | one year | Same |
| Published `manifest.json` | 60 seconds | It is the pointer; a new publication must be seen |
| Anything personalized | never shared | There is no personalized response in this tier today, and the boundary is recorded so it stays that way |

## The visual system

One rule governs every surface: **colour means loss.** In any chart, table or diagram, ink is
what survived the pipeline, vermilion is what it threw away, and slate is what cannot be verified
either way. Nothing that worked is ever coloured, so a glance at a figure says where the system
failed before you have read a label. Chrome — links, focus, selection — borrows the same
vermilion, because there it carries the meaning the eye has already learned: look here.

Two typefaces and no sans between them. Prose is set in Fraunces; every number, identifier, stage
name and micro-label is set in Geist Mono. The site is a newspaper assembled by a measuring
instrument and is meant to look like both objects at once. Both fonts are **vendored** under
`app/fonts/` and loaded with `next/font/local`, so `npm run build` never needs network access and
the bytes that ship are the bytes in the tree. Licences: [`app/fonts/LICENSE.md`](app/fonts/LICENSE.md).

`docs/DESIGN.md` governs the iOS app and is written as an iOS-first source of truth. This tier is
a different medium doing a different job — an evidence explorer, not a reading app — so it does
not inherit those tokens. `/reader` is the one surface that stays close to the app's
paper-and-serif register, because there it is showing the product rather than measuring it.

### The figures

| Figure | Where | What it draws |
|---|---|---|
| **The sieve** | `/`, `/evidence` funnel view | One cell per candidate article, **1:1 with the corpus** — 1,362 marks, not a summary of them. Stepping a stage flashes the candidates that stage removed in vermilion and settles the rest to ghost, so the discarded mass stays part of the picture. |
| **Every fixture, no averaging** | `/`, `/evidence` | A small multiple per reader fixture, composed of its story outcomes. `Daniel` is almost solid vermilion; `Will` is mostly loss. The run's 22.1% mean hides both. |
| **The slope** | `/evidence`, `/engineering` | Two runs on one shared 0–100% scale. Fraction metrics only: costs and latencies share no scale with a recall rate, and per-row normalisation would make a 0.4-point move look like a 40-point one. |
| **The trace ribbon** | `/evidence` story detail | One story's journey across the same ten stages, with its death point marked. Answers "did ranking make a mistake, or did nothing ever look at this?". |
| **The offset** | `/engineering` | The batch-scoring defect drawn: article slots, returned verdict slots, and the shift one merged entry causes. Labelled a schematic on the page — the counts are recorded, the merge point is not. |

### Reading order

Each surface leads with the figure and keeps one short paragraph beside it. The long form —
metric definitions, where the sieve's counts come from, how the repository confirms the
defect diagnosis, where this tier stops and the backend begins — sits behind a marked
disclosure rather than in the scroll. Nothing was deleted to make the pages shorter; the
depth moved one click away so the argument can be followed without wading to it. The two
long pages (`/evidence`, `/engineering`) carry their own numbered contents as jump links.

Honesty constraints the figures are held to:

- The sieve's cell count equals the recorded pool exactly, and the cells assigned to each stage
  equal that stage's recorded loss. Both are asserted in `tests/unit/sieve.test.ts` against the
  committed artifact, not against a fixture written to pass.
- Which article a stage removed is **not recorded anywhere**, so cells are scattered by a fixed
  hash and the component says so: the quantities are evidence, the positions are not.
- The sieve is drawn per fixture only. Summing ten fixtures would draw the same article up to ten
  times and call the result a corpus, so the aggregate view offers a fixture picker instead.
- Motion is one-shot and cancellable, `prefers-reduced-motion` jumps straight to the answer, and
  only `background-color` animates — 1,362 cells cost no layout work, which is what makes drawing
  the corpus at 1:1 affordable in the first place.

## Daily Lab (`/lab`)

A controlled experiment on the batch relevance scorer, built on the same evidence base. It asks one
question — *does a candidate parser associate every verdict with the article it was actually about,
and refuse when it cannot?* — and answers it with verdicts **computed by trusted code**, never
reported by the thing under test.

| | |
|---|---|
| `backend/lab/contract/` | Three preserved versions of the association (`positional-v0` as production ships it, `count-guard-v1` from PR #59, the proposed `keyed-v2`) plus three labelled defective controls. Each is one self-contained stdlib-only file. |
| `backend/lab/cases/` | 64 cases in two groups that are never mixed: 42 **observed** batches replayed from the committed recordings, and 22 **synthetic** fault injections with ground truth by construction. |
| `backend/lab/harness.py` | Runs a candidate and emits prediction records. The record schema has **no field for a grade**. |
| `backend/lab/orchestrate.py` | A resumable orchestrator whose state is an append-only event log. `--kill-after` injects a real process death so the recovery can be demonstrated rather than described. |
| `web/lib/lab/` | The trusted side: frozen spec + hash, evaluator, patch scope gate, runner selection, durable state, artifact schema. |
| `web/public/lab-artifacts/` | The committed, validated artifact set the site renders. |

### Why the boundary holds

- **A candidate cannot grade itself.** Prediction records carry no verdict field and the schema
  strips unknown keys. `control-self-reporting` emits `passed/score/all_tests_green` and is
  rejected like anything else.
- **The trust boundary is also a language and process boundary** — candidate Python, evaluator
  TypeScript, separate processes. There is nothing to monkeypatch.
- **Missing evidence is never acceptance.** Missing records, crashes and timeouts resolve to
  `incomplete`; a criterion with nothing applicable is `passed: false`, not vacuously true.
- **Nothing novel runs locally.** `selectRunner` decides from the source sha256 against an
  allowlist in trusted code; a one-byte edit goes to the sandbox.

### What it does not measure, and why

Relevance quality under `keyed-v2` is **unmeasured**. Sending article ids changes the request, and
the cache is keyed on a hash of the request (`backend/evals/llm_cache.py:133`), so every recorded
response for that runner is invalidated. New budgeted recordings would be required and none exist.
The Lab measures contract correctness and says so on the page.

It also does not reuse the −3.4pp / +15.6pp figures from
[`.context/batch-alignment-fix/FINDING.md`](../.context/batch-alignment-fix/FINDING.md). Those two
sides executed at different revisions (`47edb50` vs `3b11a3c`, 114 files apart, 89 vs 30 cache
keys), so they are not an A/B of the patch. The direction of that finding stands; the magnitudes
are not a controlled comparison.

### Implemented and not exercised

Vercel Sandbox (no `VERCEL_TOKEN`/team/project here) and the investigator agent (no
`AI_GATEWAY_API_KEY`, no spending limit). Both have real code and real tests; neither has run, no
agent trace is depicted anywhere, and `/lab` states both.

### Commands

```bash
cd backend && venv/bin/python -m lab.run_known        # every known implementation
venv/bin/python -m pytest tests/test_lab_contract.py  # 741, incl. all 720 permutations
cd ../web && npm run export:lab                       # rebuild web/public/lab-artifacts/
npm run export:lab -- --check                         # validate without writing
```

## The case study

[`/engineering`](app/engineering/page.tsx) follows one verified defect end to end: Daily's
production batch scorer asks for a positional array of verdicts and sends no article ids, so a
short or duplicated response shifted every later verdict onto the wrong article. A New Jersey
flood-adjacent roster story was rejected for "discussing a music EP"; an Uzbek policy story was
rejected for "discussing NFL team rosters". One of the misattributed articles is a *planted
needle* — an article injected so its correct answer is known by construction.

On one runner and one corpus the new guard fires **63 times**, including a cached response that
returned **201 verdicts for 40 articles**. Every production-pipeline number in the committed
scorecards was computed with lists shifted against their articles.

Fixing it makes the measured numbers **worse** — the unwanted rate rises 15.6 points — because
on a mismatch the guard now discards all forty verdicts rather than guessing, leaving those
candidates with no relevance signal at all. Both facts are true at once: the old numbers were
inflated by misattribution, and refusing to guess is expensive until the output carries ids. The
regression baseline was **not** re-recorded. Full evidence and the decision the owner still has
to make: [`.context/batch-alignment-fix/FINDING.md`](../.context/batch-alignment-fix/FINDING.md).

## Demo walkthrough

1. **`/`** — the sieve runs once on load: 1,362 candidates thinning to the 50 that reached the
   reader. Step it back to stage 02 and watch the recency window take 1,062 of them before a
   single model call. Switch fixture and the shape changes: `tom` ends at 9 delivered, `ray` at
   50, from the same corpus.
2. **`/reader?profile=ray`** — the edition the pipeline actually assembled for the `ray` fixture
   against the 2 September 2026 corpus. Note what it is: a New Jersey local-news reader handed a
   run of NHL trade stories. The demo does not flatter the product. Scroll to *The same corpus,
   nine other readers* for the product's central claim, checkable without reading a number.
3. **`/evidence`** — opens on `prod-llm` against `proto-hybrid-judge-events`, same corpus, same
   k, labelled as an algorithm comparison. The slope chart puts both runs on one scale; then read
   *Every fixture, no averaging* below it, where `Will` sits at 0.0% capped recall.
4. **Funnel tab, fixture `ray`** — the sieve again, this time beside the reconstructed
   survivorship table it is drawn from.
5. **Stories tab, filter "Lost before the scorer"** — stories the reader needed that the pipeline
   never even scored. Open one and the trace ribbon shows how far it got.
6. **`/engineering`** — the case study. Toggle the offset figure between *12 verdicts returned*
   and *11 verdicts returned* to see the whole defect in one move, then follow the links straight
   back into the explorer state that shows each misattributed story.

## Live mode is not built

Signing in and receiving a personally built feed is **not implemented**, and the reader page says
so on the page rather than only here. Three things block it, all access rather than design:

1. The backend adds CORS middleware only when `CORS_ORIGINS` is set. It is unset; the documented
   default is "no web clients". No browser can call the API until that changes.
2. `POST /auth/google` verifies a Google ID token issued for the iOS client. A browser flow needs
   a separate web OAuth client registered for this origin.
3. Feedback must echo the `feed_request_id`, `reader_generation` and `delivery_position` from the
   edition actually shown. Those exist only on a live delivery, so the contract cannot be
   exercised against frozen fixtures without inventing identifiers — which the harness's own
   delivery contract exists to prevent.

Live end-to-end behaviour is therefore **unverified**. Nothing on this site should be read as
evidence that it works, and the fixture editions are not reader evidence: they create no
sessions, no impressions and no feedback.

## What this site is careful never to claim

The repository's own truth boundaries, applied here:

- The ten reader profiles are **adversarial evaluation fixtures, not users**. Daily has never
  shipped to the App Store and has no readers.
- Labels are **model-written with an agent editorial pass**. Product-owner human review is
  outstanding, so absolute values are provisional and only run-to-run differences are
  gate-enforced.
- No statistical significance, no confidence intervals: none were computed.
- No claim about pgvector or ANN performance. No trained recommendation model exists anywhere in
  Daily, and hybrid retrieval is implemented but default-disabled behind feature gates.
- Offline replay cost is a reconstructed token-equivalent. Actual provider spend for the replays
  shown here is **$0**.
