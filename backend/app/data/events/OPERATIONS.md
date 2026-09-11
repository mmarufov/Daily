# S4 event detection operations

## Current safety boundary

Repository implementation is not a production approval. The acceptance manifest starts with
`release_ready=false`, no supported slices, no approved S4 spending ceilings and explicit blockers.
Source-origin metadata defaults to unknown; coverage and reader delivery default off. Current
clients must not receive S4 priority until their explicit expiry capability is implemented and
verified. Model schema compliance is not evidence of editorial accuracy.

At the time of this implementation, S1/S2/S3 live readiness has not been freshly established,
independent S4 holdout quality is unapproved, and hosted S4 PostgreSQL lifecycle/load verification
has not been demonstrated. Do not infer approval from these commands, synthetic unit tests, an
old S3 CI run or a previous S3 pilot budget. No S4 paid calls or production changes are authorized
by this guide. There is no localhost product-server workflow; use offline tests and disposable
hosted PostgreSQL for fault injection.

The implemented grouping v1 is conservative exact-action/object matching with explicit scope;
it is **not** the plan's fully calibrated hybrid candidate retrieval and has no verified
population recall. Coverage attestation currently takes explicit operator-supplied inputs;
there is no automatic verified S1 coverage monitor. Both are concrete integration/quality gaps,
not merely deployment switches. All new recipes remain unpromoted until their actual supported
behavior, not the intended future design, passes independent gates.

The API must never install this schema, extract evidence or call an S4 provider on a feed request.
Its event leg reads current authorized decisions separately from the ordinary feed cache.
Persistent legacy feed caches must not contain live S4 priority. Saved source-article access and
expired priority are different concerns. Source-web is a valid route; unavailable articles do
not fill reserved slots. Major-event candidates require the existing S7 scoring handoff; the pure
adapter does not force them or claim that handoff has been fully integrated.

## Operator prerequisites and target selection

Run from the repository root. Install the backend's pinned dependencies in the existing Python
environment. The examples use `backend/venv/bin/python`; the same module works with the deployed
backend interpreter. Supply the database DSN through a secret-managed environment variable named
`S4_DATABASE_URL`, not a command-line argument. Do not paste credentials into logs or evidence.

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py status --database-env S4_DATABASE_URL
backend/venv/bin/python backend/scripts/manage_s4_events.py migrate --database-env S4_DATABASE_URL
```

The first reads status; it requires an installed S4 schema. The second is a **dry run**, usable
before installation: it identifies the database and PostgreSQL version but does not migrate or
validate the entire proposed operation. Successful dry-run output contains `mode: "dry_run"`;
successful mutation output contains `applied: true`. Errors contain only the exception class, not
driver messages that might expose secrets. A failed multi-batch operation may have committed
earlier batches; inspect state before replaying.

Before any authorized production migration: verify the build SHA and target, freshly verify
upstream S3 schema compatibility, take and verify a backup, inspect populated-table migration
plans/lock timeouts and pass the disposable-hosted migration tests. Only then append `--apply`
to the migration command. Migrations are additive, explicit and serialized. Do not drop S4 or
S3 tables to roll back, and never use production as a destructive concurrency test database.

All other mutation commands also require `--apply`. The examples below intentionally omit it.
For every control-changing command, obtain the current `control.generation` from a fresh status
read and set `S4_EXPECTED_GENERATION` to that value. A stale expected generation must fail;
do not blindly retry it with an incremented number. `source` instead expects the affected
`event_source_registry.generation` from an explicit read of that article's registry row.

## Recipe and bounded intake

Prepare a reviewed `s4-recipe.json` with exactly the `DEFAULT_RECIPE` keys in
`app/services/event_repository.py`. Bind an explicitly approved S3 serving recipe, versioned
refinement and assessment providers, support policy, calibrated grouping rules, supported
languages and evidence/observation bounds. Do not set support/calibration booleans merely to
make a test or registration pass. Registration computes the content-addressed recipe ID and
always starts it disabled and unapproved.

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py register --recipe-file s4-recipe.json --database-env S4_DATABASE_URL
backend/venv/bin/python backend/scripts/manage_s4_events.py enable --recipe "$S4_RECIPE_ID" --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
backend/venv/bin/python backend/scripts/manage_s4_events.py backfill --recipe "$S4_RECIPE_ID" --max-rows 100 --database-env S4_DATABASE_URL
```

