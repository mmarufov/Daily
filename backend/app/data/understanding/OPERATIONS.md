# S3 operating contract

S3 is implemented behind two disabled flags. It is **not production-approved**.
The committed recipe is provisional: unresolved entities are preserved and stories
remain singletons until independently evaluated linking/grouping is available.
The old search/chat path and embedding writer remain the default.

## Components

- `understanding_contract.py`: deterministic evidence selection, canonical cards,
  input fingerprint and versioned recipe. Unverified legacy bodies are excluded.
- `understanding_provider.py`: fixed-origin, bounded OpenAI requests. Models return
  exact quotes; the server calculates offsets only for unique matches. Schema and
  span validity establish traceability, not semantic accuracy.
- `understanding_repository.py` / `understanding_schema.sql`: jobs, leases, immutable
  results, revisions, eligibility, spend reservations and invalidation outbox.
- `understanding_worker.py`: separate supervised process; no provider wait holds a
  database checkout. Shutdown cancels requests and retains uncertain reservations.
- `story_clustering.py`: conservative assignment and version-checked correction.
- `understanding_consumers.py`: optional current-recipe search/chat lookup through
  the existing S2 public serializer. It does not replace feed retrieval/ranking.

## Migration and rollout

Never use production for the fault-injection test suites. Their database URLs must
identify a disposable hosted PostgreSQL server with CREATEDB and pgvector 0.8.0.
CI creates randomly named databases and rejects skipped database suites.

Before production operations, verify S1 acquisition identity and S2 schema/build,
take the normal recoverable database backup, and review migration capacity and
rollback. There is no automatic S3 schema migration on API startup. Credentials
come only from environment variables; do not paste them into command arguments.

From `backend/`, migration commands default to a read-only preview:

```sh
python scripts/manage_s3_understanding.py migrate
python scripts/manage_s3_understanding.py migrate --apply
python scripts/manage_s3_understanding.py register --apply
python scripts/manage_s3_understanding.py status
```

The concurrent HNSW build is optional: `migrate --build-index --apply`. Measure
filtered recall against exact search before promotion; a built index is not proof
of retrieval quality. An interrupted invalid index can be rebuilt by the same
explicit command. Back up and capacity-check before this operation.

Enable only the reviewed recipe (`enable --recipe ID --apply`), configure an
explicit authorized daily processing budget (`configure --daily-budget-usd AMOUNT
--apply`), and run the worker as a separate process with `S3_WORKER_ENABLED=true`.
The authoritative database control must also allow submissions. No production
budget is implied by the user's separate USD 5 pilot authorization.

Use `backfill --recipe ID --max-rows 100 --apply` for bounded scheduling. Save its
`next_cursor`; resume with `--after UUID`. Repeating from the beginning safely
reconciles missed articles. Registration does not process historical articles.
Expired attempts and ambiguous provider charges stay visible in `status`.
Do not clear reservations to make retries fit a budget.

Promotion requires a matching quality report augmented with build/schema,
S1/S2, rollback, 72-hour observation, integrity, budget, load, readiness and
filtered-recall evidence. `promote --recipe ID --evidence PATH --apply` rejects
missing or failing gates. Only then enable `S3_CONSUMERS_ENABLED=true` for a
bounded search/chat cohort. Keep the legacy writer until cutover evidence allows
its separate retirement. The Fly process file is an example, not an active deploy.

## Stop, rollback and correction

- `pause --apply` stops new paid processing but preserves results and accounting.
- `disable --recipe ID --apply` hides the recipe and clears its serving pointer.
  Disable the consumer flag as part of rollback; enabled consumers deliberately
  reject a missing approved recipe instead of mixing old vectors.
- `revoke --article-id UUID --apply` immediately fences analysis outputs.
  `restore` increments eligibility again; old outputs cannot resurrect.
- Article deletion cascades private results/jobs/membership. The content-free
  deletion outbox and accounting records intentionally survive.
- Outbox consumers acknowledge exact event IDs **after** durable idempotent
  application; a numeric high-water mark alone can lose late commits.

## Still required before activation

Independently adjudicate the 600-item review queue, create story-disjoint holdout
labels, compare model quality, populate trusted entity/place candidates, calibrate
grouping, declare supported language/evidence slices and approve forecast budgets.
The small paid wire pilot is not a substitute for these gates. Complete hosted
load/ANN measurements and the production prerequisite/canary sequence in
`docs/stages/s3-implementation-plan.md`. Do not mark S3 globally ready from unit tests.
