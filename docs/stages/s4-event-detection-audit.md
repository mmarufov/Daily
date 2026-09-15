# S4 — Event detection: audit and implementation specification

Date: 2026-09-06. Status: architecture analysis complete; **not a runtime implementation or launch approval**.
Evidence: worktree based on `b667985ddc4a1e7b4a871ba33ef7c28ccbeb880d`, current S3 files,
frozen evaluation artifacts, offline diagnostics/tests and primary technical sources.
No paid model calls, production inspection/mutation, deployment or localhost service in this audit.

## 1. Decision

Build a shared, versioned **event-and-development service**, not a popularity counter followed
by an LLM deciding what everyone must read. Separate four decisions:

1. Do these evidence-backed reports describe the same bounded event or a related development?
2. What is independently reported, uncertain, contradicted, corrected or genuinely new?
3. What consequences and geographic/sector scope justify a significance tier under Daily's rubric?
4. Which eligible article should this particular reader receive, and has that development
   already been delivered? This last decision belongs to S6–S10, not to S4 alone.

Use the existing PostgreSQL/pgvector/Python stack, durable jobs and strict bounded model
adjudication. Preserve source-linked claims and immutable decision revisions. Similarity and
coverage generate candidates; neither proves event identity, truth, urgency or global importance.
An event with unknown significance stays **unknown**, not routine and not globally forced.

The old architecture's `outlets + 2·verticals + 2·regions`, top-24 cutoff, universal cosine
threshold and “embarrassed not to know” prompt are prototype heuristics, not production contracts.
Replace them before enabling S4. A fixed two-slot edition cap must not limit how many real
critical events the detector may recognize.

S3 supplies tested lifecycle primitives, but its semantic quality and production rollout remain
open. Its default grouping is singleton-only. This audit does **not** elevate S3 into a proven
production dependency; see [S3 implementation status](s3-implementation-status.md).

## 2. What the repository actually does

References below address the current worktree, not the deployed application. News descriptions
in retained fixtures are dataset examples, not claims about current world events.

| Finding | Code/evidence | Consequence |
|---|---|---|
| S4 detector exists only in evaluation code | `backend/evals/global_events.py:170`; `backend/evals/runners.py:305` | There is no production S4 worker, event store or publication contract to harden in place. |
| Greedy centroid grouping is order-sensitive | `global_events.py:73` | Related topic stories can bridge distinct incidents; replays can yield different membership. |
| Breadth counts source display names, feed verticals and a small hand-written region map | `global_events.py:31`, `:98` | Publisher sections, syndicated copies and unknown geography distort corroboration. |
| A two-source minimum precedes evaluation; only the top 24 breadth candidates are scored | `global_events.py:144`, `:170` | Early authoritative reports and undercovered regions can be excluded before significance is considered. |
| Significance sees a 110-character representative title and counts | `global_events.py:150` | No event-time, source claim, uncertainty, contradiction or material-change evidence supports the decision. |
| Loose output validation; missing verdict becomes routine | `global_events.py:161`, `:184` | Boolean IDs and non-string explanations are accepted; operational failure masquerades as editorial judgment. |
| Event IDs are enumeration offsets with no history | `global_events.py:179` | No stable identity, correction, expiry, merge/split lineage or cross-day novelty. |
| Every critical event bypasses the prototype reader path; all forced rows are prepended | `backend/evals/pipeline.py:488`, `:504` | No two-slot cap; too many forced items can exceed edition size. Dedup/policy cannot be assumed preserved. |
| Runtime feed still depends on user-linked sources | `backend/app/services/feed_service.py:152`, `:505` | Boosting already-retrieved rows cannot rescue a globally relevant event absent from the candidate set. |
| Runtime `cluster_id` is a headline hash | `feed_service.py:1337` | It is neither an S3 development identity nor an S4 event identity. |
| Feed cache carries no event decision generation | `feed_service.py:1474`, `:1609` | A corrected, withdrawn or expired priority can survive until a normal cache refresh. |
| S3 current loader fences article inputs, but checks enabled rather than production approval | `backend/app/services/understanding_repository.py:344` | S4 must additionally bind the explicitly promoted S3 recipe/cohort; do not consume arbitrary experimental results. |
| S3 recipe disable has no recipe-change outbox notification | `understanding_repository.py:65` | S4 needs recipe/control generation and read-time guards, not only article event receipts. |
| S3 deletion tombstone omits former cluster; article membership history cascades away | `backend/app/services/understanding_schema.sql:91`, `:159` | S4 must retain a reverse dependency path sufficient to invalidate the event that lost evidence. |
| September 2 event labels are detector-generated, not independent ground truth | `backend/evals/label.py:367`; `backend/evals/labels/2026-09-02/events.json` | Evaluating the same detector against its own clusters can reward its errors. |
| Event delivery credits any cluster member; false-major divides by feed slots | `backend/evals/metrics.py:78` | Existing metrics conflate detector quality, representative accuracy and edition contamination. |
| Global preparation runs before the runner's cost/latency meter | `backend/evals/runners.py:316`, `:325` | Current per-reader scorecards omit shared embedding/event preparation; the old $0.0007 claim is not an S4 cost forecast. |

The August 31 agent review explicitly rejected a 35-article AI **topic** cluster
(`backend/evals/labels/2026-08-31/events.json:330`). September 2's model-only `ev-04` again groups
many unrelated AI articles under one accelerator headline (`.../2026-09-02/events.json:112`).
This is a concrete identity failure, not a need to tune one more cosine constant.

