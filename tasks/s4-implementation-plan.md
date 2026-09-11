# S4 implementation plan — evidence-backed event detection

Created 2026-09-06. Status: **guarded implementation in progress; production activation not started**.
Current engineering evidence and open exits: [implementation status](s4-implementation-status.md).
Architecture, observed defects and primary-source rationale: [S4 audit](s4-event-detection-audit.md).
Progress index: [active plan](plan.md). Upstream readiness: [S3 status](s3-implementation-status.md).

## 1. Outcome and scope

Daily should recognize a bounded real-world event across reports, distinguish genuinely new
developments from repeated coverage, assess consequences using attributable evidence, and deliver
a current, relevant, policy-eligible article without losing corrections or over-alerting readers.

“Bulletproof” means tested invariants, explicit uncertainty, bounded spending, recoverable failures
and statistically supported quality within a declared coverage cohort. It does not mean perfect
worldwide knowledge. No finite model benchmark or short canary can establish that claim.

This plan includes the minimum end-to-end S6/S8/S9 integration needed to make S4 actually reach
readers. It does not replace all personalization/ranking, expand the worldwide source pool, add
push/emergency alerts, introduce a public multi-source generated article, or rewrite S3. A new
CAP/official-alert ingestion lane remains a separately approved S1 project, not an S4 prerequisite.

Implementation will target production contracts. Use offline deterministic tests and disposable
hosted CI PostgreSQL for destructive, concurrency and load tests; no localhost product/server.
Production migrations, paid evaluations and activation are separately authorized execution stages.
Implementation does not authorize those separately gated actions. Preserve all existing dirty S1–S3/iOS work.

## 2. Decisions to carry into implementation

- Keep Python, PostgreSQL 16 and the existing pgvector stack. Use explicit migrations, durable
  stage jobs and a separate supervised worker. No Kafka, graph database or additional vector
  service without measured need. Start with bounded exact candidate search; ANN is optional later.
- Create stable S4 event and material-development UUIDs. S3 groups are evidence inputs, never S4
  identity or proof of event membership. Topic links do not inherit criticality.
- Separate event identity, attributed claims, significance, material change and reader delivery.
  `pending`, `unknown`, `error` and `disputed` are not `routine`; tier can be absent.
- Consume only current, analysis-eligible S3 results in an explicitly approved serving cohort,
  with article/result/membership/source/control generations checked at publication and reading.
- Prefer an S4-owned, versioned evidence-refinement adapter for missing modality/time precision.
  Preserve S3 v1; bind references to result ID + hint index + hint hash. Only change S3's semantic
  schema if a contract test proves this adapter cannot carry the necessary evidence. Never infer
  precise dates, affirmative facts or canonical identities from missing v1 fields.
- Count reporting origins, distribution reach and primary authority separately. Unknown origin
  is unknown, not independent corroboration; publisher geography is not event geography.
- Models receive bounded evidence, return strict typed decisions, and have no tools or browsing.
  Server-side validation checks evidence support, IDs, versions and policy. Model choice remains
  a measured development-set decision, not a promise attached to a provider name.
- New evidence or control changes revoke obsolete priority immediately at the committed validity
  boundary; recomputation is asynchronous. Failures neither renew expiry nor downgrade unknown to
  routine. An in-flight response authorized before a later invalidation cannot be recalled.
- A critical candidate may override soft topic ranking only. It never overrides explicit reader
  exclusions, authorization, analysis rights, source blocks or current representative eligibility.
  Native body availability does not determine editorial importance: preserve S2 source-web routing.
- Recognize every supported critical event; reserve at most `min(2, edition_size)` display slots.
  No forced filler, duplicate development or feed overflow. Two slots is not a detector quota.
- Computation, shadow assessment and reader delivery have separate controls. Default all new
  production switches off; unset spending ceilings or unsupported slices fail closed.

Policy defaults and quantitative targets below are proposed release criteria. Freeze their
approval before paid calibration/holdout use; do not change them to rescue a failing score.

