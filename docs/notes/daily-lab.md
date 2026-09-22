# Daily Lab — engineering case study

**What it is.** A controlled experiment on Daily's batch relevance scorer, at `/lab`, inside the
existing repository and Vercel project. It investigates a real defect, preserves three versions of
the fix, runs them against a frozen case suite, and publishes verdicts computed by trusted code
rather than reported by the thing under test.

## The defect

`openai_service.score_articles_batch` sends forty articles as a numbered list, asks for
"one entry per article, same order", and **sends no article identifier**. The parse is positional:

```python
if len(results_list) != len(articles):
    logger.warning("... normalizing")     # logged, then ignored
for i in range(len(articles)):
    entry = results_list[i]               # association by ARRAY POSITION
```

There is no output cap and `finish_reason` is never read, so a truncated completion is
indistinguishable from a malformed one, and a blanket `except Exception` swallows the harness's
own `CacheMiss` (a `RuntimeError`) into an all-zero fallback that still reports zero cache misses.

**Measured, not asserted.** Replaying the production runner offline over the committed recordings
in `backend/evals/.cache/llm` produced 42 real batches. Of those, **21 carry a verdict count that
differs from the batch** (27/40, 31/40, 53/40, 19/20 — and one response returning **254 verdicts
for 40 articles**, with `finish_reason: "stop"`; the model did not run out of room, it looped), and
**18 are truncated completions**. The worst is published on `/lab` with the real articles and the
recorded bytes.

## The finding that did not survive re-checking

`.context/batch-alignment-fix/FINDING.md` reports the fix costing −3.4pp capped recall and +15.6pp
unwanted rate, under the line *"Only the parse differs."* That is not supportable:

| | before | after |
|---|---|---|
| scorecard | `47edb50-prod-llm-2026-09-02.json` (committed, historical) | `after-fix.json` (freshly executed) |
| revision | `47edb50` | `3b11a3c` |
| `cache_keys` | 89 | 30 |
| `meta.protocol` | absent | `production-feed-v1` |

Two commits separate them, one of which is a 114-file squash touching `evals/metrics.py`,
`pipeline.py`, `run.py`, `runners.py` and adding three modules. A third of the cache keys differ.
The **direction** of that finding is well supported — the three misattributed rejections and the
five failing regression tests are revision-independent — but the **magnitudes** are a comparison
across revisions, not an A/B of the patch. The Lab therefore does not reuse those numbers, and
scopes itself to a question a controlled experiment can actually answer.

## What the experiment measures

**Contract correctness**: does a candidate associate every verdict with the article it was about,
and refuse when it cannot? Not relevance quality — sending article ids changes the request, which
invalidates every recorded response for that runner, and no budgeted keyed recordings exist.

64 cases in two groups that are never mixed:

- **observed/** — 42 real batches replayed from the committed recordings. An observed case may
  assert only what the recording settles: a truncated, malformed or miscounted response has no
  recoverable association. It never claims which article a verdict *should* have gone to.
- **synthetic/** — 22 labelled fault injections with ground truth by construction: reordering,
  duplicate/unknown/missing ids, NaN and out-of-range scores, wrong types, malformed and truncated
  JSON, and the execution outcomes (no recording, timeout, cancelled, budget exhausted).

## The architecture, and why the boundary holds

```
  TRUSTED (reviewed repo code, TypeScript)        UNTRUSTED (candidate, Python)
  ────────────────────────────────────────        ─────────────────────────────
  lib/lab/spec       frozen criteria + hash
  lib/lab/evaluator  computes the verdict   ◀───  prediction records (JSON only)
  lib/lab/scope      patch scope gate                        ▲
  lib/lab/runner     where code may execute                  │
  lib/lab/runstate   durable event log            contract/*.py — parse(articles, raw)
```

Four properties, each with a test that fails if it stops holding:

1. **A candidate cannot grade itself.** Prediction records have no field meaning "passed"; the zod
   schema strips unknown keys. The `control-self-reporting` candidate emits
   `passed/score/all_tests_green` and is rejected exactly like any other.
2. **The trust boundary is a language and process boundary.** The candidate is Python, the
   evaluator is TypeScript, in a different process. There is nothing to monkeypatch.
3. **Missing evidence is never acceptance.** A missing record, a crash, a timeout or an
   unreadable bundle resolves to `incomplete`. A criterion with nothing applicable is `passed:
   false`, not vacuously true.
4. **Nothing novel executes locally.** `selectRunner` decides from the source's sha256 against a
   hand-maintained allowlist in trusted code. A one-byte edit to a committed implementation goes
   to the sandbox.

## Results

| Candidate | Verdict | Why |
|---|---|---|
| `positional-v0` (today's production) | **rejected** | parses all 64 cases; refuses nothing. 48/48 universal-refusal cases failed. |
| `count-guard-v1` (PR #59) | **rejected** | fixes every count case (48/48) but cannot see an equal-length reorder; 3/9 protocol violations caught. |
| `keyed-v2` (proposed) | **accepted for review** | all 5 criteria over 60 applicable cases. |
| `control-lenient-keyed` | **rejected** | last-write-wins on duplicate ids; 3/9. |
| `control-self-reporting` | **rejected** | fabricates associations and grades itself; ignored. |
| `control-zero-filling` | **rejected** | turns a missing recording into confident zeros. |

**Permutation invariance is exhaustive, not sampled.** The synthetic batch has six articles, so all
**720** orderings of a valid keyed response are checked; the association is identical across every
one. The negative control asserts `positional-v0` is *not* invariant — without it the property test
would have no power.

## Recovery, honestly

`backend/lab/orchestrate.py --kill-after attempt-started` SIGKILLs the orchestrator with an attempt
in flight (exit 137). On the next invocation it folds the persisted event log, finds an attempt
that started and never reported, and records it as **`unknown-outcome`** — not `failed`, because
whether the work completed is genuinely not knowable from the parent. Attempt #02 completes.
`/lab/interrupted` shows both, with real timestamps.

Durability makes *orchestration* recoverable. It does not make a sandbox creation or a blob write
exactly-once, so publication is idempotent on the run id: the first artifact stands and later
deliveries are counted, never merged.

## The publication boundary, fixed

`evidence-publish.yml` fired on `workflow_run` for **pull-request builds too**, checked out
`workflow_run.head_sha` — a fork's commit — then ran `npm ci` (executing the fork's install
scripts), then `npm run export:artifacts -- --check` (the "re-validation" was the fork's own code),
then `npm run publish:artifacts` with `BLOB_READ_WRITE_TOKEN` in scope. A fork branch merely named
`main` also flipped `PUBLISH_AS_LATEST` to `true`.

Now gated on `conclusion == success && event == 'push' && head_branch == 'main'`, with a step that
refuses to continue unless `HEAD` is reachable from `origin/main`. Independently, the publisher
learned to check what it was never checking: `artifact_revision` must match `/^[0-9a-f]{7,40}$/`
(a manifest declaring `"latest"` previously reached the mutable pointer with no `PUBLISH_AS_LATEST`
at all), `entry.file` must be a plain file name, and every artifact's sha256 **and** byte count are
recompared against the manifest before upload — schema conformance is not integrity.

## What is implemented but not exercised

Stated plainly rather than implied:

- **Vercel Sandbox** — the boundary, limits and selection logic exist and are tested. No sandbox
  has been created: there is no `VERCEL_TOKEN`/team/project here. Every published run took the
  local path because every candidate is byte-identical to a committed implementation.
- **The investigator** — four typed tools, a one-proposal budget, and the same scope gate a human
  patch faces. `readiness()` reports `missing-credentials`; no model has been called and **no agent
  trace is depicted anywhere on the site**.
- **Protocol-v2 recordings** — would need a provider key and an explicit budget. Until then
  relevance quality under `keyed-v2` is unmeasured, and `/lab` says so.

## Reproduce

```bash
cd backend
EVAL_OFFLINE=1 venv/bin/python -m lab.extract_observed --snapshot 2026-09-02
venv/bin/python -m lab.build_synthetic
venv/bin/python -m lab.run_known
venv/bin/python -m lab.orchestrate --candidate keyed-v2 --kill-after attempt-started   # exits 137
venv/bin/python -m lab.orchestrate --candidate keyed-v2                                # resumes
venv/bin/python -m pytest tests/test_lab_contract.py -q                                # 741 passed

cd ../web
npm run export:lab && npm run export:lab -- --check
npx vitest run && npx playwright test
```