Read-only reproduction in `.context/s4/reproduce-prototype.py` confirms:

- BBC + BBC World produce two sources, two verticals and spread 8.
- `id=True` is accepted for event 1; a dictionary is accepted as `what`.
- An absent/empty model verdict is silently classified as `routine`.
- Unit vectors at 0°, 40°, 80° with threshold .7 group as `{0,40}/{80}`; reversing arrival
  gives `{0}/{40,80}`. The normalized running-centroid update also differs from an exact mean.

## 3. Identity: article, development, event and topic are different

```text
Article revision + source evidence  ──► S3 development membership (or singleton)
                  │                              │
                  └── evidenced mentions ────────┴──► S4 bounded event episode
                                                            │
                                               material developments + decisions
                                                            │
                                            S6/S7 candidates → S8 edition → S9/S10 seen state
```

An **article** is one publisher's document. A **development** is a concrete change being
reported: an order issued, a result declared, an incident occurring, a correction published.
A bounded **event episode** connects related developments with an explicit identity boundary:
a particular election, incident, court case, outage or named storm. A topic such as AI,
Middle East conflict or inflation is not an event that can inherit a critical flag forever.

For long-running conflicts, maintain bounded episodes/developments, with optional typed
`related_to`/`part_of` links to an umbrella thread. Importance does not automatically propagate
through those links. A new escalation, peace agreement and routine retrospective are not one
duplicate story; a commodity-price reaction cannot substitute for reporting the escalation.

S3 story groups are useful input, not an infallible partition. Support singleton input and
many-to-many **evidence-level** event links: a roundup or live blog can discuss several events.
Only its specific supported mention contributes to each event; never assign its entire text,
whole embedding or publisher count indiscriminately to every mentioned event.

Use database-assigned stable UUIDs for events and developments, not title/centroid/content hashes.
Fingerprints identify immutable **versions**, not permanent real-world identities. Match every
new member to an event's bounded signature and representative evidence, not merely one neighbor.
Uncertain relationships remain separate with an explicit candidate edge; wrong merges are
correctable but must not become transitive truth.

S4 material-development IDs are explicitly separate from S3 cluster IDs. S3 membership can change
or split; S4 maps current mention/development evidence onto its own stable development identity
and immutable factual versions. A fingerprint identifies the factual version, not the stable ID.

## 4. Input contract and S3 prerequisites

Freeze the following for every piece of admitted evidence:

| Input | Required meaning |
|---|---|
| Article identity and revision | `article_id`, semantic revision, analysis eligibility generation, input hash. |
| S3 result/recipe | Exact facet/embedding result IDs and recipe/space; approved serving generation for live use. |
| Development membership | Cluster ID and membership/cluster version, or explicit singleton/unassigned state. |
| Mention reference | Immutable result ID + event-hint index + hint digest; array index alone is not stable across revisions. |
| Evidence references | Original-field/artifact identity, offsets and hashes; only currently eligible S2/S3 evidence. |
| Temporal metadata | Publisher time, first observed time, source update time, claimed event interval/precision, decision cutoff. |
| Publisher provenance | Versioned publisher/editorial group, acquisition identity, ownership facts, report-origin/syndication group and uncertainty. |
| Coverage health | Eligible monitored population, ingestion/understanding lag and unsupported slices as of the cutoff. |

Current `EventHint` is only actors/action/object/date/place IDs/evidence
(`understanding_contract.py:190`). It lacks explicit negation/modality, date precision,
claim attribution, evidence support for a normalized date and stable mention IDs. Validating
an ISO date is not proving it appears in or follows from source evidence.

Do not silently interpret that v1 schema as the richer contract. Either add a versioned S3
hint recipe with those fields, or let a bounded S4 evidence-refinement stage derive them
from eligible source spans and explicitly reference its inputs. Missing data stays unknown;
do not infer today's event date from ingestion or turn “denied” into “happened.” Keep S3 and
S4 recipes separate so adding significance rules does not re-embed the whole corpus.

S4 shadow research may consume recorded unpromoted S3 outputs with explicit provenance, but
no live priority can depend on an unapproved or unsupported S3 cohort. Do not require an image,
native body or a minimum number of words for editorial eligibility. Source-web reporting remains
usable under the existing S2 provenance/access rules.
Editorial eligibility alone is not sufficient for automatic priority: an empty/unsupported card
cannot satisfy the consequence/support gate without additional eligible, attributed evidence.

## 5. Evidence independence, reach and observation health

Maintain three separate measures, not one “outlet count”:

1. **Distribution reach:** which monitored publishers/editions carry the report.
2. **Independent reporting origins:** genuinely distinct reporting paths for the core claim.
3. **Primary authority evidence:** an attributable original statement, document or observation,
   qualified by issuer and scope. Primary does not mean universally truthful or impartial.

A single wire report republished by 100 sites may have wide reach and one reporting origin.
Two outlets repeating the same official release corroborate publication of that release,
not necessarily its underlying allegation. Different corporate owners do not prove independent
reporting; common ownership alone does not prove every investigation is the same origin.

S1 needs versioned `publisher_id`, edition/feed IDs, editorial/ownership relationships,
region/language coverage metadata and review provenance. Report-level origin groups use explicit
wire credits, attributable source references and calibrated duplicate-text evidence. Model
guesses or domain-string equality cannot certify independence. Unknown origin contributes to
reach and an unknown bucket, **not** to the minimum independent-support count.

Count core-claim support, not every background/market-angle member. Preserve distinct dates
and references when a shared source revises a claim. Missing region is missing, not an extra
geographic category; outlet headquarters are not event geography or reader relevance.

