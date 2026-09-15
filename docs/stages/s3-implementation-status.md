# S3 implementation and verification — 2026-09-06

The guarded S3 backend is implemented. **The complete production acceptance plan is not
finished, and S3 is not enabled in production.** This separates tested lifecycle integrity
from unproven model accuracy and rollout readiness.

## Implemented

- Original-evidence selection, provenance checks, semantic fingerprints and strict private
  facet contracts. Reader display permission and analysis eligibility remain separate.
- Versioned PostgreSQL recipes, per-stage jobs/results, transactional scheduling, lease and
  deadline fences, corrections/revocation/deletion handling and exact-ID outbox receipts.
- Independent worker, bounded retries, fresh/backfill fairness, graceful cancellation,
  pre-request spend reservations and conservative ambiguous-charge accounting.
- Fixed-origin structured-output provider with pinned models, token/response limits,
  exact quote anchoring, supplied-candidate identity validation and 1,536-dimensional vectors.
  Abstention bookkeeping is derived from explicit unknown/empty outputs; unsupported
  assertions are never silently converted into successful classifications.
- Current-result search/chat adapters behind a disabled flag, conservative singleton-first
  membership and versioned corrections. The legacy embedding writer remains available.
- Explicit migration/backfill/status/revoke/pause/promotion controls, default-off worker
  configuration, fail-closed promotion checks and mandatory hosted PostgreSQL CI.
- Cached evaluation harness, a 600-item **unreviewed** queue and a durable USD 5 pilot cap.

Operational guide: `backend/app/data/understanding/OPERATIONS.md`.

## Verification

Final tested backend snapshot: `5d85e6c0ac918c3e02ccfdfa1ae4eb20a80ecb30` on
`codex/s3-verification-20260906`. The workspace branch and normal index were left intact;
only an isolated backend verification snapshot was pushed. No PR, merge or deploy occurred.

- [Hosted verification](https://github.com/mmarufov/Daily/actions/runs/34067704381):
  **348 passed, zero skipped/failed**, including 23 S3 and 19 S2 real PostgreSQL tests.
  Coverage includes concurrent claims/budgets, final-attempt recovery, stale publication,
  publication-transaction lease/deadline expiry rollback and late outbox commits.
- Focused offline suite: **306 passed, 102 subtests passed**.
- Complete offline suite: **573 passed, 47 skipped, 177 subtests passed; three known S0
  regression failures**. Database tests skipped locally were independently executed above.
  The three retained failures are unchanged from the recorded starting baseline:
  `followup_recall_mean` 0.1111 → 0.0397; `never_rate_mean` 0.2694 → 0.395;
  `event_delivery_mean` 0.25 → 0.15, on frozen snapshot `2026-09-02`.
  Baselines were not relaxed or replaced.
- Python compilation and diff whitespace validation passed. The final backend files match
  the hosted verification snapshot. iOS work was preserved, not changed by S3.

Private evidence: `.context/s3/final-offline-tests.log`, `final-offline-tests.xml`,
`hosted-final/s3-verification.xml`, `baseline-results.md` and the pilot files below.

## Live pilot findings

The final v3 pilot used 20 deterministic title/summary articles from the frozen corpus,
both classifier pins and one embedding call per article. Old corpus bodies have no verified
S2 provenance and were deliberately excluded. This is not a global/labeled quality sample.

| Candidate/stage | Structurally accepted | Rejected |
|---|---:|---:|
| gpt-4o-mini-2024-07-18 facets | 20/20 | 0 |
| gpt-4.1-mini-2025-04-14 facets | 14/20 | 5 missing evidenced event actors; 1 non-exact quote |
| text-embedding-3-small | 20/20 | 0 |

Earlier pilot revisions exposed rejected cards and missing abstention bookkeeping.
Moving offset calculation to server-side quote anchoring and deriving abstention bookkeeping improved
contract acceptance without weakening evidence validation. Historical generic errors do not
prove every earlier rejection had the same cause.

Aggregate accounting across **all** pilot iterations: **USD 0.09325732 known usage**, plus
**USD 0.01093920 reserved** for one interrupted request; maximum committed **USD 0.10419652**
against the authorized USD 5 cap. The reservation was not erased. No production daily budget
or larger benchmark budget was inferred. Results: `.context/s3/pilot-v3.json`; durable ledger:
`.context/s3/pilot-ledger/pilot-budget.json`.

The provisional default remains **unpromoted**. The 4.1-mini result fails even the operational
acceptance screen; 4o-mini is a promising benchmark candidate, not an accuracy winner.

## Gates that remain open

1. Independently adjudicate article/story labels, populate trusted entity/place candidates,
   declare supported slices and run the story-disjoint benchmark. The queue is not ground truth.
2. Select a recipe from labeled evidence; meet both false-merge and missed-merge targets.
   The default singleton-only policy intentionally cannot pass clustering recall.
3. Approve benchmark/production budgets, retention and load forecasts; verify exact-vs-filtered
   ANN recall, load and latency. The USD 5 pilot authorization does not cover production.
4. Complete S1/S2 production prerequisites and deploy through the reviewed migration/rollback
   sequence. Read-only inspection found release 95 with an April 13 image and `/readyz` returning
   404; repository changes are not evidence that those prerequisites are live.
5. Observe the required 72-hour shadow canary, then cut over search/chat and separately retire
   the legacy writer. Feed retrieval/ranking adoption belongs to S6/S7, not this S3 code pass.

Do not enable production or describe S3 as globally correct until these gates have evidence.