## 3. Execution order and ownership

| Batch | Deliverable | Must follow | Useful parallel work |
|---|---|---|---|
| 0 | Baseline, support/budget manifest and dependency register | Audit | None before inventory |
| 1 (A) | Typed contracts and a non-circular evaluation ruler | 0 | Independent evidence adjudication after rubric freeze |
| 2 (B1) | Upstream validity fences, additive schema and gap-free bootstrap | 1 | Evaluation fixtures and pure evidence algorithms |
| 3 (B2) | Durable fake-provider worker, invalidation and budget proof | 2 | Offline provider adapter; grouping fixtures |
| 4 (C) | Evidence refinement, event/development grouping and material delta | 1–3 | Dataset adjudication and disabled consumer scaffolding |
| 5 (D) | Bounded significance adapter and calibrated frozen recipe | 3–4; labels ready | Batch 6 against frozen DTO/fake decisions |
| 6 (E) | Independent feed recall, reader policy, cache and client expiry | 2–4; DTO fixed | Batch 5; operating documentation |
| 7 | Integrated release candidate and mandatory hosted verification | 2–6 | Read-only upstream readiness inspection |
| 8 (F) | Capped production shadow, no reader priority | 7 + live S1/S2/S3 approval | No concurrent source/recipe expansion |
| 9 (G) | Gradual eligible-cohort delivery and monitored rollback | 8 + all release gates | Ordinary unrelated feed remains operational |

One integration owner controls shared revision writers, schema, lock ordering, feed publication
and `main.py`. Delegate independent dataset review, pure algorithms and provider-contract tests
after interfaces are fixed. Do not let parallel agents invent different generation semantics or
edit the same migration. Each batch can be several reviewable changes; completion is an exit
gate, not a commit count. Do not mix unrelated dirty workspace files into S4 changes.

Engineering batches 0–7 may proceed while upstream deployment prerequisites are open. Production
shadow cannot. A singleton S3 group is acceptable input; an unapproved S3 recipe is not.

## 4. Batch 0 — Baseline and finite acceptance manifest

Files: `.context/s4/` evidence; new `backend/app/data/events/acceptance.json`,
`backend/app/data/events/OPERATIONS.md`; future `tasks/s4-implementation-status.md`.

- [ ] Record branch SHA, full dirty-worktree inventory, scoped diff hashes, installed dependencies
  and existing S0/S3 evidence. Do not mistake uncommitted S3 work for shipped mainline code.
- [ ] Re-run the existing focused offline checks before edits. Record the three known September 2
  S0 regressions (followup `.1111 → .0397`, never `.2694 → .395`, event delivery `.25 → .15`)
  without changing the baseline, deleting assertions or applying broad xfails.
- [ ] Inventory every evidence/control writer: article revisions/deletion, analysis policy,
  source origin, S3 result/recipe/approval/membership, retention, backfill and feed cache writes.
- [ ] Define supported language/geography/event-type/evidence slices, editorial rubric owner,
  explicit reader hard rules, forecast revisions/day and burst rate, maximum event/evidence size,
  latency objectives, retention/purge deadline, queue/retry limits and failure escalation owner.
- [ ] Require numeric pilot, daily and monthly ceilings, token/request limits and priced model
  configuration before any paid stage. S3's previous $5 authorization does not authorize S4.
  Null budgets block calls. Record any desired combined S3+S4 ceiling as a separate shared-budget
  requirement; independent stage caps cannot enforce an aggregate cap.
- [ ] Track live prerequisites separately: S1 canonical acquisition/coverage/origin availability,
  S2 current revision/analysis rights, S3 promoted cohort/quality/worker health and deployment
  compatibility. Unknown metadata must remain representable, not filled with guesses.

Exit: reproducible baseline and machine-validated manifest; missing operational decisions block
the affected paid/release stage, not offline skeleton work. Never present old deployment evidence
as a fresh production check.

## 5. Batch 1 — Contracts and the independent ruler

