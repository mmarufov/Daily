# Daily Redesign — Active Plan

> **System map: `docs/architecture/systems.md`** — the app split into ten systems with contracts,
> current state, technology choices and the order to harden them in. Start there.

## S10 — Analyse, challenge, plan and implement (2026-09-10)

### Implementation authorized (2026-09-10)

User asked for full implementation of `docs/stages/s10-implementation-plan.md`'s Tier 0 scope.
Repository changes and offline verification only; no commit, push, hosted SQL, provider spend,
deployment or activation. Tier 1/2 not attempted — their evidence gates (≥20 events per
reader-intent pair; ≥1,000 receipted impressions per position bucket from ≥50 accounts) are
nowhere close to met (0 real events, 3 accounts).

- [x] A: legacy loop correctness (idempotency, the dead topic-signal ordering bug, decay-
      before-accumulate, `hide_source` suppression, the `user_feedback_signals` FK gap).
- [x] B: event contract — client-side quick-back/skip, reward-recipe versioning.
- [x] C: one shared reward definition (`reward.py`) for both the legacy and S5 loops.
- [x] D: repeated-impression discount and passive qualified-read/quick-back engagement,
      folded into scoring at read time only — never a second writer to `reader_learned_signals`.
- [x] E: entity pins, interest suggestions and all six feedback verbs reachable in the UI
      for the first time (pure wiring; the backend already existed and was tested).
- [x] F: `evals/learning_replay.py` — proves the rejection/promotion effects through the real,
      unmodified production pipeline, closing the audit's most-important-named gap (nothing
      could previously tell you whether a learning change helps or hurts).

Repository implementation verified 2026-09-10: backend 1,884 passed / 143 skipped / 235
subtests passed (same three pre-existing S0 baseline gaps as every prior status doc, confirmed
unrelated). iOS: `xcodebuild build` succeeded for the whole app; `xcodebuild test` on a real
iPhone 17 Pro simulator passed all 121 `DailyTests`. See `docs/stages/s10-implementation-status.md`
for scope adjustments made during implementation, verification evidence and what remains out
of scope (Tier 1/2, the interval-accumulation dwell bug, length-normalized dwell, account
deletion/sign-out revocation).

Historical analysis scope: source-backed literature review, four independent code traces, one
read-only production measurement, and a coherent staged architecture recommendation — not the
grab-bag a "make it impressive" brief could have produced. Explicitly rejected, with citations:
two-tower learned retrieval, Monolith-style embedding infrastructure, HSTU generative
transducers, and full LinUCB context-vector bandits, all as the wrong shape for this app's
scale regardless of future traffic.

- [x] Trace action → telemetry → reader model → retrieval → ranking → next-edition, both the
      default-on legacy loop and the default-off S5→S7 loop; identify every missing/incorrect link.
- [x] Evaluate contextual bandits, exploration, short/long-term interests, sequential models,
      online updates and learning-to-rank against ~16 live-verified primary sources; recommend
      a coherent three-tier architecture, not a collection of fashionable algorithms.
- [x] Address position/exposure bias, noisy dwell, accidental clicks, delayed/negative
      feedback, topic fatigue, diversity, cold start, interest drift and feedback loops —
      per-failure-mode table with current status, evidence and a scale-appropriate mitigation.
- [x] Map every preservation constraint (explicit-over-learned, source exclusions, S2
      provenance, S8/S9 immutable receipts, account isolation, genuine visibility) to the exact
      existing code guarantee and an acceptance rule.
- [x] Separate small-portfolio-dataset techniques from traffic-gated ones, with numeric,
      checkable gates (not vibes) for each tier.
- [x] Define reward signals, event contracts, model/update lifecycle, evaluation, exploration
      safeguards, privacy, cost limits and failure/rollback handling.

Outputs: `docs/stages/s10-learning-audit.md`, `docs/stages/s10-implementation-plan.md`,
`docs/stages/s10-implementation-status.md`. Implementation was subsequently authorized and completed
as above.

## S9 — Analyse, challenge and plan (2026-09-09)

### Implementation authorized (2026-09-09)

User approved implementation of `docs/stages/s9-implementation-plan.md`. Repository changes and
offline verification only; no hosted SQL, provider spend, deployment or activation.

- [x] A: versioned delivery envelope, publication sequence and bounded read contract.
- [x] B: account-owned persistence, cleanup barriers and saved-account launch.
- [x] C: coordinated feed states, invalidation and foreground refresh.
- [x] D: reader permission/session lifecycle and source fallback.
- [x] E: bounded images, adaptive lazy views and exposure instrumentation.
- [x] F: integrated offline regression checks and explicit remaining rollout gates.
- [ ] Release gates: no-skip SQL concurrency tests, physical-device performance/accessibility,
      source-policy approval and deployed-build canaries (require external verification/authority).

Repository implementation verified 2026-09-10: 119 iOS unit + five isolated reader UI tests
passed. Full backend: 1,833 passed, 143 skipped, 235 subtests passed, and the same three
pre-existing S0 snapshot-quality failures. See `docs/stages/s9-implementation-status.md` for
scope refinements, evidence and unpassed release gates. No deployment or paid/live operations.

Historical analysis scope: source-backed audit, offline checks and planning documents only. No runtime
implementation, paid calls, hosted database operations, deployment or activation.

- [x] Trace feed delivery, authentication, cache, reader and image ownership.
- [x] Challenge freshness, offline, background and performance assumptions.
- [x] Complete focused offline checks and distinguish measured results from hypotheses.
- [x] Write implementation phases, contracts, failure tests and release gates; update S9 status.

Outputs: `docs/stages/s9-delivery-audit.md`, `docs/stages/s9-implementation-plan.md`.
Evidence: 115 focused existing backend tests and 30 subtests passed; all 80 iOS unit tests
passed. Findings distinguish source-confirmed paths from unmeasured races/performance.
No runtime changes, live SQL, paid calls, physical-device QA, deployment or activation.
Implementation was subsequently approved above; historical analysis evidence is retained here.

## S8 — Analyse, challenge and plan (2026-09-09)

### Implementation authorized (2026-09-09)

User approved `docs/stages/s8-implementation-plan.md`. Implement repository code and offline proof;
no paid calls, hosted database operations, deployment or activation.

