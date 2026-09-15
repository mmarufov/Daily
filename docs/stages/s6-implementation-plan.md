# S6 Retrieval — implementation plan

2026-09-07. **Implementation authorized; repository work completed, release gates open.** Grounded in
[the audit](s6-retrieval-audit.md), two independent code audits and an additional design challenge.
The user subsequently authorized repository implementation. Deployment, hosted database
mutations, paid verification and live feed cutover remain separately gated.
Actual scope and evidence: [implementation status](s6-implementation-status.md).

## Outcome and scope

Produce **up to 300 distinct, currently eligible article candidates**, independently retrievable
for the reader's active interests, with complete retrieval provenance and honest shortfall reasons.
S7 decides relevance and final ordering; S8 decides edition composition. A relevant candidate
must not disappear just because a blocked source or popular interest used a raw query cap first.

Reuse PostgreSQL, S3 current artifacts, S5 state/policies/query vectors, and existing helpers.
Do not introduce a separate search cluster, new model, per-request model call, trained user tower,
second authoritative reader store or speculative cache. S1 source acquisition, a full S7 rewrite,
S4 event semantics, iOS redesign and production activation are not implementation prerequisites.
They remain explicit integration/release gates where applicable.

## 1. Freeze an internal contract before changing retrieval

Add small strict types in `backend/app/services/retrieval_contract.py`; evolve
`reader_retrieval.py` in place, not a competing retriever.

`RetrievalRequest` carries authenticated user scope, immutable reader generation/revision and
learning revision, normalized active intents, policy version, requested K (0–300), UTC `as_of`,
retrieval-recipe hash and a monotonic work deadline. Do not accept another user's ID or client
assertions of authoritative policy. Expired intents are removed at read time.

`CandidateBatch` carries:

- `request_id`, reader stamp, `as_of`, `valid_until`, retrieval recipe and S3 cohort/space IDs;
- `status`: complete/degraded/empty/stale; completion means configured search completed, not
  all relevant world news found;
- each candidate's article ID, source identity, article/content/evidence revisions, current
  eligibility evidence, `allocated_intent_id` and all `matched_intent_ids`;
- per-intent **per-leg** rank, raw distance/score, lexical query variant, identity evidence,
  query hash, applicable recipe and admission reason; never conflate these with S7 scores;
- diagnostics: requested/returned counts, leg availability, unique IDs examined, raw rows
  returned, rejection reasons, coverage per interest, rounds, elapsed/wait time and stop reason.

Leg outcomes: available, disabled, unsupported, missing_vector, missing_facets, exhausted,
budget_limited, timed_out or failed. An empty page and a timeout are different facts. Keep raw
profile text and evidence bodies out of logs; candidate attribution is private and account-scoped.
No new durable receipt system: only actually delivered items enter existing S5/S4 delivery receipts.

## 2. Define eligibility before quotas

Separate three concerns:

1. **Article/display eligibility:** S2 permitted native or original-source presentation, valid
   identity and allowed time horizon. Do not require full body or completed S3 for ordinary
   publisher metadata. Missing embeddings are not article ineligibility.
2. **Reader recommendation policy:** shared S5 article/publisher/literal/subject/language rules.
   Push equivalent safe predicates into SQL before LIMIT; retain the shared final check.
3. **Derived-evidence eligibility:** exact current S3 recipe, semantic revision, eligibility
   generation and recomputed input hash for every derived match. Never use revoked artifacts.

Extract a batch current-evidence loader alongside `understanding_repository.load_current`.
Reuse its evidence-building rules rather than rewriting hash semantics. Fetch narrow IDs/stamps
first; fetch article/artifact/card data once per unique ID per snapshot, in bounded batches.
Do not query membership for every row unless an enabled consumer needs it. Prove parity with
the existing single-item validator, including artifact edits that do not change article columns.

Project topic/entity/place fields only when their card proves the relevant evidence state.
Empty, absent, abstained, truncated and unresolved are distinct. Do not synthesize `sector_ids=[]`
or language from a URL/feed country. Explicit prerequisites:

- topic/entity/place central-versus-mentioned and negative-policy semantics must be documented;
- sector capability requires a reviewed deterministic mapping with its own version or stays
  unsupported and visibly policy-unknown;
- language filtering requires a migrated, provenance-bearing metadata/detection source plus
  regional-code matching rules. It cannot be claimed supported from test-only columns;
- unsupported hard policies remain fail-closed, with a diagnostic rather than a fake no-news result.

Avoid importing the legacy `content_quality>=0.4` prefilter as an unexplained new authority.
Define which source/analysis/display quality gates belong here and test source-only eligible
stories. Low editorial relevance belongs to S7, not an undocumented S6 SQL cutoff.

## 3. Independent retrieval legs