New files: `backend/app/services/event_contract.py`, `backend/app/data/events/rubric.json`,
`backend/evals/events/` for versioned schemas, manifests, alignment, labels and replay fixtures;
`backend/tests/test_event_contract.py`, `backend/tests/test_event_eval.py`.
Existing integration: `backend/evals/{run,runners,label,metrics,global_events,pipeline,llm_cache}.py`.

- [ ] Define immutable evidence references, uncertain time intervals and modality, attributed
  contradictory claims, origin groups, event signatures, development versions, decision status,
  consequence dimensions, supported scope, `as_of`, `valid_until` and material-delta categories.
- [ ] Freeze same-development / same-event-new-development / related-only / different /
  insufficient matching semantics. Make core evidence versus side-angle membership explicit.
- [ ] Define the S3 handoff and consumer DTO, including approval generation, evidence manifest
  digest/count, admitted-member-set generation, event version and source registry version.
- [ ] Run global detection on the canonical pool before persona needles. Global synthetic cases
  live in a separate scenario manifest. Hash full inputs, source metadata, recipe and time cutoff;
  move global preparation/retries into system-wide cost and latency accounting exactly once.
- [ ] Quarantine model-only labels as seeds. Independently adjudicate September 2's 17 events;
  retain disagreements and reviewer provenance. Freeze rubric and dev/holdout partitions before
  tuning, including the S3 cohort/recipe, source-origin snapshot, support declarations, alignment
  and interval methods. Review complete sampled windows or use documented event-level inclusion
  probabilities. Protect heldout IDs/access from candidate tuning.
- [ ] Separate representative-stream estimates from balanced/adversarial tests; split event
  families, syndicated origins and neighboring time windows. Prevent future corrections, updated
  metadata and model historical knowledge from supplying unavailable evidence at a replay cutoff.
- [ ] Implement deterministic one-to-one prediction/gold alignment. Duplicate predicted events
  are extra predictions; one broad topic cannot match multiple gold incidents. Score event and
  development membership separately, deweight syndication and report family macro scores.
- [ ] Critical recall includes every gold critical development with qualifying available input:
  abstention, missing, failed and late outputs are misses. Report S4-conditional and S1–S4
  end-to-end recall separately. Keep slot contamination as a distinct reader metric.
- [ ] Add mandatory S4 gate validation: missing labels, unreviewed slices, empty predictions,
  underpowered samples and cache misses cannot produce a passing release report. Do not reuse
  optional `EVAL_GATE_STRICT` skips as S4 certification.

Exit: validators reject malformed/boolean IDs, absent verdicts and unsupported claims; tiny
hand-calculated fixtures prove metric denominators/alignment/abstentions; label provenance and
heldout protocol are frozen. Label collection may continue, but semantic promotion stays blocked.

## 6. Batch 2 — Durable schema and upstream validity before projections

New files: `backend/app/services/event_schema.sql`, `event_repository.py`,
`backend/scripts/manage_s4_events.py`, `backend/tests/test_event_postgres.py`,
`backend/tests/test_s4_management.py`.
Existing boundary edits: `understanding_repository.py`, `understanding_schema.sql`,
`article_content.py`, article deletion/source-policy writers identified in batch 0.

- [ ] Add versioned S3 serving approval/control and source-origin/policy revision notices before
  building an S4 current projection. Read-time validity checks remain authoritative even when
  notifications are delayed. Keep semantic S3 recipe content immutable.
- [ ] Add `event_recipes`, `event_control`, `events`, `event_developments`,
  `development_versions`, `event_evidence`, `event_snapshots`, `event_assessments`, `event_jobs`,
  `event_changes`, namespaced inbox/outbox/receipts and spend reservations. Define uniqueness,
  positive versions, ownership, stage checks, reverse indexes and cycle-free redirect constraints.
- [ ] Document generation ownership: upstream writers advance their input/control revisions;
  evidence admission/removal and event changes advance S4 event/member generations; publication
  binds the exact snapshot; cache entries store dependency generations, not just a TTL.
