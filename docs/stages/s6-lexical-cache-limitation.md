# S6 lexical retrieval: the real reliability limitation, and what it isn't

2026-09-12. Investigated live against production while hardening Phase 4.2 (S6/S7 shadow).
Not fixed for free; the complete fix costs real money and is deliberately deferred. This file
exists so the reasoning survives past one chat's context — see `bulletproof-architecture-plan.md`
Phase 4 for the checklist-level summary this expands on.

## The symptom

Against the one real, 15-intent reader profile available for testing, S6 shadow retrieval
(`retrieval_runtime.shadow`) completes only ~2 times out of every 6 attempts. The rest hit the
2-second retrieval deadline (`build_candidate_batch`'s own `deadline_seconds`) and report
`timed_out`, even after fixing a real round-trip-count bug (savepoint-per-state, timeout
tightened once per state instead of once per round — see commit `c7a0cbc`) that was previously
the dominant cost.

## What it is NOT (ruled out directly, not assumed)

**Not a per-connection "cold first query" tax.** The first hypothesis was that a freshly opened
pooled connection's first lexical query costs more (Postgres session-local plan building,
catalog cache population, etc.), and that pre-running a synthetic warm-up query via
`ConnectionPool(configure=...)` at connection-open time would pay that cost once, off the
request path. This was implemented, deployed (commit `1111fdf`), and **disproved by live
verification** rather than trusted because it looked clean in isolated testing:

- Per-term instrumentation on a single, unchanging connection showed the real search term `'AI'`
  going `1553.9ms -> 67.7ms -> 37.3ms` across three repeated *real* executions, while other
  terms (`'football'`, `'vibe coding'`, etc.) were fast from their very first use.
- A synthetic warm-up probe using fake text (`'warm probe'`) cannot touch the same data pages as
  a real, broad term like `'AI'` — so it measurably did not help. After deploying it, fewer
  shadow attempts completed than before (1/6 vs. the pre-warmup 2/6 baseline).
- The probe and the `min_size == max_size` pool sizing it required were reverted in commit
  `cf4955f`.

**Not `shared_preload_libraries` / an extension-permission restriction.** This was the next
guess raised in review, and it's worth stating precisely why it's wrong, since it's a
plausible-sounding but incorrect mental model: `pg_prewarm` has *two* independent features —

1. The plain `pg_prewarm(regclass)` **SQL function**, which loads a specific relation's pages
   into `shared_buffers` on demand when called. This only needs `CREATE EXTENSION pg_prewarm`
   (a normal, unprivileged extension install — confirmed working on this project's free tier)
   and needs **no** preload configuration.
2. The `pg_prewarm.autoprewarm` **background worker**, which periodically dumps a list of
   currently-buffered blocks to disk and automatically restores them after a server restart.
   *This* feature needs `shared_preload_libraries` to include `pg_prewarm`, which requires a
   full postmaster restart to take effect (`SHOW shared_preload_libraries` reports context
   `postmaster`, not `sighup`/`user`) and typically is gated by managed platforms.

This project never used or needed feature 2. Verified directly against the live database:

```
shared_preload_libraries: pg_stat_statements, pgaudit, plpgsql, plpgsql_check, pg_cron,
                           pg_net, pgsodium, auto_explain, pg_tle, plan_filter, supabase_vault
```

`pg_prewarm` is not in that list and was never added to it — only feature 1 is used, via a
one-time call at app startup and a periodic loop, both from application code (`app/main.py`:
`_prewarm_relations`, `_prewarm_loop`), not a Postgres-level autoprewarm configuration. No
preload restriction was ever hit or worked around.

## What it actually is: `shared_buffers` is too small for the working set, under real contention

Directly measured on the live database:

- `shared_buffers` = 224MB (`28672` 8kB pages) — fixed by the project's compute tier, not a
  user-adjustable `postgresql.conf` setting on a hosted Supabase instance without a plan change.
- `public.articles` (the base table) = 114MB. `public.reader_article_lexical_v2` (the GIN index
  S6's lexical leg reads) = 9.3MB. Combined working set: ~123MB, which looks like it should fit
  in 224MB with room to spare — but that ignores everything *else* sharing the same 224MB
  (other application tables, indexes, system catalogs, and whatever the ingestion loop is
  actively reading/writing at any given moment).

`pg_prewarm`ing both relations at startup was verified to work exactly as intended: right after
deploying it, `pg_buffercache` showed `reader_article_lexical_v2` **100% resident** (1162 of
1162 buffers, the entire index) — proof the prewarm call itself is correct and effective, not a
no-op. But `public.articles` showed only **46MB of 114MB (40%) resident**, already partial only
~15-20 minutes after startup, and a live re-test at that point still only completed 1/6 shadow
attempts. The GIN index tells Postgres *which* rows match a term; computing `ts_rank_cd` and
returning the row still requires reading that row's actual heap page. For a broad term like
`'AI'` (an AI-news app; most articles plausibly mention it), that can mean touching a large
fraction of the table's pages — and if those specific pages have been evicted by competing
activity since the last prewarm, that read costs real disk I/O again.

**This is a genuine capacity constraint, not a caching bug.** No warm-up strategy — synthetic
probe, real-relation prewarm, or a tighter re-warm interval — can *durably* solve "the working
set doesn't reliably fit in memory" without either (a) more memory, or (b) a smaller working set
(e.g. a fundamentally different retrieval strategy — see Phase 6, semantic/ANN retrieval, which
doesn't have this "common term touches many rows" cost shape).

## What's actually deployed today (free, partial mitigation)

- `CREATE EXTENSION IF NOT EXISTS pg_prewarm` at app startup (idempotent, harmless if already
  installed).
- `_prewarm_relations(conn)`: calls `pg_prewarm('public.articles')` and
  `pg_prewarm('public.reader_article_lexical_v2')` once at startup, and again every 15 minutes
  via a new leader-elected background loop (`_prewarm_loop`, matching the existing
  `_ingestion_loop`/`_source_quality_loop` pattern — one lock key, `"prewarm"`, added to
  `_LOCK_KEYS`).
- Failure anywhere in this path is caught and logged, never fatal — this is a latency
  optimization, not a schema dependency, unlike `_ensure_tables`.
- This measurably keeps the *index* fully warm. It does not fully solve the *table* eviction
  problem under contention, per the live re-test above.

## The complete fix, and why it's deferred

The durable fix is more `shared_buffers`, which on Supabase requires the org to be on the paid
Pro plan ($25/month base) plus a compute add-on on top (Micro/1GB ~$10/mo, Small/2GB ~$15/mo,
Medium/4GB ~$60/mo — checked directly via the Supabase Management API, `GET /v1/projects/{ref}/
billing/addons`). This project's org (`azitvudegahjteyfzjgp`) is confirmed on the **free** plan
with no compute add-on selected.

**Deliberately not purchased right now.** `S6_SERVING_ENABLED`/`S7_SERVING_ENABLED` are both
still `false` — nothing here is user-facing yet, and there is no real traffic at all (confirmed:
zero requests to any `/feed/*` endpoint in the available log window, and no iOS client has been
released to generate any). Paying $35-75+/month recurring to fix a reliability problem nobody
is currently exposed to isn't worth it yet. Revisit this sizing decision as part of pre-launch
hardening (Phase 7/8), once real usage patterns exist to size against, or immediately if Phase 6
(semantic/ANN retrieval) doesn't end up replacing this lexical path first.