- [x] A: backend–iOS status, generation and immutable receipt identity.
- [x] B: strict assembly contracts and deterministic full-pool selector.
- [x] C: current membership evidence and generation-scoped acknowledged history.
- [x] D: atomic integration, immutable cache and valid-ranking reuse.
- [x] E: evaluation, management/default-off controls and combined verification.

Repository evidence: 341 focused backend tests and 33 subtests passed; 18 S8 PostgreSQL
cases skipped (no database selected). Final full backend: 1,797 passed, 140 skipped,
235 subtests passed, with the same three pre-existing S0 quality failures. Final iOS:
80 DailyTests passed. Compile/diff checks passed. No activation or paid/live operations.
See `docs/stages/s8-implementation-status.md` for refinements and the unpassed release gates.

Historical analysis scope: read-only runtime analysis, offline checks and planning documents only. No implementation,
paid calls, hosted database operations or activation. Preserve the existing dirty workspace.

- [x] Trace assembly, story identity, novelty, final ordering and client consumption.
- [x] Challenge product promises, algorithm choices and S4/S7/S9 ownership boundaries.
- [x] Verify findings with focused offline evidence and identify evaluation gaps.
- [x] Write a bounded implementation plan, test map and release gates; update system status.

Outputs: `docs/stages/s8-edition-assembly-audit.md`, `docs/stages/s8-implementation-plan.md`.
Evidence: 267 focused existing tests and 68 subtests passed; seven synthetic probe groups
reproduce current assembly/wire-contract defects. No runtime edits, paid calls, live SQL,
iOS build or activation during the analysis phase. Implementation was subsequently approved above.

## S7 — Analyse, challenge and plan (2026-09-08)

### Implementation authorized

User approved `docs/stages/s7-implementation-plan.md`. Repository implementation and offline proof;
no paid calls, hosted database operations, deployment or production activation.

- [x] A: strict ranking contracts and candidate-stage evaluator.
- [x] B: bounded current evidence and deterministic/abstention ranking service.
- [x] C: async provider, zero-spend controls, claims and atomic result persistence.
- [x] D: semantic-fenced learning and final-only receipt attribution.
- [x] E: safe serving/cache integration across feed, chat and background consumers.
- [x] F: final combined regression run and implementation-status handoff.

Implementation evidence (2026-09-09): 308 focused tests passed; full backend run 1,602 passed,
122 skipped and the same three pre-existing S0 quality-gate failures. Compile and diff checks
passed. See `docs/stages/s7-implementation-status.md` for explicit unpassed activation gates.

Historical analysis scope: read-only runtime analysis and implementation planning. No runtime edits, deployment,
hosted database operations, provider calls, or activation. Preserve the dirty S1–S6 worktree.

- [x] Trace existing rankers, acceptance decisions, model calls, caching and all feed consumers.
- [x] Challenge ranking objectives, technology, cost/failure semantics and S6/S8 boundaries.
- [x] Verify defects with focused offline evidence and inspect evaluation gaps.
- [x] Write a file-scoped implementation plan with acceptance tests and rollout gates.
- [x] Update the system map with confirmed current status and deliver the recommendation.

Outputs: `docs/stages/s7-ranking-audit.md`, `docs/stages/s7-implementation-plan.md`.
Evidence: 161 focused existing tests passed; fake-provider/pure-function probes reproduce
malformed output acceptance, fallback promotion, entity-pin override and cached-order drift.
Implementation was subsequently approved. No paid calls, hosted database operations or activation.

## S6 — Analyse, challenge and plan (2026-09-07)

### Implementation authorized

User approved the S6 plan. Repository implementation only; no paid calls, hosted database
mutations or deployment. S6 shadow/serving/ANN stay default-off. Preserve existing S1–S5 edits.

- [x] A: strict candidate contract and independent retrieval evaluator.
- [x] B: batched current evidence and conservative policy projection.
- [x] C: independent legs, policy-aware bounded refill, attribution and fair allocation.
- [x] D: bounded execution/cancellation, SQL/index management and opt-in PostgreSQL tests (live SQL/load proof pending).
- [x] E: typed S7 handoff and default-off shadow integration with fresh authorization.
- [x] F: offline regression checks, release controls, CI and actual implementation status.

Final evidence: 359 focused tests passed. Full offline suite: 1,342 passed, 112 skipped,
182 subtests passed; the same three S0 snapshot-quality subtests fail. S6 SQL contracts:
15 skipped without explicit test database configuration, required without skips in CI.
No production activation, deployment or provider spend. See `docs/stages/s6-implementation-status.md`.

Historical analysis scope: repository-backed candidate-retrieval analysis and implementation specification.
No runtime edits, deployment, paid calls or hosted database changes. Preserve the existing
dirty worktree. Distinguish the legacy feed path from default-off S5 retrieval.

- [x] Trace candidate selection, caps, eligibility, provenance and all consumer handoffs.
- [x] Challenge hybrid-search technology and present-day schema/index compatibility.
- [x] Define candidate recall/coverage evaluation, failure semantics and performance budgets.
- [x] Produce a staged implementation plan with explicit boundaries and unresolved decisions.
- [x] Verify findings with focused offline diagnostics and update the system map.

Outputs: `docs/stages/s6-retrieval-audit.md`, `docs/stages/s6-implementation-plan.md`.
Evidence: 106 focused offline tests passed; `.context/s6-diagnostics.py` reproduces policy-after-cap
starvation and 40-row per-interest underfill. Independent retrieval/evaluation audits and design
challenge incorporated. Analysis-stage evidence is retained; implementation is now authorized above.
Actual implementation and deferred release gates: `docs/stages/s6-implementation-status.md`.

## S5 — Analyse, challenge and plan (2026-09-07)

### Implementation authorized — 2026-09-07

User approved implementation, deferring paid evaluations and extra review cycles. Essential
offline correctness checks remain part of implementation. No deployment, live database
mutation or paid model calls. Defaults: canonical typed field patches (missing unchanged,
empty clear), 24 intents, conservative explicit policies, deterministic reviewable Tune
commands, optional embeddings default-off with zero spend budget. Unknown semantic intent
requires clarification; no unverified global-quality claim.