- [ ] Retain non-content reverse links/tombstones sufficient to invalidate all former events
  after deletion, split or retraction. Missing expected rows must fail validation; joins may not
  silently shrink a previously complete manifest. Include negative and withdrawn evidence.
- [ ] Make migration explicit, serialized, additive, idempotent and version checked. No feed
  request DDL. Test old application compatibility, populated-database upgrade and interruption
  recovery on disposable hosted PostgreSQL. Set bounded lock/statement timeouts and inspect
  large-table index/backfill plans before production. Initial rollback disables new use; it does
  not drop data or require a destructive down migration.
- [ ] Register the S4 consumer and implement gap-free bootstrap: establish change retention first,
  enumerate current eligible inputs with stable pagination, validate revisions when applying,
  and replay retained changes with exact receipts including late commits. Do not advance a numeric
  high-water cursor past unseen lower-ID transactions. Test writes/deletes during every phase.
- [ ] Schema/backfill/control commands default to inspect/dry-run, require expected versions and
  explicit bounded scope for mutation, and display target database/build without secrets.

Exit: current projection cannot exist without all validity fences; hosted migration/bootstrap/
delete/control-change tests pass. Missing DB configuration in required CI is a failure, not a skip.

## 7. Batch 3 — Prove the lifecycle without paid intelligence

New files: `event_worker.py`; extend repository/schema; deterministic provider interface/fake;
`backend/tests/test_event_worker.py`, `test_event_budget.py`, `test_event_postgres.py`.

- [ ] Implement independently retryable refinement/grouping/assessment/reconciliation stages with
  dedup keys, lease tokens, deadlines, attempts, backoff/jitter and terminal/quarantine outcomes.
  Bound intake and recovery work; prevent one large event or failed source from starving others.
- [ ] Transactionally apply upstream changes to S4 inbox receipts and dirty jobs. Commit job
  claims before model work. Freeze immutable input manifests and reserve maximum priced cost
  before each dispatch; release database connections before network I/O.
- [ ] Handle timeout/crash before and after send: persist exact request identity, maximum held
  charge and known usage. An uncertain provider charge remains reserved until reconciliation;
  never release it merely because a lease expired. Every actual retry receives accounting.
- [ ] Publish decision, membership, current pointer, job completion and outbox atomically under
  expected versions. Use a final real-clock lease/deadline check; expiry rolls back all effects.
- [ ] Enforce the reviewed lock order: S3 control SHARE → S4 control/recipe SHARE → sorted source
  policy/registry SHARE → sorted articles → S3 recipe SHARE → sorted S4 events → sorted S4
  developments → S4 job. No lock upgrades or S3 job/cluster-lock acquisition. Changed discovery
  sets require rollback/rediscovery, not late acquisition of an earlier lock class.
- [ ] Keep exclusive control/recipe administration isolated: control+notice then commit, no
  article/event/job locks afterward. Claims/reapers are job-only transactions; reservation
  transactions lock controls only; dirty scheduling locks event before job. Audit FK/trigger
  side effects and every existing S2/S3 writer for reverse edges before accepting this protocol.
- [ ] Implement immediate authorization invalidation separately from bounded private-content
  purge. Reconcile old/new event dependencies after membership moves, source-origin edits,
  recipe disable, corrections, disappearance and rights revocation. Enforce expiry at reads
  even if scheduling is down; never let a failed refresh extend an old assessment's validity.
- [ ] Validate dependencies/control/expiry in a coherent read snapshot with a documented
  authorization point. Cache publication requires a serialized final generation fence; test
  invalidation during dependency reads, after authorization and before cache publication.
- [ ] Provide inspect, pause submissions, disable delivery, drain, reconcile, retry/quarantine
  and bounded backfill operations. Recovery must be resumable, observable and idempotent.

