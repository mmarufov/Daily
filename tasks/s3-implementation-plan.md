# S3 implementation plan

Created 2026-09-05. Updated 2026-09-06: guarded runtime and hosted database verification
implemented; labeled quality, production prerequisites and rollout remain incomplete.
Architecture and evidence: [S3 audit](s3-understanding-audit.md).
This document is the execution checklist; the audit remains the detailed contract and rationale.

Execution status is tracked in `tasks/plan.md`; retained test/pilot evidence is in `.context/s3/`.
The checklists below are the full acceptance contract, not a claim that implementation alone
satisfies semantic quality or production rollout. The operating guide is
`backend/app/data/understanding/OPERATIONS.md`. No production flags or schemas have been changed.

## Outcome and boundaries

Deliver a shared article-understanding service that produces current, evidence-backed facets,
compatible embeddings and correctable story memberships. Every article revision must have a
visible processing outcome. Corrections, outages, retries and restarts must preserve correctness.

Implement against production contracts, with no localhost application or alternate local
product configuration. Deterministic tests run offline; destructive fault injection uses a
disposable CI PostgreSQL database, never customer data. Production changes happen through the
staged migration and canary sequence below.

S3 includes migrating the existing semantic-search/chat embedding consumers. Replacing global
feed retrieval, ranking, event gravity and reader novelty belongs to S6/S7/S4/S8. Deliver the S3
interfaces and explicit handoff tests for those systems; do not call the whole personalized
feed complete merely because S3 is running. Keep native-reader eligibility entirely within S2.

## Fixed implementation choices

- PostgreSQL is authoritative for jobs, results, revisions and publication events. Use pgvector
  for candidate lookup and a separate supervised worker from the backend image.
- Start with one original-evidence article vector and one article per classification request.
  Reuse successful facet/vector substages independently; improve batching only after measurement.
- Use strict typed outputs plus semantic/evidence validation. Missing or ambiguous evidence
  produces explicit abstention. Models cannot invent canonical entity/place IDs.
- Version all semantic inputs, analysis eligibility, processing recipes and story assignments.
  A body-only version does not cover a headline correction. Display-only policy changes do not
  automatically force recarding; analysis revocation does invalidate current results.
- Allow several enabled computation recipes for shadow comparisons; select the serving recipe
  separately. Keep old and new embedding writers in separate storage until consumer cutover.
- Treat all model choices in the audit as benchmark candidates. Pin the winning model, SDK,
  tokenizer, taxonomy and recipe only after the required evaluation and compatibility checks.

## Sequence and useful parallel work

| Batch | Deliverable | Depends on | Can run alongside |
|---|---|---|---|
| 0 | Baseline, dependency register and acceptance manifest | Existing audit | None before baseline is recorded |
| 1 | Input/output contracts, evidence selection, revision rules and initial fixtures | 0 | S1/S2 deployment prerequisite verification |
| 2 | Durable jobs, immutable results, invalidation and worker with fake provider | 1 | Labeling, vocabulary curation and isolated provider adapter from batch 3 |
| 3 | Validated classifier/linker/vector pipeline and model selection | 1; publication uses 2 | Batch 2; cluster fixtures for batch 4 |
| 4 | Conservative persistent story grouping and consumer loader | 2 + 3 | Migration/runbook preparation |
| 5 | Integrated release candidate and required CI proof | 2–4 | Read-only production readiness checks |
| 6 | Additive production rollout, shadow processing and bounded backfill | 5 + S1/S2 activation gates | No source expansion during the canary |
| 7 | Search/chat cutover, legacy retirement and S6/S7 handoff | 6 passes | Later-system design against the now-stable S3 interface |

One owner integrates schema, article revision writers and publication locking. Delegate labels,
provider implementation and independent review only after the relevant interface is fixed.
Avoid two agents independently modifying `main.py`, `article_content.py` or the same migration.
Use one reviewable commit/PR-sized unit per deliverable, split a batch if needed; each remains
disabled until its dependencies are complete. Publishing or deploying is a later execution
action, not something performed by this planning task.

