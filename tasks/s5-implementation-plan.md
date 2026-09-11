# S5 Reader model — implementation plan

Status: implementation authorized and repository slice implemented on 2026-09-07.
The original specification below remains the target; actual scope adjustments, verification
and open rollout gates are in [implementation status](s5-implementation-status.md).
This is not a statement about deployed behavior.
Companion: [source audit](s5-reader-model-audit.md).

## Outcome and scope

A reader can state, inspect and change their interests; every consumer sees the same
committed meaning; unrelated interests remain independently retrievable; retries,
provider failures and account changes cannot undo or misattribute their choices.

For this portfolio, the technical demonstration is a working, measurable vertical slice:
three unrelated interests → typed reader state → compatible per-interest query vectors →
bounded candidate retrieval with attribution → an explicit correction → a revised feed.
Storing vectors without a consumer is not completion. Neither is a convincing demo without
failure-path tests. No finite test suite establishes that personalization works perfectly
for every reader or that Daily sees all news worldwide.

Proposed scope includes S5 and the minimum S1/S6/S7/S10 adapters needed for this slice.
It does not authorize a full retrieval/ranker rewrite, new editorial assembly, deployment,
paid evaluation, changing upstream S3/S4 quality gates, or implementing unrelated backlog.
Each batch below needs its own exit evidence; do not land this as one unreviewable rewrite.

## Acceptance contract — freeze before implementation

1. Explicit typed edits survive save/reload unchanged. Missing patch fields mean unchanged;
   empty arrays mean clear. No provider call is required for a direct structured edit.
2. Every committed reader has one monotonic revision. All legacy projections and compiled
   inputs derive from that snapshot; no independent writer can bypass it.
3. Concurrent edits cannot silently overwrite; a retried operation applies at most once.
   A lost response can be reconciled without resubmitting an expensive interpretation.
4. Explicit policies outrank inferred taste. A removed interest cannot return through an
   old job/cache. A blocked publisher remains blocked after profile edits and discovery.
5. A preference commit changes subsequent eligible delivery immediately for hard policies.
   Soft personalization may rebuild asynchronously and must expose pending/stale status.
   This applies to new server authorization after commit, not bytes already in flight or
   an offline client's previously downloaded content.
6. A reader following three unrelated subjects retains eligible candidate opportunities
   for all three after union, deduplication and caps. Empty/no-relevant corpus slices produce
   a coverage diagnostic, not irrelevant filler. Final edition mix remains S8's job.
7. Tune has an actual typed mutation/review/apply path. Cancel changes nothing; unsupported
   requests ask for clarification. Show Undo only if an exact safe reverse is implemented.
8. Feedback has immutable served attribution and stable event identity. Duplicate delivery
   changes weights once; decay is applied before accumulation. No exposure is not a dislike.
9. Auth generations fence all async results. A→B and A→B→A cannot move events, drafts,
   receipts, profile results or notifications across sessions.
10. Reset removes learned influence and invalidates its derivatives. Account deletion cannot
    leave reader-owned rows or allow late jobs to recreate them. Retention is bounded.
11. Semantic quality and performance are independently measured, not inferred from passing
    unit tests, embedding dimensions, ten personas, or a model's advertised capability.

## Architecture and authority

```text
Settings / explicit onboarding fields / reviewed Tune proposal / accept suggestion / follow
                  │ typed patch + base revision + operation ID
                  v
         Reader service: validate and commit (short PostgreSQL transaction)
                  ├── canonical profile + deterministic compiled/legacy projections
                  ├── operation receipt + derived-work records
                  └── revision/generation used by every reader-dependent cache
                                  │
                 bounded async embedding / source reconciliation
                                  │ compare current identity, hash, generation
                                  v
   lexical + verified identity + compatible per-intent dense retrieval
                  │ shared hard-policy gate and immutable served reasons
                  v
            ranking / feed / briefing / chat
                  │ stable explicit feedback event
                  v
          bounded decayed overlay (cannot rewrite explicit policy)
```

### Canonical contract