Enablement of a recipe does not approve quality, turn on submissions or enable reader delivery.
Backfill processes at most `--max-rows` article rows, in batches of at most 100, and returns
`scanned`, `inserted`, and `next_cursor`. Resume with `--after "$S4_NEXT_CURSOR"`; retain cursor
evidence across partial failures. It schedules durable work and does not itself call a model.
Zero inserted jobs can mean deduplicated work, not successful completed analysis.

For an existing registry entry, prepare a reviewed source metadata JSON object matching the
strict `Source` contract: `publisher_id`, `reporting_origin_id`, `origin_status`,
`primary_verified`, `language`. Unknown reporting origins cannot be counted as independent.
Publisher ownership or the number of copied articles is not corroboration. Acquisition-specific
provenance IDs and reader-facing publisher/source IDs are separate namespaces.

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py source --article-id "$S4_ARTICLE_ID" --source-file s4-source.json --reviewed-by "$S4_REVIEWER" --expected-generation "$S4_SOURCE_GENERATION" --database-env S4_DATABASE_URL
```

## Budgets, coverage and independent kill switches

Do not submit paid requests until numeric pilot, daily and monthly S4 ceilings, prices, maximum
tokens, supported slices and request limits are approved. S3's budget is not S4 authorization.
Set `S4_APPROVED_DAILY` and `S4_APPROVED_MONTHLY` only from that approved decision. The repository
serializes reservations before dispatch; uncertain charges remain accounted until reconciliation.
An expired worker lease is not permission to release an uncertain provider charge or repeat an
unaccounted request. Unexpected cost beyond a reservation must trip the circuit and be reviewed.

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py configure --submissions-enabled --daily-budget-usd "$S4_APPROVED_DAILY" --monthly-budget-usd "$S4_APPROVED_MONTHLY" --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
backend/venv/bin/python backend/scripts/manage_s4_events.py pause --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
```

`configure` writes the exact requested switch values: omitted `--delivery-enabled` means delivery
off, omitted `--submissions-enabled` means submissions off. It is not a patch operation. `pause`
stops submissions while preserving the observed delivery setting and numeric budgets under the
control-generation fence; current authorized decisions still expire normally. Do not describe
this as extending their lifetime.

To stop delivery and submissions together, use `configure --expected-generation ...` without
either enable flag, then explicitly apply it after checking the current target. To remove a
recipe from service and clear its approval, use:

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py disable --recipe "$S4_RECIPE_ID" --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
```

Coverage must come from an independently observed upstream acquisition/processing watermark,
not the time an assessment happened to run. A stalled feed cannot become healthy by re-assessing
old articles. Refresh the control generation after any coverage update.

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py coverage --observed-through "$S4_OBSERVED_THROUGH" --verified --reviewed-by "$S4_REVIEWER" --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
backend/venv/bin/python backend/scripts/manage_s4_events.py coverage --reviewed-by "$S4_REVIEWER" --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
```

The second withdraws verified coverage. Never set a future watermark or manufacture an upstream
health attestation. Read-time checks must fail closed on missing, expired or unverified coverage.

## Recovery and replay