| Family | Initial behavior | Guardrail |
|---|---|---|
| Lexical | Original-script exact/name/phrase and qualified all-term match, native GIN | Query parameters, bounded text, deterministic parser version |
| Identity | Current resolved entity/place and supported topic IDs | Independent of dense flag/query-vector availability; no ambiguous-name guess |
| Dense | Cached S5 intent vector against compatible current S3 vectors | No request-path embedding; finite/dimension/recipe checks |
| Cold start | Explicitly generic, eligible recent pool when no active intents | No invented personalized reason, exposure is not relevance truth |

Start with existing strict lexical behavior as a comparison baseline, not the final multilingual
claim. Add bounded query variants using reviewed aliases and supported analyzer configurations.
Preserve the original qualified query; do not turn every word into OR or reinterpret free-text
qualifiers as hard structured policy. A relaxed match is a **candidate with unresolved qualifiers**,
not evidence that the full interest was satisfied. Keep lexical variants inside one family during
fusion. Fuzzy proper-name matching/automatic translation stays off until its ambiguity tests pass.

Freeze a bounded freshness policy: initial comparison keeps the existing 14-day corpus, with
recent and older-within-window opportunities separated in diagnostics. Use ingestion cutoff and
valid publication bounds at `as_of`; future timestamps follow an explicit quarantine/skew rule.
Any 30-day niche/context expansion is a separately configured/evaluated recipe, never silent.
An old article's new S4 development is not equivalent to blindly widening its publication date.

## 4. Bounded policy-aware refill and fair allocation

Do not slice to 300 and then discard policy failures. Each leg yields a bounded page of IDs;
validate and filter, fuse by intent, deduplicate, allocate, then refill deficits within a global
budget. Stable sort keys include article ID. Exact SQL pages use snapshot-local keyset cursors;
ANN uses bounded deeper search with seen-ID tracking, not a false stable OFFSET promise.

Provisional engineering defaults, to be benchmarked before release:

- K=300, at most 24 active intents (existing S5 bound);
- 2,400 **unique article IDs examined across the entire request**, not per leg/interest;
- separate cap of 7,200 returned leg rows to bound duplicates and provenance work;
- three rounds **total**, initial + two refill rounds; reserve fair initial work for all
  active interests before any broad interest consumes surplus;
- each interest may grow beyond 40 using redistributed capacity; raw page allocations cannot
  consume all budget on the first interest;
- provisional two-second total service deadline including connection acquisition, SQL,
  validation and any retry; this is a safety ceiling, not a latency target or verified capability.

These limits bound work, not completeness. Stop with an explicit diagnostic at budget/deadline.
SQL rows visited may exceed returned rows: additionally bound statements, ANN visited tuples and
lock waits; record actual query-plan work under load. Tune limits on training/validation data,
not the held-out quality set. Never fill K with arbitrary unrelated news to make counts green.

Allocation has two phases: give each nonempty intent an opportunity after policy/ID dedup,
then distribute remaining capacity by explicit priorities, bounded fairness and available hits.
If K is below the number of eligible distinct opportunities, state that universal coverage is
impossible and resolve deterministically. An article matching three intents has three matches
but consumes one slot; record which intent was charged. Do not assign that charge by UUID order.
Do not apply S10 learned weights here initially: keep the retrieval comparison independent of
learning and preserve the overlay for S7. This deliberately removes current S5 scheduling from
the candidate-generation boundary, without deleting reader learning.

Mandatory article-ID dedup; avoid title-hash or unverified semantic hard collapse. Current
verified story membership can support a separately evaluated soft duplicate-pressure cap with
bounded alternate representatives. If that cap harms rare-angle recall, leave it to S8.

## 5. Snapshot, cancellation and publication correctness

```text
authenticate + load reader
  -> bounded read-only repeatable snapshot
       -> capture S3 cohort / retrieve legs / batch validate / policy / refill
       -> CandidateBatch (not public authorization)
  -> leave read snapshot
  -> S7 work, if configured (never inside DB locks)
  -> fresh authorization transaction
       -> current reader + time/expiry + recipe + article/artifact stamps + S2 policy
       -> unchanged: delivery receipt / serialization
       -> changed: discard affected result or one bounded rebuild; otherwise stale/retry
```

Snapshot setup must precede its first data query on an exclusively owned connection; do not
change isolation inside a nested request transaction. `as_of` is a time boundary, not a persistent
database snapshot ID. Exact replay uses a frozen evaluation corpus. No lock is held over model
or outbound network work; retrieval itself makes none.

