# S7 Ranking — implementation plan

2026-09-08. **Implementation authorized; repository implementation completed 2026-09-09.**
See [implementation status and release gates](s7-implementation-status.md).
Grounded in [the audit](s7-ranking-audit.md), current S6 contracts and independent ranking,
evaluation and boundary challenges. No paid quality run, deployment or activation implied.

## 1. Outcome and ownership

For every S6 candidate, produce an explainable, identity-bound relevance decision and base
ranking utility. Never lose an item through positional parsing, hidden recapping or provider
failure. A candidate can be accepted, rejected or unknown; unknown is not irrelevant truth.

```text
S5 canonical reader + semantic-fenced learned signals
                 + S6 full CandidateBatch (<=300)
                 + current, bounded, permission-appropriate S3/S2 evidence
     -> immutable RankingRequest
     -> cheap features / validated deterministic decisions
     -> optional budgeted semantic judgment for unresolved items
     -> RankBatch: decision for EVERY input ID + base ordered accepted IDs
     -> S8 chooses actual positions/representatives + independently validated S4 items
     -> one fresh authorization + atomic publication + final-only delivery receipts
```

S7 does not impose final topic quotas or silently reserve world-critical slots. It provides
judgments/features for S8; S4 significance is not personal relevance. No new iOS redesign,
search cluster, fine-tuned model, click-through optimization or full S8 rewrite in this task.
The small S8 publication adapter needed to safely consume S7 is explicitly in scope.

## 2. Contract first

Add `ranking_contract.py`; keep the existing S6 verdict adapter for compatibility.

**RankingRequest** binds authenticated account, request ID, normalized ReaderProfile and
profile hash, generation/revision/learning_revision, per-intent semantic hashes, frozen
as_of/expiry, S6 request/recipe, S3 cohort, ranking recipe and whole candidate-set digest.
Validate the supplied reader against S6's hash/stamp. It is an internal server-built object,
never a client assertion of policy or evidence. Own defensive immutable/copy boundaries.

Each evidence pack contains article ID and article/evidence hashes, provenance tier, bounded
publisher title/summary, selected permitted analysis fields, validated central facets, explicit
missing/truncated/abstained state and retrieval provenance. Do not send raw `a.*`, cross-source
text as publisher text, reader credentials, browsing history or unrelated profile context.
Analysis-revoked articles can remain S2-readable but cannot enter a provider or derived analysis
route; retain only separately approved ordinary metadata/deterministic behavior or abstain.
The plan does not assume display permission grants external analysis permission.

**ArticleJudgment** contains article ID, input fingerprint, decision accept/reject/abstain,
reason code, bounded grounded explanation, confirmed intent IDs, and per-assessed-intent grade
0=unrelated, 1=incidental/weak, 2=substantive, 3=strong direct usefulness. Unknown is separate,
not grade 0. Qualifiers: satisfied/contradicted/unknown with evidence. Grades are judgments,
not probabilities. Reasons reference source evidence or explicit reader rules, not invented facts.

**RankBatch** has exactly one decision per input ID, status complete/degraded/stale, base ordered
accepted IDs, recipe/context hashes, diagnostics, actual usage and unmet coverage. A provider
sub-batch must match its exact ID set: duplicates/foreign/missing IDs, wrong hashes, nonfinite
values, coercions and unsupported reasons fail that sub-batch; other completed batches can
survive. Missing judgments receive explicit abstentions. Never salvage by array position.

The S6 boolean/score conversion is an explicit internal compatibility view only: accept=true;
reject/abstain=false for publication while the richer RankBatch retains the distinction.
An async rank entry point must await the scorer outside database transactions.

## 3. Relevance and order are different decisions

Implement pure, recipe-versioned feature extraction once for all <=300 candidates. Preserve
all candidates and retrieval provenance; do not call legacy prefilter/source-scoped loaders.
Use explicit intent priority rather than list position, canonical source identity rather than
display name, frozen time for freshness and semantic-hash-fenced learned signals.

Hard policy/current evidence checks precede admission and repeat at publication. Positive
feedback, source familiarity, extraction quality, popularity, entity mentions or freshness
cannot turn rejected/unknown relevance into acceptance. Missing full text is not rejection.

Baseline behavior:

- Explicitly generic cold-start mode has its own recipe and neutral reason, still policy-gated.
- Simple current central-identity matches without unresolved qualifiers may be a narrow
  deterministic on-topic rule only under a declared tested capability. Central identity alone
  does not establish urgency, trustworthiness or “must see.” Unsupported cases abstain.
- Literal/dense/label matches alone are features, not validated accept/reject bands. Until a
  measured classifier exists, unresolved semantic cases require the optional judge or abstain.
- Use a lexicographic initial order: confirmed relevance tier, explicit intent priority with
  bounded learned adjustment, then frozen freshness and stable article-ID tie-break. Document
  aggregation (strongest confirmed intent, not a sum rewarding keyword/intent count). Keep
  detailed features; do not present the derived order as a calibrated probability.
