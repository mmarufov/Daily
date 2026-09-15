# S3 — Article understanding: audit and implementation specification

Date: 2026-09-05. Status: architecture analysis complete; S3 runtime implementation pending.
Evidence: current worktree based on `b667985`, prior dated production measurements, focused
offline tests, and official technology documentation. No production inspection, mutation,
model benchmark, paid model call, or deployment was performed for this analysis.

## 1. Decision

Build one shared, versioned understanding record for each article revision. It contains
evidence-backed facets, a semantic vector, and a separately versioned story assignment.
Use PostgreSQL, pgvector, a durable Python worker, strict structured model outputs, and
controlled topic/entity/place identifiers. The existing stack is sufficient for the first
production version; an additional vector database, graph database, or agent framework is
not justified by the evidence in this repository.

The unit of reuse is **article input revision + understanding recipe**, not an article URL
forever. Understanding describes what the available article evidence supports. It cannot
guarantee that a publisher's claims are true or that an unseen body says what a headline implies.

S3 is necessary for the personalized product but does not deliver that product alone. S1
defines the pool Daily actually covers; S6 retrieves from it; S7 decides relevance; S8 assembles
the edition. “All news in the world” is a coverage ambition, not an observable input set.
Measure missing publishers/languages/regions separately from articles lost after ingestion.

## 2. What is actually present

Paths and line numbers below refer to the audited worktree, not a deployed build.

| Finding | Evidence | Consequence for S3 |
|---|---|---|
| S0 has a real labeled, frozen replay framework, but outstanding quality failures | `backend/evals/README.md:45`, `docs/stages/s2-content-pipeline-audit.md:38` | Extend its ruler; do not claim current absolute quality gates pass or rebaseline failures away. |
| S1 implementation checklist only has P0 complete | `docs/notes/plan.md`, S1 section; `docs/stages/s1-ingestion-audit.md:17` | Registry, canonical acquisition identity, and poller remain production activation dependencies. |
| S2 repository work is complete; production gates remain | `docs/stages/s2-content-pipeline-audit.md:52` | Consume its provenance artifacts; preserve the source-web/native separation. |
| Worker embeds up to 50 rows with non-null analysis text per ingestion cycle | `backend/app/main.py:173` | No title/summary-only coverage; no independent S3 freshness or durable retry lifecycle. |
| Vector input includes title, summary, and first 2,000 body characters | `backend/app/main.py:195` | Relevant detail can be absent; evidence coverage must be explicit. |
| Version fence only checks selected analysis-body version | `backend/app/main.py:214`, `backend/app/services/article_content.py:1542` | A title update with unchanged body can preserve a stale vector. |
| Ingestion updates title on conflict | `backend/app/services/news_ingestion.py:355` | Fingerprint metadata as well as body and handle every writer. |
| Embedding helper slices 8,000 characters and returns `None` on failure | `backend/app/services/openai_service.py:162` | Token-aware limits, typed failures, provider deadlines, and vector validation are missing. |
| S2's private analysis can include cross-source or legacy text | `backend/app/services/article_content.py:1474`, `backend/app/services/article_enrichment.py:42` | Private ranking context is not automatically evidence about this publisher's article. |
| Production feed uses source joins, recency, lexical filtering and per-reader scoring | `backend/app/services/feed_service.py:415`, `backend/app/services/feed_service.py:505` | Writing vectors/cards alone cannot make missing stories reach readers. |
| Existing `cluster_id` hashes a normalized headline | `backend/app/services/feed_service.py:1337` | It is not persistent semantic story membership. |
| Semantic clustering exists only in the evaluation prototype | `backend/evals/global_events.py:73` | Greedy cosine grouping is a baseline to beat, not a production correctness proof. |
| Search and chat already consume the legacy vectors | `backend/app/main.py:2228`, `backend/app/services/chat_service.py:988` | Migrate these consumers before retiring legacy fields. |
| Feed caches have scores/reasons but no understanding revision | `backend/app/services/feed_service.py:1474`, `backend/app/services/feed_service.py:1586` | Adoption needs revision-aware invalidation and stale-build rejection. |
| “Content quality” measures length and image availability | `backend/app/services/article_enrichment.py:49`, `backend/app/services/feed_service.py:511` | It must not become factual confidence, editorial merit, or S3 readiness. |

