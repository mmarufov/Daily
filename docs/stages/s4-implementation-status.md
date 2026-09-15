# S4 implementation status

2026-09-06: guarded implementation present; **not production-ready or enabled**.
The implementation request is authorized. Paid S4 processing, hosted verification publication,
production migration and rollout are separate execution gates. No S4 paid calls, production
database mutations, deployments, commits or pushes have been performed in this implementation.

Baseline before implementation: branch `mmarufov/sydney-v7`, HEAD
`b667985ddc4a1e7b4a871ba33ef7c28ccbeb880d`; existing dirty S1–S3/iOS files preserved.
The focused baseline command in the implementation plan passed **137 tests, 24 subtests**.
The existing S0 September 2 regressions are retained (followup .1111→.0397, never .2694→.395,
event delivery .25→.15). No paid calls or production mutations have been made for S4.

## Implemented engineering

- Strict evidence, snapshot, assessment and refinement contracts. References bind original
  quotes, article revisions, S3 result/recipe IDs and reviewed source generations. Missing,
  refused, malformed, unsupported or stale results do not become routine or critical decisions.
- Explicit additive PostgreSQL schema and separate supervised worker. Intake, refinement,
  grouping and assessment use bounded durable jobs, real-clock leases and atomic publication.
  No migration, extraction or model processing starts on an S4 feed request.
- Complete current evidence-manifest checks, sorted publication locks, control generations,
  exact outbox receipts and cyclic anti-entropy. Late old invalidations cannot purge newer valid
  evidence; obsolete private snapshots/refinements are purged by dependency coordinates.
- Strict no-tools provider adapters with exact prepared request hashes, priced reservation
  ceilings, daily/monthly accounting and conservative unresolved charges. Settlement precedes
  publication; a duplicate attempt cannot dispatch twice. These controls do not constitute
  permission to spend or proof of model quality.
- Conservative opt-in exact development grouping, immutable refined versions, factual
  fingerprints and version-specific merge aliases. Active evidence selects the representative
  development; historical inactive IDs cannot suppress a new development. Uncertain matches
  abstain. Pure broader candidate/delta mechanics are not a calibrated semantic matcher.
- Default-off independent event recall on all three feed endpoints, including no followed
  sources. Fresh snapshot checks apply current hard reader exclusions to ordinary rows and event
  representatives; public S2 fields and source-web routing are preserved. At most two critical
  slots and 100 total items; priority is never written into the ordinary feed cache.
- Content-free delivery receipts bind account/request/article/development/version. Only explicit
  later tap/read/already-knew events acknowledge them; issuance alone is not a read. Merge aliases
  preserve these acknowledgments, and user deletion cascades receipt deletion.
- Optional iOS event metadata validates identifiers, versions, timezone/microsecond precision,
  future dates and expiry. Ordinary reader caches strip priority; article-detail responses cannot
  invent or renew it. The client does **not** advertise the S4 capability header.
- Independent evaluation package with family/time/protocol bindings, confidence-bound gates,
  negative and representative denominators, execution/outcome evidence and fail-closed promotion.
  Historical model-seeded labels are not recast as independent ground truth.
- Dry-run-first management CLI, disabled deployment template, operating guide and mandatory
  deterministic/PostgreSQL CI gates that reject absent or skipped required suites.

## Verification

- iOS simulator: **32 tests passed** — 9 S4 metadata, 16 reader and 7 cache contracts.
  Result: `~/Library/Developer/Xcode/DerivedData/Daily-hhybyatzshtarmcozjzzdtzdjxzp/Logs/Test/Test-Daily-2026.09.06_19-34-40--0700.xcresult`.
- Deterministic S4 gate: **480 passed, 5 subtests passed**, zero skips across **15 modules**.
  XML: `.context/s4-contract-results.xml`; required module/no-skip assertions also passed.
  Focused endpoint/S1-loop/feed checks: **68 passed, 4 subtests passed**. Local fixtures validate
  contracts, not actual PostgreSQL transaction isolation or model quality.
- Disposable PostgreSQL suite: **50 cases collect; not executed** because no
  `S4_TEST_DATABASE_URL` is configured. CI requires real S2/S3/S4 execution with zero skips.
  An isolated GitHub verification snapshot/run was requested; approval has not been received.
  Required-database mode was checked separately and correctly fails collection without a URL.
- Full regression initially found 982 passing tests, 75 skipped, the three retained S0
  subtest regressions and three offline cache failures after the evaluation protocol changed.
  New prompts cannot consume old cached answers. Historical S0 replay is now explicitly named
  `proto-s0-legacy-v1`, with protocol-bound comparisons and unchanged baseline JSON/response cache.
  The default `proto` remains canonical-global-events-v2 and truthfully fails on missing exact
  cached responses. Historic reader-only call ceilings remain 12/30; preparation is reported
  separately and included in total cost/calls. Historical replay does not certify current S4.
- Final full backend run: **1,042 passed, 97 skipped, 182 subtests passed; three known S0
  metric subtest failures remain**, and no new cache/source-inspection failures. Command:
  `EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests -q`.
  Log: `.context/s4-final-tests.log` (103.82 seconds). This is **not an all-green release**:
  required hosted database tests have not run, and the retained S0 quality regressions are open.
- `git diff --check` passes. Current branch and normal index remain unchanged; no changes staged.

## Remaining engineering before reader activation

These are explicit unfinished plan exits, not features implied by the implemented files:

1. Run and repair real hosted migration, concurrency, crash/replay, invalidation and accounting
   tests; then measure at least 2× the approved load forecast. Mock tests cannot close this gate.
2. Calibrate event recall and correction/material-change adjudication on independent evidence.
   Runtime grouping currently supports conservative exact signatures; hybrid semantic recall,
   explicit reviewed split/reconciliation and full historical material-delta adjudication are
   not certified or fully connected. No universal recall or automatic re-alert claim is made.
3. Supply independently reviewed provenance and supported coverage slices. The current coverage
   watermark is an explicit operator attestation, never refreshed by assessment time; automatic
   upstream coverage monitoring and a measured purge/retention operating loop remain required.
4. Separate live priority state/ordering from iOS ordinary article caching, implement visible-time
   expiry and lifecycle tests, then advertise genuine client capability. Current live feed loaders
   call the cache sanitizer, intentionally stripping S4 metadata. Do not enable the header yet.
5. Scoped major events are returned as an unforced candidate handoff; this task leaves ordinary
   S7 scoring unchanged. No claim is made that those candidates already reach personalized ranking.
6. Implement stable eligible-account cohort controls and measured canary/rollback automation
   before 1% → 10% → 50% → 100% delivery. A global delivery boolean is not cohort rollout.

## External release gates

- Approved support/rubric owners, immutable independent labels/holdout and statistically
  sufficient event-family/negative/representative evidence.
- Explicit numeric S4 pilot/daily/monthly budgets. Prior S3 pilot approval does not cover S4.
- Current live S1/S2/S3 prerequisites, approved build, backup/restore and rollback evidence.
- Separately authorized production shadow for at least 72 hours **and enough qualifying cases**,
  then explicit delivery approval. Sparse or quiet traffic is not a passing quality result.

`backend/app/data/events/acceptance.json` deliberately remains unapproved with empty support
slices and unset budgets. See the implementation plan and operations guide for exact commands.
Passing deterministic fixtures must never be reported as complete S4 quality or production proof.