Use strict Pydantic models and a versioned JSONB document in PostgreSQL. Keep one row per
user with `schema_version`, `revision`, `learning_revision`, `generation`, timestamps and
the canonical document. `generation` changes on learning reset, full reset or recreation;
use this one named reset epoch consistently, not an undefined second learning generation.
Do not reuse old job identities. `revision` advances for explicit semantic changes; `learning_revision`
advances for committed changes to the learned overlay. Do not bump explicit revisions or
re-embed on every passive impression.

An intent contains stable ID, kind (`topic`, `entity`, `place`, `utility`), display label,
explicit priority, qualifiers, optional resolved identity, optional expiry, and provenance.
Preserve conjunctions such as “AI regulation affecting startups” as one qualified intent;
do not split it into three independent broad interests. Distinguish following a location's
news from asserting that the reader lives there. Retain original script; never silently
strip non-Latin words. Ambiguous identities remain unresolved or require confirmation.

Keep content languages, depth, user-authored context, and explicit policies separate.
Policies declare their scope: publisher identity, article suppression, exact lexical rule,
or an evidenced subject/entity predicate. “Less politics” is a soft preference, not an
automatic permanent ban. A generated synonym must not acquire hard-exclusion authority.
Do not infer sensitive identity from news interests or put private biography into query text.

Start with a proposed bound of 24 active intents, 64 explicit policies, 280 characters per
label/query and a bounded total document size. Validate and return actionable errors; never
silently truncate. These are engineering defaults to confirm at Batch 0, not measured user
needs. Expired temporary interests stop serving at read time even if cleanup is delayed.

### Small persistence boundary

Proposed additive tables: `reader_profiles`, `reader_operations`, `reader_intent_embeddings`
and `reader_jobs`. Store rubric/projections on the profile row initially. Extend existing
reading-event, feedback and feed-receipt structures where they support the needed identity;
do not introduce a second competing edition/receipt system. Use existing S3/S4 schema-install,
lease, retry and transaction conventions without building a generic workflow framework.

All reader-owned rows use a user FK with explicit cascade or tested deletion ordering.
Embedding rows are tenant scoped. Index user/intent/hash and job readiness; an ANN index
over a reader's handful of vectors is unnecessary. Article ANN indexing belongs to S6.

### Mutation protocol

Recommended new contract: GET `/user/reader`, PATCH `/user/reader`, POST
`/user/reader/proposals`, GET `/user/reader/operations/{operation_id}` and POST
`/user/reader/reset-learning`. GET includes supported capabilities, migration review state
and current generation/revisions. Existing preference/suggestion/entity endpoints become
adapters to the same service; endpoint names can follow existing project conventions.

PATCH carries account-scoped `operation_id`, `base_generation`, `base_revision`, and a typed operation list
against stable intent IDs/fields. It returns the canonical profile, committed revision,
operation result and derived-work status. Reject unknown fields, malformed IDs and unsafe
coercions. On conflict return 409 with current revision; retain the client's draft for
review rather than silently merging contradictory instructions.

Within one transaction, lock the reader row; check an existing operation receipt first;
reject reuse with different request bytes/hash; validate base generation/revision; apply and compile;
write canonical state, projections, receipt and job/invalidation records; commit. A retry
of a committed operation returns its original result even if the current profile has since
advanced, with current generation/revision separately available. The client marks that
operation successful without reinstalling its historical snapshot; reconcile current state
monotonically by generation/revision. No-op mutations do not re-embed or
rediscover. Use a documented fixed lock order across profile, operation and overlay rows.

Provider interpretation happens outside locks. Proposal requests also have a stable operation
ID and persisted pending/completed/failed status checked before inference; reconcile a lost
response by ID before retrying paid work. A proposal is tied to its original reader
generation/revision, input hash, authenticated identity and explicit user turns. Structured Outputs
helps schema conformance, not truth: validate evidence spans, supported operations and
contradictions deterministically, and show the proposed change for confirmation. Refusal,
timeout, malformed/empty output or omitted late corrections cannot complete onboarding.
Never ratify a transcript prefix containing assistant suggestions. Typed onboarding can
still save without an AI provider. Accepted suggestions and entity follows use this writer;
accept/dismiss are terminal, idempotent transitions, not status overwrites.

For old clients lacking revisions, use an explicit compatibility policy: transactionally
patch only supplied supported legacy fields, do not invoke an LLM or erase omitted v3 fields.
This cannot detect a stale legacy form. Gate canonical editing to the upgraded client before
claiming conflict safety; retire revisionless writes with an upgrade-required response after
the agreed compatibility window. Do not pretend adapter serialization solves stale intent.