- [x] Implement strict reader contract/compiler, additive schema and atomic authority.
- [x] Integrate versioned writers, retire revisionless writes when enabled, fence publication and preserve source policies.
- [x] Implement real Settings/Tune/onboarding edits and account-safe telemetry.
- [x] Add compatible cached per-intent embeddings and bounded retrieval/worker wiring.
- [x] Make feedback idempotent, attributed, decayed and reset-safe.
- [x] Run focused offline/backend/Swift verification and document actual remaining gates.

Repository implementation and bounded scope changes: `docs/stages/s5-implementation-status.md`.
Latest focused checks: 191 backend tests plus 4 subtests; 9 iOS unit tests and simulator
build pass. An earlier broad offline run has three existing S0 snapshot-quality failures;
do not treat the full suite as green. All S5 runtime/semantic activation flags remain off.

Paid semantic evaluation, hosted-database proof and deployment are deferred by the user's
current instruction; they are not prerequisites for finishing repository implementation,
and must not be described as passed.

Historical analysis scope (before implementation approval): reader-model architecture and implementation plan only. Portfolio value comes from
measurable correctness, inspectable design and working end-to-end behavior, not extra infrastructure.
Preserve all existing S1–S4/iOS work. No runtime changes, paid calls, deployment or publication.

- [x] Trace every S5 writer, stored representation and downstream consumer in current code.
- [x] Verify defects and separate architectural risks, missing capabilities and unknowns.
- [x] Define acceptance criteria, alternatives and the smallest complete technical design.
- [x] Independently challenge architecture, lifecycle, test validity and performance.
- [x] Produce a file-scoped, end-to-end implementation/test plan with explicit approval gates.
- [x] Verify the analysis artifacts and report remaining decisions before implementation.

Working outputs: `docs/stages/s5-reader-model-audit.md`, `docs/stages/s5-implementation-plan.md`.
Analysis-stage evidence: backend/client/architecture audits, independent draft challenge and incorporated
corrections; 94 selected offline tests pass; pure diagnostics reproduce current compiler/
normalizer defects. System map corrected. No runtime implementation, paid/live verification
or deployment during that analysis stage. Implementation is now approved and recorded above;
production/semantic-quality gates remain open.

---

## S4 — Implementation plan (2026-09-06)

Plan: `docs/stages/s4-implementation-plan.md`. Architecture: `docs/stages/s4-event-detection-audit.md`.
Implementation authorized 2026-09-06; in progress. Paid S4 calls and production actions remain
separately gated. Preserve the existing S1–S3/iOS worktree. See `docs/stages/s4-implementation-status.md`.

- [x] Translate the audit into file-scoped implementation batches, dependencies and exit gates.
- [x] Independently review lifecycle/integration and evaluation/rollout sequencing; resolve gaps.
- [x] Verify plan consistency and preserve the existing runtime/worktree baseline.

Execution (checkboxes represent full exit gates, not merely files written):

- [ ] Batch 0: baseline, acceptance manifest and upstream dependency register.
- [ ] Batch 1: contracts, independent labels, correct metric/cost ruler.
- [ ] Batch 2: upstream validity, additive schema and gap-free bootstrap.
- [ ] Batch 3: fake-provider durable worker, invalidation, leases and budgets.
- [ ] Batch 4: evidence/origin accounting, event/development grouping and material delta.
- [ ] Batch 5: strict significance provider, approved pilot and frozen quality gates.
- [ ] Batch 6: disabled independent feed recall, reader policy, cache and client expiry.
- [ ] Batch 7: integrated release candidate and mandatory hosted verification.
- [ ] Batch 8: separately authorized production shadow after live S1/S2/S3 prerequisites.
- [ ] Batch 9: separately approved 1% → 10% → 50% → 100% eligible-cohort delivery.

Offline engineering can proceed while upstream production gates are open; shadow/delivery cannot.
The detailed plan separates implementation proof, semantic-quality approval and live activation.

Engineering progress (not equivalent to the full exit gates above):

- [x] Implement strict evidence/snapshot/assessment/refinement contracts and non-circular evaluator.
- [x] Implement additive schema, reverse dependencies, exact notice receipts and cyclic reconciliation.
- [x] Implement fenced durable worker stages, bounded provider requests and reservation/settlement ledger.
- [x] Implement conservative grouping, factual fingerprints, immutable versions and merge acknowledgment aliases.
- [x] Wire default-off final feed composition, current hard-policy checks and actual delivery/read attribution.
- [x] Add optional iOS metadata with strict expiry parsing and ordinary-cache separation; verify simulator regressions.
- [x] Add dry-run operational CLI, mandatory no-skip CI gates and disposable PostgreSQL lifecycle cases.
- [ ] Execute the hosted PostgreSQL suite from an approved isolated verification snapshot.
- [ ] Finish client live priority ordering/expiry and supported semantic/operational release requirements in the status file.

---

## S4 — Event detection architecture audit (2026-09-06)

Scope: repository-backed analysis and implementation specification only. Preserve existing
S1–S3 work; no runtime edits, deployment, production mutation or paid model calls.

- [x] Reconstruct S4 prototype/runtime/evaluation and the actual S3 handoff.
- [x] Audit event identity, evidence independence, significance, novelty and reader boundaries.
- [x] Verify consequential technology choices using primary documentation/research.
- [x] Specify durable lifecycle, storage, uncertainty, failure handling and downstream invalidation.
- [x] Define adversarial evaluation, operational/quality gates and staged implementation/rollout.
- [x] Independently challenge findings, run focused offline checks and publish the S4 audit.

Deliverable: `docs/stages/s4-event-detection-audit.md`. Reproduced prototype defects; focused event/
evaluation/S3 contract checks **137 passed, 24 subtests passed**. Independent runtime and
evaluation reviews completed; final revisions resolved their must-fix issues. Existing S0
regressions remain recorded, not relaxed. System map updated; runtime code and production unchanged.

---

## S3 — Execution plan (2026-09-05)

Plan: `docs/stages/s3-implementation-plan.md`. Architecture: `docs/stages/s3-understanding-audit.md`.
Status: guarded runtime implemented and verified; capped pilot completed. Production activation
remains blocked by quality evaluation, S1/S2 prerequisites and canary proof.
Final evidence and remaining gates: `docs/stages/s3-implementation-status.md`.

