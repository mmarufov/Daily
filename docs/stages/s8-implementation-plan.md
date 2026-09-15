# S8 Edition assembly: implementation plan

2026-09-09. **Approved and implemented in the repository; activation remains gated.**
See [implementation evidence, refinements and open gates](s8-implementation-status.md).
The original design below is based on the dirty S1–S7 checkout and [audit](s8-edition-assembly-audit.md).
Policy values are not claims of calibrated optimal behavior.

## 1. Objective and boundary

Create an ordered edition from the *whole accepted S7 pool*, with non-redundant coverage,
explicit preference coverage, conservative novelty and independently authorized S4 priority.
Preserve S7 judgments; make every omission, relaxation and representative choice inspectable.

```text
S7 RankBatch + whole S6 candidate context (<=300 ordinary opportunities)
  + current approved story memberships / source identity
  + receipt-backed history snapshot + assembly recipe
  + bounded independently authorized S4 critical opportunities
       |
       v
pure S8 assembly: eligibility -> identity -> novelty -> representative-aware selection
       |
       v
AssemblyResult: exact ordered IDs + origins + dispositions + dependency manifest
       |
       v
existing S6/S7 publication fence extended for membership/history/assembly config
       |
       v
one immutable envelope + final-only receipts -> S9 renders this exact order
```

No paid assembly calls, request-time embeddings, source discovery, trained reranker or new
search infrastructure. Do not repair assembly by weakening S7 rejection or inventing missing
candidates. S3 owns specific-development identity; S4 owns significant-event evidence; S5 owns
explicit reader policy; S7 owns relevance; S8 owns final selection/order; S9 renders it.

## 2. First fix the consumer contract

These are S7/S9 boundary prerequisites discovered during S8 analysis, explicitly in scope:

- Stamp final public cards with reader generation/revision, edition/feed request ID and
  immutable delivery position, after all representative swaps and ordering. S4-only cards
  receive reader context, not fabricated confirmed interests.
- Align building/unavailable/needs-build/ready-empty states between API and Swift decoding.
  Old-client policy must be explicit: either capability-gated new statuses or stable compatible
  statuses with additive reason/retry metadata. Do not return `ready: []` for infrastructure
  failure. New clients should show busy/retry states without a discovery/build loop.
- Persist per-card edition/position through normalization, detail merging and offline cache.
  Feed impression/tap/read calls use the displayed card's receipt identity, not the latest
  global request ID or an array index shifted by a local hide. Standalone search/bookmark
  opens without delivery proof stay unreceipted and cannot influence edition novelty.
- Keep hero selection equal to the first backend-selected card, even without an image.
  Missing artwork changes layout/fallback, not article order or relevance.

Test real serialized backend fixtures with the Swift decoder and feedback payload builder.
Existing mocked Python endpoint tests are necessary but insufficient for this boundary.
This is a contract fix, not a SwiftUI redesign or broad S9 offline/security audit.

## 3. Typed assembly inputs and outputs

Add `assembly_contract.py` with strict Pydantic DTOs and canonical fingerprints:

**AssemblyRequest**: authenticated account; S7 request/context/recipe hashes; reader stamps;
frozen as_of/expiry; output capacity 1..100; approved assembly recipe/hash/epoch; client
capabilities; full accepted ordinary set; bounded S4 candidates; current identity/novelty
evidence; history revision. Keep rejected/abstained S7 IDs in the parent RankBatch, never
present them as ordinary eligible alternatives.

**Per-candidate features**: article ID; S7 ordinal and confirmed intent grades/IDs; current
publisher ID/domain; central topic IDs (unknown is explicit); story membership namespace,
ID, version and semantic/evidence stamps; novelty state; S2 readable route. Provider prose,
raw bodies and guessed country/source quality are not selection features.

**AssemblyResult**: stable ordered selections with article ID, origin (`ordinary` or
`world_critical`), own S7 attribution if present, coverage-unit identity, original rank and
final position; one disposition for every supplied eligible opportunity; constraint/shortfall
diagnostics; frozen history/config/member manifest and validity bound. Dispositions include
selected, equivalent_copy, known_read_repeat, capacity, diversity_deferred, policy/stale,
critical_overflow and identity_unknown. Do not overwrite S7 accept/reject/abstain.