The old system map's “every article is embedded” is unsupported. The last retained live
measurement found 0/34,525 embeddings on 2026-09-02; that is historical evidence, not a
fresh measurement. Current code also contradicts full coverage. Likewise, the prototype's
quiet-day false-major rate is recorded as 0.18 in `backend/evals/README.md:157`; S4 is not proven
bulletproof by the earlier war example.

## 3. Correct the old S3 contract

| Old assumption | Replacement |
|---|---|
| Cache a card forever | Cache immutable results by complete input and recipe fingerprint; recard corrections, evidence upgrades, taxonomy and model changes. |
| Twenty-five articles per LLM call | Begin with one article per strict-output request; test bounded microbatches only after identity isolation and quality parity are demonstrated. |
| Every article must have a successful vector | Every retained article has an accounted-for outcome; unsupported inputs/outages remain explicit. Ready coverage and latency have separate SLOs. |
| A cosine threshold establishes a story | Similarity proposes candidates. Entity, action, time and place compatibility decide conservative membership. |
| Novelty is a permanent 0–1 article field | S4 computes development relative to prior reporting; S8/S10 compute whether this reader has already seen it. |
| Commercial is a boolean | Use `yes`, `no`, `unknown`, with affirmative evidence for `yes`; discussion of gambling or advertising is not itself an advertisement. |
| Facets completely eliminate per-user judgment | Facets support matching; S7 may still need bounded adjudication for ambiguous or compound reader intents. |
| $31/month follows from 1,000 readers | S3 cost follows unique article revisions, tokens, attempts, escalation, and backfill; calculate it separately from reader-dependent spend. |

## 4. Evidence and output contract

S3 consumes canonical article identity and a frozen evidence bundle supplied from S1/S2.
The bundle includes title, publisher summary, known publication/update timestamps, publisher
identity, language evidence, chosen body artifact ID/version/hash, acquisition identity,
completeness, and preprocessing version. Keep source publication time, observed ingestion
time, and claimed event time distinct; do not turn a missing date into `now()`.

Input tiers:

- `publisher_body`: identity-validated text from this article, with completeness recorded.
- `publisher_excerpt`: attributable summary/partial body; classify only what is supported.
- `title_only`: usable headline, explicitly limited; conservative topics and unresolved entities.
- `insufficient`: missing identity or usable article text; defer/quarantine with a reason.

Analysis permission and native-display permission are separate. A source-web article can
receive full understanding from legitimately acquired analysis evidence. Conversely, do not
elevate a body to trusted evidence merely because its S2 artifact kind is `publisher_feed` or
`origin_extract`: validate article ownership, acquisition identity and extraction identity.
Cross-source/legacy context cannot populate this article's authoritative facets or its primary
embedding in v1. Preserve it separately for later related-coverage use, with explicit provenance.

Suggested typed record, expressed as fields rather than executable JSON Schema:

| Field | Meaning |
|---|---|
| `article_id`, `semantic_revision`, `analysis_eligibility_generation`, `input_hash`, `recipe_id`, `result_id` | Immutable identity, evidence eligibility and compatibility boundary. |
| `evidence_tier`, `language`, `input_manifest`, `truncated`, `coverage` | What was actually examined; document language is nullable when indeterminate. |
| `kind` | `report`, `analysis`, `opinion`, `explainer`, `interview`, `review`, `roundup`, `listicle`, `promo`, `obituary`, `satire`, `other`, `unknown`. |
| `topics[]` | Controlled ID, `primary`/`secondary`/`mentioned` role, evidence references. Mentioned topics cannot alone justify a subject match. |
| `entities[]` | Surface mention, entity type, evidence reference, role, nullable resolved ID, resolution state/version. |
| `places[]` | Mention, nullable place ID, administrative hierarchy, `event_location`/`affected_area`/`mentioned` role and evidence. |
| `commercial` | `yes`/`no`/`unknown`, plus supported subtype such as sponsored or affiliate and evidence references. |
| `about` | Short source-attributed description preserving allegations, uncertainty and negation; internal in v1. |
| `event_hints[]` | Supported actors, action, object, date interval/precision, and locations. Hints do not establish gravity or a globally verified event. |
| `abstentions[]` | Field and reason: ambiguous mention, insufficient evidence, unsupported language, conflicting evidence, etc. |
| `vector_ref`, `embedding_space_id` | Validated embedding result, model, dimensions and document recipe. |
| `story_assignment_ref` | Independent versioned membership or explicit singleton/unassigned state. |