Exit: hosted adversarial schedules prove zero stale/partial publication, duplicate durable effect,
lost change, deadlock under the declared protocol, and unaccounted dispatch. Include final-lease
expiry, lower outbox ID late commit, control toggles, deletion, concurrent merge/split, restart,
budget bursts and missing-dependency tests. Fake-provider success is infrastructure proof only.

## 8. Batch 4 — Evidence, identity and genuinely new developments

New files: `event_evidence.py`, `event_grouping.py`, `event_delta.py`;
`backend/tests/test_event_evidence.py`, `test_event_grouping.py`, `test_event_delta.py`.

- [ ] Refine bounded S3 mention evidence into attributable claims with modality, uncertain time,
  explicit supported location and source references. Missing or ambiguous evidence abstains;
  prompt injection remains inert source text. Do not silently truncate away contradictions.
- [ ] Implement versioned reporting-origin metadata, alias/wire/translation relationships and
  primary-authority evidence. Ownership alone neither proves independent reporting nor sameness.
  Origin corrections invalidate downstream support even when the article text is unchanged.
- [ ] Union bounded lexical/entity/time/place/vector candidates with explicit candidate-stage
  recall diagnostics. Unresolved entities cannot be a hard recall gate. Apply event-type windows
  and compatibility before calibrated matching; no universal cosine or seven-day event window.
- [ ] Persist stable event/development identities with conservative ambiguous candidates, bounded
  episodes and typed topic relationships. Use deterministic tie-breaking and reviewed match
  margins; support many-to-many mentions without counting an entire roundup in each event.
- [ ] Implement version-checked merge/split/retraction and lineage. Retain evidence associations
  and map prior delivered development IDs without suppressing genuinely new developments forever.
- [ ] Separate corroboration, correction, substantive new facts and republishing. Keep conflicting
  claims attributed; no casualty max/sum rule. Purely cosmetic updates do not become new alerts.
- [ ] Enforce maximum aggregate sizes. Oversized/incomplete snapshots become non-ready or are
  explicitly partitioned/versioned; they cannot silently sample away inconvenient evidence.

Exit: deterministic fixture/lifecycle correctness and development-set diagnostic coverage for
singleton recall, topic bridges, permuted arrival order, same-place different-date events,
syndication, denials, old translations and roundups. Model-assisted refinement/matching stays
behind the batch-3 fake interface until batch 5 provides the approved real adapters; integrated
semantic acceptance, including grouping/delta gates, occurs in batch 5, not before it.
Deterministic replay is stable for the same ordered input log; permutation tests measure and
bound semantic differences, not require identical arbitrary UUIDs.

## 9. Batch 5 — Significance provider and measured model choice

New files: `event_provider.py`, `backend/scripts/pilot_s4_events.py`,
`backend/evals/events/provider_cache.py`, `backend/tests/test_event_provider.py`.

- [ ] Implement one bounded event revision per request with strict schemas, exact evidence IDs,
  explicit consequence/scope/uncertainty fields, refusal/timeout handling and semantic validation.
  Missing verdicts never become routine. No evidence-free generated reason is a publishable fact.
- [ ] Implement any model-assisted refinement, pairwise matching or delta adjudication through
  the same namespaced stage/accounting contract. No hidden direct calls from pure grouping code.
  Evaluate the entire exact S4 recipe, not a gravity classifier fed idealized gold groupings.
- [ ] Make consequence and evidentiary support separate gates. Primary authority can supply
  support without two outlets when verified under the approved policy; it does not establish
  consequence automatically. Existing permitted publisher evidence does not require a new CAP feed.
- [ ] Cache exact request bytes and model/recipe/schema/evidence/cutoff identity; meter cache misses,
  retries, refinement, embeddings and assessment once in total shared preparation costs. Keep
  reader delivery marginal costs separate. Enforce budgets across concurrent worker instances.
- [ ] Test all provider paths using fake/recorded fixtures first. Only with explicit S4 spend
  approval run a small capped structural pilot; then compare candidate recipes on development
  evidence, including counterfactual and novel cases. Pick the least-cost candidate that meets
  required quality/latency, not the cheapest schema-valid response.