Coverage velocity may prioritize assessment only after deduplication and adjustment for the
active, healthy source population in that slice. Adding 500 feeds must not manufacture an
“event burst.” A source outage must not manufacture a quiet day or evidence that an event ended.
The denominator is Daily's observed coverage, never “all news in the world.”

## 6. Candidate formation and event matching

Use an incremental, bounded candidate graph represented in PostgreSQL, not an unbounded
all-pairs clustering job. Recommended v1 path:

1. Consume current S3 changes; select explicit event mentions, including eligible singletons.
   Keep unknown/unsupported inputs accounted for rather than silently discarded.
2. Retrieve a union of candidates from entity/structured identifiers, temporal/geographic
   compatibility, lexical names and same-space embeddings. An unresolved entity must not
   make vector/lexical candidate recall impossible; it lowers certainty at verification.
3. Apply event-type constraints: actors, action class, object, place, occurrence interval,
   named case/election/storm/issuer identifiers where available. Do not use one fixed seven-day
   rule for both an earthquake and an election process. Missing dates are not exact matches.
4. Verify `same_development`, `same_event_new_development`, `related_only`, `different` or
   `insufficient` against a bounded event signature and source evidence. Similarity merely
   proposes the pair. The narrow hard-negative boundary is more important than topic recall.
5. Require a calibrated match margin over competing candidates. If two episodes are plausible,
   keep a provisional separate event instead of attaching to the first one encountered.
6. Revalidate membership after concurrent changes. Persist accepted relations and rejected/
   ambiguous candidates with reason codes and versions; allow reviewed merge/split corrections.

Broad similarity may support `related_only`; it must not broaden an event's consequence facts
or force duplicate suppression. Multilingual evidence requires supported language evaluation:
translated wire copies do not create independent origins. Prefer original evidence; any derived
translation has its own recipe/hash and cannot replace source attribution.