Validation: unique output IDs, exact input membership, no forged origin/attribution, no
position gaps, capacity respected, at most one selected verified-equivalent unit, no
unsupported priority. Every ordinary selected representative needs its *own* accepted verdict.
Shared-intent accounting assigns a selected card once for scheduling; it preserves every
confirmed intent for explanations and learning. Multi-interest matches do not consume several
slots or receive repeated rewards simply because the reader expressed overlapping interests.

## 4. Conservative identity and representative choice

1. Deduplicate exact article identity first. Use a trusted normalized URL only under an explicit
   article-identity rule that preserves meaningful query parameters and distinguishes mutable
   live pages/revisions. URL similarity, equal titles and embedding proximity alone are not
   proof of identical developments.
2. Batch-hydrate current S3 memberships, including recipe/input/eligibility/member and cluster
   versions. Consumption is a declared assembly capability, enabled only after identity tests
   and quality validation. Unsupported/unapproved/missing membership becomes an explicit
   singleton, never a fabricated cluster or a reason to remove otherwise eligible news.
3. Keep S3 story clusters, S4 event IDs and S4 development IDs separate namespaces. Event
   membership alone cannot collapse all consequences, analysis, corrections and direct reports.
   A cross-namespace duplicate requires corroborated article/development/coverage evidence.
4. Within a verified-equivalent unit retain eligible alternative representatives until selection.
   Prefer own strongest accepted grade and supported direct coverage; then reader priorities
   and original S7 order. An image or a longer extracted body cannot win over these criteria.
5. Source diversity can choose an equally eligible/equally strong alternative representative;
   do not collapse too early and unnecessarily lose that option. No representative outside
   the supplied accepted ordinary set is fetched and promoted after ranking.
6. No inferred home-country publisher preference. Existing explicit publisher *blocks* remain
   hard; a future explicit preferred-publisher feature would only be a safe tie-break, not
   a reason to prefer an incidental angle. Canonical domain is not editorial quality.

This guarantees uniqueness under verified identity, not zero semantic duplicates throughout
the world's news. Measure both missed duplicate pairs and erroneous merges; a false merge
can conceal a correction or another genuinely useful story.

## 5. Selection policy: grade-protected, opportunity-aware, deterministic

Use a pure bounded greedy selector in `assembly_service.py`; no optimization framework.
For N<=300 and K<=100, an O(N*K) scan over cached features is adequate as an initial bounded
algorithm. Benchmark it; do not assert a latency number before measurement.

Recommended initial recipe:

1. Apply current hard eligibility and verified-equivalence rules. Remove known identical read
   repeats from the *new edition* under the novelty rule below. Never remove the underlying
   article from search/bookmarks or override explicit reader blocks.
2. Reserve up to min(2,K) independently valid S4 critical units, preserving the existing S4
   policy and stable candidate order. Recheck all actual representatives. Critical reservations
   do not consume personal-interest quotas; report their effect on remaining capacity.
3. Fill ordinary slots from all remaining accepted candidates. Protect S7 relevance grades:
   grade 3 before grade 2; generic cold-start items use their separate neutral mode. Within
   a grade, schedule across confirmed active intents using explicit priority-weighted service
   counts. Use the original S7 order as the deterministic quality/tie-break reference, not
   retrieval similarity presented as a relevance probability.
   Start with the available intent having the smallest selected-count / validated positive
   explicit-priority-weight ratio; resolve ties by best available S7 ordinal then stable intent
   ID. Count a multi-intent selection once against the scheduled intent. Recompute availability
   after each choice; do not multiply in the learned overlay again after S7 already used it.
4. Within the eligible grade, prefer underrepresented canonical publishers/central topics and
   avoid repeated source streaks when an eligible alternative exists. Unknown metadata must
   not masquerade as a fresh publisher/topic, or force all unknowns into a hard exclusion.
   Define target shares/streak settings in the recipe, not hidden constants in multiple files.