- Duplicate representation/diversity/intent allocation belong to S8 and operate only on accepted
  eligible candidates. No forced low-quality fill to reach 50; explicit all-rejected is valid.

Calibration later may replace rules/ordering with tested bands or a cross-encoder. Freeze
thresholds before holdout evaluation; report abstention coverage and band errors. No guessed
15% middle band and no untested 0.35 acceptance threshold.

## 4. Bounded semantic provider, zero-spend default

Add a narrow `ranking_provider.py` using existing `httpx.AsyncClient`/Pydantic/tiktoken patterns
from S3. Avoid a broad SDK migration: installed OpenAI 1.12.0 is not current documentation.
Pin a supported model snapshot in a ranking recipe; choose among existing supported economical
models only after a separately approved benchmark. No assertion that newest/largest is best.

Generate wire schema from strict models, explicitly handle refusal, incomplete finish status,
oversized output, invalid UTF/JSON, NaN, duplicate keys, unknown IDs and malformed usage.
Treat article and profile text as quoted data, not instructions. No tools/web access in judgment.
Validate evidence quotes against the frozen pack; verification proves the quote exists, not
that the conclusion follows. Test prompt injection, order, batching and unrelated-item effects.

Proposed safety ceilings, configurable downward; these are limits, not latency/quality claims:

- <=300 total candidate decisions; <=50 candidates per provider request, token-packed, not padded;
- <=12k input / 6k output tokens per attempt, <=6 attempts and <=72k input / 36k output per build;
- <=20 seconds ranking wall time including admission/packing/provider waits, <=2 active provider
  operations per process; separate global/per-account budget admission across app processes;
- default provider calls and dollar allowance zero; configured model pricing and positive budget
  required before any real call. Reject unknown model/pricing rather than invent a cost estimate.

The token packer can fit fewer than 50. Fairly schedule unresolved candidates across active
interests; overflow/deadline/budget exhaustion yields explicit unjudged IDs and degraded coverage,
not omitted candidates or automatic acceptance. Do not include every long profile in every
prompt unnecessarily; preserve relevant qualifiers and negative constraints when reducing context.

One retry owner. Prefer no automatic request retries initially; any enabled retry must acquire
another reservation and fit the same total deadline/attempt cap. A timeout may mean the provider
already charged: keep ambiguous spend reserved, do not free it on client cancellation. Track
actual tokens/request IDs when known. Fail closed if the budget store is unavailable.
No DB connection held during model awaits; no to_thread timeout loop around sync provider calls.

Use a small S7-owned PostgreSQL recipe/control and reservation ledger; reuse S3 transaction,
reservation/settlement patterns but never its article-job semantics or budget rows. Reserve in
a short transaction; finalize outcomes idempotently; stale work may settle cost but not publish.
Bound retention and account deletion cleanup. No new durable queue required for initial S7.

## 5. Caching, freshness and feedback

Do not extend the legacy timestamp-only feed cache. Add an account-scoped immutable ranking
result cache keyed by generation/revision/learningrevision + ranking recipe + reader hash +
candidate-set/evidence fingerprints. Store a whole RankBatch atomically, never delete/insert
partial result rows. Include all abstentions/reasons and expiry; do not indefinitely cache
transient failures. A cache hit revalidates current reader/config/article evidence before reuse.

For the minimal S8 adapter, persist the exact final ordered ID list and its S4 dependencies/
expiry separately from base scores in that same published result envelope. Distinguish ranking
cache from delivered edition; GET must not reconstruct different positions from relevance scores.
Only explicit build/refresh may call the provider. GET/cache reads are provider-free. Background
refresh has a separate explicit enablement and budget; chat/briefing reuse safe published results,
not secretly call the legacy paid scorer. Unsupported/deleted/changed input returns needs_build.

Admit duplicate builds by account + reader/recipe epoch using a short leased build claim in the
same result store, with fencing token. No model work under row locks; stale claim owners cannot
overwrite a newer publication. Busy readers receive a current safe result or explicit building,
not queued unbounded paid work. Reset/deletion invalidates claims/caches atomically.

Extend S5 receipts with learning revision, ranking recipe, final position, content/evidence stamp,
confirmed intent IDs and their semantic hashes. Only the final selected set gets receipts under
one final request ID. Receipt means server delivery, not proof of visual exposure. Passive events
must join own account/request/article receipts before any future use as training signals.
Keep passive events non-learning in this implementation.

Fence learned signals by intent semantic hash. Same UUID with changed query/qualifier/entity must
not inherit old weights; priority-only edits may preserve them. Old receipts without semantic
proof may retain exact-article feedback behavior, but cannot update a newly defined intent.
No feedback from an incidental retrieval match unless S7 confirmed relevance to that intent.

## 6. Publication and consumer cutover

Keep legacy serving unchanged until the new entire path is ready. S7 enabled requires canonical
S5, S6 retrieval and its database gates; it never routes back to an unchecked legacy scorer.
Flags separate shadow, provider, serving and background work. Shadow is provider-free by default;
paid shadow is a separate explicit budgeted experiment, not implied by enabling observation.