Store confidence separately from evidence completeness and source reliability. A model's
self-reported number is not a calibrated probability. Thresholds used for auto-exclusion or
entity linking must come from held-out precision/coverage measurements.

For evidence references, use immutable input field/artifact IDs plus normalized-text offsets
and hashes. Verify span bounds and text equality. This establishes traceability, not semantic
truth: a correctly copied sentence can still be assigned the wrong topic. Keep evidence spans
private; the public serializer remains an allowlist and does not expose analysis text or prompts.

Examples that must behave correctly:

- “Highest RTP slots at NJ casinos” → promotion when the text supports it; “NJ regulator
  investigates casino advertising” → reporting about regulation, not automatically promotion.
- “Mikal Bridges traded” resolves a person; “bridges closed after flooding” has no such person.
- “Newark water alert” cannot resolve NJ versus Delaware from the word Newark alone.
- A Zelda gameplay mod is not software-engineering news merely because it mentions code.
  An article about the mod's compiler implementation may legitimately have both topics.
- “Company denies layoffs” cannot become “Company announces layoffs.”
- Headline-only breaking news remains eligible for later retrieval with limited evidence;
  lack of an image, full native body, or complete card is not an editorial rejection.

## 5. Technology choices

### Storage and execution

Keep PostgreSQL as the source of truth, with pgvector HNSW for candidate lookup. Use a
separate supervised Python worker process from the same backend image; claim jobs through
short PostgreSQL transactions. The API process must not own long-running model calls on
the feed request path. No Redis/Celery/Kafka dependency is required for the initial design.