5. Relax *soft* variety targets in a fixed recorded order when no alternative exists within
   the protected grade. Never relax explicit blocks, own relevance, verified identity or S4
   validity to meet size. A smaller edition is allowed; a sparse single-interest feed may
   legitimately concentrate on that interest. All quotas are ceilings/targets, not obligations.
   Proposed relaxation order: central-topic target, publisher-share target, source-streak
   target. Retain interest scheduling and grade protection throughout. Record the recipe's
   exact targets before evaluating it; target tuning is not permission to change hard rules.
6. Refill from the whole accepted pool after duplicates, priority displacement or exclusions;
   apply final K only here. Choose representation and ordering together enough to avoid an
   avoidable publisher-cap dead end. Record unavoidable shortfalls and greedy approximation
   gaps rather than claiming the selection is globally optimal.

The default intentionally does **not** promise diversity at any relevance cost. Protecting
grade 3 can leave a lower-grade interest unrepresented; expose that reason. A variant permitting
grade displacement needs an explicit relevance-loss allowance and holdout evaluation.
Test priority-only edits and overlapping intents so schedules remain understandable.

MMR is a challenger after compatible similarity geometry and relevance-vs-variety evaluation,
not the default. Do not mix ordinal grades with cosine values using an invented lambda.
Compare with plain accepted-S7 top-K and verified-dedupe-only baselines first.

## 6. Novelty without pretending delivery is comprehension

Use separate states: unknown, delivered_only, opened, acknowledged_read_same_content,
seen_unit_changed, and supported_new_development/correction where evidence actually exists.

- Only own-account receipt-attributed events with the frozen card/content/unit identity can
  drive novelty. Impression/delivery never means read; tap is at most a soft signal.
  The app's read-duration event remains a proxy. Unknown legacy history remains neutral.
- For the initial deterministic rule, suppress an acknowledged read of the same supported
  content/unit snapshot from a newly assembled edition. Do not hard-suppress a whole broad
  topic, all event history or changed stories based only on an old article ID.
- Metadata/image refresh, S3 membership version, S4 version bump and newer publication time
  are invalid evidence of a *material* development. Changed/uncertain content is neutral or
  explicitly uncertain; no unproved “new update” badge. S4 candidate deltas requiring
  adjudication cannot automatically re-alert.
- Respect all current S5 blocks, including the existing permanent already_knew article policy.
  Do not silently migrate it into weaker suppression. Changing that product control later
  requires an explicit contract/UX decision; this plan does not erase existing blocks.
- Bound history to configured retention and relevant candidate keys using receipt indexes.
  An unavailable history store must not be represented as “nothing read”; reject reassembly
  or expose an explicitly configured degraded novelty mode. Default to needs_build/unavailable.

Add a small account/generation-scoped `reader_edition_state` revision (S8-owned, not a second
reader profile) and receipt fields for assembly recipe, coverage identity and novelty content
key. Index account/generation/key/time. Advance history revision only on newly accepted,
novelty-relevant receipt-backed events, transactionally and idempotently. Duplicate retries,
unreceipted telemetry and impressions must not churn editions. Reset/delete and retention
semantics must be explicit. Do not use MAX(event_id) as a commit-order revision.

Keep this revision separate from S5 taste/learning revision: reading a card does not imply
changed interests or justify another model call.

## 7. Cache and publication: one result store, separate validity layers

Reuse `ranking_results` and S7 build claims, retaining the frozen RankBatch alongside the
final AssemblyResult. Do not build a competing feed cache or store only floating scores.
Distinguish ranking validity from assembly validity:

- Reader semantics, ranking recipe or article evidence changed: existing S7 rebuild rules.
- Only assembly recipe, reading history or eligible S4 composition changed: explicit build
  may reuse a *freshly reauthorized, still-valid* RankBatch, then assemble without provider work.
  If it is expired/stale, return the appropriate rebuild state; never extend its TTL.