- [ ] Freeze model version, prompt, source registry, grouping/refinement/delta rules, thresholds,
  rubric, supported slices and interval method. Evaluate untouched holdout once for promotion.
  Failed holdout requires a new version and fresh holdout; no repeated tuning against it.

Engineering exit: every model-assisted stage uses the validated adapter and complete accounting.
Semantic exit: section 13's identity, criticality, negative-decision and material-delta gates
pass on the integrated frozen recipe with sufficient independent evidence. Consumer/representative
acceptance follows in batch 6; aggregate hosted load/operational proof follows in batch 7. Track
adapter-complete and semantic-approved separately: underpowered evaluation does not prevent offline
batch-6/7 integration work, but blocks release readiness and production shadow/delivery.
Structural pilot success is not classification accuracy or rollout approval. S3's earlier
20-item pilot and unreviewed 600-item queue are not S4 labels or model selection. Underpowered
slices remain unpromoted, even if every observed example looks correct.

## 10. Batch 6 — Make approved events actually reach the right reader

New file: `event_consumers.py`; existing `feed_service.py`, `main.py`, `evals/pipeline.py`,
feed/eval tests. Client boundaries: `Daily/Features/News/Models/NewsArticle.swift`,
`Daily/Services/BackendService.swift`, feed cache/ViewModel and reading-event services only
where the new contract requires them; add focused Swift model/cache tests.

- [ ] Add a bounded current-event candidate leg independent of user-linked-source retrieval,
  including the existing no-active-source early return. Join only current eligible representative
  articles; perform no new S4 extraction, schema installation or model work on the feed request
  path. The existing S7 personalized scoring path remains unchanged by this scope.
- [ ] Pick core-development support before language/readability, source preference or image.
  S2 presentation/attribution remains authoritative; source-web is a legitimate representative.
  If no permissible representative exists, omit priority and record the reason.
- [ ] Apply scoped relevance for major events using explicit reader settings; unknown reader or
  event location cannot authorize a guessed local alert. Enforce reader hard exclusions before
  reservation, deduplicate both article and development identities, and enforce the total cap.
- [ ] Replace the prototype prepend/bypass behavior with tested reserved-slot selection; keep
  the detector's full critical set and record which events were not selected and why.
- [ ] Bind cached feed membership/priority to event assessment versions, source/control and
  reader-policy generations. Revalidate on reuse and during serialized final publication; stale
  priority must be removed without unnecessarily deleting ordinary eligible source reporting.
- [ ] Add optional version/expiry/development fields via a public allowlist; never serialize
  private evidence, prompts or analysis bodies. Older clients continue decoding. If an old
  client cannot enforce priority expiry offline, exclude it from enabled S4 delivery rather than
  promise an unsupported revocation guarantee.
- [ ] Separate saved source-article access from expiring priority. Use versioned delivered/seen
  development references and lineage for novelty, preserving account isolation and correction
  behavior. If durable S9/S10 acknowledgments need an extension, include that narrow contract and
  replay test; do not replace personalization or fabricate read state.

Exit: complete feed-path tests show an eligible event arrives without user-source recall, blocked
events never override policy, >2 events never overflow, wrong side-angles get no delivery credit,
cache withdrawals cannot reappear and offline priority expires. Verify representative accuracy
on independently adjudicated evidence with the frozen selector, not just fake decisions; this
semantic exit can await batch 5's recipe without blocking fixture-level integration. Delivery
is still disabled.

## 11. Batch 7 — Integrated release candidate

Files: `.github/workflows/backend-tests.yml`, S4 operating guide/management scripts,
inactive `backend/fly.s4.example.toml`, worker entrypoint, status/evidence manifest.

- [ ] Add required S4 PostgreSQL contracts beside existing S2/S3 tests, with a required-database
  flag and explicit zero-skip/collected-test assertions. Keep all normal CI provider calls offline.