Fresh validation includes article deletion/correction, in-place artifact changes, S3 disable/
promotion, source/display policy, reader changes and intent/policy expiry without writes. A
reader-only guard is insufficient. Reuse lock ordering from existing writers; document and test
the full reader/control/recipe/article/artifact acquisition graph before introducing publication
locks. Select IDs in deterministic order, enforce short lock timeouts, and never acquire reader
locks while holding the long retrieval snapshot. If relevant writers cannot be fenced safely,
revalidate/restart rather than claim atomic publication. Define the authorization linearization
point explicitly; bytes already authorized or downloaded cannot be remotely recalled.

Use a bounded thread executor with a connection owned for the entire synchronous retrieval unit,
or a narrowly scoped async DB adapter if cancellation proves simpler. Do not share one connection
across tasks. A timed-out optional leg rolls back its savepoint before using validated fallback;
unrecoverable transaction failure rolls back the unit. Safe fallback still requires fresh
authorization. On timeout/cancellation, cancel SQL and wait for cleanup before returning the
connection; abandon/discard a damaged connection. Admission control must prevent abandoned worker
threads or 24-interest fan-out from exhausting the existing ten-connection application pool.

## 6. PostgreSQL-first index and performance plan

1. Reuse the S5 concurrent GIN command; check expression/configuration, validity and query-plan use.
   Install/repair indexes explicitly, never DDL on feed requests. Test interrupted concurrent build.
2. Inspect temporal filter selectivity and compatible B-tree/expression indexes against real plans.
   Avoid assuming separate `published_at` and `ingested_at` indexes optimize `COALESCE` automatically.
3. Batch identity/card joins; add a narrowly justified index on actual S3 base relations, not an
   ordinary view. No giant duplicated corpus projection initially.
4. Exact compatible dense search is the oracle and small-corpus serving baseline. Scope planner
   controls to dense queries so exact mode does not disable unrelated efficient lookups.
5. Evaluate HNSW cosine indexing on actual versioned embedding storage, with current recipe/
   revision eligibility applied and bounded iterative scans where supported. Check server extension
   version, geometry, SQL ordering and actual index use. Legacy `articles.embedding` is not a fallback.
6. If obsolete-result filtering overwhelms ANN, either retain measured exact serving at the supported
   scale or separately approve a current-only fenced search projection. Do not claim historical
   result indexing automatically solves growth. This decision is evidence-triggered, not hidden work.

Record hardware, PostgreSQL/extension version, active/history ratio, indexes, warm/cold state,
filter selectivity, concurrency, connection wait, SQL count/rows, validation time and p50/p95/p99.
Initial measured envelope: 10k and 100k eligible recent rows; 1/3/24 intents; concurrency 1/10;
0/50/95% rejection rates. 1m rows/concurrency 25 are stress characterization, not invented MVP
capacity. **p95<200ms** remains a retrieval-stage objective for a declared envelope. Report full
service latency including pool wait separately. Do not disguise a two-second timeout as speed.

## 7. S7 and rollout boundary

Expose the whole CandidateBatch to ranking without rerunning legacy source joins or lexical
prefilters. Do not change `_reader_score` into relevance probability or `relevant=True`.
Preserve per-candidate stamps through any ranker and validate again before delivery.

First integrate in deterministic/offline and default-off shadow mode. An ID-keyed legacy scorer
adapter may consume candidates for comparison, but it must not reinterpret canonical hard policy,
silently re-cap to 100 or introduce paid work during verification. The production S7 consumer
requires its own policy/cost/output-contract review before enabling S6 delivery. A repository S6
implementation can be complete while live cutover is intentionally gated; say which is complete.

S4 event candidates remain independently authorized at S8 with their own expiry and receipts.
Measure their contribution separately; they cannot conceal a poor S6 recall result. Public search
and chat may later reuse bounded retrieval helpers, but this task does not replace all such APIs.
Add separate shadow/serving/ANN flags with defaults off and an explicit retrieval recipe. Rollback
must retain canonical reader-policy enforcement; routing S5 users to an unchecked legacy feed is
not a safe rollback. No mobile deployment or model spend is implied by flag implementation.

## 8. Evaluation that measures the actual candidate stage

Add `backend/evals/retrieval.py` invoking the same candidate builder with a frozen corpus,
reader, timestamp, S3 artifacts and configuration. Do not relabel old S0 metrics as S6 results.

- **In-pool raw recall@300:** retrieved independently judged must-see IDs divided by all eligible
  must-see IDs in the frozen corpus. Missing/stale embeddings remain misses, not removed positives.
- **Known-positive recall:** explicitly named when labels come from pooled systems rather than
  exhaustively judged corpus. Unjudged is unknown, not negative. Include random residual judging
  so all compared retrievers cannot jointly hide their blind spots.
- **Conditional ANN recall:** compare against exact eligible vector neighbors with the same
  frozen geometry/filter, tie-aware. The evaluation oracle must not use serving raw caps/early exits.