- Add separate assembly recipe/hash/epoch to control/result metadata so changing variety
  policy does not automatically invalidate semantic judgments. Keep existing S7 model approval
  and budget controls separate. Assembly remains default-off until its own gates pass.
- GET returns the stored order/prefix after dependency checks, or needs_build; it never
  silently returns new positions under the old edition ID. No model, retrieval expansion or
  new receipt-generating assembly on GET. Internal ordinary-only views retain original positions.
- A newly assembled edition gets a new request ID and final-only receipts atomically. A card
  appearing both in S7 and S4 can preserve its own proved S7 intent attribution, but an S4
  replacement cannot inherit another article's verdict.

Extend fresh publication to cover ALL decision dependencies, including unselected candidates
whose group/availability affected selection. Capture membership presence/absence, partition
versions, history revision, assembly configuration and selected S4 dependencies.

Proposed lock discipline: reuse user -> reader -> existing S4 control/source prerequisites ->
sorted union articles -> S3 recipe/artifacts/results -> relevant membership/cluster rows ->
S4 event/development rows -> S7/assembly control and result/claim. Validate against every
existing writer before finalizing implementation; this is a proposal, not a certified lock order.
History writers acquire the same user/reader guard before updating S8 state. Membership inserts
must be fenced through their parent article lock or another shared writer protocol; locking
only existing membership rows does not protect a missing row. Never acquire S3's clustering
advisory lock before article locks in the delivery path.

Hydrate batch inputs outside long publication locks, perform pure selection, then reauthorize
and publish. No provider awaits or network work while locks are held. Recheck expiry/deadline
after receipt writes before commit. On conflict, fail closed or perform one bounded provider-free
retry with a new coherent snapshot; do not reuse stale identity or replay a paid call under locks.

## 8. File-scoped implementation batches

| Batch | Files / responsibility | Exit evidence |
|---|---|---|
| A: wire prerequisites | ranking_service.py; BackendService.swift; NewsArticle decoding/normalization/reader merge; ReadingEventTracker.swift; relevant News/reader call sites | Real JSON -> Swift -> feedback/telemetry identity; busy/unavailable/empty states; no reordered cards |
| B: pure contracts/selector | new assembly_contract.py, assembly_service.py; strict assembly recipe fixture | Every input disposition, representative own verdict, full-pool refill, stable grade-protected selection |
| C: evidence/history | new assembly_repository.py + additive assembly_schema.sql; narrowly extend understanding_repository/reader_retrieval and reader_feedback receipt/event handling | Batch identity hydration, presence/absence stamps, acknowledged revision, reset/delete/idempotency |
| D: atomic integration | ranking_service/ranking_repository/control management; ranking_events/event_feed split candidate authorization from final selection | Fresh ranking reuse for history-only rebuild; one cache/order/receipt publication; no paid GET/assembly |
| E: proof/release | new evals/assembly.py and tests incl disposable SQL; CI, env/status docs and bounded management command | Required deterministic + SQL jobs, measured offline baselines, default-off activation/rollback |

Three new modules separate data contract, pure selection and database evidence. Existing
ranking storage/claims, S2 serialization and S4 eligibility are reused. This spans several
files because output identity reaches Swift telemetry; omitting that wiring would leave
backend-only correctness. Do not add another provider adapter, task queue or data platform.

Out of scope: new S4-major retrieval leg (record opportunity loss; ordinary major items still
require S6/S7), broad S3 clustering redesign, paid semantic relabelling, full S9 UI/offline
redesign, breaking existing already_knew controls, home-country inference, implicit exploration
of rejected items, production operations and unrelated dirty workspace changes.

## 9. Proof plan

```text
full accepted pool -> duplicate/representative/diversity/novelty -> actual final edition
   |                       |                                     |
   + grade/reject tests    + unknown vs verified identity          + ID/position/receipt fixtures
   + all 300 reach S8      + S3 split/merge/missing-row races       + GET stable / rebuild new ID
   + independent S4       + history/reset/config races             + Swift cache/detail/telemetry
```

Mandatory deterministic cases:

- All reproduced audit failures; no lost refill after K; no rejected representative rescued
  by images; title-language/changed-number/bridge-group adversaries; all-unknown metadata.
- K=1,2,5,10,50,100; no accepted candidates; all repeats; one topic/source; many overlapping
  intents; explicit priority edits; critical capacity/overflow; multiple developments in one
  event; ordinary + critical equivalents and distinct useful angles; expired representative.
- Permuting transport/input order while retaining S7 ordinals does not change the edition.
  Adding a strictly ineligible item cannot affect selection. Output is a unique authorized
  subset; relaxed soft constraints have recorded reasons. Simple variety fixtures improve
  the displayed prefix, not just aggregate list statistics. No unsupported optimality claims.
- Canonical URL edge cases, mutable live pages, singleton unknown, revoked analysis evidence,
  stale memberships, image-only updates, changed meaning vs changed identity version.
- Acknowledged read vs impression/tap, wrong-user/position/receipt events, duplicate retries,
  legacy unknown history, old generation, reset/delete, retention boundary, simultaneous builds.
- Membership update/insert/split during publication, history insert during publication, config
  disable/re-enable, stale lease, receipt-write failure and post-write expiry. Required disposable
  PostgreSQL tests, not only fake cursors. No production database is a test fixture.
- Backend-produced fixtures decoded by Swift; per-article generation/edition/position through
  local hide, offline restore, detail open and overlapping foreground/background editions.

Evaluation on actual input pools and final outputs:

- Reuse S7 graded precision/nDCG and explicit unknown denominators. Separately score S4 critical
  opportunity delivery, never credit forced significance as personal-relevance ground truth.
- At K=5/10/50 measure verified duplicate-unit rate, erroneous-merge rate on independently
  labelled pairs, known-read repeat rate, distinct relevant unit coverage, intent opportunity
  coverage, source/topic concentration/streaks, grade displacement and underfill reasons.
- Count identity/history label coverage and slice sample sizes. Report outcomes conditioned
  on available accepted opportunities AND end-to-end losses from S1/S6/S7, without inserting
  missing positives. Evaluate temporal/story/source-disjoint fixtures including repeated days.
- Compare unchanged S7 top-K, verified-dedupe-only, proposed selector, then optional MMR.
  A tiny exhaustive selector for synthetic small pools can expose greedy constraint/coverage
  gaps; it is a test oracle, not a new production solver.
- Record pure assembly and DB-phase latency separately, rows/queries, cache churn and new
  ranking calls after history-only changes. Assembly must make zero provider calls. Freeze
  numerical quality/latency promotion targets before heldout evaluation, not after seeing results.

## 10. Release gates and recommendation

Repository implementation can use offline fixtures and no paid credits. Activation separately
requires additive schema compatibility, real SQL race/rollback proof, Swift wire verification,
independent identity/edition-quality evaluation and observed latency on a declared workload.
Keep S0's three known quality failures visible and do not claim S3/S4/S7 live quality is proven.

Default `S8_SERVING_ENABLED=false`; enable only with compatible S5/S6/S7 and approved assembly
config. Disabled S8 must preserve the existing default path. Disabling the assembly recipe
must fence its cached editions; any downgrade to an older composer needs an explicit recipe
transition/new edition, not an in-place order change. No schema install/activation on startup.

Recommendation: approve batches A–E as a bounded S8 implementation, with grade-protected
selection, conservative acknowledged novelty and no new paid AI layer. Semantic diversity
weights, meaningful-update claims and publisher preference remain evidence-gated, not guessed.

Primary sources checked for the design:

- [Original MMR paper](https://www.cs.cmu.edu/afs/cs/Web/People/jgc/publication/MMR_DiversityBased_Reranking_SIGIR_1998.pdf): relevance/redundancy trade-off, not an identity guarantee.
- [PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html): coherent snapshots alone do not establish serializable publication.
- [LeaDivRec](https://arxiv.org/abs/2204.00539): learned diversification exists as a research alternative; not evidence that Daily needs that architecture now.
