# S7 Ranking — implementation status

2026-09-09. Repository implementation; **not deployed or activated**. Existing S1–S6 and
unrelated iOS/workspace changes were preserved. No hosted database or paid provider was used.

## Implemented

- `ranking_contract.py`: strict recipes, full-candidate identity binding, graded relevance,
  explicit abstention, confirmed intent attribution and stable base ordering.
- `ranking_service.py`: current permission-appropriate evidence, bounded provider scheduling,
  separate connection-owned database phases, build fencing and fresh publication.
- `ranking_provider.py`: async HTTP transport, strict structured output/ID/quote validation,
  token ceilings, no retries, two-operation process limit and defensive copying.
- `ranking_repository.py` / `ranking_schema.sql`: approved configuration epochs, leased claims,
  global/account spend reservations, idempotent settlement, overrun shutdown and atomic envelopes.
- `ranking_events.py`: minimal S8 adapter independently authorizes S4 representatives and
  current canonical reader policies. S6 locks the bounded union of ordinary/event dependencies.
  Only the final edition receives reader/event receipts under one request ID.
- Canonical feedback stores semantic hashes, learning revision, recipe, evidence/content stamp
  and final position. Reused intent IDs with changed meaning cannot inherit attribution.
  Passive telemetry remains non-learning; legacy receipts do not prove intent relevance.
- Feed build/refresh use S7 only when enabled. GET is provider-free and preserves the published
  order after reauthorization. Chat/briefing can reuse only ordinary stories from that edition.
  Background ranking is separately opt-in. No S7 failure falls back to legacy acceptance.
- `evals/ranking.py`: actual-candidate graded metrics, abstention/label coverage, slices and
  separate conditional versus full-pool recall. Unknown truth has no invented denominator.
- Offline tests, opt-in disposable PostgreSQL tests, required CI jobs, explicit management CLI
  and an example recipe. Startup does not install/approve/enable S7.

## Deliberate limits

The default semantic path **abstains** for personalized candidates when no provider is enabled.
Generic readers get neutral, policy-authorized news. Central-identity acceptance is separately
declared and disabled in the example recipe. There is no unmeasured lexical acceptance band,
forced filler or claim of “perfect” relevance.

The pinned model snapshot and stored pricing establish an executable transport/accounting
contract, not a winning model choice. A separately authorized benchmark must establish its
precision/coverage/cost trade-off before activation. Changing model/pricing/rubric requires an
explicit implementation and new recipe approval, not silently accepting an arbitrary model name.

Shadow is provider-free in this implementation. A paid shadow experiment is not implemented
or implicitly enabled. No full S8 diversity redesign, learned ranker or new iOS presentation
was included. Stored results expire within the S6 validity window (at most 15 minutes), sooner
for S4 expiry. Dependency changes return `needs_build`; they never rerank on GET.

Receipts prove server delivery, not visual exposure. Cancellation can leave uncertain provider
spend reserved; this deliberately reduces remaining allowance rather than risk overspending.
Database timeout cleanup retains ownership of its worker/connection until it actually ends.

## Verification and remaining release gates

Offline verification (2026-09-09):

- Focused S7 plus S6 handoff: **308 passed, 53 subtests passed**.
- Full backend regression: **1,602 passed, 122 skipped, 235 subtests passed**; the same
  **three pre-existing S0 quality-gate failures** remain (`followup_recall_mean`,
  `never_rate_mean`, `event_delivery_mean`, legacy `prod-llm` / `2026-09-02`).
- All ten opt-in S7 PostgreSQL tests remain unrun without an explicit disposable database.
- Python compilation, `git diff --check`, and management CLI dry-run passed.
- Logs: `.context/s7-focused-tests-final.log` and `.context/s7-full-tests-final.log`.

The final added wrong-account-before-scoring case is included in the focused count; the
full-suite run was already collected before that case was added. No gates were loosened.
Real SQL concurrency tests are opt-in and required in CI, but have **not** been executed
against a database in this session.
Mocked transaction tests are not proof of live PostgreSQL locking or deployment compatibility.

Before activation, separately authorize and complete:

1. Additive S5 receipt/schema upgrades plus S6/S7 schema/index installation; run the required
   disposable PostgreSQL suites and validate production schema compatibility/lock behavior.
2. Independent frozen graded labels and recipe-bound holdout evaluation, including prompt
   injection/qualifiers, source/language/evidence slices, uncertainty and precision vs coverage.
3. Measured retrieval/ranking/publication latency and cost under the declared workload.
4. Explicit reader cohort, approved recipe, spend limits, rollout observation and rollback check.

Do not loosen the existing S0 legacy quality gates or treat fake-provider fixtures as human
semantic truth. No live-quality, latency or cost-saving claim follows from unit-test success.

## Operator entry points

From `backend/`, these commands are dry-run only and do not connect to a database:

```sh
venv/bin/python scripts/manage_s7_ranking.py install
venv/bin/python scripts/manage_s7_ranking.py configure --recipe-file ranking.recipe.example.json
```

Actual operations require `--apply --database-env <explicit-environment-variable-name>`.
Do not add those switches until authorized. Installation defaults to zero spend and disabled
serving. Configuration flags are explicit (`--approve`, `--serve`, `--provider`, `--daily-usd`,
`--account-daily-usd`); both database and environment gates must permit the requested operation.
Serving requires S5 and S6 enabled. Environment defaults remain:

```text
S7_SHADOW_ENABLED=false
S7_SERVING_ENABLED=false
S7_PROVIDER_ENABLED=false
S7_BACKGROUND_ENABLED=false
```

Disabling database serving bumps the configuration epoch and invalidates old claims/results.
`prune` bounds maintenance batches; account deletion removes private state but preserves the
global spend total. Disabling only the provider stops new semantic calls, not an already
authorized ordinary cache. Global spend reservations never share S3 budget rows.
