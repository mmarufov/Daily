# S7 Ranking — analysis and challenge

2026-09-08. Source: current dirty `mmarufov/sydney-v7` checkout, HEAD `b667985`.
This is analysis/planning, not runtime implementation or production verification.
Existing S1–S6 changes are included in the inspected tree, not all committed in HEAD.

## Conclusion

S7 needs a real decision boundary, not another blend of similarity scores. Today there are
two materially different paths: legacy LLM scoring with unsafe normalization/fallbacks, and
default-off S5 retrieval that labels retained candidates relevant without semantic judgment.
S6 supplies a safer candidate interface, but its injected scorer is not an installed ranker.

Keep S7 responsible for evidenced reader relevance, acceptance/abstention and base order.
S8 owns final edition positions, diversity, duplicate representatives and S4 event insertion.
The integration must preserve judgments and authorize the actual final selection once.

## Current paths

```text
Legacy build -> source-linked shortlist (default 100; ceiling 200)
             -> batches of 40 -> positional LLM output -> heuristic blend/gate
             -> save scored rows -> dedupe/role composition -> final limit
Legacy GET   -> scored-row cache -> relevance filter -> final limit
S5 enabled  -> 300 retrieval candidates -> policy/learning -> limit -> relevant=True
S6          -> typed CandidateBatch -> injected scorer + fresh authorization
             -> no installed production S7; serving flag intentionally returns 503
```

Entry points: `feed_service.py:138`, `user_source_pipeline.py:281,308`,
`reader_integration.py:103`, `reader_retrieval.py:655`, `main.py:2159`.
Chat uses feed service too; background refresh uses the pipeline directly. A feed-route-only
cutover would leave inconsistent ranking and uncontrolled background/provider behavior.

## Confirmed findings

| Priority | Finding and evidence | Consequence |
|---|---|---|
| P1 | `openai_service.py:638-663` maps arrays positionally and coerces booleans/numbers | Reordered verdicts can attach to the wrong story; string `false` becomes true; NaN clamps to 1 |
| P1 | `feed_service.py:1197-1201` converts unavailable/incomplete scoring into lexical acceptance | An outage changes the relevance policy without an explicit degraded verdict |
| P1 | `feed_service.py:1215-1224` sets model relevance true for a pinned mention | Incidental mentions can override model rejection |
| P1 | `reader_integration.py:103-138` marks retained S5 candidates relevant | Retrieval rank is presented as editorial judgment |
| P1 | `retrieval_contract.py:56-113` has raw article dicts, reader hash but no reader, only boolean verdict | S6 is not a safe provider payload or complete S7 context; missing abstention/reason/confirmed intent |
| P1 | `openai_service.py:617-676` retries timed-out synchronous thread calls | Caller timeout does not terminate real work; retries can overlap, with unbounded actual cost relative to logs |
| P1 | `feed_service.py:1589-1647` deletes then inserts cache rows; no enclosing transaction | Autocommit readers can see mixed/partial builds; timestamps cannot fence profile edits during model work |
| P1 | Cache saved before assembly, then read in score order (`feed_service.py:230-237,1514,1548`; `user_source_pipeline.py:294-305`) | Refresh and GET can show different order/membership without new input |
| P1 | `feed_service.py:535-555` uses legacy analysis_text/content rather than current S3 evidence | Ranking can reason over unversioned or revoked evidence if this path is reused |
| P1 | `reader_feedback.py:19-28,96-113` stores retrieval intent IDs; learning keyed by intent UUID | Attribution is not semantic confirmation; reusing an intent UUID for a new topic can inherit old learning |
| P2 | `feed_service.py:1175-1255` uses hand-chosen blend/boost/threshold; content multiplier affects acceptance | A polished irrelevant article can outrank a thin relevant one; numbers are not probabilities |
| P2 | `feed_service.py:1259-1276` puts every category overflow back | Claimed category cap is a no-op; fix belongs primarily to S8 |
| P2 | `user_source_pipeline.py:337-350` derives quality_met from article count | Quantity does not certify ranking precision or reader value |

Additional S6/S8 handoff gaps:

- S6 matches prove *why retrieved*, not why relevant. Do not teach S5 from all retrieval IDs.
- `rank_candidate_batch` is synchronous; an async provider needs a deliberate async boundary,
  not blocking under a transaction or nested event loop.
- Current authorization sorts accepted results by score/ID. S8 positions must be an explicit
  validated subset/order, not accidentally reordered at final authorization.
