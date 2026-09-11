# S5 Reader model — implementation handoff

2026-09-07. Repository implementation completed for the bounded slice below. **Not deployed
or production-proven.** The user deferred paid evaluation and additional review rounds;
no provider calls, hosted database mutations, deployment, commit or push were performed.
Existing unrelated S1–S4, iOS and document changes were preserved.

## Implemented

- Strict v3 reader document: explicit typed interests, qualifiers, priorities, expiry,
  language/depth/context and separately scoped policies. Original script is retained;
  biography is not embedded. Unknown fields and over-limit input are rejected, not truncated.
- PostgreSQL authority with user-before-reader locks, atomic projections/invalidation,
  generation/revision/learning revision, stable operation receipts and stale-base conflicts.
  Imported legacy profiles require explicit review; projections do not create extra authority.
- Authenticated reader GET/PATCH, operation lookup, reviewable Tune proposals and reset.
  Settings, onboarding and Tune use real canonical writes. Cancel does not apply anything;
  no pretend Undo. Settings can remove publisher/article/subject rules and confirms reset.
- Shared current-policy checks around feed/S4 publication and personalized chat evidence.
  Excluded historical thread metadata cannot enter new generation. Briefing uses an honest
  deterministic headline digest. In-flight bytes and offline copies cannot be recalled.
- Bounded independent-interest lexical retrieval, per-leg reciprocal-rank fusion, deduplication
  and balanced candidate union. Explicit feedback adjusts later allocation without removing
  each nonempty interest's initial opportunity. Empty interests do not receive invented matches.
- Optional compatible per-interest query vectors with S3 recipe/space checks, durable leases,
  conservative token reservation, deadlines, capped attempts and publication fencing.
  Unreviewed/deleted accounts cannot start or publish embedding work. Reset removes optional
  vector/job rows atomically and changes generation; late worker publication cannot recreate them.
- Source reconciliation changes only reader-owned associations; manual/legacy controls survive.
  Every active explicit query gets a deterministic search-feed candidate. No discovery model call.
- Immutable served-interest receipts, stable explicit feedback IDs, decay before accumulation,
  bounded weights and reset-safe learning. Missing delivery evidence does not invent attribution.
  Passive telemetry does not infer S5 preferences. Client batches/retries retain stable IDs and
  are fenced against account changes; explicit-feedback pending receipts are account-scoped.
- Explicit dry-run operational CLI, separate concurrent lexical-index command, bounded receipt
  retention sweeps, and independently disabled serving/worker/semantic flags.

Core backend files are `app/services/reader_{contract,compiler,repository,api,integration,
retrieval,worker,feedback,source_reconcile}.py` plus three additive SQL schemas. iOS contracts
and transport live in `Daily/Models/ReaderProfile.swift` and `Daily/Services/Reader*.swift`.

## Deliberate scope adjustments and limits

- Typed **field patches**, not an arbitrary operation language: omitted fields preserve values;
  empty lists clear them. Stable IDs and revisions still protect identity and concurrent edits.
- When S5 is enabled, old revisionless preferences/entity/suggestion mutation endpoints return
  409 instead of guessing a base revision. Updated mobile flows use the canonical service.
  A dedicated entity-resolution/suggestion editor is not included; rich existing intent fields
  survive Settings edits. Coordinate client/backend cutover; old clients cannot edit in S5 mode.
- Tune supports deterministic “More…”, “Less…”, “Follow…” and “Stop following…” proposals.
  Ambiguous/mixed instructions require clarification or structured editing, not LLM guesswork.
- No reader feed cache or request-path model scoring. Candidate results are recomputed and
  publication is version-checked. This reduces cache correctness surface; production latency
  and recall still need measurement. S6/S7/S8 are not claimed complete.
- Semantic serving is experimental and disabled. It requires compatible approved S3 artifacts,
  cached vectors and an explicit measured similarity threshold. RRF is not a probability.
  Current lexical matching is conservative, all-term, PostgreSQL `simple` full-text matching;
  it does not establish multilingual semantic recall or worldwide news coverage.