## Batch 0 — Record the starting point and release conditions

- [ ] Capture branch SHA, complete dirty-worktree inventory, S0 snapshot hashes and test results
  in `.context/s3/`. Preserve existing S1/S2/iOS work; establish its integration baseline before
  applying S3 changes. Do not treat the current uncommitted S2 implementation as present on main.
- [ ] Reproduce and record existing failures, especially the three named S0 metric regressions.
  Retain exact failing metrics/snapshots; no baseline replacement, test deletion or broad xfail.
- [ ] Inventory every writer of title, summary, identity, dates, chosen analysis artifact and
  provenance. Include global/per-user ingestion, extraction, corrections and backfill.
- [ ] Inventory vector consumers, feed cache generations and article deletion/retention paths.
- [ ] Create a machine-readable acceptance manifest: supported language/evidence slices,
  forecast article revisions/day and burst load, freshness targets, quality thresholds, retention,
  benchmark spending cap and production spending ceiling. Unset budgets prevent paid runs.
- [ ] Confirm S1/S2 prerequisites with current code and read-only deployed schema/build checks.
  Track blockers separately: canonical registry/poller/acquisition identity, S2 schema/backfill,
  deployment/readiness and rollback. Native display grants are not required for source-only use.

Exit: an auditable baseline and finite dependency list. Engineering on batches 1–5 can continue
while deployment prerequisites are addressed; batch 6 cannot bypass them.

## Batch 1 — Fix the contract before adding intelligence

Primary files: new `backend/app/services/understanding_contract.py`,
`backend/app/data/understanding/`, `backend/tests/test_understanding_contract.py`;
integration inventory for `article_content.py`, `news_ingestion.py`, `user_source_pipeline.py`.

- [ ] Define typed evidence bundles, facet cards, embedding results, readiness/abstention states
  and recipe identity. Keep internal evidence out of the public serialization contract.
- [ ] Implement one deterministic S2-to-S3 evidence selector. Preserve title-only/excerpt cases;
  reject mismatched provenance and exclude cross-source/legacy text from authoritative v1 inputs.
- [ ] Define normalized input hashing and metadata revision rules. Include all model-visible
  fields and artifact identities; test semantic changes versus harmless formatting changes.
- [ ] Define analysis-eligibility generation and recipe generation separately from native-display
  policy. Specify the shared DB trigger/transaction primitive that covers every inventoried writer.
- [ ] Freeze the initial bounded topic hierarchy, place roles, entity resolution states and
  documented unknown behavior. Use canonical IDs with versioned definitions and examples.
- [ ] Add 40–60 hand-auditable contract cases spanning negation, namesakes, promotions versus
  reporting, title-only input, source-web stories, stale headline corrections and prompt injection.
- [ ] Define the internal consumer loader interface and stage-level trace before implementing it.

Exit: deterministic contract tests pass. The same inputs reproduce the same fingerprint; a
headline correction changes it; a display-only change does not manufacture semantic changes;
revoked analysis evidence becomes unusable. An independent reviewer signs off the contract.

## Batch 2 — Prove durable processing with a fake provider

Primary files: new `understanding_repository.py`, `understanding_worker.py`, additive migration
and status/reconcile scripts under `backend/scripts/`; focused PostgreSQL and worker tests.

- [ ] Add schema for revisions/eligibility, recipes, per-stage jobs, immutable results, per-recipe
  current projections, usage reservations and outbox. Enforce ownership and unique publication.
- [ ] Wire transactional scheduling into all semantic writers, plus bounded reconciliation for
  missed jobs/pre-migration rows and resumable recipe upgrades on unchanged articles.
- [ ] Claim with leases and stable ordering; reserve fresh and backfill capacity, enforce source
  fairness and bounded attempts/deadlines. Reap expired final attempts as well as retryable ones.
- [ ] Run provider work outside transactions. Persist successful stages independently. Publish
  by CAS against article revision, evidence eligibility, enabled recipe and lease token/expiry.
- [ ] Use one documented lock order compatible with S2: articles first, then jobs/projections,
  then cluster state; sorted IDs for multi-article changes. Job-only claims acquire no article lock.