- [x] Batch 0: capture worktree/test baseline, dependency register and acceptance manifest (unset production budgets stay blocked).
- [x] Batch 1: typed evidence/card contracts, revision rules, taxonomy and initial fixtures.
- [x] Batch 2: durable per-stage processing, leases, invalidation, budgets and fake-provider/hosted PostgreSQL proof.
- [ ] Batch 3: strict classifier/linker/embedding pipeline, cached labels and model selection.
- [ ] Batch 4: conservative persistent story grouping and shared consumer loader.
- [ ] Batch 5: mandatory PostgreSQL CI, migration/consumer compatibility and release review.
- [ ] Batch 6: satisfy S1/S2 production prerequisites; shadow canary and bounded backfill.
- [ ] Batch 7: search/chat cutover, legacy writer retirement and explicit S6/S7 handoff.

After batch 1, durable-worker work and dataset/provider work can proceed in parallel with
separate file ownership. Each batch has an exit gate in the detailed plan. Source expansion,
event gravity and replacement feed retrieval/ranking remain separately gated system work.

Batch 3 runtime/cache/pilot tooling is implemented; the 600-item queue is not adjudicated labels.
Batch 4 persistence/loader/correction is implemented; merge quality/ANN calibration is unproven.
Batch 5 mandatory CI, control tooling and disabled consumer adapters are implemented; production
load/rollback evidence remains open. Do not mark these quality/operational exits complete based
only on code coverage. See the execution evidence in `.context/s3/` and the S3 operating guide.

---

## S3 — Article understanding architecture analysis (2026-09-05)

Scope: inspect the current production code path and prior S0–S2 contracts; produce a
production-oriented implementation specification. This task does not implement runtime
changes, deploy, mutate production data, or start a localhost service.

- [x] Reconcile the system map with current S0/S1/S2 implementation and rollout evidence.
- [x] Audit embedding generation, analysis provenance, consumers, clustering, and evaluations.
- [x] Verify relevant technology behavior against official documentation.
- [x] Define S3 contracts, lifecycle, schema, failure handling, and boundaries with S4/S6/S7.
- [x] Specify quality/cost/freshness gates and a staged production rollout with rollback.
- [x] Independently challenge the design and publish the source-linked S3 audit/specification.

Deliverable: `docs/stages/s3-understanding-audit.md`, including the still-open implementation batches
A–G. Existing focused offline checks: **58 passed, 4 subtests passed**; final specification
review findings resolved. `docs/architecture/systems.md` now reflects observed S0–S4 state and the revised
S3 contract. No runtime changes, paid model calls, production mutations or deployment in this task.

---

## S2 — Content pipeline architecture audit (2026-09-03)

Scope: read-only product/code review of whether a selected story has trustworthy readable
content, and whether the app has a polished original-source path when it does not.

- [x] Reconstruct prior S0/S1 decisions and the existing S2/reader plans.
- [x] Audit backend acquisition, extraction, enrichment, provenance, retry, and quality-state contracts.
- [x] Audit the iOS native-reader/original-source routing, loading, error, and weak-network states.
- [x] Verify focused backend tests and inspect missing iOS/contract coverage.
- [x] Record the present-state verdict, blockers, target architecture, and implementation order.

---

## S2 — Bulletproof content and reader implementation (2026-09-03)

Source of truth: `docs/stages/s2-content-pipeline-audit.md`. This is an additive, production-oriented
migration: older mobile clients keep decoding optional legacy fields while the new client routes
from an explicit presentation contract. No production database mutation or deployment is run as
part of local implementation verification.

### P0 — Integrity and contract

- [x] Add typed content provenance, rights policy, completeness, presentation mode, and versioned
      content/job storage with idempotent schema setup and an explicit migration/backfill script.
- [x] Keep canonical publisher metadata immutable; separate user-visible bodies from ranking text
      and derived embeddings.
- [x] Disable Tavily/combined-snippet writes to publisher bodies and disable generated article
      imagery by default.
- [x] Preserve publisher-feed bodies as the highest-precedence acquired variant; never let a
      re-extractor or stale worker overwrite them.
- [x] Replace fresh/cache `content` truncation with one serializer returning `body_excerpt`,
      `presentation`, and a valid original URL.
- [x] Validate article-detail sessions and make invalid/expired tokens return 401 before lookup or
      outbound work.

### P1 — Extraction lifecycle and security

- [x] Replace extraction booleans/telemetry-driven retry control with atomically leased jobs,
      typed final states, failure classes, retry-at, expiry, and compare-and-set completion.
- [x] Remove outbound extraction from the request path; background work alone mutates content.
- [x] Add same-origin identity/completeness validation, deterministic paywall/block detection, and
      content-version invalidation of embeddings and other derived data.
- [x] Harden article and image fetching: registered/allowed hosts, manual redirect validation,
      bounded hops, public-IP checks, HTML content types, streamed byte limits, and timeouts.
- [x] Record article-level final outcomes separately from per-rung telemetry so production rates
      have the correct denominator.

### P1 — iOS reading experience

- [x] Decode typed presentation/provenance fields and remove character-count completeness guesses.
- [x] Route source-only stories directly to item-based `SFSafariViewController` presentation;
      retain a visible original-source action for native stories.
- [x] Refactor detail loading into one enum state that always preserves title/source/summary through
      missing auth, timeout, cancellation, error, and offline states.
- [x] Connect the existing background feed cache to foreground startup; cache permitted complete
      native bodies and show an honest connection-required state for source-only articles.
- [x] Replace misleading `Daily` source fallback and inaccessible tap-anywhere retry behavior.

### Verification and rollout gates

- [x] Add backend unit/contract/concurrency/security tests for provenance precedence, fresh/cache
      parity, invalid auth, redirect SSRF, size/type limits, state transitions, stale workers,
      telemetry failure, and derived-data invalidation.
- [x] Add iOS model/state/router tests plus UI coverage for native, source-web, no-token, offline,
      timeout, invalid URL, retry, double tap, and feed-position preservation.
- [x] Run focused and full backend suites, static checks, iOS build/tests, and an adversarial diff
      review; distinguish unrelated S0 gate failures from S2 regressions.
- [x] Update system/README claims and the S2 audit with implemented state and exact remaining
      production-only migration/deployment/canary steps.

