# S6 Retrieval — analysis and challenged architecture

2026-09-07. Read-only runtime audit of `mmarufov/sydney-v7`, including uncommitted S1–S5
work. This describes the checkout, not the deployed database or app. Implementation is
not authorized by this analysis request. Companion: [implementation plan](s6-implementation-plan.md).

## Verdict

**S6 has a useful S5-era seed, but does not yet reliably produce a few hundred eligible,
well-attributed candidates for ranking.** The largest gaps are selection order, evidence
availability, candidate budgets and the S7 handoff. Adding an approximate vector index alone
would not fix them and could make candidate loss harder to explain.

Keep PostgreSQL, native full-text indexes and pgvector. First make lexical and identity
retrieval correct and observable, add compatible cached dense retrieval, then adopt ANN
(approximate nearest-neighbor search) only when measurements justify its speed/recall tradeoff.
No separate search service, trained user tower or new model is justified by current evidence.

Retrieval should maximize relevant **opportunities**, not certify relevance or final feed mix.
It can search only Daily's ingested, eligible corpus. It cannot recover reporting absent from
S1, guarantee all important news worldwide, or keep fixed recall at fixed K under unlimited
corpus growth. Pool coverage, retrieval recall, ranking quality and delivery are separate metrics.

## Actual execution paths

```text
Legacy flag-off:
  active user sources -> source-linked articles -> recent windows 300/600/1200
    -> deterministic prefilter (usually 100) -> legacy LLM scoring -> final feed

S5 flag-on, currently default-off:
  global articles -> each active intent:
    lexical 40 + [identity 40 + cached semantic 40, only if semantic enabled]
      -> per-intent fusion -> ID-dedup/round-robin <=300
        -> current reader policy -> learned scheduling -> final limit (usually 50)
          -> serialize/relevant=True -> optional S4 -> final reader check

Required S6 boundary:
  global eligible pool -> bounded per-intent legs -> validate/filter/refill
    -> attributed CandidateBatch <=300 -> S7 judgment -> S8/S4 composition -> S9
```

Legacy windows and early stopping are in `backend/app/services/feed_service.py:356`,
with source association filtering at line 505. S5 bypass is at line 145;
its candidate builder is `reader_retrieval.py:168`, immediate delivery at
`reader_integration.py:100`. These are different paths, not one uniformly deployed retriever.

## Verified findings

| Priority | Finding and user impact | Evidence |
|---|---|---|
| P1 | Policies run after per-leg/global caps, without refill. A blocked first page can hide allowed matches farther down. | `reader_retrieval.py:109`, `:175`, `:212`; `reader_integration.py:113` |
| P1 | One interest gets at most 40 lexical candidates; unused budget is not redistributed from the corpus. | `reader_retrieval.py:202`: `lexical_rows(conn, intent)` uses default 40 |
| P1 | Resolved entity/place matching requires semantic activation even though it needs no vector. | `reader_retrieval.py:186`: `if threshold is not None`; `:203`: `if recipe` |
| P1 | Policy inputs are missing: facet validation does not populate normalized topic/entity/place/sector IDs. Conservative subject policies can withhold even known-safe reporting. | `reader_retrieval.py:137`–`:143`; `reader_compiler.py:63`: `values = article.get(policy["scope"] + "_ids")` |
| P1 | S5 returns candidates as relevant stories, not a distinct S6 result for S7. A vector or lexical match is not a judgment. | `reader_integration.py:127`: `item.update(relevant=True, relevance_score=...)` |
| P1 | Repeated per-row current-card checks can cause thousands of DB reads at 24 interests. No shared candidate validation cache or end-to-end work deadline. | `reader_retrieval.py:137`; `understanding_consumers.py:63`; `understanding_repository.py:344` |
| P2 | Fusion loses per-intent/per-leg evidence: the first row wins, later semantic stamps can disappear, aggregate max is not sufficient attribution. | `reader_retrieval.py:53`: `articles.setdefault(identifier, dict(row))`; `:81`–`:99` |
| P2 | Every word of query plus qualifiers must occur in title/summary. Grammar, aliases, inflection and translated wording reduce recall. | `reader_worker.py:41`; `reader_retrieval.py:114`–`:120` |
| P2 | Legacy widening stops after enough non-excluded rows, not enough relevant candidates, while source joins exclude global-pool matches. | `feed_service.py:397`–`:407`, `:1044`–`:1069`, `:505`–`:512` |
| P2 | Current exact-search setting applies to the whole transaction; repeated `a.*` hydration and absence of a measured workload compound cost. | `reader_retrieval.py:21`, `:200`; `understanding_consumers.py:46` |
| P2 | Fixed 14-day lower bound has no corresponding frozen upper bound; future timestamps and different statement snapshots are not a replay contract. | `reader_retrieval.py:114`, `:132`, `:181`; S3 `semantic_rows` |

These are code-confirmed findings, not claims about observed production frequency or latency.
The single-interest cap is an architectural restriction, not proof that every interest deserves
300 stories. Bounded retrieval may legitimately return fewer than K; it must explain why.

### Important prerequisites, not imaginary fields

The S3 facet schema supplies topics, entities, places, abstentions and evidence references
(`understanding_contract.py:200` onward). It does **not** currently provide a universal sector
or detected-language classification. `build_evidence` reads optional article language, but
production schema inspection did not find the same article-language column that some test
fixtures create. A plan cannot fix this by silently filling missing evidence with empty lists.

Topic/entity/place evidence can be projected from a current, validated card, preserving
abstention/truncation/ambiguity. Sector mapping and language provenance need an explicit supported
contract or remain unavailable. Unknown does not mean known-not-matching. Reader language codes
also require an explicit base-language/regional matching rule, not accidental string equality.