`SKIP LOCKED` is appropriate for queue consumers, as documented by
[PostgreSQL](https://www.postgresql.org/docs/current/sql-select.html). It does not by itself
provide leases, retries, stale-worker fencing or exactly-once external calls; implement those
explicitly. Extraction and understanding have separate job budgets and can fail independently.

### Embeddings

Start the evaluation with existing `text-embedding-3-small`, explicitly requesting 1,536
dimensions. Use one original-evidence article vector first. Compare title+summary against a
token-bounded evidence recipe including body coverage; do not embed only the generated facet
description, which would propagate its omissions into retrieval. Keep text preparation
deterministic, preserve negation, and record omitted ranges. A chunk-vector variant is a later
measured option for long/multi-story content, not a prerequisite for v1.

Use tokenizer-based budgets. The documented model limit is 8,192 input tokens and its default
dimension is 1,536; 8,000 characters is not that limit.
[OpenAI embedding guide](https://developers.openai.com/api/docs/guides/embeddings)

Validate response count/index, numeric finiteness, dimension and nonzero norm. Keep query
embeddings in the same model/dimension space. Version both document and query preparation.
An embedding-model change gets a parallel space/index and recarded comparisons, never mixed
distances. Benchmark `text-embedding-3-large` with an explicitly compatible dimension if the
small model fails multilingual or ambiguity slices; do not silently substitute it.

HNSW is approximate. Compare filtered ANN results with an exact scan on the same active
population. Date/language/readiness filters can underfill ANN results; iterative scanning
requires pgvector server extension >=0.8.0. `pgvector==0.3.6` in requirements is the Python
client version, not evidence of the installed server extension. Inspect `pg_extension` before
using those settings. Standard HNSW `vector` indexing supports up to 2,000 dimensions, so a
default 3,072-dimension large-model migration is not a drop-in change.
[pgvector documentation](https://github.com/pgvector/pgvector)

### Facet extraction

Use a pinned model with strict Structured Outputs and one Pydantic contract, then application
validation. Start the bake-off with `gpt-4.1-mini-2025-04-14` as the provisional extraction
candidate and `gpt-4o-mini` as the existing low-cost baseline. This is a reproducible initial
comparison, not a claim that either is currently the best model. Select the least expensive
candidate that passes every supported-language quality gate and freshness/cost budget;
escalate difficult evidence only if a tested stronger model improves it. Missing evidence
should produce abstention, not an escalation loop.

Both candidate families support structured outputs; the 4.1 mini documentation lists the
dated snapshot. [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini),
[GPT-4o mini](https://developers.openai.com/api/docs/models/gpt-4o-mini)

Structured Outputs constrain schema, not factual accuracy. Explicitly handle refusals,
incomplete responses and semantic validation failures. Do not accept unknown IDs merely
because the result parses. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)

The repository pins `openai==1.12.0`. Before implementing modern typed parsing, select and
pin a compatible SDK release, and run all existing scorer/chat/cache adapter tests. Preserve
the legacy calls while adding the S3 adapter; do not combine S3 with an unrelated whole-app API
migration. If choosing Responses, extend the offline cache adapter first: it currently wraps
Chat Completions and embeddings only (`backend/evals/llm_cache.py:1`).

Fresh articles use ordinary async requests with bounded concurrency, per-call timeouts and
explicit output budgets. Historical backfill may use provider Batch API, which offers a 50%
discount and a 24-hour completion window; that window is unsuitable as the freshness path
for breaking news. Match outputs by unique request ID and fingerprint, not output order.
[Batch API](https://developers.openai.com/api/docs/guides/batch)

Treat every article as untrusted data. The extraction model has no tools, browsing, database
access, secrets, or reader profile. Article instructions cannot choose system prompts, enums,
entity IDs or retry behavior. Separate articles into independent requests initially; grouping
25 unrelated articles amplifies cross-article contamination and partial-output failure risk.

### Vocabulary and entity linking

Use a versioned, reviewed subset of IPTC Media Topics as the broad hierarchy, extended with
Daily-owned IDs for useful narrower concepts. IPTC supplies a maintained news taxonomy and
multilingual labels; it does not supply Daily's trained classifier or comprehensive local
entities. [IPTC Media Topics](https://iptc.org/standards/media-topics/)

Ship topic definitions with positive/negative examples and parent mappings. Begin with a
bounded vocabulary that can fit the classification context. If later using candidate-topic
retrieval, measure its recall separately and retain `other`/unknown so the shortlist cannot
silently censor emerging subjects. Never coerce a new concept into the nearest familiar label.

Entity recognition and entity linking are distinct steps. Maintain canonical Daily IDs,
aliases by language/script, types and disambiguating metadata in PostgreSQL. Resolve against
candidate records; a model may choose a supplied candidate or abstain, but cannot invent an
external ID. Ambiguous mentions remain unresolved with their evidence. New entities enter a
provisional registry with provenance and correction history; do not merge them by normalized
name alone. Optional reviewed external mappings can be added later without changing Daily IDs.

Places need hierarchy and role, not just strings. Do not infer event location from the outlet's
headquarters. Test Cyrillic/Latin aliases, transliteration, mixed-language names, and identical
city names. Initial supported languages must be declared from measured slices; the product's
global ambition does not make an English-only benchmark sufficient.

## 6. Schema and lifecycle

Names are proposed. Use additive, explicit migrations with validation; do not put index
backfills or corpus recarding in API startup. Normalized indexed child tables can be introduced
for S6 entity/topic lookup where actual queries need them; the immutable card remains JSONB.

| Storage | Required responsibilities |
|---|---|
| `articles.semantic_revision`, `analysis_eligibility_generation` | Monotonic semantic-input revision and evidence-eligibility generation, independent of native-display policy version. |
| `understanding_recipes` | Immutable schema/prompt/taxonomy/linker/preprocessor/model/dimension settings, hash, and promotion state. |
| `article_understanding_jobs` | Unique article/revision/recipe/stage, input hash, state, lease token/expiry, attempts, retry-at, deadline, reason, priority and usage reservation. |
| `article_understanding_results` | Immutable validated result and evidence manifest, article/revision/recipe/hash, stage, provider request metadata and actual usage. |
| `article_understanding_current` | One current projection per article and enabled recipe, including shadow recipes; facet/vector substates and compatible result references. Serving-recipe promotion is a separate setting. |
| `story_clusters`, `story_memberships` | Persistent IDs, representatives, membership confidence/evidence, versions and merge/split history. |
| `understanding_outbox` | Transactional change/revocation events, idempotent consumer keys and retention/checkpoint tracking. |
| Topic/entity/place registry tables | Versioned definitions, aliases, hierarchy and auditable resolutions/corrections. |

Foreign keys must enforce article/result ownership. Uniqueness must prevent duplicate result
publication for the same stage/revision/recipe. Add bounded queue scans and an index on ready
vectors for one compatible embedding space. Preserve artifact text only under S2 retention;
do not build a second permanent body store in S3. Deletion/tombstones invalidate current
results and jobs and prevent an old callback from recreating them. Historical metadata and
cluster aliases need a declared retention policy; replays needing old text use frozen eval
assets with their own permitted retention, not an accidental production archive.

Lifecycle:

1. **Register input.** All metadata writers and S2 artifact-selection changes atomically bump
   `semantic_revision` and schedule work when semantic input changes. Inventory global/per-user
   upserts, extraction completion, backfill and correction paths. Use a database trigger or
   equivalent shared transaction primitive to cover these writers; test it directly. Compute
   the deterministic input hash from exact normalized inputs and evidence identities. A bounded
   reconciliation sweep repairs missed scheduling, including pre-migration rows. A new immutable
   recipe/taxonomy/linker version explicitly enqueues the retained target population through a
   resumable rollout cursor, even if article text has not changed. Analysis-evidence revocation
   or provenance correction increments `analysis_eligibility_generation`, invalidates affected
   projections and memberships, and schedules a new permitted evidence bundle if one exists.
   A native-display-only policy change does not itself require recarding.
2. **Schedule fairly.** Two queues/classes: recent arrivals and historical backfill, with reserved
   capacity for each and per-source fairness. Stable order by priority, due time and ID; no
   unordered `LIMIT 50`. Distinguish ingest-to-ready latency from publisher-to-ingest latency.
3. **Claim.** Use `SKIP LOCKED`, a fresh unguessable lease token, attempt increment, and a deadline
   in a short committed transaction. Reap expired leases, including a crash during the final
   permitted attempt. A job cannot remain `running` forever at the attempt limit.
4. **Compute.** Release the transaction/connection before network work. Facets and embeddings
   are independently recoverable stages over the same frozen input. Cache successful stage
   results; retrying the other stage does not buy the first result again. Cluster work follows
   only compatible evidence/results. No user-specific work is introduced here.
5. **Validate.** Check article/request identity, schema, finite/bounded values, allowed vocabulary,
   evidence spans, supplied entity candidates, input hash and refusal/completion status. A schema
   failure or wrong ID cannot become an empty “successful” card.
6. **Publish.** In one short transaction, lock article before job, then current projection and
   cluster rows in a documented total order. CAS against current semantic revision, recipe and
   lease token/expiry and current analysis-eligibility generation. The recipe must remain enabled
   for computation; it need not be promoted for serving, so shadow results can persist. Insert
   validated immutable results, update compatible current references, and append an outbox event
   atomically. Stale, deleted or revoked input cannot publish.
7. **Consume.** Replay outbox events idempotently. Current readers verify revision/recipe when
   loading data even if an invalidation event is delayed, including evidence-eligibility generation
   and the serving-recipe selection. Consumers cannot combine a new card with an old-model vector
   or an old cached explanation.

Claiming only a job row must not subsequently acquire its article lock in that transaction;
that would invert the completion lock order. For a multi-article cluster mutation, discover
affected IDs first, acquire article locks in sorted order, then jobs/projections/clusters in
the agreed order, revalidate membership versions and retry on conflict. Keep external work
outside this transaction. Document the order alongside S2's article-before-job invariant.

States: `pending`, `running`, `retry_wait`, `ready`, `insufficient`, `unsupported`,
`failed_terminal`, `superseded`, `revoked`. `ready` still carries an evidence tier and field
abstentions. An independently ready vector can support a measured fallback when facets are
pending; absence of facets is not `commercial=no` and cannot bypass hard user exclusions.

Start with a configurable bounded attempt policy (for example five attempts per stage within
24 hours), exponential backoff with jitter and provider `Retry-After`. Treat authentication or
quota exhaustion as a provider-wide circuit condition, not thousands of separate hot retries.
Refusals/unsupported input have explicit outcomes; bounded validation repair is separately
metered. Reopening terminal work requires new input/recipe or an audited replay action.

Exactly-once provider execution is not promised: a worker can crash after the provider bills
but before persisting its response. Guarantee idempotent publication, meter duplicate attempts,
and reconcile provider batch IDs when available. Reserve expected maximum spend atomically
before submitting concurrent calls; reconcile actual tokens afterward. An ambiguous timeout
keeps a conservative reservation until settled. A post-response counter alone is not a hard cap.

## 7. Story grouping without destroying useful news

Keep three identities distinct: canonical document identity (S1/S2), coverage of the same
specific development (S3), and the broader evolving event/storyline (S4). A war includes many
important developments. Grouping them all for duplicate suppression would hide updates the
reader needs. A wire report reprinted by eight sites is also not eight independent confirmations.

For v1, each usable article starts as a stable singleton. Retrieve candidate story clusters
from a bounded recent window using vectors and resolved entity/place/time hints. Use a
configurable, evaluated window with explicit handling for unknown dates, late arrivals and
long-running stories; an arbitrary 36-hour cutoff is not a truth rule.

Require compatible actors/action/object, time and location evidence, plus a margin over the
next plausible cluster. Missing evidence means abstain/singleton. Compare with a stable
representative and several central members, not just any member; one bridging article cannot
merge two unrelated developments through transitivity. Roundups/live blogs may describe
several events: store multiple supported hints and avoid forced single-event deduplication.

Select thresholds on development data and freeze them before held-out evaluation. Start with
conservative grouping and measure false merges separately from missed merges. Do not carry
the prototype's 0.55/0.62 cosine values into production without this calibration.

Membership is revisable independently of expensive facet extraction. Support retraction,
reassignment, cluster split and merge with versioned redirects/history. Cluster summaries and
centroids must remove superseded/revoked members. Preserve seen article IDs and the assignment
version observed by a reader; a later split cannot cause an unrelated new development to be
treated as already read. Source ownership/syndication identity from S1 travels with memberships
for S4 breadth accounting. Do not use unknown ownership as affirmative source independence.

Initial singletons are a safe fallback, not proof clustering works: require same-development
recall as well as precision. A classifier that never joins anything cannot pass the cluster gate.

## 8. Consumer boundary and user-visible behavior

S3 adds internal data and observability first. Its shadow phase does not replace current feed
ranking or repair the source-join gate incidentally. S6/S7 adoption must explicitly change
candidate generation, hard exclusions, scoring, diversity and cached explanations with S0
replay. Keep display eligibility independent of every new editorial feature.

Expose one internal loader returning the compatible card/vector/assignment with typed
missing/stale outcomes. Migrate semantic search and chat to it before disabling the legacy
embedding writer. Dual-run in separate columns/tables during shadow, compare results and then
cut over; do not let old and new workers race to update the same vector.

For later feed integration, record the understanding and cluster revision used for scores and
reasons. Reject an in-flight feed build if any decision-critical input was revoked or changed;
enqueue a bounded rebuild and preserve explicit degraded behavior. Invalidation must account
for candidate-set changes as well as articles already in a cached feed: an outbox cursor/feed
epoch or retrieval generation prevents a newly understood missing story waiting indefinitely.

S3 failure must not erase a feed, synthesize an explanation, mislabel publisher text, or hide all
source-web stories. A stale result may remain in audit history but cannot drive current hard
exclusions or attribution. With no current understanding, retain the existing bounded fallback
and explicit quality telemetry. Whether that fallback is acceptable for release remains an
S0/S6/S7 quality decision, not an unconditional S3 guarantee.

## 9. Proof required before promotion

These are proposed acceptance targets, not achieved results. Final promotion depends on
adequate sample sizes, declared supported slices, and measured infrastructure capacity.

Build article-level labels in addition to persona relevance labels. Start with at least 600
distinct articles across dates, regions, source types, languages and evidence tiers, with
separate development and held-out portions. Add labeled same/different-development pairs and
cluster groups. Split by story and publisher where feasible so syndicated copies cannot leak
between tuning and test. Expand samples until critical-rate confidence intervals are useful;
600 overall does not validate every language or a sub-1% error claim.

Record label provenance (`human`, `agent`, `model`) and adjudicated disagreements honestly.
Use existing S0 labels to seed hard cases, not as ready-made facet ground truth. An independent
review must assess ambiguous entities, commercial reporting versus promotion, and false merges.

| Gate | Proposed promotion requirement |
|---|---|
| Integrity | Zero accepted wrong-article evidence, stale publications, mixed vector spaces, private-text leaks or hostile-instruction escapes in contract/adversarial tests. |
| Kind/topics | Kind macro-F1 >=0.90; primary-topic precision >=0.95 and recall >=0.90 on supported evidence/language slices. Publish per-class counts. |
| Entity/place resolution | Precision >=0.98 among resolved mentions and recall >=0.90 among adjudicated resolvable mentions; report unresolved coverage separately. |
| Promotion detection | Precision >=0.99 for auto-suppressed promotional content, recall >=0.95 on labeled promos; separately report legitimate reporting falsely suppressed. |
| Evidence grounding | All accepted references resolve to the exact input; independently reviewed unsupported assertions <=1%, with a 95% interval and denominators. |
| Story grouping | Pairwise precision >=0.98 and recall >=0.90, plus B-cubed precision/recall and merge/split error reports. No catastrophic cross-event merges in the adversarial suite. |
| ANN | Recall@50 >=0.98 against exact search on identical filtered data; report latency, underfill, and difficult rare-language/time slices. |
| Lifecycle | Every retained article has a state; no unbounded leases/retries; fault tests prove deletion/revision/policy fences and restart recovery. |
| Freshness | Initial target >=99% of supported usable new inputs reach ready within 5 minutes at forecast load; report all-input coverage and terminal rates alongside this subset. |
| Throughput | Sustain 2x forecast ingestion without unbounded queue age; prove backfill cannot starve fresh or niche sources. |
| Product regression | Replay all frozen S0 snapshots with the actual adopted consumer path; no new regressions, and preserve the named pre-existing failures until fixed. |
| Cost | Measured cost per 1,000 accepted revisions, retry/escalation share and projected monthly ceiling meet the chosen operating budget. |

Metric estimates below target block promotion. If a critical precision claim is underpowered,
collect more labels or keep its destructive consumer action disabled. Include abstentions in
coverage metrics: perfect precision obtained by resolving nothing is a failure. Freshness SLOs
must also report availability incidents; do not exclude provider outages from the published
all-input service picture merely to keep the ready percentage green.

Required negative-path tests:

- Same-body headline/summary correction; extractor/body upgrade while a model call is pending;
  article deletion and evidence revocation; taxonomy/linker/model change during execution.
- Duplicate enqueue, concurrent claims, lease expiry, stale completion, crash on the final
  attempt, outbox delivery twice, lost invalidation, deadlock and bounded reconciliation.
- Timeout, disconnect after billing, 429, quota/auth error, refusal, truncated JSON, unknown
  enum/ID, missing/duplicate response, nonfinite/zero/wrong-dimension vector, budget exhaustion.
- Prompt injection, copied instructions, negation, allegations, satire, mixed scripts,
  transliteration, namesakes, changed entities, thin headlines and unrelated cross-source text.
- Same topic/different event; same event/different wording; yearly repeated events; wire
  syndication; multi-event roundups; shuffled arrival order; bridge articles; late reports;
  revoked cluster members; concurrent merge/split and downstream seen-state preservation.
- Shadow/live recipe coexistence; delayed old API worker; current card with stale score;
  recovered backlog; empty ready feed; source-web article without native content.

Use real PostgreSQL integration tests for claims, CAS, constraints and locking; fake connections
cannot prove concurrency correctness. Use provider fixtures for failure injection and cached
real model outputs for quality replay. Pin requests, snapshots, pricing tables and recipe IDs;
return the same stored vector precision on cold and warm cache paths. No live model calls in CI.

## 10. Cost and capacity, with explicit assumptions

S3 cost scales with **unique analyzed revisions**, not users. Suppose each revision averages
1,000 input tokens, 250 output tokens, and a 600-token embedding. At documented standard prices
of $0.15/$0.60 per million input/output tokens for 4o mini, $0.40/$1.60 for 4.1 mini, and
$0.02 per million embedding tokens, arithmetic gives:

| New revisions/day | 4o mini + embedding, 30 days | 4.1 mini + embedding, 30 days |
|---|---:|---:|
| 3,500 | $32.76 | $85.26 |
| 20,000 | $187.20 | $487.20 |
| 50,000 | $468.00 | $1,218.00 |

These are illustrations, not measurements or a quote. Input includes the amortized prompt,
taxonomy and evidence; if that cannot fit 1,000 tokens the estimate increases. Excluded:
retries, model escalation, reprocessing, extra vectors, linking calls, provider tools, database,
worker and index storage, source acquisition, and reader-specific S4–S10 work. Backfill Batch
discounts must not be applied to the live path. Prices verified from the linked model pages
above and [embedding model pricing](https://developers.openai.com/api/docs/models/text-embedding-3-small).

Formula: `30 * revisions_per_day * (input_tokens * input_price + output_tokens * output_price
+ embedding_tokens * embedding_price) / 1_000_000`, plus measured additional stages/attempts.
Set the production spending ceiling after measuring this distribution; do not hardcode $31
because a previous document tied it to reader count.

At 50,000/day, average arrival is about 0.58 articles/second, before bursts/corrections. Size
concurrency from measured provider p95 latency, requests/minute and tokens/minute limits, with
headroom; a semaphore of six is not a capacity proof. At 14-day retention this example retains
700,000 vectors: float32 payload alone is about 4.3 GB decimal before indexes, rows and history.
Measure actual database/index size before committing the deployment's memory/disk budget.

## 11. Implementation sequence and production gates

Implement and review these as bounded batches. Checkboxes deliberately remain open: this
analysis did not implement them.

- [ ] **A — Contract and ruler.** Add typed input/card/result schemas, vocabulary snapshot,
  input hashing, adversarial article/pair labels and an `understanding` S0 runner. Inventory
  metadata writers and consumers; freeze acceptance criteria before tuning.
- [ ] **B — Durable lifecycle.** Add additive migrations, semantic-revision scheduling, per-stage
  jobs/results/current projection, reaper, usage reservation, outbox and a supervised worker.
  Prove real-PostgreSQL concurrency and fault recovery with fake provider responses.
- [ ] **C — Model bake-off.** Add the strict-output provider adapter and tokenizer, compatible
  pinned SDK, cache adapter, evidence validator, entity/place linking and vector validation.
  Warm bounded development and held-out evaluation sets; choose model/recipe by the gates.
- [ ] **D — Conservative story grouping.** Add persistent assignments and a calibrated candidate
  verifier, singleton/multi-event outcomes, reconciliation and merge/split history. Pass
  precision and recall gates; keep event gravity/reader novelty in their later systems.
- [ ] **E — Shadow production.** Verify deployed S1/S2 schema/build/acquisition contracts first.
  Review migration dry-run counts, back up, deploy additive schema and separate disabled
  worker/consumer flags, then enable a capped recent-article shadow cohort. S1 expansion waits.
- [ ] **F — Backfill and operational proof.** Backfill a bounded recent window, then enlarge
  through checkpoints. Run revision/delete/lease/circuit/cost canaries, inspect per-source and
  per-language errors, and prove p95/p99 latency and queue recovery. Enable constraints and
  build indexes with a production-safe migration plan; verify server extension capabilities.
- [ ] **G — Controlled consumer adoption.** Migrate search/chat with exact semantic comparisons,
  then hand the validated S3 loader and readiness events to S6/S7. Add card/cluster revision
  fencing to all adopted caches and build paths. Retire the old embedding writer only after
  its consumers have cut over and rollback is proven.

Suggested module ownership: `understanding_contract.py`, `understanding_repository.py`,
`understanding_worker.py`, `understanding_provider.py`, `entity_linker.py`, `story_clustering.py`;
versioned resources under `backend/app/data/understanding/`; migrations and resumable backfill
under `backend/scripts/`; evaluation adapters under `backend/evals/`. Reuse the connection pool,
provider/cache conventions and S2 artifact references; avoid expanding `main.py` into the pipeline.

Use separate flags for worker execution, active recipe, and consumer adoption. Rollback first
disables S3 consumers, then stops/limits new submissions; do not drop additive tables or erase
completed evidence. Revert to the old consumer path or previous compatible recipe only after
checking input currency. A prior card for an older body is not a valid rollback result for a
corrected article. Ensure old-worker callbacks fail publication after a recipe is disabled.

Require a canary covering at least 72 hours including a weekend/quiet period and a real burst
or controlled load replay, with enough examples in every promoted slice; elapsed time alone
does not establish quality. Observe end-to-end visible delivery separately when S6/S7 activate.
Production acceptance requires a build SHA, migration version, promoted recipe, model IDs,
population counts, latency/quality/cost report and rollback evidence. A green unit suite is not
a production claim.

## 12. Verification performed for this analysis

- Read the system map, prior architecture/S1/S2 audits, active checklist and S0 documentation;
  inspected the production code paths and retained the distinction between code and deployment.
- Independent read-only audits examined embedding/provenance/lifecycle consumers and
  evaluation/clustering boundaries. A final specification review identified two contract gaps;
  the document now separates shadow computation from serving promotion and explicitly schedules
  recipe upgrades and unchanged-text evidence revocations.
- Verified relevant API, model, vector-index, taxonomy and queue behavior against the official
  sources linked above. No provider quality or account availability was inferred from those docs.
- Ran `EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/test_global_events.py
  backend/tests/test_main_loops.py backend/tests/test_article_content_contract.py -q`:
  **58 passed, 4 subtests passed**. These existing tests support the audit context; they do not
  test the proposed S3 system or establish that the full backend/S0 suite is green.

The completed deliverable is this analysis and execution plan. The first implementation batch
is A, followed by B; production activation remains gated by the actual S1/S2 deployment state.