- [ ] Add a mandatory deterministic S4 regression gate. Semantic promotion additionally requires
  the frozen independent-evaluation artifact; code CI must not imply that missing labels passed.
- [ ] Re-run affected backend, S2/S3 lifecycle and feed regressions plus iOS decoding/cache tests
  and build when client fields change. Preserve unrelated known S0 failures visibly; a general
  production promotion requires resolving them or a separately documented, approved scope decision.
- [ ] Exercise populated upgrades, restart/replay, crash points, control rollback and at least
  2× declared forecast load on disposable hosted infrastructure. Measure DB plans, bounded
  candidate recall, p95/p99 transactions, queue recovery and provider-outage/budget behavior.
- [ ] Verify submission and delivery kill switches independently, including warm feed caches.
  Prove old application compatibility with additive tables and retained historical decisions.
- [ ] Produce a runbook with exact inspect/migrate/backfill/promote/disable commands, expected
  outputs, numeric alerts, retention/purge SLO, on-call owner and backup/restore verification.
  Commands remain dry-run/default-off until the production stage is authorized.

Exit: a reproducible release manifest binds code/schema/recipe/data hashes, CI run, performance,
quality, budget and rollback evidence. Implementation-ready, quality-approved and live-enabled
statuses remain separate. No unverified “all green” summary that hides skipped suites.
All applicable preproduction gates in section 13 must close here; live freshness/coverage and
operating behavior must additionally be confirmed in batch 8 before any batch-9 delivery.

## 12. Batches 8–9 — Production shadow, then bounded delivery

### Batch 8: shadow only

- [ ] Obtain production execution and numeric spend approval; freshly verify S1 acquisition and
  coverage, S2 analysis policies and S3 promoted cohort/live readiness. Block if any are unknown.
- [ ] Verify backup/restore evidence, inspect migration plan and apply additive schema with
  submissions/delivery off. Register retained-change consumption, bootstrap a bounded cohort and
  deploy the worker from the verified artifact. Keep user delivery off.
- [ ] Observe at least 72 hours and enough independent quiet/busy/event cases; extend sparse
  periods. Audit every proposed critical decision plus sampled misses/unknowns and source outages.
  No destructive production fault injection and no concurrent source/recipe expansion.
- [ ] Check critical quality, correction freshness, origin accounting, cost ceilings, expiry,
  backlog recovery and cohort eligibility against frozen gates. Rehearse non-destructive disable
  and cache invalidation; keep exact release/recipe/control IDs in evidence.

Exit: shadow passes all required gates and sufficient-case rules; zero incidents in a short
window alone is not evidence of 99% precision. Obtain explicit delivery approval.

### Batch 9: eligible-cohort delivery

- [ ] Enable 1% → 10% → 50% → 100% of the declared supported, client-compatible cohort using
  stable account allocation. Each rung requires at least 24 hours, sufficient relevant cases,
  all absolute safety/cost gates and the approved observation protocol; extend rather than infer
  success from sparse traffic. No automatic time-based promotion.
- [ ] Monitor decisions and actual reader delivery separately: missed eligible events, representative
  correctness, hides/repetition, explicit-policy conflicts, freshness, stale cache rejection,
  source/region coverage, failures, reserved/spent money and DB/worker load.
- [ ] Immediately disable affected delivery on stale/revoked priority, unsupported critical
  consequence, wrong-event evidence, hard-policy bypass, lost correction or budget-integrity
  failure. Stop submissions too when processing integrity or spend is at risk. Pause expansion
  for recall, freshness, coverage or latency regressions. More than two real critical events is
  an investigation signal, never an instruction to hide genuine detector results.
- [ ] Rollback advances delivery/control generation, invalidates priority/cache authorization,
  preserves ordinary eligible reporting and retains audit/accounting history. Reconcile before
  retrying; do not delete tables or silently reactivate an old recipe.

Exit: sustained measured behavior at the supported scope, proven rollback and an assigned owner.
“100%” means that eligible cohort, not all users, languages or worldwide events.