Inspect jobs and unresolved spend with `status`. Separate provider outage, budget pause,
unsupported refinement, stale input, oversize evidence and terminal contract errors. Fix the
cause and verify the affected scope before replaying an explicit job:

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py replay --job-id "$S4_JOB_ID" --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
```

Replay delegates to repository reconciliation; it must not reset historical attempts, erase
charges, reuse an expired lease or mutate a reviewed assessment. Retain exact outbox receipts,
including lower IDs that commit late. Missing dependencies, corrections, rights revocation,
source-origin edits and upstream approval changes must invalidate old priority immediately at
the committed read-authorization boundary, independently of later recomputation.

Historical notice coordinates are significant: a late invalidation must purge only superseded
dependencies, not newer valid evidence. Exact-development merges persist version-specific
`event_development_aliases`. Delivery receipts alone never suppress a development; the feed
joins them to explicit reading events on account, request and article, then resolves aliases.
Later development versions remain unseen until separately acknowledged. Receipt rows contain no
article text and cascade on account deletion; they are not a priority cache or read authorization.

The optional iOS metadata contract is implemented and tested, but current live feed loaders still
use ordinary-cache sanitization. Do not enable capability negotiation until live expiry-aware
ordering is separated from saved article state and its lifecycle is verified.

Do not manually release spend rows whose provider outcome is unknown. This CLI intentionally has
no blanket refund, delete, arbitrary SQL, label-editing, auto-approve or unrestricted job-reset
command. No separate purge/drain command is exposed unless the repository provides a verified,
bounded API; operational gaps remain release blockers rather than undocumented SQL recipes.

## Promotion is quality proof plus operational proof

Create the report with the offline `evals.events` evaluator using frozen, independently reviewed
labels, immutable recipe/data/protocol bindings, execution evidence, adversarial evidence and
outcome reviews. A missing or underpowered dataset is a failure, not a skipped promotion test.
Do not reuse development examples as untouched holdout or repeatedly tune against failed holdout.

Promotion takes **three separate reviewed artifacts**:

- `s4-quality-report.json`: trusted evaluator report with passing required independent gates.
- `s4-frozen-bindings.json`: the expected release recipe/data/protocol digests, not recomputed
  from whatever report is supplied at promotion time.
- `s4-operations.json`: real build/schema, upstream readiness, hosted lifecycle/load, observation,
  integrity, privacy, budget and rollback evidence required by `event_repository.promote`.

Current operational validator fields (supply measured/reviewed values, not a copied passing
template): `build_sha` is an exact 40-character lowercase Git SHA; `schema_version` is the exact
integer S4 schema version. `s1_s2_s3_verified`, `hosted_postgres_passed`,
`no_skipped_database_tests`, `rollback_verified`, `reader_policy_verified`, `budget_verified`,
`source_policy_verified`, and `independent_review_approved` require actual affirmative evidence.
`load_multiplier` must measure at least 2 and `observation_hours` at least 72. The integer
integrity counters `stale_publications`, `lost_invalidations`, `hard_policy_bypasses`,
`unaccounted_requests`, and `wrong_representatives` must all be zero. `approved_by`,
`verification_run`, and `rollback_run` must name the responsible reviewer and real evidence
references. These object-shape checks are not independent verification of an operator's claims.

```sh
backend/venv/bin/python backend/scripts/manage_s4_events.py promote --recipe "$S4_RECIPE_ID" --report s4-quality-report.json --bindings s4-frozen-bindings.json --operations s4-operations.json --expected-generation "$S4_EXPECTED_GENERATION" --database-env S4_DATABASE_URL
```

The CLI passes artifacts through unchanged; the repository revalidates them. `--apply` is not
permission to skip failed gates. Promotion and delivery enablement are separate steps. After
approved promotion, reader delivery additionally needs the feature switch, current DB delivery
control, supported cohort and genuine client expiry capability. The request integration uses
the explicit `X-Daily-Event-Expiry: 1` capability and a default-off server feature flag; current
clients do not advertise that header. Do not inject it on their behalf or pretend this proves
offline expiry. Rollout remains 1% → 10% → 50%
→ 100% only when those cohort controls and monitored rollback are implemented and verified; do
not simulate cohorts by setting a global boolean.

Minimum production-shadow evidence is 72 hours **and enough independent qualifying cases**,
with no reader priority. Hosted load must include at least 2× the declared forecast. Review
quiet and burst traffic, provider failure/restart, lower-ID late commits, deletion, source-policy
and recipe changes, merge/split, lease expiry, missing negative evidence, budget bursts and warm
ordinary caches. Finite deterministic tests cannot certify universal event understanding.

## Verification and alert acceptance

Run deterministic offline tests without provider credentials:

```sh
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest backend/tests/test_event_contract.py backend/tests/test_event_consumers.py backend/tests/test_event_feed.py backend/tests/test_s4_management.py -q
```

Hosted PostgreSQL gates must collect their required tests with zero skips; a missing database
configuration is not success. Tests that destroy schemas, alter rows or force lock schedules
belong only on disposable hosted infrastructure. Require migration/restart/recovery evidence,
not just mocked connection tests. Maintain the three previously documented S0 failures visibly;
they are not made harmless by S4 passing its own suite.

Release alert targets in `acceptance.json` are requirements, not claimed measurements: p95
qualifying evidence → assessment at most 300 seconds, private purge within 3600 seconds, zero
stale/partial publication, lost receipts, unaccounted dispatch, privacy leaks and explicit-policy
bypass. At most two reserved slots and total edition bounds must hold. Semantic quality requires
the specified confidence-bound gates, not raw percentages on a handful of synthetic cases.
Numeric forecast/queue saturation alerts, a named operational owner and verified backup/restore
evidence are still mandatory before production enablement; absent values block release.