- Source query feeds currently use Google News's English/US configuration and are unvalidated
  discovery candidates, not guaranteed coverage. Publisher filtering occurs on article identity.
- Literal hidden phrases mean exact token phrases in title/summary, not an inferred broad topic
  ban. Canonical subject/language policies abstain on missing evidence; this can reduce or empty
  a feed. Broader facet availability and quality are upstream/S6 gates, not guessed here.
- Canonical state survives server reload. In-progress Settings/Tune drafts and mutation IDs are
  retained in the current view/session, not a durable preference-write outbox across app death.
  On restart, fetch canonical state. Explicit-feedback retry receipts persist for seven days;
  passive telemetry is bounded best-effort and in memory, not lossless analytics.
- Retention: operation receipts 7 days, proposals 1 day, delivery/feedback receipts 30 days,
  token-spend rows 90 days. Request paths prune their own receipts; schedule the bounded cleanup
  command for inactive accounts too. Worker reconciliation removes obsolete non-running jobs.
  User/reader foreign keys cascade new S5-owned state on actual deletion; hosted lifecycle and
  existing account-deletion integration are not proven by mocked tests.

## Verification actually run

- Latest focused backend suite: **191 passed, 4 subtests passed**. Includes reader contracts,
  authority, vectors, integration, management and existing feed/chat/preferences/loop regressions.
  These are offline tests using fakes/stubs, not proof of PostgreSQL lock behavior.
- Latest simulator build and selected tests: **9 passed**, `TEST SUCCEEDED` (ReaderProfileTests
  and ReadingEventTrackerTests, iPhone 17 Pro simulator). Unit-test app startup bypasses normal
  auth restoration; no live application walkthrough was run.
- Earlier full offline backend run (before final added regressions): **1,120 passed, 5 skipped,
  182 subtests passed; 3 failed subtests** in the existing S0 `prod-llm` snapshot gate:
  follow-up recall 0.0397 vs baseline 0.1111, never-rate 0.395 vs 0.2694,
  event delivery 0.15 vs 0.25. Gate thresholds and fixtures were not weakened.
- `git diff --check` passes. Logs: `.context/s5-focused-tests.log`,
  `.context/s5-unit-tests.log`, `.context/s5-backend-tests.log`.

## Activation runbook — not executed

Keep `.env.example` defaults: `S5_READER_ENABLED=false`, `S5_WORKER_ENABLED=false`,
`S5_SEMANTIC_ENABLED=false`. No similarity threshold or positive spend budget is supplied.

From the repository root, this is a disconnected preview:

```sh
backend/venv/bin/python backend/scripts/manage_s5_reader.py migrate
```

After separate authorization and hosted verification, use an explicitly selected database
environment variable and `--apply`. Core/S1–S3 schemas must already exist. Commands:

1. `migrate`: atomically install authority, feedback and optional embedding schemas; no activation.
2. `index`: build the matching article full-text GIN index concurrently, outside migration locks.
3. `status`: inspect aggregate review/job state and embedding controls without private query text.
4. `cleanup`: remove at most 1,000 expired rows per receipt/spend table per invocation; schedule it.
5. `budget --daily-global-tokens N --daily-user-tokens M`: explicit positive budgets (M ≤ N),
   enabling only the DB worker gate. `pause` disables that gate; it does not disable lexical serving.

Enable canonical lexical serving only after schema/API/mobile compatibility, hosted transaction
and account lifecycle tests, index/query-plan/latency checks and a controlled rollout. Semantic
activation additionally needs held-out relevance/coverage measurements, a threshold, approved
S3 recipe and consciously allocated spend. Run the worker separately with
`PYTHONPATH=backend backend/venv/bin/python -m app.services.reader_worker`; process flag and DB
budget must both allow work. Turning off semantic serving leaves lexical retrieval available.

Those production and paid-quality gates remain open. The implementation is inspectable and
offline-tested; it is not a claim that personalization works perfectly for every reader.