### Reader-dependent publication

Feed, briefing, source selection and embeddings capture their input snapshot before awaits.
Build cache keys/metadata from explicit revision, learning revision, generation and relevant
compiler/policy/embedding versions. Publish complete sets atomically only if still current;
otherwise discard/requeue. Publication acquires the same reader-row lock used by mutations,
then compares captured state and writes the complete derived set within that transaction.
A SELECT followed by a separately guarded write is insufficient. Initialize the first row
with conflict-safe insert before locking, with concurrent first-save/delete tests; document
the same lock order across all mutation, publication and account-deletion paths.
A timestamp after an edit does not establish freshness.

Artifacts also record scoring `as_of` and `valid_until`: time decay changes ranking even
without another event/revision. Propose at most 15 minutes of soft-ranking staleness, shortened
to the earliest intent/policy/recipe expiry. Apply current hard-policy time semantics at
authorization, not a TTL alone. Test clock advancement without writes, not only edit races.

Filter eligible evidence before briefing/chat generation, including live search, direct
article context and reused conversation context; removing a citation afterward cannot erase
its influence on prose. Revalidate captured policy before publishing generated output and
before authorizing additional streamed batches. On policy change stop pending generation/
stream output and offer a fresh response. Already-authorized/in-flight bytes cannot be
recalled; document this cutover rather than promising instantaneous remote erasure.
Use the current hard policy again at the delivery boundary, including cached S4 events.
Failure to load authoritative policy must not deliver an unchecked
personalized result. Soft-model/provider failure can fall back to eligible lexical results.
Never let a fallback silently bypass a block. Clients invalidate old memberships on a
committed policy change; offline content cannot be guaranteed remotely revoked until sync.

| Surface | Proposed reader-policy scope |
|---|---|
| Feed, S4 recommendations, automated briefing | Current recommendation blocks apply before selection/generation and at publication |
| Personalized chat/live search | Same default; all context sources checked, not just personalized-feed retrieval |
| Explicit article request / saved bookmark | Recommendation block is not an access/security revocation; allow an intentional direct read with truthful provenance, never automatic re-recommendation |
| Historical chat / downloaded material | Do not rewrite history or promise offline deletion; excluded material must not silently reenter new personalized context |

Keep recommendation controls distinct from S2 rights/security revocation, which remains
authoritative on every access. Any user override is explicit and request scoped, not inferred
from a vague chat turn. Confirm this product scope at Batch 0.

Replace source graph deletion with reconciliation. Keep durable publisher blocks separately
from discovered associations. Track which intents justify an association; adding an intent
enqueues incremental discovery, removing one retires only its unsupported associations.
Preserve still-useful/manual sources and last-good usable sets during discovery failure.
No-op/priority-only changes do not restart discovery. Work completion checks current reader
identity/version. Where older source-selection logic requires a whole recomputation, compute
a desired set then atomically diff it; never delete the live set before asynchronous work.

### Per-interest embeddings, correctly bounded

Reuse S3's provider and compatibility contract. Current checked-in provisional recipe uses
`text-embedding-3-small`, 1536 dimensions, raw NFC/whitespace query normalization and the
declared article document recipe. This is a starting candidate, not permission to bypass
S3 promotion. Same dimensions alone do not make vectors comparable. Record embedding-space
identity (model, dimensions, preprocessing, query/document recipe compatibility) separately
from broader S3 facet/taxonomy provenance so unrelated facet changes need not re-embed text.

Cache by `(user, intent ID, query hash, embedding space)`. Reuse unchanged compatible vectors;
weight/order edits do not call the embedding API. New/edited intents immediately participate
in lexical/identity retrieval and expose `pending` semantic state. Deleted/expired intents
never serve old vectors; late jobs cannot restore them. Jobs are leased, deduplicated,
bounded, classified for retry and fenced against resets, edits and recipe changes.

Persist the job before provider work, reserve bounded spend, cap attempts/input, and record
usage without raw private text. A timed-out provider request may already have cost money:
promise bounded at-least-once provider work, not exactly-once external billing. Account and
global budgets plus a kill switch are required before paid activation. No exact dollar cap
is assumed approved in this plan. No per-feed embedding generation.