## 13. Release gate checklist

These targets are **proposed, not achieved**. Freeze test units, eligibility, confidence method,
minimum effective samples and support-slice criteria before calibration. Correlated families/days
need blocked estimates; duplicate articles/personas are not independent statistical samples.

| Gate | Required evidence |
|---|---|
| Identity | Event and development membership each: precision ≥.98, recall ≥.90; separate results and supported hard slices |
| Criticality | One-sided 95% lower confidence bounds: precision ≥.99 and recall ≥.95 on representative streams; empty/underpowered fails |
| Negative decisions | Zero false critical on fixed adversarial suite; representative independent-negative error 95% upper bound ≤.005 |
| Material delta | Precision ≥.98, recall ≥.90; zero unchanged-fact re-alert in deterministic replay |
| Representative | Direct-core-support accuracy ≥.99; zero wrong/revoked/stale evidence in integrity tests |
| Lifecycle | Zero stale/partial publication, lost invalidation, duplicate durable effect or unaccounted request in hosted fault tests |
| Reader | Zero hard-policy bypass, duplicate development or edition overflow; reserved slots ≤min(2, edition size) |
| Freshness | p95 qualifying evidence available → assessment ready ≤5 minutes under declared load; expose S1/S2/S3/S4 delays and misses |
| Revocation | Reads beginning after committed invalidation cannot authorize old priority; expire at authorization and on supported clients |
| Cost and load | Explicit daily/monthly ceilings and per-stage limits, 2× forecast test, bounded fair backlog recovery and measured query plans |

The audit's sample-size examples are planning aids, not available proof. If the criticality gate
cannot be supported with enough independent evidence, keep automatic reserved-slot promotion
off; offline replay/development work and ordinary eligible news can continue. Production shadow
still requires the batch-8 prerequisites. Do not silently lower the confidence target.

All 23 adversarial rows in [audit section 13](s4-event-detection-audit.md#13-required-negative-path-and-adversarial-matrix)
must map to named deterministic, hosted-race or independently adjudicated tests. Mark an external
CAP lane not enabled rather than claim its integration was tested. Coverage gaps are release
blockers for their affected scope, not reasons to label unobserved world events routine.

## 14. Verification record and completion reporting

At implementation start, baseline command from the workspace root (already used in the audit):

```sh
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/test_global_events.py backend/tests/test_eval_metrics.py backend/tests/test_eval_label.py backend/tests/test_eval_runners.py backend/tests/test_understanding_contract.py backend/tests/test_story_clustering.py -q
```

Future focused command, once the proposed `test_event_*` / `test_s4_*` modules exist:

```sh
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/ -q -k 'event or s4'
```

Required real-database verification runs in hosted disposable CI with `S4_TEST_DATABASE_REQUIRED=1`
and an isolated test URL, plus the existing required S2/S3 suites. Offline runs may exclude DB
tests, but cannot certify batch 3/7. Semantic quality is a separate frozen-data artifact, not the
number of passing tests. Never run production data mutations to create failure-test evidence.

Each batch records: changed file scope, exact code/schema/recipe/dataset versions, tests and
non-skipped counts, semantic metrics with denominators/intervals, spend, unresolved blockers,
rollback evidence and next safe action. Keep durable status in `tasks/s4-implementation-status.md`
and the operating guide; `.context/s4/` holds local evidence, not the only release proof.

The planning deliverable is complete when independently reviewed and consistent with the audit.
S4 implementation is complete only when engineering batches pass; S4 production delivery is
complete only when separately authorized rollout gates pass. Do not collapse these milestones.

Planning verification (2026-09-06): independent lifecycle and evaluation reviews completed;
provider/quality dependencies, later-batch gate ownership, legacy-scoring scope and insufficient-
evidence wording corrected. Documentation whitespace checks pass. Backend and workflow content
remain identical to the retained pre-plan S3 verification index. No runtime tests, paid calls,
production actions or implementation were performed by this planning task.