- [ ] Implement transactional outbox and idempotent consumers; validate input currency at load
  time even when an invalidation event is delayed or lost.
- [ ] Implement provider circuit state, bounded retries and atomic spend reservations. Preserve
  conservative accounting after ambiguous timeouts; reconcile actual usage and duplicate attempts.
- [ ] Handle deletion, retention, revocation and recipe disablement without stale resurrection.
- [ ] Add worker supervision, graceful cancellation and readiness/liveness checks independently
  of the existing ingestion loop. Keep all provider work disabled by default.

Exit: real PostgreSQL tests prove duplicate claims/publication, final-attempt crash recovery,
lease loss, mid-call correction/deletion/revocation, disabled recipes, spending races, deadlock
avoidance and outbox replay. Restarting a worker completes or accounts for every claimed job.
No model spending is needed to prove these invariants.

## Batch 3 — Implement and evaluate understanding quality

Primary files: new `understanding_provider.py`, `entity_linker.py`, tokenizer/input recipe;
`backend/requirements.txt`, `backend/evals/llm_cache.py`, new understanding labels/runner/metrics.

- [ ] Pin a compatible SDK after testing existing OpenAIService, chat/scoring and offline cache
  surfaces. Introduce a small S3 adapter; avoid an unrelated whole-app API migration.
- [ ] Implement strict per-article output parsing with bounded input/output tokens, response-ID
  checks, refusal/incomplete handling, evidence-span validation and supplied-ID validation.
- [ ] Embed deterministic original evidence; verify dimensions, finiteness, nonzero norm and
  request/response alignment. Version query/document recipes and prevent mixed embedding spaces.
- [ ] Resolve entity/place mentions against supplied canonical candidates, or abstain. Keep
  unresolved new entities representable; do not merge namesakes by normalized name.
- [ ] Build at least 600 distinct article labels plus story pair/group labels as the initial
  dataset. Split development/holdout by story to avoid syndicated-copy leakage. Expand any
  underpowered supported-language or critical-error slice before promotion.
- [ ] Cache every provider request by exact request/recipe hash. Add the S3 cache adapter before
  warming; CI cache misses fail offline. Label human/agent/model provenance accurately.
- [ ] Register explicit prices for every selected dated model ID and fail before submission if
  pricing is unknown. `evals/llm_cache.py:64` currently falls back to zero for unknown IDs and
  checks budget after responses: fix benchmark accounting and use batch-2 pre-call reservations
  for production. Test pinned aliases, cache-hit accounting and concurrent budget exhaustion.
- [ ] Run a small capped pilot first. Reject structurally broken candidates before spending on
  the full matrix. Compare the audit's model/input candidates on development data, freeze the
  winning recipe, then evaluate held-out data without tuning against its answers.
- [ ] Measure cost per accepted revision including failures/retries and optional escalation.
  Escalate only resolvable ambiguity; missing evidence terminates in explicit abstention.

Exit: the selected recipe passes the audit's supported-slice quality gates and the batch-0
budget. Unknown outcomes remain visible. If it fails, revise on development data and obtain
a fresh holdout for the next promotion attempt; do not hide failure by lowering requirements.

## Batch 4 — Add correctable story membership

Primary files: new `story_clustering.py`, cluster/membership migration, internal understanding
loader, and article-pair/group quality tests. Reuse result storage and outbox from batch 2.

- [ ] Start each usable article as a persistent singleton. Retrieve compatible candidates by
  embedding space and bounded time window; keep unknown-date and late-arrival behavior explicit.
- [ ] Verify specific development using supported entity/action/object/time/place evidence,
  representative members and an ambiguity margin. Similarity alone cannot authorize a merge.
- [ ] Handle roundups/live blogs with multi-event hints; no forced destructive single-story dedupe.
- [ ] Implement assignment revision, retraction, merge/split history and concurrent revalidation.
  Remove superseded members from summaries/centroids and retain observed versions for consumers.