At `get_personalized_feed`, select the flagged canonical-reader candidate path before the
legacy `has_sources` early return and `_load_candidates_for_profile` recency/keyword shortlist.
The new path may search the eligible global pool without personal source associations; it
must not bypass S1/S2/S3 validity or reader policies. Keep the legacy branch for ineligible
cohorts. Carry new match evidence into scoring/fallback rather than re-rejecting semantic-only
matches with legacy keyword gates or generated exclusion expansions. Test a genuinely
relevant synonym-only article reaching the resulting feed even when the scoring provider
fails; if no calibrated fallback can justify it, expose abstention instead of claiming recall.
The minimal S6 adapter queries eligible current S3 article artifacts, combines lexical,
verified identity and dense legs, preserves per-intent evidence through deduplication, and
allocates a bounded opportunity to each active intent before filling remaining capacity.
Use comparable per-leg fusion (initially reciprocal-rank fusion is a candidate), not raw
cosine plus keyword scores or top-hit normalization that makes weak matches perfect.
Calibrate abstention separately; a quota is not evidence of relevance. Test caps after every
stage. Default to exact eligible-corpus search as the quality reference; choose ANN only
when measured scale/latency requires it. Do not substitute legacy unversioned article vectors.

### Feedback, reset and iOS behavior

Capture immutable served attribution: user, feed/edition receipt, article revision, reader
generation/revision, matching intent IDs, policy/recipe identity and time. Reuse S4 provenance where
available, extending it rather than attributing later from a mutable cache or current
article. Validate ownership. Missing attribution may allow explicit article suppression but
must not invent topic learning. An old receipt cannot resurrect a removed intent.

All feedback commands and background jobs capture and validate the reader generation;
delayed pre-reset telemetry cannot become fresh learning just because its arrival time is new.
Insert the explicit feedback event and apply its effect in one transaction, once per stable
event ID. Decay stored weight to server time before adding a bounded delta, then clamp;
decay at read time as well. Normalize multi-intent attribution so one article cannot multiply
an unbounded update. Keep explicit priorities and learned overlays inspectably separate.
Disable or gate the existing coarse implicit boosts until exposure/dwell quality is proven;
do not combine uncalibrated implicit and explicit penalties without measuring the result.

Reader reset-learning preserves explicit interests/policies but removes learned weights and
pending inferred suggestions and `behavior_cache`, advances `generation` and
`learning_revision`, and invalidates derived results. Generation-scope or delete retained
observations used by recomputation and `interest_evolution`; otherwise old taps immediately
recreate the removed influence. Reject pre-reset edits/feedback/proposals/jobs. Compatible
unchanged intent vectors can still be reused by semantic hash without resurrecting learning.
A full preference reset is a distinct,
confirmed operation, not an accidental side effect of Save. Account deletion must cover
all reader-owned data, backups/operational retention documented separately; do not claim
immediate erasure from external providers or backups that has not been implemented.

Reuse existing Settings/onboarding surfaces and auth-generation boundary. Add a typed reader
model/service with initializer-injected test dependencies; preserve the established SwiftUI
ownership/design. Keep save/proposal/apply/pending/conflict/failure distinct. No completed
notification without a committed response, no cleared failed draft, no late response after
cancel/sign-out. Tune should show the actual proposed patch and resulting applied revision.
Replace Settings' rediscovery notification and Tune's independent loaded-once cache with
shared account-scoped reader generation/revision and derived-work state. Invalidate affected
News/Tune/briefing caches together, without forcing full discovery. Add a Settings → Tune →
News round-trip test and out-of-order operation-receipt replay tests.
Initially omit Undo if a compare-and-swap inverse cannot safely reverse the exact operation;
do not ship the current cosmetic Undo. General assistant chat remains distinct from tuning.
Use Settings for the migration review and confirmed Reset learned preferences controls.
Use the existing interest editor for entity follows; accepting a suggested interest uses
the same reviewable proposal surface (with dismiss). If these optional suggestion/follow
entry points are deferred, retain tested adapters but explicitly exclude their UI from
the shipped claim; migration review and reset remain required for affected users.

