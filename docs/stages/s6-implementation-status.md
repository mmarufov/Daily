# S6 implementation status — 2026-09-07

Repository implementation is complete for the approved S6 candidate-stage scope.
It is **not production activation or proof of perfect relevance**. Existing S1–S5 and iOS
changes were preserved. No deployment, hosted database operation or paid provider call was made.

## Implemented

- `retrieval_contract.py`: strict private request/candidate/batch and ID-keyed ranking verdicts.
  Retrieval scores remain retrieval ranks, never relevance probabilities or feed acceptance.
- `reader_retrieval.py`: independent strict/label lexical, current central identity, optional
  compatible cached dense, and explicit generic cold-start legs. Global pool, not source membership.
  Eligibility precedes fair weighted allocation; duplicates retain every matching intent/leg.
  Three rounds, at most 300 candidates, 2,400 examined IDs and 7,200 returned leg rows.
- `understanding_repository.load_current_batch`: bounded batched article/artifact/current-result
  hydration using existing S3 evidence hashes and validators. Policy projection distinguishes
  missing, abstained, truncated, unresolved and known central subjects. No fabricated language
  or sector evidence. Analysis revocation does not automatically prohibit S2 source-only metadata.
- Read-only repeatable-read retrieval transactions on idle exclusively owned connections;
  per-leg savepoints, remaining-time SQL limits and explicit failures/shortfalls.
- `retrieval_runtime.py`: two admitted workers per process, no work queue, two-second caller
  deadline including connection wait, aggregate-only shadow diagnostics. Abandoned workers retain
  their slot/connection until actual cleanup; no unsafe cross-thread cancellation or early reuse.
  Shutdown drains safely; a subsequent lifespan cannot create more workers before old ones drain.
- Full-batch injected S7 scorer receives a defensive copy outside transactions. Exactly one finite,
  ID-keyed verdict per candidate is required. No silent legacy prefilter or 100-candidate recapping.
- `authorize_candidate_batch`: synchronous publication context fences account, reader generation,
  revision, learning revision, full profile, expiry, retrieval configuration, S3 recipe, article,
  selected artifact state, current result digests and hard policies. Shared locks protect fresh
  evidence through caller serialization/receipt writes. No provider/network work inside this context.
- Authenticated feed build/read/refresh invoke default-off shadow before final reader/S4 fences.
  Shadow creates no receipts, never changes response candidates and logs no profile/article data.
- `manage_s6_retrieval.py`: disconnected dry-run by default; explicit-target concurrent lexical,
  temporal, current-facet and S3-result HNSW index operations. Exact-definition/catalog validation;
  repairs only recognized invalid S6-owned indexes. Does not enable retrieval or ANN.
- `evals/retrieval.py`: actual CandidateBatch evaluation, raw known-positive/complete-corpus recall,
  capacity ceiling, unjudged coverage, per-interest/marginal-leg metrics and tie-aware ANN-vs-exact
  comparison. It does not relabel S0 final-feed evaluation as S6 recall.
- CI requires collected, non-skipped deterministic S6 tests and opt-in disposable PostgreSQL
  contracts. Environment example documents all S6 gates as false.

## Verification

Final offline verification:

- Focused S6 plus neighboring S3/S4/S5/feed contracts: **359 passed**.
- Full backend: **1,342 passed, 112 skipped, 182 subtests passed; three failed S0 quality subtests**.
  These are the already recorded 2026-09-02 `prod-llm` snapshot regressions:
  `followup_recall_mean`, `never_rate_mean`, `event_delivery_mean`. They were not weakened or
  relabeled as passing. The full backend suite is not green.
- S6 PostgreSQL suite: **15 collected, 15 skipped** without the explicit disposable DB setting.
  Includes actual lexical/keyset/snapshot/refill SQL, exact cosine ordering/settings restoration,
  current identity independent of dense activation and refusal of ANN without its managed index.
- Modified Python modules compile; `git diff --check` passes. All three management commands
  (`status`, `index`, `dense-index`) were verified in disconnected dry-run mode.

Commands used from `backend/`: `EVAL_OFFLINE=1 venv/bin/python -m pytest tests/ -q --tb=short`
and the focused retrieval, reader-vector/integration, understanding-consumer, feed-service,
user-source-pipeline and event-integration/endpoint modules. No test server was started.
Offline test evidence is kept in `.context/s6-focused-tests.log` and `.context/s6-full-tests.log`.
PostgreSQL contracts are collected but skip without explicit `S6_TEST_DATABASE_URL`;
`S6_TEST_DATABASE_REQUIRED=1` changes missing infrastructure into failure in CI.
No hosted SQL, query-plan benchmark or semantic quality report was produced.

## Activation/runbook

1. Keep `S6_SHADOW_ENABLED`, `S6_DENSE_ENABLED`, `S6_ANN_ENABLED` and `S6_SERVING_ENABLED=false`.
2. An operator first inspects the explicit production target and reviews schema/index readiness.
   `python scripts/manage_s6_retrieval.py status` and `... index` are disconnected previews.
   Only a separately authorized `--database-env NAME --apply` reads/mutates that named database.
   HNSW provisioning is separate (`dense-index`); never target legacy `articles.embedding`.
3. Run required SQL contracts, actual EXPLAIN plans, concurrent correction/publication races and
   the declared 10k/100k-row load envelope before rollout. Exact dense is the baseline/oracle;
   an ANN flag requires the valid matching S6 cosine index and iterative-scan-capable server.
4. Shadow requires installed S5 canonical profiles. Missing/review-needed readers report unavailable;
   shadow never auto-migrates them. Enable only after SQL correctness/capacity gates pass.
5. Dense needs compatible cached S5 vectors and explicit measured `S6_MIN_SIMILARITY`; no threshold
   is invented and no request generates embeddings. Missing vectors degrade, not erase lexical recall.
6. Review/install the actual S7 policy/cost/output adapter and S8 delivery/receipt integration before
   live cutover. Today `S6_SERVING_ENABLED=true` fails feed requests closed with 503, by design.
   The existing legacy/S5 feed remains the serving implementation while all new flags are false.
7. Roll shadow back by turning it off; canonical S5 policy enforcement remains unchanged.

## Honest remaining boundaries

- Language provenance and sector mapping are unsupported, with fail-closed policy-unknown results.
- Simple PostgreSQL FTS and bounded label expansion are not proven multilingual semantic recall.
- A two-second cooperative/SQL budget is not a p95<200ms performance result. Worker cleanup can
  outlast caller timeout; bounded admission prevents unbounded orphan work. Two Uvicorn processes
  each admit two workers. Database statement cancellation and rollback need real-server evidence.
- Recall≥0.95 and ANN recall≥0.98 are release targets, not measured accomplishments. Use independently
  judged frozen holdouts and an exhaustive exact oracle, not serving caps, to establish them.
- Publication must serialize/write receipts inside the synchronous authorization context; it cannot
  promise atomicity with bytes arriving on a remote device after the transaction ends.
- Private CandidateBatch is not a public API/cache format. No new cache, search cluster, model,
  automatic provider spend, iOS change or complete S7 rewrite was introduced.