- S5 writes receipts before S4 composition, and finalization writes again
  (`reader_integration.py:84-100,119-122`; `event_integration.py:151-165`). S7 adoption must
  remove preliminary receipts on its new path and persist only actual final-delivery candidates.
- `reader_repository.py:145-161` detects changed intent semantics for embeddings, but does not
  fence learned weights by the same semantic hash. Retain priority-only learning, invalidate
  changed-topic learning and reject old receipt attribution to a reused UUID.

## Offline evidence

161 focused existing tests passed (feed service, source pipeline, reader integration,
S6 handoff/evaluation, eval runners/metrics), recorded in `.context/s7-baseline-tests.log`.
These establish existing behavior, not S7 quality. No paid calls or database server started.

Independent ranking audit reproduced with an in-memory provider/pure functions:

- provider `relevant="false", score="NaN"` normalized to `True, 1.0`;
- an incidental AI-mention story accepted at 0.8 on scoring-unavailable fallback;
- model false/0.2 became accepted at 0.47975 after a pinned mention;
- 9 tech + 1 sports unchanged by the advertised category-diversity helper;
- fresh role order differed from cached score order on the same 12 articles.

Detailed trace: `.context/s7-ranking-audit.md`. The prior full-suite evidence remains the
S6 run: 1,342 passing, 112 skipped, three known S0 quality subtest failures. That suite was
not rerun or claimed green for this analysis.

## Challenge the old system-map prescription

1. **“One model call” is not the optimization target.** One giant prompt can cost more and
   silently truncate or confuse items. Bound input/output tokens, actual attempts, dollars,
   wall time and abstention loss. Batch size is a measured parameter, not a quality guarantee.
2. **“Only the uncertain 15%” has no evidence yet.** High lexical/dense score is not calibrated
   relevance. Start with a transparent baseline; allow non-model accept/reject bands only
   when independently labeled data supports their false-positive/false-negative rates.
3. **“Train LightGBM once there are clicks” is insufficient.** Exposure, rank, identity,
   semantic-intent revision and delayed feedback matter; a nonclick is not an irrelevant label.
   Current passive telemetry should remain outside automatic learning.
4. **“LLM score is interest probability” is false.** Use a graded rubric and separate finite
   utility score. Structured output validates shape, not the truth of a relevance judgment.
5. **“All profiles in one string” loses explicit priorities/qualifiers.** Use typed intent IDs,
   exact qualifier semantics and per-intent judgments; unknown qualifications must not become
   broad positive matches. Do not assume list position represents user priority.
6. **S7 cannot repair missing S1/S6 candidates.** Measure conditional ranking and whole-pipeline
   quality separately. Never insert missing positives into the candidate set to flatter results.

## Technology choice

Recommend Python/Pydantic for strict contracts and pure versioned ranking, PostgreSQL for
account-scoped receipts/budgets/cache identity, and the existing async HTTP transport pattern
for an optional schema-constrained LLM judge. No new search infrastructure or mandatory GPU.
Reuse S3 evidence construction, S5 canonical intent semantics, S6 candidate/freshness fences.
Reuse patterns, not S3 job tables for unrelated per-reader ranking spend.

A cross-encoder is a legitimate challenger, not automatically the solution: it scores a
query/document pair, but must be tested on Daily's qualified multi-interest judgments,
languages, cost and hosting limits. At 24 interests × 300 candidates a naive design has
7,200 pairs per build. Its model score also needs task-specific acceptance calibration.
LightGBM/LambdaMART is deferred until trusted exposure-aware graded training data exists.

Primary technical references checked 2026-09-08:

- [Sentence Transformers retrieve/rerank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html): supports two-stage cross-encoder comparison, not automatic personalized-news correctness.
- [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs): strict schema plus explicit refusal/error handling; still allows semantic mistakes.
- [OpenAI Python retry behavior](https://github.com/openai/openai-python#retries): explicit retry ownership is necessary. Installed legacy code must be inspected separately from current SDK docs.
- [Reranking evaluator](https://www.sbert.net/docs/package_reference/cross_encoder/evaluation.html): beware default insertion of positives; evaluate actual retrieved documents without positive injection.
- [LightGBM ranking parameters](https://lightgbm.readthedocs.io/en/latest/Parameters.html): grouped ranking labels/gains and positional-bias facilities do not replace valid training data.
- [News-recommendation bias research](https://arxiv.org/abs/2410.02897): motivates order/framing/identity bias tests; does not establish Daily-specific error rates.

Next: [implementation plan](s7-implementation-plan.md). Implementation awaits user approval.