- [ ] Carry source ownership/syndication uncertainty for later S4 breadth calculations.
- [ ] Compare approximate candidate recall against exact search with real date/language/readiness
  filters. Verify the server's pgvector capabilities independently of the Python package version.
- [ ] Expose current, missing, partial, stale and revoked outcomes through the shared loader.

Exit: false-merge and missed-merge gates both pass, including bridge articles, repeated events,
shuffled arrival order, namesakes, multi-event articles and late reports. All-singleton output
cannot pass by precision alone. S3 never labels world-critical events or reader-relative novelty.

## Batch 5 — Make the release candidate verifiable

Primary files: `.github/workflows/backend-tests.yml`, S3 migration/backfill/status scripts,
`backend/fly.toml`/worker launch configuration, consumer adapters, operational documentation.

- [ ] Add a required disposable PostgreSQL CI job with the selected production-compatible
  pgvector version. Fail when DB setup/extension/permissions are missing; do not silently skip.
  Existing S2 tests use opt-in setup, so strengthen the required job's execution/collection checks.
- [ ] Run S2+S3 migrations twice, resume after interruption, validate constraints and test old/new
  backend coexistence. Build heavy indexes outside API startup with a documented online procedure.
- [ ] Prepare resumable dry-run/capped-apply backfill, deterministic cohorts, status counters,
  per-source/language dashboards and flags separating work submission, recipe promotion and use.
- [ ] Integrate search/chat adapters behind disabled flags; test query-space compatibility,
  evidence privacy, stale-result behavior and rollback without removing legacy columns/writer.
- [ ] Run the full offline backend suite and snapshot matrix once the integrated change settles.
  Compare exact failures with batch 0. New or unexplained failures block this candidate; previously
  recorded S0 quality failures remain explicit and block claims that the whole product is green.
- [ ] Run an independent blocker review of migrations, locking, provider/cost behavior,
  privacy/serialization, deletion and all consumer boundaries. Fix findings and rerun affected checks.
- [ ] Package the deployment/runbook with build SHA, schema version, recipe IDs, cohort caps,
  abort conditions and rollback commands. Deployment credentials/secrets stay out of artifacts.

Exit: required tests actually execute, the release candidate is reproducible, migration rollback
behavior is demonstrated and the shadow launch package is concrete. No live customer ranking
has changed. Do not rerun unrelated iOS builds unless the public API/client surface changes.

## Batch 6 — Deploy in shadow, then backfill fairly

- [ ] Reconfirm S1/S2 activation prerequisites from batch 0 against the intended deployed build.
  Complete additive schema/backfill/readiness requirements; use source-only display where appropriate.
- [ ] Back up and review migration dry-run results. Apply schema and deploy the worker with
  submissions and consumers disabled; verify build/schema/extension and worker health.
- [ ] Enable a capped, stratified recent-article cohort. Persist shadow results separately from
  serving state. Audit actual evidence, outputs, costs and queue fairness before widening.
- [ ] Grow processing cohorts 1% → 10% → 50% → 100% of the declared target population only after
  each gate passes. Use stable assignment within source/language slices; absolute article/token
  ceilings override percentages so a burst cannot exhaust the budget.
- [ ] Backfill recent articles first with checkpointed batches and reserved capacity for fresh
  arrivals. Older history follows only if needed by consumers and retention permits it.
- [ ] Observe at least 72 hours, with quiet/weekend coverage and burst behavior, plus sufficient
  examples in every enabled slice. Fault/load replay stays on disposable infrastructure; live
  canaries observe production behavior and exercise only controlled authorized test records.
- [ ] Validate freshness, terminal/error rates, retry/escalation share, budget accounting,
  filtered ANN performance and recovery from naturally observed provider issues.

Immediate abort: accepted wrong-article evidence, current stale/revoked results, private-text
leak, mixed vector space, spend ceiling breach, growing unresolved lease backlog or migration
integrity error. Stop submissions if needed and disable consumers; retain diagnosis evidence.
Quality/latency/coverage thresholds failing their observation window pause cohort expansion.

Exit: production artifact includes counts/denominators, supported slices, quality samples,
latency distribution, cost distribution and rollback evidence. Time elapsed alone is insufficient.