Order: load reader/claim -> retrieve -> prepare bounded evidence -> release connection -> rank
-> read/compose S8/S4 without receipts -> fresh authorization -> atomic cache + final-only receipts.
Reuse S6 fencing, but add rank recipe/claim and exact selected-ID/order validation. Confirmed
intent IDs must belong to active reader semantics and accepted judgments. S4-only candidates use
their independent significance/policy authorization and attribution, not forged S7 decisions.
An alternate article chosen as an S4 representative must itself be authorized, not inherit an
old article's verdict by event membership.

Check lock order against S2/S3/S4/S5 writers with real PostgreSQL concurrency tests. No provider
or await under publication locks. Recheck expiry before commit; no mutation after final fence.
Bounded retry for stale builds must re-admit cost; never unbounded automatic recomputation.

## 7. Evaluation and acceptance

Add `evals/ranking.py` using the actual RankBatch and frozen S6 candidates. Keep two reports:
conditional ranking given actual retrieved candidates, and end-to-end S6/S7/S8 quality with
upstream misses retained. Graded nDCG@10/@50, acceptance precision/recall, prohibited rate,
unjudged/abstention coverage, per-intent opportunity coverage, false-accept/false-reject bands,
freshness, actual cost, latency and source/language/evidence-tier slices. Empty denominators are
undefined, not perfect. Unknown labels remain unknown. Include policy-safe high-recall baselines.

Current S0 production-feed-v1 results test legacy flows; no current S7 benchmark exists. Retain
the three known failing S0 quality gates rather than loosening them. Existing model/agent labels
are useful seeds, not independent human truth. Freeze development/calibration/holdout partitions
by story/event/time/source with reader-level checks; adjudicate ambiguous labels independently.
Do not use the same model's output as both judge truth and evaluated prediction. No missing-positive
injection into candidate sets; explicit ideal oracle reports must be labeled separately.

Deterministic acceptance requires zero identity/policy/stale-publication violations in the named
tests and every input receiving a decision. Semantic promotion requires predeclared holdout
thresholds, precision-vs-coverage tradeoff, per-slice sample sizes/uncertainty, and cost/latency
envelope. Choose numerical semantic targets after establishing label rubric/base rates, before
looking at holdout results. No fixed quality or cost-saving claim is currently supported.

Minimum test map:

```text
request -> wrong account/profile/hash/recipe/expiry -> reject before spend
        -> exact full candidate set -> bounded evidence + all-item decisions
provider -> reordered -> ID mapping succeeds
         -> missing/extra/duplicate/coerced/nonfinite/refused/truncated -> abstain batch
         -> timeout/cancel/429/ambiguous charge -> bounded work + reserved spend
rank     -> incidental/qualified/contradictory/multilingual -> graded evidence tests
         -> freshness/learning/quality change -> cannot promote rejected relevance
publish  -> edit/reset/delete/recipe/artifact/lease race -> stale result rejected
         -> S4 representative/expiry change -> independent final authorization
         -> GET/refresh/pagination -> exact stable published order, final-only receipts
feedback -> wrong receipt/reused intent UUID/old generation -> no misattributed learning
```

## 8. Implementation batches

| Batch | Files / change | Exit evidence |
|---|---|---|
| A: contract + evaluator | new ranking_contract.py, evals/ranking.py, fixtures/tests; adapt retrieval_contract.py only at compatibility boundary | all 300 IDs, explicit unknown, graded denominators and raw recall |
| B: evidence + baseline | new ranking_service.py; reuse understanding_repository.py/reader_compiler.py; reader_retrieval.py typed async boundary | no raw a.* to provider, qualifier/cold-start behavior, stable priority/rank |
| C: provider + controls | new ranking_provider.py, ranking_schema.sql, ranking_repository.py; reuse transport/lease/budget patterns | fake transport negatives, usage accounting, no new submissions after cancellation; ambiguous remote spend stays reserved |
| D: learning + freshness | reader_feedback.py/schema, reader_repository.py, rank repository | intent-semantic mutation/receipt fences; atomic result/claim CAS; cache replay |
| E: serving adapter | feed_service.py, user_source_pipeline.py, reader_integration.py, event_integration.py, main.py; reuse retrieval_runtime ownership | all consumer paths consistent; no preliminary receipts or network under locks |
| F: release evidence | ranking tests incl opt-in PostgreSQL, CI, management commands, env/status docs | mandatory no-skip deterministic/SQL CI; default-off gates; frozen quality report before activation |

This crosses more than eight files because the existing boundary spans retrieval, learning,
cache and delivery. Keep runtime behavior in three small modules (service, provider, repository)
plus a data-only contract, not a ranking framework or a
second authoritative reader store. Schema/control persistence is justified by multi-process spend
and stale-write safety, not speculative analytics infrastructure. Ship batches separately.

Repository implementation can finish with fake-provider and offline tests while live SQL,
model choice/calibration and activation stay explicit unpassed release gates. Paid evaluations
and production mutations require separate user authorization. Activation is not implied by repository completion.