`manage_s5_reader.py:28` already provides concurrent lexical GIN installation. Its existence is
not deployment evidence. Check index definition **and validity**; `IF NOT EXISTS` alone does not
repair an invalid index left by an interrupted concurrent build. The legacy HNSW index on
`articles.embedding` is not an index over the current S3 versioned-result geometry.

## Reproductions and checks

Ran `.context/s6-diagnostics.py` with fakes only:

- Top 300 forbidden rows, then 50 allowed matches: cap-then-policy returned **0**, despite
  **50** eligible rows beyond the cap. This reproduces the ordering defect, not a corpus benchmark.
- A subject policy and absent facet field returned **0**; an explicit known-empty list returned
  **1**. This demonstrates why evidence completeness is consequential, not permission to invent it.
- One 40-row lexical leg with requested K=300 returned **40**.

Focused existing offline tests: **106 passed** (`.context/s6-baseline-tests.log`): reader vectors,
reader integration, understanding consumers, feed service and source pipeline. These tests do
not measure SQL semantics, real lock behavior, filtered ANN recall or production latency.
No paid requests, database connections, local server, runtime edits or deployment were made.

## Technology decisions, challenged

**PostgreSQL full-text search first.** Native GIN supports the existing lexical index path.
Keep a script-preserving name/phrase leg; add language-specific analysis only for explicitly
supported language evidence. `plainto_tsquery` joins terms with AND; replacing it with
`websearch_to_tsquery` does not automatically provide useful synonym recall. Never interpolate
user text into raw query syntax. [PostgreSQL text-search controls](https://www.postgresql.org/docs/current/textsearch-controls.html),
[index guidance](https://www.postgresql.org/docs/current/textsearch-indexes.html).

**Cached dense search complements, not replaces, exact names.** Reuse S5 vectors and the complete
S3 embedding-space identity. No per-feed embedding generation. Missing vectors are a declared
capability loss with eligible lexical/identity fallback. pgvector supports exact and approximate
search; filtered approximate search can underfill, and iterative scans require server extension
support and bounded settings. Validate the extension version separately from the Python package.
[pgvector documentation](https://github.com/pgvector/pgvector#filtering).

**RRF is a starting baseline, not truth.** Reciprocal-rank fusion avoids adding incomparable
raw lexical and cosine scores. Preserve underlying ranks/distances and test it against best-leg
and calibrated alternatives. Correlated strict/relaxed lexical variants are one family, not
independent votes. Neither an RRF score nor a cosine threshold certifies a qualified interest.
[Original RRF paper](https://cormack.uwaterloo.ca/cormack/cormacksigir09-rrf.pdf),
[fusion comparison research](https://arxiv.org/abs/2210.11934).

**Do not add infrastructure before measuring the current database.** Exact dense search is an
evaluation baseline, not necessarily the serving choice for every scale. HNSW over accumulated
historical S3 results may waste work on obsolete revisions; require measured eligible-index
selectivity. If native current-result filtering cannot meet the declared workload, a fenced
current-search projection is a separate evidence-triggered optimization, not a second authority.
Elasticsearch/OpenSearch, a trained retriever, query-expansion LLM and broad fuzzy search remain
deferred until measured failures justify their operational cost.

**A transaction is not automatically one stable snapshot.** Default Read Committed can observe
different state on successive statements. Use a bounded read snapshot for retrieval and a separate
fresh publication validation; holding an old snapshot does not make later revocations safe.
[PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html).

**Concurrency must be real and bounded.** Multiple tasks on one psycopg connection do not make
its SQL execute in parallel. Batch queries and hydration before adding connections per interest.
Keep synchronous DB work off the async request loop and preserve exclusive connection ownership.
[Psycopg concurrency guidance](https://www.psycopg.org/psycopg3/docs/advanced/async.html).

## Independent challenge incorporated

Separate retrieval-trace and evaluation agents examined the checkout; the evaluation agent then
challenged the proposed design. Evidence: `.context/s6-retrieval-trace.md` and
`.context/s6-evaluation-audit.md`. Corrections incorporated into the plan:

1. Fresh publication must validate reader state **and** current article/evidence/recipe stamps.
2. A global raw-ID limit is not a DB scan limit; separately cap rows returned, query rounds,
   connection wait, validation and elapsed time. Reserve fair work before a broad interest runs.
3. A timed-out SQL transaction cannot run fallback until rollback. Cancellation must release or
   discard its connection safely; a canceled Python await alone does not stop synchronous SQL.
4. The exact evaluation oracle must not share serving truncation shortcuts.
5. Missing S3 evidence stays visible in overall retrieval-quality accounting. Ordinary permitted
   publisher metadata need not wait for S3; revoked derived evidence must never be reused.
6. Expiry can change without a reader revision; recheck at publication time.
7. Separate every matched intent from the intent charged for allocation; UUID order is not taste.

## Correct success criteria

The old map's recall≥0.95 and p95<200ms are **unverified objectives**, not current capability.
The plan defines a frozen in-pool denominator, known-positive recall, per-interest coverage,
conditional ANN-versus-exact recall and a named load envelope. Corpus-wide completeness is not
established by pooled labels or ten evaluation personas. Cases with more than K distinct positives
have a real ceiling: report raw recall and capacity, rather than redefining the denominator to K.

Highest-value portfolio artifact: one reproducible report showing exactly which relevant stories
survived each stage, what every leg added, why misses occurred, and the latency/recall cost of ANN.
That is stronger technical evidence than another database logo or a claim of universal precision.