Telemetry batches are at most 100, stable-ID, account/generation scoped, bounded and explicitly
acknowledged. Retry 429/5xx/transport failures; handle auth separately; classify invalid events
without discarding unrelated valid events. Explicit feedback requires durable retry identity;
passive telemetry can remain best effort if its loss is measured and no stronger claim is
made. Bind feed identity to the rendered item, not a mutable global latest-feed ID. Never
requeue a suspended A request into B's queue. Foreground visibility—not background wall-clock
dwell—is required before enabling behavioral learning.

## Implementation batches and exit gates

Paths below are file-scoped targets, not permission to rewrite all of each file. New module
names are proposed. Read current S3/S4 changes and shared transactions before editing.

| Batch | Files / work | Required exit evidence |
|---|---|---|
| 0. Freeze the ruler | `tasks/s5-*`, `backend/tests/test_preferences.py`, new `backend/evals/reader/` fixtures | Inventory every writer/consumer; independent expected profiles/policies; migration precedence and limits recorded; baseline and scope approved. No runtime feature yet. |
| 1. Pure contract | new `reader_contract.py`, `reader_compiler.py`; `profile_model.py` compatibility helpers; new compiler tests | Strict validation, stable IDs, clear-vs-missing, qualified/Unicode intents, expiry, deterministic projections, policy conflicts and provenance tests. No network/DB dependency. |
| 2. Atomic authority | new `reader_schema.sql`, `reader_repository.py`; narrow `main.py` adapters; new repository/endpoint/Postgres tests | Additive resumable migration, transactional CAS/idempotency, legacy guard, all existing save/accept/pin writers routed through authority; concurrency/FK/fault tests on isolated hosted PostgreSQL. |
| 3. First working edit | `BackendService.swift`, new typed reader service/model; News `PersonalizationSettingsView` and view model, `NewsViewModel.swift`, Chat onboarding view/model, auth tests | Direct edit → committed reader → reload; migration review/reset surfaces; explicit clear; preserved fields; shared cross-tab revision; offline/conflict/missing-token/account-switch tests. Provider fallback cannot mark completion. |
| 4. Coherent consumers | `feed_service.py`, `source_discovery.py`, `user_source_pipeline.py`, `event_integration.py`, briefing routes, relevant `openai_service.py` prompts | All consume one compiled revision/policy; stale publication rejected; hard blocks immediately enforced; source edits reconcile instead of wipe. Preserve S3/S4 behavior and source availability. |
| 5. Honest tuning and feedback | `chat_service.py` only if needed as proposal adapter; reader proposal service, `feedback_signals.py`, feedback/event routes; Tune view/model and `ReadingEventTracker.swift` | Review/apply/cancel works; no fake Undo; immutable receipt attribution; duplicate/decay/reset/100–101–250 batch and A→B→A tests. Existing general chat remains functional. |
| 6. Semantic vertical slice | new bounded `reader_worker.py`; existing provider/worker wiring; narrow reader retrieval adapter; `understanding_consumers.py` contract; new `backend/evals/reader.py` | Compatible per-intent vectors actually consumed under a disabled flag; unchanged reuse, edit/delete/recipe races, no per-feed spend; lexical fallback; independent cap/coverage ablations. |
| 7. Integrated verification | new hosted S5 verification script, `.github/workflows/backend-tests.yml`, backend suites, injected Swift/unit/UI tests; `tasks/s5-implementation-status.md` | Full baseline regressions, real hosted transactional proof, migration/restart/rollback, release client build, approved quality/spend/latency report. Report unavailable evidence as pending. |
| 8. Separately approved activation | production config/runbook only after authorization | Eligible S3/S4 cohorts verified; designated-account smoke; bounded shadow and opt-in delivery with rollback, hard-policy checks and actual usage measurements. No automatic global enablement. |

Parallelize Batch 1 contract tests and independent label preparation; once the contract is
stable, backend repository and injected client work can run independently. One owner handles
`main.py`, shared feed/source interfaces and SQL ordering. Consumer/feedback integration must
wait for shared revision and receipt contracts. A fresh reviewer challenges each high-risk
batch; independent agents are additional scrutiny, not proof by agreement.

## Test and evaluation plan

### Deterministic tests: zero violations in the defined suite

