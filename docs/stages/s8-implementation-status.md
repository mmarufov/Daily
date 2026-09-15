# S8 implementation status

2026-09-09. Repository implementation on `mmarufov/sydney-v7`, including the pre-existing
dirty S1–S7 worktree. **Default-off; not deployed or approved for production activation.**
No paid calls, hosted database operations, commits or pushes were performed.

## Implemented

- `assembly_contract.py` / `assembly_service.py`: strict full-pool inputs, own accepted
  relevance, explicit unknown identity, grade-protected priority-weighted interest scheduling,
  representative-aware verified deduplication, soft publisher/topic/streak targets with
  recorded relaxations, critical cap, full-pool refill and one disposition per opportunity.
- `assembly_repository.py` / `assembly_schema.sql`: current approved S3 membership evidence,
  bounded history, control epochs and separate reader-edition history revisions. Parent
  article locks fence absent memberships; reader locks serialize acknowledgement with publication.
  The additive schema includes reset cleanup and receipt-backed deletion cascades.
- `assembly_integration.py`: explicit S7/S4 adapter, separate significance versus relevance,
  exact own-article attribution, independent critical authorization and frozen dependencies.
  Supported core S4 development equivalence never collapses unrelated side angles.
- `ranking_service.py` / `ranking_repository.py`: one result/claim/publication path. S8 receives
  all accepted ordinary candidates, applies the limit last, and atomically writes the final
  order and receipts. History-only builds reuse freshly reauthorized, unexpired RankBatch
  judgments without retrieval or provider calls; expired semantic TTLs cannot be extended.
  GET validates the stored selection without re-running the selector or issuing new receipts.
- Backend–Swift wire fixes: per-card generation/revision/request/original-position survives
  normalization, detail merging and feed caching. Local hides and background editions no
  longer change feedback attribution. Standalone bookmarks/detail caches strip feed receipts.
  Busy/unavailable responses are handled without a build/discovery loop; an image cannot
  displace the first backend-selected card.
- `X-Daily-Edition-Version: 1` capability: S8 feed routes reject incompatible clients before
  build/cache work. Older S7 clients receive HTTP 503 for unrecognized transient states, not
  an unknown enum or authoritative empty feed. This does not enable S4's separate capability.
- Exact-read novelty requires the actual S2 native presentation to match the complete trusted
  analysis body, and the reading event to report the same content hash as its immutable receipt.
  Source-web reads, unloaded content, stale detail-body versions and missing hashes remain
  unknown. A dwell-time event is still a proxy, not proof of comprehension. Existing permanent
  already-knew blocks are unchanged; metadata/version churn never creates a new-update claim.
- `evals/assembly.py`: compares actual-input S7 top-K, verified-dedupe-only and assembled
  outputs; preserves unknown label denominators, opportunity losses, false merges and false
  read suppression. Independent labels are not fabricated, and reports never self-certify quality.
- Disconnected-by-default management CLI, example recipe/environment, required deterministic
  CI job, and an opt-in disposable PostgreSQL suite which fails rather than skips when required.

## Design refinements made during implementation

- A fourth module is a narrow integration adapter. Keeping S4 authorization/S2 serialization
  out of the pure selector avoids duplicating caches or expanding the ranking service further.
- Metadata/history is hydrated outside publication; the bounded pure selector runs after fresh
  authorization inside the existing two-second publication guard. There is no network/provider
  work under those locks. SQL-phase latency and lock contention remain activation gates.
- Unknown identity stays singleton; no title-similarity or uncalibrated URL-equivalence rule
  was added. S3 membership consumption is separately disabled in the example recipe.
- Recipe values (topic share 0.6, publisher share 0.5, streak 2) are transparent initial policy
  settings, not calibrated optima. Relevance grades and hard reader policies never relax.
- The final cross-module proof caught undisplayed-analysis novelty. Native display/hash
  matching and read-content receipt validation close that gap; source-web novelty is deliberately
  conservative rather than pretending to know the publisher page's current body.

## Verification

Final combined evidence:

- Focused backend: **341 passed, 33 subtests passed**; 18 S8 PostgreSQL cases skipped.
  `.context/s8-focused-final.log`.
- Final full backend: **1,797 passed, 140 skipped, 235 subtests passed; three failures**.
  `.context/s8-backend-full-final.log`.
- Final entire iOS unit suite: **80 passed, zero failures**, including ten edition tests.
  `.context/s8-swift-final-all-tests.log`.
- Python compilation and `git diff --check` passed. No server/listener was started.

The suites exercise shared backend/Swift JSON fixtures and actual native-body read hashes.
The full backend suite retains the three pre-existing S0 quality failures (follow-up recall,
never-rate and event delivery on the 2026-09-02 prod-llm snapshot); no baseline was weakened.
An import-order-only httpx test stub failure discovered by the new test collection order was
fixed by preferring the installed transport over a partial stub. No provider runtime was changed.

The PostgreSQL suite is **authored, not executed here**. It creates its own randomly named
disposable database only with explicit `S8_TEST_DATABASE_URL`; `S8_TEST_DATABASE_REQUIRED=1`
prohibits silent skips. It tests actual schema/receipt/history operations and lock protocols,
but is not a full deployed S1–S8 concurrency or latency canary.

## Activation and rollback gates — still open

1. Preserve the existing S2–S7 migration/quality/deployment prerequisites. Install S8's additive
   schema explicitly after S5 reader/feedback tables; application startup never migrates it.
2. Run the required disposable SQL jobs and combined publication races on the intended
   PostgreSQL version. Check migration compatibility and permissions against the hosted schema.
3. Evaluate independent temporal/story/source-disjoint edition labels and freeze promotion
   thresholds before heldout results. Include false merges, missed duplicates, corrections,
   read-history coverage, precision loss and sparse multi-interest feeds. S0's existing failures
   remain visible and are not waived by deterministic S8 tests.
4. Measure bounded 300-ordinary/600-dependency hydration, publication lock duration, cache churn,
   and history-only provider reuse under a declared workload. No production latency is claimed.
5. Release the receipt-capable client. Approve an explicit assembly recipe in the database only
   after evidence review; independently enable S3 membership only after its own identity gates.
6. Enable `S8_SERVING_ENABLED` only alongside compatible S5/S6/S7 and approved serving controls.
   Begin with a controlled canary. Existing legacy serving remains unchanged while S7/S8 are off.

Disabling/altering assembly advances its control epoch; old editions fail authorization.
Turning off the process S8 flag does not reinterpret an S8 cache as a legacy edition. A downgrade
requires an explicit new build/new edition ID; safe existing S7 judgments can be reused only
while their original evidence and TTL remain valid. No schema removal is required for rollback.

Safe disconnected commands (no database access):

```sh
backend/venv/bin/python backend/scripts/manage_s8_assembly.py status
backend/venv/bin/python backend/scripts/manage_s8_assembly.py configure --recipe-file backend/assembly.recipe.example.json
```

Any real installation/configuration additionally requires `--apply --database-env NAME` with
an explicitly selected DSN. No real command was executed as part of this implementation.

See [approved plan](s8-implementation-plan.md) and [historical audit](s8-edition-assembly-audit.md).