Start exact vector search within bounded time/entity candidate sets, with measured size/latency.
Introduce HNSW only when load requires it. pgvector 0.8.0 applies filters after approximate scans
and provides iterative scans to improve filtered retrieval; compare the actual filtered query
against exact search before relying on it. This is an index capability, not an event-matching
accuracy guarantee. [pgvector v0.8.0 documentation](https://github.com/pgvector/pgvector/tree/v0.8.0)

Streaming and cross-language clustering are established research problems, not solved by a
universal cosine threshold. Miranda et al. evaluate online monolingual/cross-lingual grouping;
their language-specific evidence is not a claim of all-language Daily support.
[Multilingual Clustering of Streaming News](https://aclanthology.org/D18-1483/)

Temporal event-focused summaries are another candidate representation, but must retain evidence
links and be evaluated for drift. Nakshatri et al. study temporal-guided news clustering and
release KeyEvents; media attention in that task is not Daily's criticality definition.
[Temporal-Guided News Stream Clustering](https://aclanthology.org/2023.findings-emnlp.274/)

## 7. Significance is a versioned editorial policy

Adopt a product-owner-reviewed rubric. The following is a proposed starting policy, not an
empirically selected classifier or a universal moral ranking of events.

| Dimension | Question |
|---|---|
| Consequence | What supported change affects safety, civic institutions, essential services, livelihoods or consequential decisions? |
| Scale and scope | Which affected populations, places and sectors are actually evidenced? Do not derive this from publisher locations. |
| Time sensitivity | Is there a new actionable/current development, a scheduled future event, background or a retrospective? |
| Reporting support | What is attributable, independently reported, disputed or withdrawn? Evidence breadth and factual certainty remain distinct. |
| Material change | What changed relative to the event's previous accepted factual state? |
| Coverage quality | Is the available observation complete enough for this decision? What input/region/language gaps remain? |

`world_critical` requires a supported current development with consequences crossing a
high, explicitly defined general-interest threshold. A catastrophe can warrant broad awareness
even if geographically concentrated; cross-border publication is neither necessary nor sufficient.
`major` describes substantial scoped importance, including regional/local/sector impact;
it is not shorthand for “less important people.” `routine` means an assessed case does not
meet those thresholds. Use nullable tier with a separate status for insufficient, disputed,
unsupported, pending or failed assessments.

Separate **event significance** from **new-development delivery eligibility**. A historically
critical episode can remain historically significant while its latest article adds nothing new.
A local water/transport disruption can be major for affected readers without a global override.
War, death, election and “breaking” keywords alone are never policy predicates.

The v1 model receives one event revision per call: bounded source-attributed core claims,
contradictions, consequence evidence, occurrence/observation times, origin-group coverage and
the previous factual state. It returns structured dimension assessments, supporting evidence
IDs, abstentions and a proposed tier. Deterministic code verifies identity, current dependencies,
allowed values, evidence references, scope consistency and policy prerequisites before publishing.
No free-form “what happened” text may become fact solely because the model wrote it.

Preserve allegations, negation and uncertainty in any explanation. Two models agreeing do not
constitute two independent sources. A second bounded judge is an optional benchmarked escalation
for resolvable ambiguity, not an automatic truth oracle or an endless retry loop.

Structured Outputs constrains shape but can still contain substantive mistakes; refusals need
separate handling. Follow the S3 adapter's bounded transport/accounting pattern while defining
a separate S4 schema and recipe. Do not call the existing S3 provider with an unsupported new
stage or silently change its contract. [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

Do not select the gravity model from S3's pilot alone. That pilot tested article-card transport,
not event significance. Benchmark the existing pinned inexpensive model as a baseline, plus
an explicitly priced stronger candidate if justified; choose using S4 development-set errors,
latency and all-in cost, then freeze the candidate before the untouched holdout gate. No model
spending is authorized by this analysis, and the previous USD 5 was
an S3 pilot authorization, not an S4 allocation.

### The two-key rule, corrected

Require both a **support/eligibility gate** and a **consequence-policy gate** for automatic
elevation. The first is not a mandatory count of press outlets; otherwise early local emergencies
are impossible to recognize. Broad ordinary coverage must pass independent-origin scrutiny.
An optional separately approved primary-authority lane may admit a single authenticated issuer's
scoped notice. It does not automatically make that notice world-critical.

If that lane is added, use issuer allowlists and original authenticated acquisition. CAP provides
separate urgency/severity/certainty plus message update/cancel semantics, expiry and geographic
targeting. A CAP-shaped payload does not authenticate its issuer. Reject test/exercise/private
messages from public delivery, honor issuer cancellation and retain the original instructions;
do not synthesize safety advice. This is an additional S1 integration requiring its own tests,
not assumed present in Daily. [OASIS Common Alerting Protocol 1.2](https://docs.oasis-open.org/emergency/cap/v1.2/CAP-v1.2-os.html)

GDELT may supply external discovery hints, not authoritative Daily identity or gravity. Its
Goldstein score is assigned by event type rather than the magnitude of a particular occurrence;
legacy source/mention counts have observation-window limitations. Do not map it directly to
criticality, treat its confidence as truth probability, or count it as an independent publisher.
[GDELT 2.0 event codebook](https://data.gdeltproject.org/documentation/GDELT-Event_Codebook-V2.0.pdf)

## 8. Novelty, contradiction, time and corrections

Represent source-attributed claims with subject/action/object, occurrence interval/precision,
claimant, modality/negation and immutable evidence IDs. Classifications such as `reported`,
`alleged`, `denied`, `disputed`, `corrected` and `retracted` describe reporting state; avoid an
unqualified `true` flag. Numeric claims retain units, ranges and source timestamps. Conflicting
casualty estimates are not summed or silently resolved by choosing the largest number.

Compare each bounded factual snapshot with the previous accepted snapshot:

- Paraphrase, syndication and another outlet repeating the same fact: no material development.
- Independent corroboration: support changes; possible decision reassessment, but not automatically
  a second “breaking” story or new world event.
- A supported new action, ruling, official result, consequence or scope change: candidate material delta.
- Prediction → occurrence, allegation → denial, correction → revised consequence: typed transitions,
  not interchangeable sentences. A correction can require a visible update without a new incident.
- An anniversary, background explainer or stale republish: no new-event alert based on fresh ingestion.

Keep occurrence time, published time, first observation, source correction time and assessment
time separately. Event-type policy governs inactivity/expiry; time passing can invalidate a
decision even when no new article arrives. Schedule expiry work and enforce `valid_until` at
read time. A frequently republished article cannot extend the event's freshness indefinitely.

Use stable material-development identifiers/fingerprints under a versioned delta recipe.
S9/S10 record delivered/seen development and decision versions; reading one war article must
not suppress every future escalation. Event merge aliases and split lineage must be available
to that deduplication, without declaring newly separated developments already seen.

## 9. Durable lifecycle and transaction protocol

Keep entity lifecycle and computation state distinct:

- Event lifecycle: `candidate`, `active`, `inactive`, `withdrawn`, `merged` (with lineage).
- Computation: `pending`, `running`, `retry_wait`, `ready`, `insufficient`, `unsupported`,
  `failed_terminal`, `superseded`; historical decisions remain inspectable.
- A missing/failed assessment is **not** a routine judgment. A previously approved decision may
  remain current only while its exact dependencies and validity interval still hold. Provider
  failure never renews it or creates a new escalation.

Recommended protocol:

1. Read S3 outbox events with exact-ID receipts. In one transaction, persist an idempotent S4
   inbox receipt plus dirty-event/candidate work. Acknowledge only after durable application.
2. Use reverse evidence dependencies to dirty both old and new events after corrections,
   membership changes, revocations and deletion. Reconcile missed work periodically by bounded
   revision cursors; never treat an outbox sequence high-water mark as commit order.
3. Claim a bounded stage job with `SKIP LOCKED`, lease token, attempt ceiling and deadline;
   commit. Freeze input dependency versions and an immutable assessment snapshot.
4. Reserve maximum priced request cost atomically. Release database connections before provider
   I/O. Persist successful grouping/assessment stages independently; ambiguous charges remain held.
5. In a short publication transaction, acquire the required control/source locks, then affected
   article/dependency rows, event/development rows and S4 job under the order below. Re-read S3/current
   approval, membership, origin metadata, event generation, policy/recipe and evidence digest.
   If the affected set changed since discovery, rollback and rediscover; do not acquire earlier
   lock classes after event locks. S4 must not lock S3 job rows or reuse its cluster advisory lock.
6. Publish the immutable decision, current pointer and invalidation outbox atomically. Check
   ownership, lease and deadline again at the **end**; expiry rolls back every projection,
   membership change and event, not merely the job's final state.
7. At serving time, independently verify current decision generation, recipe/control state,
   complete dependency manifest, observation-lag policy and expiry. Delayed invalidation
   delivery cannot authorize a stale forced slot.

Proposed S4 publication lock order, with explicit modes: S3 control (`FOR SHARE`) → S4 control/
recipe (`FOR SHARE`) → source policy/registry rows (`FOR SHARE`, sorted) → articles (sorted) →
S3 recipe (`FOR SHARE`) → S4 events (sorted) → S4 developments (sorted) → S4 job. Never upgrade
or mutate S3 control/recipe locks from this transaction. Existing S3 publication takes article →
S3 recipe `FOR SHARE` → S3 job (`understanding_repository.py:307`, `:189`); do not introduce
an exclusive recipe→article path against it. Existing S2 policy writes take source-policy →
article → content-job (`article_content.py:1253`, `:1183`).

Keep S3/S4 control/recipe administration isolated: update control/recipe plus its notification
and commit, **never** subsequently lock articles/events/jobs in that transaction. Reconciliation
and materialization follow in separate jobs. Claims/reapers lock jobs only and commit before
further work; spend reservation transactions lock controls only and do not subsequently lock
articles/events/jobs. Event-dirty scheduling locks event before upserting its job, matching S4
publication. Batch B must audit every writer/FK side effect and prove the combined lock modes
and ordering with concurrency tests; this is a proposed protocol, not existing proven S4 code.
Do not add synchronous cross-system triggers that introduce an unreviewed reverse lock edge.

The serving guarantee needs an explicit linearization point: validate the entire dependency/control
set in one coherent database snapshot, not unrelated successive READ COMMITTED reads. Bind
authorization to that snapshot and its live generation/expiry. For cache publication, acquire
the relevant generation fence under the same ordering and revalidate the expected versions in
the commit transaction. Reads beginning after a committed invalidation must not authorize the
old priority. An already-authorized in-flight response cannot be recalled if invalidation commits
later; its version/expiry must still be carried to clients. Test invalidation between dependency
reads, after authorization and before cache publication separately; do not promise impossible
instant revocation of bytes already sent.

Use PostgreSQL row skipping only for queues, not to read an incomplete set of supporting
evidence and then claim the aggregate is complete. PostgreSQL explicitly distinguishes those
uses. [PostgreSQL 16 SELECT](https://www.postgresql.org/docs/16/sql-select.html)

Use `clock_timestamp()` for final lease/deadline expiry: `now()` is transaction-start time and
can stay valid after the real lease expires. Freeze a separate explicit business-time cutoff
for deterministic replay. [PostgreSQL date/time semantics](https://www.postgresql.org/docs/16/functions-datetime.html)

### Important cross-system races

S3 currently emits article/membership changes but not recipe disable/promotion events. Add a
versioned serving-control generation and recipe/source-policy change events before materialized
S4 consumption. Still validate the actual state at read time; outbox notifications alone are
not an authorization boundary. A source ownership/origin revision must invalidate breadth and
assessment even when article text did not change.

Store a complete expected dependency count/digest and admitted-member-set generation, including
contradicting, denying, correcting and withdrawn evidence—not just supportive claims or the
subset selected for a provider prompt. Admitting a material new member advances that generation.
If an article or result disappears,
an inner join over the remaining rows must not accidentally certify the old snapshot. Preserve
content-free tombstones/reverse links or dirty affected events synchronously before deleting
dependencies. Purge private derived snippets when analysis rights are revoked; retain only the
minimal non-content identity/accounting history needed for invalidation and audit.
Decision invalidation is immediate at the committed rights change; any asynchronous historical
content purge has a separate bounded completion SLO and cannot delay that authorization change.

New unrelated evidence arriving after a snapshot is not retroactively part of that snapshot.
Expose `as_of`/observed-through and pipeline lag honestly. Prioritize incoming contradictions
and corrections; do not claim instantaneous knowledge of unprocessed reports or unseen sources.

If snapshots exceed bounded membership/evidence limits, mark completeness unknown, partition
the episode or use explicitly versioned incremental aggregates. Never sample away contradictions
and then classify the convenient remainder as a complete evidence set.

## 10. Storage and technology scope

Use additive migrations and private typed tables/JSONB records. A concrete starting layout:

| Relation | Purpose/invariant |
|---|---|
| `event_recipes`, `event_control` | Immutable rubric/model/input/grouping/delta definitions; approved serving generation; independent submission/delivery switches and budgets. |
| `events` | Stable identity, bounded signature, lifecycle, current generation and optional canonical redirect. |
| `event_developments`, `development_versions` | S4-owned stable material-development IDs and immutable factual versions; explicit current S3 mention/group mappings, not reused mutable S3 cluster identities. |
| `event_evidence` | Many-to-many mention/development membership, roles and expected article/S3/source versions; reverse indexes for correction/deletion. |
| `event_snapshots` | Immutable bounded factual/coverage state, time cutoff, complete dependency digest and selected evidence manifest. |
| `event_assessments` | Immutable snapshot+recipe decision, dimension outcomes, tier/status, evidence links, expiry and usage receipt. |
| `event_jobs` | Independent grouping/assessment/reconciliation work with dedup keys, lease/deadline, attempts and explicit outcome. |
| `event_changes` | Merge/split, correction, withdrawal and material-development lineage; actor/reason/expected version for reviewed interventions. |
| S4 inbox/outbox/receipts | Durable change consumption/publication; idempotent application without assuming sequence commit order. |
| S4 spend reservations | Namespaced stage-job/attempt receipts, known usage and unresolved maximum charges. |

Enforce one result per immutable job/input recipe, positive versions, bounded typed values,
ownership references and acyclic redirects. Unknown metadata must be representable. Keep arbitrary
model text out of SQL identifiers, policy expressions and job destinations. No runtime DDL,
outbound article fetching or new model work in the feed request path.

Use a separate supervised Python process; start with the same operational job pattern as S3,
not an immediate whole-system queue refactor. Reuse validated utilities where interfaces match.
Do not insert S4 jobs into S3's fixed stage enum or reuse an unnamespaced numeric job ID for spend.
If a combined S3+S4 ceiling is desired, build and race-test a shared namespaced budget boundary;
two separate daily caps do not automatically enforce one aggregate cap.

A graph database, Kafka and a dedicated vector database are not justified by observed S4 load.
Record candidate counts, dirty-set sizes, database plans and p95/p99 transaction/worker latency;
revisit infrastructure only when measured contention/throughput needs it. A generic event-news
API is an optional source/discovery dependency, not a replacement for Daily's revision and
editorial contract. Licensing, attribution, availability and independent evidence still apply.

## 11. Consumer, privacy and reader contract

S4 returns internal candidate records, not final feeds:

`event_id`, event generation, assessment ID/version, development IDs/versions, tier and status,
scope/affected-place references, evidence cutoff, expiry, policy/recipe generation, material-delta
type, eligible representative evidence IDs and source-attributed reason codes.

S6 must add an independent current-event retrieval leg, bypassing only the user-source recall
limitation. S7 applies scoped relevance to major events. S8 decides whether a current global
candidate may occupy a reserved slot under the approved reader policy.

Proposed default: priority may override **soft topic ranking only**, not explicit source/article
blocks, reader safety exclusions, authorization, deleted/revoked evidence or eligibility. Unknown
location does not authorize a local-alert override. Reader location/language come from explicit
S5 settings, not nationality guesses, device tracking or publisher headquarters. Any stronger
override is a separate product decision requiring approval and evaluation.

S8 enforces `reserved_slots <= min(2, edition_size)` and total edition size, then deduplicates
article and material-development identities across event and ordinary candidate legs. Empty
reserved slots are not filled with low-confidence “critical” news. Three genuine critical
events remain three recognized events; the display cap is selection, not reclassification.

Representative selection order: current eligibility → direct support for the specific material
development → supported language/readability → source preference → visual polish. Never prefer
an image-rich market side-angle over the core event; a source-web article can be the right choice.
No eligible representative means no forced slot, with an observable reason rather than bypassed
source policy. S4 does not publish generated multi-source prose as one publisher's article.

Feed cache keys/publication fences need event serving generation, selected assessment/development
versions, expiry and reader-policy generation. Revalidate before cache commit **and** on reuse;
an invalidation event arriving during a feed build must defeat the stale commit. Fanout may be
lazy via shared generations plus targeted edition dependencies, not an O(all users) model run.

S9 may add optional event/version/valid-until fields to its public DTO, retaining backward
compatibility and S2's allowlisted article serializer. No private spans, prompts or source-claim
ledgers enter the public payload. Offline clients must not keep an expired “breaking” override
alive indefinitely; ordinary saved-article access is a separate reader contract. Push notifications
and emergency-alert reliability are out of scope for the initial S4 feed path.

## 12. Evaluation: measure five different outputs

1. **Identity:** event/development membership, false merges/splits, repeated-event discrimination,
   multilingual linking and permutation/late-arrival stability.
2. **Significance:** event-level critical precision/recall, major classification separately,
   unknown/error coverage, scope accuracy and unsupported consequence assertions.
3. **Material novelty:** precision/recall of factual deltas, false re-alerts, correction/retraction
   recognition and stale-republish handling across a real timeline.
4. **Representative correctness:** the selected article directly supports the currently claimed
   development, rather than merely being a member of a broad event/topic.
5. **Delivery:** eligible-reader recall, hard-exclusion compliance, duplicate development exposure,
   slot/edition caps and correction invalidation. This is S6–S9 integration, not detector precision.

Repair the ruler before tuning: freeze event detection on the canonical global pool **before**
per-reader fixture injection; global synthetic scenarios belong to a separate global scenario
manifest. Cache by full evidence/source/recipe/time-cutoff digest, not article IDs. Include
shared preparation, retries and model cache misses once in system totals and report reader
delivery cost separately. Preserve the old slot-contamination metric under an honest name.

Adjudicate original event evidence independently of the detector. Human and agent reviews are
both allowed with accurate provenance, blind review where feasible, explicit disagreements and
product-owner signoff on the rubric. Model-generated seed clusters are candidates, not holdout
truth. Sample random unflagged coverage as well as detected events so missed-event recall is
observable. Unsupported or unreviewed slices block promotion instead of disappearing.

Define metric units before evaluation. Compute pairwise same-event membership and same-development
membership **separately** over canonical mention units, with syndicated copies deweighted/collapsed;
also report event-family macro scores so one large incident cannot dominate all pair counts.
Freeze predicted-to-gold event/development alignment (identity/type/time/place compatibility and
gold core-evidence coverage, deterministic one-to-one matching within the declared granularity).
Duplicate predicted events are extra predictions, not extra true positives; broad topic clusters
cannot match several distinct gold events and claim credit for all of them.

Critical recall denominator is all gold critical material developments for which qualifying
source evidence is available and permitted in the declared input population at the cutoff.
Missing, unknown, failed and late predictions are misses; do not define eligibility by successful
model processing. Report both conditional S4 component results and end-to-end S1–S4 misses,
attributing absent/unprocessed input rather than hiding it. Abstention/error coverage is separate.
Critical precision is correct critical predictions divided by all critical predictions under
the frozen alignment policy, not correct article slots divided by a full feed.

For population estimates, completely adjudicate selected time windows or use documented event-level
probability sampling/inclusion weights. A random sample of unflagged articles alone cannot estimate
population event recall. Report prevalence-sensitive precision on representative streams separately
from deliberately balanced or adversarial suites; do not pool them without valid weighting.

Split by event family, syndicated origin and adjacent time windows; retain frozen availability
at each replay cutoff. Do not leak later corrections, casualty totals, updated source metadata
or model-generated future summaries into earlier decisions. Research models may already know
historical events, so evidence-only counterfactuals and private/novel cases are needed alongside
historic replay. A ten-persona delivery test is one detector example, not ten independent events.

The quiet derivative of August 31 is a useful removal stress test, **not an independent quiet
news day**. Add independently captured quiet/busy days, undercovered regions, supported languages
and event-free topic noise. The September 2 17 model-only event labels must be adjudicated before
they can certify S4. Task-specific datasets, separate evaluation and continuous error-driven
expansion align with [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices).

### Proposed release targets — not achieved measurements

| Gate | Initial requirement |
|---|---|
| Event membership | Held-out precision ≥.98 and recall ≥.90; separate repeated-event, topic-bridge and multilingual results. |
| Critical significance | One-sided 95% lower bounds meet precision ≥.99 and recall ≥.95 on the frozen representative-stream protocol; an empty/underpowered sample fails. |
| Critical negative cases | Zero false critical promotions in the fixed adversarial suite; independently sampled negative-decision error upper bound ≤.005 at 95% confidence. |
| Material delta | Precision ≥.98, recall ≥.90; zero re-alert for unchanged facts in deterministic replay. |
| Representative | Direct-support accuracy ≥.99; zero wrong-article, revoked or stale evidence in integrity tests. |
| Lifecycle | Zero stale publication, lost invalidation, duplicate durable effect or unaccounted provider request in hosted fault tests. |
| Reader policy | Zero explicit-policy bypass; reserved slots ≤2 and total size always respected; no duplicate development in an edition. |
| Freshness | From qualifying evidence becoming available: p95 assessment-ready ≤5 minutes under declared load; report S1/S2/S3/S4 delays separately. |
| Invalidation | Reads beginning after committed invalidation cannot authorize obsolete priority; expiry is checked at the authorization linearization point. Queue lag cannot extend validity. |
| Cost/load | Explicit global daily/monthly ceilings, per-stage maximum requests/tokens, 2× forecast load test and bounded outage recovery backlog. |

These are proposed risk tolerances requiring policy agreement, not universal constants. Freeze
the gate definitions and support declarations before holdout evaluation; do not lower them after
seeing results. Extend any insufficient slice rather than calling it accurate from a handful of cases.

For scale: with zero errors in 600 independent negative opportunities, the exact one-sided 95%
upper binomial bound is `1 - 0.05^(1/600) ≈ 0.00498`. That calculation assumes independence;
correlated reports/repeated prompts do not qualify. For precision, 300 independent correct
critical predictions with no errors give a lower bound `0.05^(1/300) ≈ .99006`. These are sample
planning examples, not a mandate to manufacture 300 critical events or proof from this repo.
Use event-family/day blocked intervals for correlated streams; report underpowered critical
and language slices honestly. Zero false alerts during a short canary cannot prove perfection.
Freeze the interval method, sample sufficiency rules and each supported-slice promotion test
before model selection. Unsupported or underpowered slices remain disabled, rather than passing
as null or borrowing the same event's many copies/personas as independent samples.

## 13. Required negative-path and adversarial matrix

| Case | Required behavior |
|---|---|
| Many publisher sections / one wire on many sites | Reach grows, independent core support does not; no automatic critical escalation. |
| AI launch, newsroom policy and AI warfare share vocabulary | Separate events; topic relation cannot become corroboration. |
| Same named storm/earthquake area on different dates | Distinct episodes unless supported identifiers/time connect them. |
| Different places with the same name | Keep unresolved/scoped unknown; no guessed local alert. |
| Early authenticated primary notice before press pickup | Consider through separately approved authority lane; geographic scope and expiry remain mandatory. |
| Official notice is a test, cancelled, expired or forged | No live priority; cancellation invalidates cached decisions. |
| Prediction, denial, allegation, confirmed action | Preserve modality and evidence, never normalize into the same asserted fact. |
| Casualty totals conflict or are corrected down | Preserve attribution/conflict; recompute consequence assessment; no max/sum heuristic. |
| Old report is republished or translated | No new material-change alert and no new independent origin. |
| Roundup includes war, sports and finance | Link only evidenced mentions; no cross-event contamination or forced duplicate article. |
| Market consequence article is visually better than core report | Choose direct support first; do not give event-delivery credit to a side-angle. |
| Article/S3 recipe/source-origin changes mid-call | Old result cannot publish as current; already billed attempt remains accounted for. |
| Lease/deadline expires inside publication transaction | Roll back decision, membership, outbox and completion together. |
| Two workers discover/merge/split same event | Stable lock order, unique effects, expected-version correction and bounded replay. |
| Lower outbox ID commits late / consumer crashes after application | Exact receipts and idempotency prevent lost or duplicated durable work. |
| Removed evidence disappears through a join | Expected-manifest mismatch invalidates the old assessment; no accidental recertification. |
| Model timeout, refusal, malformed ID, empty result, NaN score | Typed non-ready outcome; no routine default, fabricated explanation or retry storm. |
| Budget exhausted during breaking-news burst | Fair bounded queues, explicit degraded freshness and no ceiling breach; no silent “quiet.” |
| More than two real critical events | Detect all supported events; S8 selects bounded slots without reclassifying the rest. |
| Explicit hidden article/source/topic-policy collision | Honor approved hard rules; do not let a model's “important” bypass them. |
| Cache rebuild races withdrawal; client remains offline | Server rejects stale build; client priority expires; saved source article behavior stays separate. |
| Healthy-source population changes or regional outage | Coverage state changes, not manufactured gravity; missing coverage remains visible. |
| Malicious article instructs model to mark critical or fetch URL | Treat as source data; no tools or instruction execution; enforce evidence/policy validation. |

## 14. Ordered implementation and rollout

Each batch is a later implementation task. This audit changes documentation only.

**A — Contracts and evaluation baseline.** Define the event/development/rubric/scope/unknown
contract, source-independence metadata and promoted S3 handoff. Repair circular labels and global
metering; add frozen time-series fixtures and fail-closed support/budget manifests. Exit: approved
interface and genuinely independent evaluation design, with current regressions retained.

**B — Durable skeleton with no models.** Add explicit schema migration, event identities,
dependency/inbox/outbox tables, stage jobs, control generations, spend reservations and deterministic
fake-provider snapshots. Add recipe/source change invalidation. Exit: hosted PostgreSQL race,
deletion, expiry, replay and migration-idempotence tests pass with required database setup.

**C — Evidence grouping and factual updates.** Implement hybrid bounded candidates, event-type
compatibility, versioned evidence refinement, independent-origin accounting and material-delta
history. Start uncertain groups as separate candidates. Exit: identity/novelty gates pass; do
not use only clean synthetic vectors or all-singleton precision as evidence of success.

**D — Significance classifier and calibration.** Add strict event provider/schema, exact request
cache and complete budget/latency accounting. Run an explicitly authorized small pilot, then
development comparisons; freeze recipe and evaluate untouched holdout. Exit: supported-slice
criticality/uncertainty/directness gates pass with adequate samples. No pilot was run in this audit.

**E — Consumer contract, still disabled.** Implement S6 event candidate access, S8 hard-policy/cap/
dedup/cache-generation rules and S9 expiry-compatible fields. Validate old clients and S2 source
destinations. Exit: complete feed-path tests show event recall without hard exclusions or stale
priority regressions. Do not call detector-only tests proof that readers receive the event.

**F — Shadow production.** Only after S1 acquisition/coverage and S2/S3 approved cohorts are
verified live, back up/review migrations, deploy S4 worker/control with consumers disabled, and
process an explicitly capped supported cohort. Observe at least 72 hours including quiet and
busy periods plus sufficient event examples; sparse periods require longer observation. Compare
exact/ANN candidates, audit all proposed critical promotions and sample misses/unknowns. No
production fault injection; use disposable hosted infrastructure for crash/load races.

**G — Controlled delivery.** Enable a bounded reader cohort only after frozen gates and rollback
evidence pass. Expand 1% →10% →50% →100% of the declared eligible cohort, subject to absolute
article/token/call caps and observation windows. Track scope, repetition, hides, delivery misses,
cost and stale decisions. Keep independent submission and delivery kill switches. Existing feed
behavior is the fallback; disabling S4 must not remove ordinary eligible reporting.

Immediate abort: unsupported critical consequence, wrong-event evidence, hard-policy bypass,
stale/revoked priority, lost correction, mixed recipe/space or budget integrity failure. Pause
expansion for false-positive/recall/latency/coverage regressions. A sustained >2 critical events/day
is an anomaly to investigate, not an automatic quota that suppresses a real disaster sequence.

## 15. Audit verification and completion boundary

- Read-only diagnostic script reproduced the four concrete prototype defects in section 2.
- Focused current event/eval + S3 contract/clustering checks: **137 passed, 24 subtests passed**.
- Independent evaluation pass: **34 focused tests passed**; existing gate reproduced **3 passed,
  4 strict-only skips, 56 subtests passed and 3 pre-existing prod-llm subtest failures** on
  `2026-09-02`: followup `.1111 → .0397`, never `.2694 → .395`, event delivery `.25 → .15`.
- Existing tests validate selected mechanics. They do not establish event semantics, independent
  ground truth, live freshness, source completeness, cost per revision or production safety.
- Architecture review covers code/runtime boundaries and evaluation separately. No runtime fix,
  model comparison, schema migration, PR/push or production action was performed for S4.

Reproducible commands from the workspace root (all provider calls disabled):

```sh
backend/venv/bin/python .context/s4/reproduce-prototype.py
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/test_global_events.py backend/tests/test_eval_metrics.py backend/tests/test_eval_label.py backend/tests/test_eval_runners.py backend/tests/test_understanding_contract.py backend/tests/test_story_clustering.py -q
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/test_global_events.py backend/tests/test_eval_metrics.py backend/tests/test_eval_label.py backend/tests/test_eval_runners.py -q
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/test_eval_gate.py -q
```

The last command is expected to fail on the three recorded baseline regressions; do not change
the baseline to make this audit green. The 137-test and 34-test runs overlap, not additive coverage.

The code findings, design invariants and implementation gates were independently reviewed;
identified identity, metric-denominator, negative-evidence and lock-order ambiguities were resolved.
The architecture analysis is complete. S4 itself is complete only after batches A–G have passing evidence.
“Bulletproof” here means failures are contained, visible and recoverable, with measured semantic
quality—not a claim that a model can guarantee perfect judgments about every event worldwide.