- Schema/property tests: strict types and bounds, normalization idempotence, compile
  determinism, no invented intents/policies, unknown fields rejected, no private context leak.
- State-machine tests: operation retries, mismatched operation hash, concurrent edits,
  accept-vs-dismiss, intent rename/delete/expiry, clear values, reset, old-client policy.
- Fault injection: fail between statements, lost response after commit, provider refusal or
  timeout, invalid vector/NaN/dimension/space, duplicate jobs, lease expiry, crash/restart.
- Publication races: capture revision N, commit N+1, release N's feed/source/briefing/vector;
  no stale publication; test learning-only revision changes, time-only decay, policy expiry,
  concurrent first-profile creation and lock ordering with account deletion.
- Ownership: forged/other-user receipts/IDs, deleted users, old generation, A→B→A, account
  deletion during a leased job, no orphan feedback or data resurrection; reset followed by
  behavior recomputation/evolution and delayed pre-reset edits/events cannot relearn old data.
- Client: draft retention, field preservation, truthfully empty vs failed feed, save/apply
  double-submit, stream/response cancellation, real Undo or no Undo, batch acknowledgements,
  historical receipt replay after a newer save and Settings/Tune/News coherence.
- Generated surfaces: blocked live-search result never enters model context; changing policy
  during generation prevents new unauthorized output; record already-emitted-text limits.
- Regression: current S0 frozen replay plus S1–S4, general chat and iOS reader/auth behavior.
  Offline Python tests and injected Swift fixtures are allowed; do not launch localhost.

Real PostgreSQL tests must use an explicitly authorized isolated hosted database/schema with
unique test identities, production-engine version/extensions and verified target guards.
Never aim destructive fixtures at real accounts. If no safe hosted target is available,
that gate stays pending; mocked SQL is not a substitute for transactions or concurrency.

### Semantic proof: separate interpretation from retrieval

Prepare a proposed initial panel of 60 hand-adjudicated scenarios, including at least ten
each covering multi-interest competition, corrections/negation, entity/location ambiguity,
multilingual inputs, cold start/sparse corpus and time/temporary interests. Cases may overlap
categories. Split instruction/intent families before compiler development (proposed 40
development / 20 untouched acceptance); hold out whole paraphrase/correction families, not
just random messages from the same template. Keep deterministic conformance fixtures separate.
Add a separate untouched set of article/event families for retrieval judgments.
This panel is engineering evaluation, not evidence about the global user population.

Label expected meaning from original user input, blind to compiler output and system scores.
The existing labeler imports `compile_rubric`; freeze old labels for regression but do not
use that coupled path as the new compiler's correctness oracle. Record human/model/agent
label provenance and adjudicate disagreement. Pool several retrieval systems plus random
tail candidates; audit unjudged items rather than treating them as negatives.

Compare equal-corpus, equal-budget lexical-only, centroid, per-intent dense and hybrid runs.
Report intent preservation/unsupported-constraint rate; per-intent Recall@50 and Recall@300;
minority-intent starvation after every cap; nDCG@10; hard-policy violations; semantic
exclusion misses/false blocks; latency, candidate count, provider tokens/cost and storage.
Separate no eligible article in pool from retrieval loss, ranking loss and final mix loss.
Keep S6's recall@300 ≥ 0.95 as an end-to-end target, not an S5 unit-test achievement.

Freeze semantic promotion thresholds before opening the untouched set. Proposed release
rule: no deterministic policy/lifecycle failures; hybrid non-inferior macro recall/nDCG
within a predeclared small margin and demonstrable minority-interest gain versus lexical,
within budget. Report paired uncertainty by reader/event family, not articles as independent
samples. If sample size cannot distinguish gain, report inconclusive; keep vectors disabled
or explicitly experimental. Do not tune thresholds on the holdout until a graph looks good.
Supported same-language and cross-language slices need separate judgments and gates; English
averages and model branding do not justify an unrestricted multilingual claim.

Benchmark compile/read/write and retrieval separately under a recorded hosted workload.
Proposed initial budgets: no provider on GET/direct PATCH; reader load+compile p95 ≤ 50 ms
server-side on the documented test hardware; at most one active job per intent/query/space;
retrieval adapter within S6's p95 < 200 ms target at the declared eligible corpus size.
These are targets, not current measurements or guarantees at arbitrary global scale.
Measure DB connections, query plans, queue lag and hot-account contention before adding
Redis, ANN indexes or additional services. 24 × 1536 float32 values are about 144 KiB per
reader before row/index/retention overhead; repeated historic versions need cleanup bounds.