- Per-interest and language/topic/source slices, oldest/newest reporting, freshness latency,
  minority opportunity coverage, policy-unknown rate, duplicate pressure, marginal contribution
  of each leg, and stage-by-stage loss IDs. Score final-feed relevance separately.
- No positives => undefined recall, not 100%. More than K positives => report the capacity ceiling
  and raw recall; never silently replace the denominator with K.

Proposed release objectives: zero prohibited/stale candidate publication in adversarial tests;
all named deterministic positive fixtures recovered within their configured capability/budget;
known-positive recall≥0.95 on a frozen supported holdout, with denominators and uncertainty;
ANN recall≥0.98 versus exact plus no material product-recall regression. These are **targets**,
not passed evidence. Split by story/time/source to prevent leakage; freeze labels/thresholds before
the holdout run. If targets fail, preserve the failure and adjust the design or supported envelope.

## 9. File-scoped implementation batches and exit gates

| Batch | Main files | Exit evidence |
|---|---|---|
| A: contract/oracle | new `retrieval_contract.py`, `evals/retrieval.py`, retrieval fixtures/tests | strict CandidateBatch; frozen candidate-stage denominator; baseline reproducible |
| B: evidence and policy | `understanding_repository.py`, `reader_retrieval.py`, `reader_compiler.py` | batched/single validation parity; known/unknown projection; no missing-vector article veto |
| C: legs/refill/fusion | `reader_retrieval.py`, `test_reader_vectors.py`, new retrieval tests | beyond-first-page recovery, one/24-interest budgets, overlap attribution, bounded stop reasons |
| D: SQL/cancellation | `understanding_consumers.py`, S5 management/index tooling, opt-in PostgreSQL tests | real FTS/filter/plan semantics; cancellation cleanup; migration/index retry; named load envelope |
| E: consumer/shadow | `reader_integration.py`, thin feed/pipeline adapters, `reader_feedback.py` attribution | full S6→S7 batch preserved; no final relevance assertion; existing S4/policy regression tests |
| F: release controls | backend CI, `.env.example`, status/runbook | required non-skipped SQL/contract gates; explicit default-off flags and safe rollback |

One small contract module and one evaluator are justified; multiple new services are not. This
touches more than eight files because it replaces a cross-system boundary and adds real tests.
Split batches, preserve existing dirty changes and avoid unrelated feed/ranker cleanup. An index
or current-search projection optimization cannot bypass baseline correctness gates.

Minimum test map:

```text
request -> malformed/unauthorized/review-needed -> reject before retrieval
        -> reader valid
           -> empty/expired intents -> honest generic fallback
           -> strict/identity/dense available or independently unavailable
              -> first page forbidden/stale/duplicate -> validate + refill
              -> budget/deadline/DB failure -> rollback + explicit partial/failure
              -> union -> per-intent attribution -> <=K unique eligible candidates
                 -> concurrent edit/reset/promotion/artifact correction/expiry
                    -> reject stale result, bounded retry, no stale receipts
                 -> S7 -> final authorization -> permitted S2 presentation
```

Fixtures include multilingual/decomposed Unicode, AI versus airline, Apple company versus fruit,
ambiguous places, entity mentioned versus aboutness, qualified synonym without literal overlap,
language/sector unknown, rank-41 allowed match, one broad/two rare interests, multi-intent overlap,
syndication flood, future timestamp, missing vector, mixed recipe, failed dense leg after successful
lexical, account deletion, stale retry and provider spy asserting zero calls.

Hosted PostgreSQL tests use the existing isolated-disposable-database pattern, not live user tables
or a developer localhost service. Current CI has a disposable SQL job; add explicit S6 collection/
no-skip checks and pin supported extension behavior. Execute hosted tests/load only when authorized.
Offline analysis tests are not substitutes for these gates.

## Decisions and approval boundary

Recommended implementation scope: A–F repository work, PostgreSQL-first, no paid providers,
default-off runtime. Proposed numeric budgets and the 14-day baseline are adjustable engineering
defaults, not factual guarantees. Keep language/sector capabilities explicitly unknown until their
upstream evidence contracts exist; do not solve them by guessing inside retrieval.

Still required before live delivery: supported-language/time-horizon product envelope, authoritative
language/sector coverage where required, hosted SQL/performance evidence, held-out quality results,
S7 consumer readiness, operational budgets and separate deployment approval. None prevents writing
the bounded implementation, but all prevent claiming globally correct or fully activated retrieval.

Analysis validation: 106 focused offline tests passed; deterministic diagnostics reproduce
post-cap policy starvation and per-interest underfill. Independent challenge corrections are
listed in the audit. The interactive existing-plan skill was stopped as a workflow mismatch;
this document is a new repository-backed plan, not a completed interactive skill review.