### Final independent-audit closure (2026-09-04)

- [x] Bind publisher-feed artifacts to the exact reviewed feed URL that supplied the text; fail
      closed for aggregator or unregistered feeds.
- [x] Use one article-then-job lock order and cover ingestion/completion/policy concurrency on real
      PostgreSQL.
- [x] Normalize and validate rights-basis tokens at backend policy writes, materialization, API
      serialization, and the iOS render/cache boundary.
- [x] Requeue acquisition when a policy changes from a ready feed artifact to an origin-only grant.
- [x] Keep analysis text private to ranking; never synthesize a user-visible publisher summary from
      cross-source or legacy analysis.
- [x] Require structural or declared-count evidence before an extracted page is called complete.
- [x] Fail startup/readiness when the S2 schema contract is missing.
- [x] Persist authoritative empty feeds so stale rows cannot return offline, then rerun unit, real
      PostgreSQL, iOS UI, and Release gates.
- [x] Keep resumable-backfill batch and cumulative counters in one additive schema so reporting
      cannot crash after a committed batch or falsely claim that durable work rolled back.

Repository implementation and local verification are complete. Production remains deliberately
unchanged until the reviewed source-policy rows, staged backfill/constraint validation, deploy,
and live canary gates in `docs/stages/s2-content-pipeline-audit.md` are executed.

### Post-review iOS lifecycle closure (2026-09-05)

The final independent iOS audit found five P1 transitions that were not covered by the earlier
green suite. These are repository blockers before S2 can be called complete; production remains
unchanged throughout this pass.

- [x] Centralize auth identity loss/change so `/me` 401 and replacement login clear or switch all
      account-owned bookmarks, read IDs, pending reading events, and cached reader/feed state.
- [x] Make accepted authenticated detail downgrades return an explicit cache disposition and evict
      a previously verified native body instead of allowing offline resurrection.
- [x] Serialize reader-cache mutation and reject an older in-flight detail result when a newer feed
      mode, content version, or policy version has already revoked or superseded it.
- [x] Once a typed presentation contract exists, honor explicit `unavailable` over any retained
      legacy URL and require native detail URL/provenance identity before merging a body.
- [x] Add transition-focused tests for implicit auth loss/account replacement, downgrade eviction,
      stale detail completion, explicit unavailable with a stale legacy URL, and missing/mismatched
      native origin identity.
- [x] Rerun focused backend/PostgreSQL checks, iOS unit and S2 UI suites, Release build, static diff
      checks, and a final independent blocker audit; record repository versus production status.

Repository closure is complete. No production database mutation, source-policy change, deploy,
commit, or push was performed; the production-only gates in `docs/stages/s2-content-pipeline-audit.md`
remain mandatory.

---

## S1 — Sources & ingestion (approved 2026-09-02)

Plan: `~/.claude/plans/create-a-plan-to-adaptive-cray.md`. Audit: `docs/stages/s1-ingestion-audit.md`.
Decisions: in-process advisory-lock leader; Google News for discovery only; ~120-feed registry;
enrichment gated with generated images off; migrations idempotent, one-way steps run by the user.

- [x] **P0** loop that never ran (`users.last_active_at`), leader election, build SHA in `/healthz`, schema DDL once per process
- [ ] P1 `sources` registry table + seed data with region/language + `source_id` backfill
- [ ] P2 `source_poller.py`: conditional GET, `calendar.timegm`, canonical dedupe, always writes `article_source_links`, adaptive cadence, health
- [ ] P3 retire Google News as a source; `discover_publishers_for_term`; purge script for the 23,892 stubs
- [ ] P4 enrichment gated on reachability; `ENRICH_GENERATED_IMAGES=false`
- [ ] P5 `source_health` + `GET /admin/sources` + richer `/healthz`
- [ ] P6 preference edits reconcile instead of wiping the source graph
- [ ] P7 re-measure with S0; refresh baselines; grow the registry

**Deploy is a hard dependency.** Production runs a pre-2026-04-14 image; none of this is live
until it ships. `fly deploy --build-arg GIT_SHA=$(git rev-parse --short HEAD)`.

---

## S0 — Evaluation system (approved 2026-09-01)

Plan: `~/.claude/plans/create-a-plan-to-adaptive-cray.md`. Decisions: labeler = OpenAI gpt-4.1-mini pass 1 / gpt-4.1 pass 2 with a hard $30 cap; snapshots + LLM cache committed; prod build log included; GitHub Actions CI.

- [x] P0 track `backend/evals`, lazy OpenAI client, `requirements-dev.txt`, drop duplicate `scorecard.py`
- [x] P1 `evals/snapshot.py` + frozen `snapshots/2026-08-31.json.gz` + manifest
- [x] P2 `evals/llm_cache.py` caching client (chat + embeddings), meter, offline mode
- [x] P3 personas built via `build_complete_user_preferences`, 10 persona files
- [x] P4 `evals/fake_db.py` + `evals/runners.py` (ProductionRunner llm/fallback, PrototypeRunner) with stage traces
- [x] P5 `evals/label.py` pooling bootstrap + review CLI; `labels/<snapshot>/{persona.jsonl,events.json,needles.json}`
- [x] P6 `evals/metrics.py`, `evals/run.py`, scorecards, `compare.py` rewrite, README rewrite
- [x] P7 `tests/test_eval_gate.py` + `.github/workflows/backend-tests.yml`
- [x] P8 `feed_build_log` table + `_record_feed_build` in `get_personalized_feed`

### S0 completion pass (2026-09-01)

- [x] Apply an independently reasoned Codex editorial pass to every queued `must_see` and
      contested label for all ten personas with honest `source=agent` provenance; retain the
      interactive `source=human` pass as a separate product-owner gate.
- [x] Re-run production and prototype scorers fully offline against the reviewed labels.
- [x] Refresh `baseline-prod-llm.json` and `baseline-proto.json` from those reviewed runs,
      with per-snapshot delta summaries for the live and quiet corpora.