## Migration, deployment and portfolio evidence

Audit conflicting legacy records without logging private text. No existing column has
reliable per-field explicit-edit provenance; do not silently choose a canonical truth.
Recommended migration: import consistent records deterministically with `legacy_import`
provenance; preserve conflicting variants as bounded private migration evidence and mark
`needs_review`. Existing service can remain on its legacy path until the reader confirms
the candidate; do not label unresolved migration as canonical-ready. Explicit blocks visible
in any trusted existing control must not disappear during transition. Preserve raw S4
canonical source/topic/place/sector/language fields before any legacy normalizer drops them.
Inactive source associations are ambiguous: user hiding and repeated fetch failures both
set `active=false`. Preserve inactive state without automatically reactivating it, but do
not invent an explicit publisher ban from it; flag missing reason/provenance for review.
Freeze source-URL-to-publisher identity mapping and test aliases/subdomains against the
declared block scope. Run count/hash/parity checks and prove interruption-safe resume before
enabling new writes.

Use additive schema and backfill, no destructive cleanup in the rollout. Gate canonical
writes/readers together per user; no dual independent authority. Roll back semantic serving
to eligible lexical retrieval without undoing committed reader choices. Application rollback
must use a compatibility build that still reads the new canonical projections/policies;
an old binary that forgets a hard block is not a safe rollback. Keep new data until a later
explicit retention/migration approval. Preflight upstream actual serving recipe, not docs alone.

Portfolio evidence should include a small architecture diagram, inspectable synthetic reader
before/after, race/negative-path test results, hosted DB evidence, equal-budget ablation report
and a real end-to-end correction demo. Distinguish implemented, verified, quality-approved
and deployed. Do not claim a trained recommender, unbiased behavioral learning, global news
coverage, or production interest-vector ranking until evidence supports each statement.

## Decisions and approval gates

Recommended defaults: explicit multi-intent model; no persona assignment; per-intent vectors
as a measured optional leg; no learned user tower; no new external vector database; reviewable
Tune changes; no Undo until real; implicit behavioral adaptation disabled until validated.

Implementation approval is outstanding. Batch 0 must finalize supported languages, strict
semantic-exclusion behavior/unknown handling, migration review UX, legacy-client retirement,
retention periods, numeric semantic margins and resource limits. A provider/hosted-test budget,
safe database target and production activation require separate authorization. Do not invent
those approvals. These open choices do not prevent completing this analysis/plan.

## Technical sources and why they matter

- [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings): model/dimension
  API behavior. Compatibility/version fencing is Daily's responsibility, not an API promise.
- [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  typed output validation does not establish that extracted preferences are true.
- [PostgreSQL 16 isolation](https://www.postgresql.org/docs/16/transaction-iso.html): use explicit
  transactions and concurrency controls; separate autocommit statements are not one mutation.
- [pgvector](https://github.com/pgvector/pgvector): exact search provides the nearest-neighbor
  reference, while approximate filtering can underfill. Exact vector recall is not relevance.
- [Google Rules of ML](https://developers.google.com/machine-learning/guides/rules-of-ml):
  establish metrics and serving/data correctness before escalating learned-model complexity.

The engineering-plan review shaped the transactional boundaries, failure tests, alternatives
and staged gates. OpenAI documentation verification constrained the proposed embedding and
proposal contracts. These choices remain proposals until approved.

## Independent draft challenge — incorporated corrections

Backend, client and architecture reviewers separately challenged this document after their
source audits. Corrections incorporated: generation on all commands/jobs/receipts; reset
isolation from retained observations; shared-lock publication; time-bounded cache validity;
pre-generation policy filtering and explicit surface scope; proposal retry identity;
monotonic client receipt reconciliation; cross-tab refresh; visible migration/reset controls;
inactive-source migration ambiguity; an exact semantic retrieval insertion point; and an
instruction-family holdout distinct from development and article-family splits.

These corrections resolve gaps in the proposed specification, not the runtime defects.
Remaining product/operational approvals are still listed above.