## Batch 7 — Cut over existing consumers and hand off feed adoption

- [ ] Promote the validated recipe for a controlled search/chat cohort. Migrate query embeddings
  and document lookup together; compare relevant results against the legacy path and exact search.
- [ ] Verify S2 presentation and private/public evidence separation through each consumer. A
  missing current card cannot be interpreted as affirmative evidence or default commercial=false.
- [ ] Expand consumer cohorts only when their quality/latency gates pass. Preserve a tested
  fallback and independent consumer-disable flag.
- [ ] Disable the legacy embedding writer only after all consumers have migrated and the rollback
  path is proven. Keep additive history/columns through the rollback window; cleanup is a separate,
  explicitly scoped follow-up after dependency checks.
- [ ] Deliver S6/S7 integration contract: current result loader, compatible query recipe,
  topic/entity lookup, assignment versions, fallback states and transactional change events.
- [ ] Supply feed-adoption tests covering changed candidate membership, invalidation cursors,
  stale in-flight builds and stored reason/score revisions. Existing feed TTL alone is insufficient.
- [ ] Record remaining S4/S6/S7/S8 work in their system checklists. The current source-join/recency
  gate still needs its own retrieval implementation before shared S3 results improve the feed.

Exit: S3 is operational and its current consumers are correct; later systems have stable
interfaces and acceptance fixtures. End-to-end personalized-feed perfection is not an S3-only claim.

## Acceptance scoreboard

Detailed definitions and adversarial cases are in audit §9. These are release requirements,
not measurements already obtained. Report counts, coverage and uncertainty for every slice.

| Area | Gate |
|---|---|
| Publication integrity | Zero wrong-article, stale/revoked, mixed-space or private-text violations in required fault/contract tests and canary inspection |
| Article kind / primary topics | Kind macro-F1 >=0.90; topic precision >=0.95 and recall >=0.90 |
| Entity/place resolution | Precision >=0.98 and recall >=0.90 among resolvable mentions; abstention coverage reported |
| Promotional suppression readiness | Precision >=0.99 and promo recall >=0.95; underpowered/failed slices cannot authorize automatic suppression |
| Story grouping | Pairwise precision >=0.98 and recall >=0.90; B-cubed metrics and catastrophic merge cases included |
| Vector lookup | Filtered ANN recall@50 >=0.98 against exact search on the same population |
| Freshness / capacity | >=99% of supported usable fresh inputs ready within 5 minutes at forecast load; sustain 2x forecast load and report all-input outage/terminal rates |
| Cost | Actual accepted-revision cost and projected spend fit the batch-0 ceiling, including retries/reprocessing |
| Regression | No new unexplained backend/S0 failures; required real-DB tests cannot be skipped |

Practical release discipline: qualify semantic accuracy for the supported inputs using held-out
evidence, and make stale-result prevention/recovery deterministic. Do not promise that a model
will never misclassify an article; prevent uncertain classifications from silently becoming
authoritative decisions for every reader.

## Efficiency rules

1. Spend on the model only after fake-provider lifecycle tests and the evaluation cache work.
2. Pilot on a small set before the full model matrix; classify revisions once and reuse results.
3. Reserve fresh-article capacity before backfill. Delay source expansion until retrieval is ready.
4. Start with a bounded taxonomy and one vector; add chunking, extra models or infrastructure only
   to solve a measured failed gate.
5. Run focused tests during each batch, full integration checks at batch 5 and after material
   changes. Do not repeatedly rerun identical green suites without new evidence.
6. Keep migrations, model promotion and consumer promotion independently reversible.
7. Treat confirmed final-review findings as open checklist items to fix before declaring completion.

## Planning verification

The plan was checked against the current worktree, S3 audit, existing S2 PostgreSQL harness,
OpenAI cache meter and hosted CI workflow. Independent review findings on required DB test
execution, pinned-model pricing, old/new worker overlap and scope boundaries are incorporated.
`git diff --check` passed. This planning task changed documentation only; it did not rerun
runtime suites or execute any implementation, paid benchmark or production action.