- [x] Run the complete backend suite, snapshot integrity checks, and offline eval gate.
- [x] Commit only the S0 evaluation slice; keep unrelated dirty-worktree changes uncommitted.
- [x] Make quiet derivation clone/prune ground truth and measure must-see `followup` recall.
- [x] Freeze and agent-review the second live corpus (`2026-09-02`, 50+ hours after the first).
- [x] Derive `2026-08-31-quiet` after agent-reviewing event tiers and memberships.
- [ ] Time-based follow-up: freeze the third live corpus on or after 2026-09-04 UTC, then
      bootstrap/review it and refresh both per-snapshot baselines.

---

## Phase 1 (personalization) — Close the feedback loop

**Status:** backend complete. See `docs/architecture/filtering-architecture-plan.md` for the full roadmap.

- [x] `user_feedback_signals` table + migration in `_ensure_tables`
- [x] `app/services/feedback_signals.py` — attribution, decay, adjustment, suppression
- [x] `/feed/feedback` writes durable weights instead of an inert `reading_events` row
- [x] `ScoringContext` carries feedback signals + suppressed article ids
- [x] `_apply_individual_analysis_results` applies the learned adjustment
- [x] Explicitly rejected articles can never re-enter the feed
- [x] 27 regression tests (`tests/test_feedback_signals.py`); full suite 150 passed
- [ ] Cold-start persona bucketing (Artifact's approach — assign nearest persona, refine from behaviour)
- [ ] Surface the two dormant loops in iOS: entity pins and interest suggestions
      (backend + `BackendService` methods already exist; no view calls them, so the
      +0.2 entity boost has never fired for anyone)

---


This file tracks the **current phase** of the whole-app redesign. The full design system is in `DESIGN.md`; the per-surface execution roadmap (Phases 1–10) is in `docs/architecture/design-redesign-plan.md`. This file is the focused checklist for what's being built right now.

---

## Phase 2 — Feed surface (NewsView)

**Status:** complete

Phase 2 wires the Phase 1 components into `NewsView`. Substitution is mechanical (one component swap per existing card) but the visible result is large: card chrome disappears from the feed, the hero is full-bleed, the edition signature replaces the wordmark+date treatment, and long-press on any row surfaces the "Why this story?" sheet.

### Substitution map

| File / Lines | Today | After Phase 2 |
|---|---|---|
| `NewsView.swift:22` | `heroHeader` | `editionHeader` (delegates to `EditionHeader` component) |
| `NewsView.swift:63` | `Color(.systemBackground)` | `EditionPalette.paper` |
| Hero card | `FeaturedArticleCard(style: .hero)` + `.contextMenu` | `HeroStory(article:, provenance: featured.whyThisStory, isRead:)` + `.onLongPressGesture` |
| Feed rows | `FeaturedArticleCard(style: .feed)` + `.contextMenu` + `HairlineDivider` | `StoryRow(article:, isRead:)` + `.onLongPressGesture` + sepia `Rectangle` hairlines |
| `sectionLabel` helper | serif `sectionHeroTitle`/`headline`, `BrandColors.textPrimary` | small-caps `metaCaps`, `inkBlue`, tracked 0.8 |
| Profile button | 34×34pt | 44×44pt, embedded in `EditionHeader` avatar slot |
| Removed | `articleContextMenu`, `heroHeader`, `dateHeader`, `profileButton`, `formattedHeroDate`, `SectionLabelStyle` | — |
| `BriefingCard.swift` | `BrandColors.*` | `EditionPalette.ink` / `ink60` / `inkBlue` |
| `SkeletonViews.swift` | `Color(.tertiarySystemFill)`, `Color(UIColor.label).opacity(0.15)` | `EditionPalette.paperSecondary`, `EditionPalette.ink.opacity(0.10)` |

### Three judgment calls (approved before execution)

1. **Long-press swap.** `.onLongPressGesture` → `WhyThisStorySheet` (3 corrective actions). The 4 other contextMenu actions are dropped from the feed: Bookmark/Share/Discuss reachable from `ArticleDetailView`; **More Like This is lost** in Phase 2 — Phase 4 (Tune) re-introduces it. Captured in `docs/notes/lessons.md`.
2. **Provenance gating.** `HeroStory.provenance = article.whyThisStory` (nil → no line). Cold/Warming/Earned state machine deferred until taste-model exposes confidence. Today's behavior: hero shows provenance only when backend populates it.
3. **Section label restyle scope.** `sectionLabel` helper restyled (affects "Top Story" + "For You"). Welcome banner / error banner / loading subtitle keep their current `BrandColors` references — Phase 9 cleanup migrates them globally.

### Checklist

- [x] **2a.** `editionHeader` calls `EditionHeader(dateLabel: editionDateLabel, editionName: editionName) { profileAvatar }`. Helpers compute "MAY 7" and "SARAH".
- [x] **2b.** `ScrollView.background = EditionPalette.paper`.
- [x] **2c.** `sectionLabel` simplified to one style: `metaCaps`, tracking 0.8, `EditionPalette.inkBlue`, `.textCase(.uppercase)`.
- [x] **2d.** Hero swap: `HeroStory` + `.onLongPressGesture`. Horizontal padding dropped (full-bleed).
- [x] **2e.** Feed rows swap: `StoryRow` + `.onLongPressGesture` + sepia hairline `Rectangle` between rows.
- [x] **2f.** `@State private var selectedFeedbackArticle: NewsArticle?` + `.sheet(item:)` presenting `WhyThisStorySheet` wired to `viewModel.submitFeedback`.
- [x] **2g.** Removed dead helpers: `heroHeader`, `dateHeader`, `profileButton`, `articleContextMenu`, `formattedHeroDate`, `SectionLabelStyle` enum.
- [x] **2h.** BriefingCard palette swap (8 token replacements).
- [x] **2i.** SkeletonViews palette swap (2 token replacements).
- [ ] **2j.** Build clean (`xcodebuild ... iPhone 17 Pro`).
- [ ] **2k.** Simulator boot: tap-through Feed → ArticleDetail → back; long-press a row → WhyThisStorySheet appears with three actions; tap profile (44pt) → ProfileView.
- [x] **2l.** `docs/notes/lessons.md` updated with the contextMenu-loss note for Phase 4.
- [ ] **2m.** Single commit: `feat: replace feed surface with edition header + hero + story rows`.

### Out of scope

- `welcomeBanner`, `errorBanner`, "Loading your personalized feed..." text — Phase 9 global migration.
- `FeaturedArticleCard` struct stays as dead code; Phase 9 deletes it.
- Re-introducing "More Like This" affordance — Phase 4 (Tune) takes ownership.

---

## Previously shipped

- **Phase 1** — Tokens & Components Scaffolding. Commit `38b83ef`. Added `EditionPalette`, 7 typography tokens, 6 components (`EditionHeader`, `HeroStory`, `StoryRow`, `ProvenanceLine`, `WhyThisStorySheet`, `DiffToast`).
- **Foundation** — DESIGN.md and 10-phase plan. Commit `1df9f6b`.

---

## Presentation — Keep Our Park Clean

**Status:** in progress

- [x] Inspect every slide in the retained Team Alignment template.
- [x] Map five output slides to reusable template layouts.
- [x] Write an English environmental-campaign narrative with substantial text.
- [x] Source and embed two relevant photographs per slide.
- [x] Render all five slides and fix overflow, cropping, and overlap issues.
- [x] Run template-fidelity and slide-overflow checks.
- [x] Deliver the verified PowerPoint file.

---

## Read-only resume evidence audit — Daily (2026-09-02)

- [x] Baseline branch/worktree state and compare the audited tree with `origin/main`.
- [x] Verify iOS architecture, auth/session handling, caching/offline behavior, background work, and Apple integrations.
- [x] Verify backend ingestion, storage, deduplication, ranking, personalization, feedback, Tune, and AI implementation.
- [x] Verify deployment, reliability, privacy/App Store requirements, tests, CI, and retained evidence.
- [x] Produce interview-defensible Google/Meta, Apple/iOS, backend, and applied-AI resume variants.
- [x] Recommend Daily's resume position and whether it should replace LookMatch or YConstruction.
- [x] Save and validate the complete report at `.context/resume-evidence-daily.md` without editing product code.

## Neon staging provisioning — 2026-09-12

- [x] Create isolated `daily-staging` Neon project in the separate Free organization; do not touch the old production database.
- [x] Obtain its pooled connection URL and validate PostgreSQL/pgvector against the empty staging database.
- [x] Stage only `daily-backend-staging` credentials using the existing provisioning script.
- [x] Deploy current checkout with its Git SHA and run the staging smoke script.
- [x] Record live verification and provide a credential-free handoff; leave production unchanged.

Evidence: `.context/staging-provision.log` and `.context/staging-provision-result.json`;
script exited 0, all nine smoke checks passed, both staging Fly machines healthy.
Deployed `mmarufov/sydney-v7` at `3cbffb25ec64a3c71b1641fb676329afd3ee80f6`.
This verifies deployment/readiness/auth guards, not all product flows or production readiness.

### Follow-up, 2026-09-13: the first deploy was healthy only while warm

- [x] Re-verify staging independently after the machines had auto-stopped. They did not
  come back: `/healthz` returned 503 after ~59s, and every uvicorn child process died on
  spawn. The first smoke run passed because the deploy had left the machines warm, so it
  never exercised the cold-start path that `min_machines_running = 0` guarantees.
- [x] Diagnose. Not the database (Neon pooler connects, `_ensure_tables` completes), not
  memory (805MB free, `oom_killed=false`), not the app (`--workers 1` boots cleanly). The
  differentiator was the VM: `shared-cpu-1x`, which I had set to save money. Production
  runs the same image, same 1gb, same `--workers 2` on `shared-cpu-2x` and is fine.
- [x] Fix: staging now matches production's VM shape. Cold start from fully stopped is
  9.8s / HTTP 200, and all nine smoke checks pass from cold, twice.
- [x] Add `backend/.dockerignore`: the build context was 265MB, 213MB of it the local
  venv, and it included `backend/.env` with a live `OPENAI_API_KEY`. Now 12.6kB.

Lesson, recorded in `docs/notes/lessons.md`: a deploy smoke test that only ever runs while the
machines are warm does not test the deploy, and shrinking staging away from production's
shape means rehearsing something that is not production.

## Repository presentation for GitHub (2026-09-14)

Goal: make the public repo read like a professionally maintained project without changing
any runtime behaviour. Constraint: no functional change, prove it with the test suite.

- [x] Rewrite `.gitignore` so nothing that must stay private depends on a machine-local
      `.git/info/exclude` — `.context/`, `artifacts/`, `*.pptx`, `*.inspect.ndjson`,
      `node_modules/`, CI scratch. Verified `git ls-files -i -c --exclude-standard` is
      empty (no tracked file became ignored) and `git add -A` stages only 70 real files.
- [x] Add `.gitattributes`. `linguist-generated=true` on `backend/evals/.cache/**`,
      `snapshots/`, `labels/`, `results/` and `*.pbxproj` so GitHub collapses them in pull
      requests and keeps them out of the language bar; `export-ignore` on dev-only paths.
      The committed LLM cache is kept — CI needs it for `EVAL_OFFLINE=1`.
- [x] Move `tasks/` → `docs/{architecture,stages,notes}/` and `DESIGN.md` → `docs/`, with
      `git mv` so history follows. Rewrote all 118 cross-references, including 14 source
      comments; verified every one resolves. Root went from 26 entries to 15.
- [x] Delete `PRODUCTION_READINESS.md` — every "Current State" claim contradicted by code.
- [x] Deduplicate `CLAUDE.md` into a symlink to `AGENTS.md` (they were byte-identical).
- [x] Add `docs/README.md` as the documentation index (S0–S10 audit/plan/status table).
- [x] Add `.github/`: PR template, two issue forms + `config.yml`, `CODEOWNERS`,
      `dependabot.yml` (monthly, grouped), `release.yml`, `SECURITY.md`, `CONTRIBUTING.md`.
- [x] Rewrite `README.md` around the honest built-vs-live distinction, the S0 harness and
      its real numbers, the ten-stage table, and a Known gaps section.
- [x] Correct four false README claims (iOS 17 → 26, Apple Sign-In, `/docs` in production,
      Tune live re-sort) against the code.
- [x] Set repo description + 15 topics; disable wiki and projects; enable
      delete-branch-on-merge.
- [x] Verified: `EVAL_OFFLINE=1 pytest tests/ -q` → 1,960 passed, 185 skipped. Every
      source-file change in this pass is a comment or docstring.

Deliberately not done, pending a decision:

- [ ] `LICENSE` — still `null`, so GitHub shows no license chip and the repo fails the
      community checklist. Needs an owner decision, not a default.
- [ ] Prune stale remote branches (75, including `hong-kong-v1`…`v22`) and close or
      finish PR #40 (open since April).
- [ ] Delete the unrelated `artifacts/` + `*.pptx` from the working copy (45 MB). Now
      gitignored, so harmless, but still local clutter.
- [ ] No shared Xcode scheme, so iOS tests cannot run in CI. Adding one means editing the
      project file — out of scope for a presentation-only pass.
- [ ] Social preview image (1280×640) is UI-only; no CLI or API path.
- [ ] `AppConfig.swift` defaults to the owner's production backend, so anyone who clones
      and runs the app spends the owner's OpenAI budget.


## Visa pipeline correctness evidence audit — 2026-09-19

- [x] Establish clean checkout, current default revision, and prior audit boundaries.
- [x] Inspect leases, stale writes, stage enforcement, provenance, durable cache, and cost guards.
- [x] Verify source counts, current CI, failure tests, and measurement limits.
- [x] Produce five ranked findings with exact evidence and explicit gaps.

Evidence: `.context/visa-audit/`; HEAD and current GitHub main `3b11a3c`. Fresh offline suite: 1,960 passed, 185 skipped, 239 subtests in 105.08s. Exact-revision CI run 34928490180: 155 PostgreSQL tests passed. No runtime changes, live database operations, or deployment.


## Vercel integration — 2026-09-21

- [x] Research pass: eval artefact surface, LLM provider map, web/share surface, hosting and
      database constraints. Three read-only subagents; no runtime or deployment changes.
- [ ] Decide scope. Full analysis and a tiered build plan: `docs/notes/vercel-integration-plan.md`.

Headline finding: every remaining activation gate in this repository is blocked on reader
traffic that does not exist (never released, zero `/feed/*` requests ever, 3 accounts), so a
web edition is the unblock rather than a résumé line. Second: `backend/evals/` already emits
dashboard-ready JSON that nothing renders, and CI emits no scorecard at all, so there is no
time series. Third: the documented S6 blocker is Supabase free-tier `shared_buffers`, and
staging already runs Neon. Explicitly rejected: migrating the FastAPI daemon to Functions —
`lifespan()` runs seven infinite loops plus advisory-lock leader election.


## Vercel web companion — 2026-09-21

Implementation of the brief in `.context/attachments/`: a web tier for Daily on Next.js, an
interactive explorer for the S0 harness, and one verified debugging case study.

Facts established first, each of which changed the design:

- [x] `47edb50` (the revision every stored scorecard records) is **not an ancestor of HEAD** — a
      side branch off `b48f244`; everything under `backend/evals/` reached main in one squash
      commit. `git log --follow` on the results files therefore cannot detect edits, which is why
      the export uses `git merge-base --is-ancestor` and records reachability explicitly.
- [x] 9 result files = **7 run scorecards + 2 baselines**, and the 2 baselines duplicate two runs.
      Only 6 independent LLM experiments (2 pipelines x 3 corpora); `prod-fallback` is a
      deterministic no-model control, not an experiment.
- [x] **No stored scorecard records a protocol.** The harness added `meta.protocol` later, so
      protocol equality between runs cannot be verified from the artifacts. Exported as `unknown`.
- [x] `baseline-prod-llm.json` is a hybrid document: its `snapshot_baselines["2026-09-02"]` was
      re-recorded on 2026-09-11 while its embedded timestamps still read 2026-09-02. The export
      detects this by comparison, not by hardcoding, and marks `timestamps_trustworthy: false`.
- [x] `cache_misses_total == 0` does **not** prove offline replay — the counter only increments on
      the live network path, so it is structurally zero under `EVAL_OFFLINE=1`. Execution mode is
      exported as `unknown`.
- [x] `stage_counts` is **terminal-stage** counts, not survivorship. Reading it directly yields a
      growing funnel. Reconstruction validated against three independent facts in the same
      scorecard, plus the 4-article needle delta.
- [x] The vault's "branch hazard" is resolved: `backend/evals/` is on the default branch, and
      `main` now exposes 42 endpoints and 80 tables, not 32 and 18.

Delivered:

- [x] Versioned, validated public artifact contract + reproducible export (`web/lib/artifact.ts`,
      `web/scripts/export-artifacts.ts`). Byte-identical across runs; timestamps come from the
      HEAD commit, not the wall clock.
- [x] Evidence explorer with shareable URL state, run/corpus/pipeline/fixture selection,
      compatibility-checked comparison, reconstructed funnel, and per-story trace drill-down.
- [x] Reader demo replaying a dated frozen edition, no login, no backend, no provider key.
- [x] CI: `evidence-artifacts.yml` (untrusted, no secrets, always uploads diagnostics) plus
      `evidence-publish.yml` (trusted, `workflow_run`, publishes only on success, manifest last,
      revision-scoped prefix). `backend-tests.yml` extended additively only.
- [x] Scoped backend fix + 9 regression tests (5 fail without it) for the positional
      output-misalignment defect in `score_articles_batch`, and for `CacheMiss`/`BudgetExceeded`
      being swallowed by a blanket handler.

**Open decision for the owner.** The alignment fix makes the regression gate red. Full offline
suite with the fix: `6 failed, 1969 passed, 185 skipped, 233 subtests passed`. All six are
`test_eval_gate.py` subtests on `prod-llm` (`never_rate_mean`, `lookalike_rate_mean`,
`needle_recall_mean`); the same suites without the fix give `42 passed, 4 skipped, 59 subtests
passed, 0 failed`, so the six are attributable to this change alone and nothing else in 1969
tests broke.

The cause is that the fix stops the scorer misattributing verdicts, and the committed production
numbers depended on that misattribution. Under identical inputs the unwanted rate rises 15.6 pp.
The baseline was deliberately **not** re-recorded. Evidence, the measured before/after, and the
three options: `.context/batch-alignment-fix/FINDING.md`.

Not done: live signed-in reader flow. Blocked on `CORS_ORIGINS` being unset, the absence of a web
Google OAuth client, and delivery receipts that only exist on a live edition. Marked unverified in
the UI rather than simulated.
