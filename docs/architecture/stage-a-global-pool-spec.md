# Stage A — Global pool + scalable retrieval

**Hand this whole file to the implementing session. It is self-contained.**

Prereq reading (same repo): `docs/architecture/personalization-audit.md` (what's broken),
`docs/architecture/source-architecture.md` (why these sources).

---

## Why this stage exists before "add more sources"

The obvious plan is: add thousands of feeds, then improve filtering. That order does
not work here, for two concrete reasons.

**1. `user_sources` is a join gate, not a preference.** `feed_service._query_candidate_rows`
retrieves via `articles ⋈ article_source_links ⋈ user_sources(active)`. An article only
exists for a user if it arrived through one of *their* 12–20 feeds. Adding 2,000 feeds to
the registry changes nothing until this join goes away — you'd have to assign all 2,000
feeds to every user, which is absurd, or the articles stay invisible. This is the same
defect that already makes the 3-minute global ingestion loop dead weight.

**2. Retrieval is recency-ordered and would drown.** Today: `LIMIT 300` ordered by
`published_at DESC` over 72h, then a keyword prefilter cuts to 100. With 12–20 low-volume
feeds, 300 rows covers ~3 days. With 2,000 feeds it covers roughly **20 minutes** of global
publishing. You would get a random recent slice and the feed would get *worse*, not better.

So: **the pool refactor and the retrieval refactor are one unit, and they ship before the
source expansion.** Prove them against the existing 82 feeds, then turn up the volume in
Stage B, where the source count is just a knob.

---

## Goal

Every user ranks over **one shared article pool**. `user_sources` becomes a ranking boost.
Retrieval becomes semantic + multi-vector, so the candidate set stays relevant no matter how
large the pool grows.

Success = the same feed quality or better, with the join gate gone and retrieval no longer
dependent on pool size.

---

## 1. Schema

```sql
-- Global source registry. Replaces per-user source ownership.
CREATE TABLE IF NOT EXISTS public.sources (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feed_url             TEXT UNIQUE NOT NULL,
    site_url             TEXT,
    name                 TEXT NOT NULL,
    category             TEXT,
    language             TEXT DEFAULT 'en',
    tier                 TEXT DEFAULT 'standard',   -- premium | standard | niche
    active               BOOLEAN DEFAULT true,
    -- conditional GET state (see §3)
    etag                 TEXT,
    last_modified        TEXT,
    body_hash            TEXT,
    -- adaptive polling
    poll_interval_seconds INTEGER DEFAULT 900,
    next_fetch_at        TIMESTAMPTZ DEFAULT now(),
    last_fetched_at      TIMESTAMPTZ,
    last_success_at      TIMESTAMPTZ,
    failure_count        INTEGER DEFAULT 0,
    articles_last_fetch  INTEGER DEFAULT 0,
    created_at           TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sources_due ON public.sources (next_fetch_at) WHERE active;

-- Per-interest profile vectors. One row per interest, NOT one per user (see §4).
CREATE TABLE IF NOT EXISTS public.user_interest_vectors (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     TEXT NOT NULL,
    label       TEXT NOT NULL,            -- the interest as the user expressed it
    kind        TEXT NOT NULL,            -- primary | background | entity | utility
    weight      REAL DEFAULT 1.0,
    embedding   vector(1536),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id, label)
);
CREATE INDEX IF NOT EXISTS idx_uiv_user ON public.user_interest_vectors (user_id);
```

Keep `article_source_links` — it becomes **provenance** ("which feed surfaced this"), used
for the `hide_source` feedback action and for source-affinity boosts. It is no longer an
access gate.

Keep `user_sources` — it becomes **affinity**: which registry sources this user's profile
matched, with `precision_score` / `coverage_role` used as ranking signal only.

`articles.embedding vector(1536)` and its HNSW index already exist. Reuse them.

---

## 2. Remove the join gate

In `feed_service._query_candidate_rows` (~line 345), delete the
`JOIN public.article_source_links ⋈ public.user_sources` scoping. Candidates come from
`public.articles` globally. Source affinity is applied later as a score boost, not here.

Keep the existing quality predicate
(`content_quality >= 0.4 OR enrichment_completed = false`).

---

## 3. Central poller

New `app/services/source_poller.py`. Replaces the per-user fetch in
`user_source_pipeline._fetch_from_user_sources` and the hardcoded `RSS_FEEDS` list.

- Select due sources: `WHERE active AND next_fetch_at <= now() ORDER BY next_fetch_at LIMIT 200`.
- Fetch with `asyncio.Semaphore(50)`.
- **Conditional GET.** Send `If-None-Match: {etag}` and `If-Modified-Since: {last_modified}`.
  On `304`, skip parsing entirely and just bump `next_fetch_at`. **Measured: 4 of 10 real
  publisher feeds honour this and return a true 304** (Ars Technica, The Verge, TechCrunch,
  Guardian). For the rest, hash the body and skip parsing when the hash is unchanged.
- Reuse `news_ingestion._fetch_single_feed` for parsing — it already extracts
  `content:encoded` full text (added this session) and images.
- Write articles once, globally. Write one `article_source_links` row per (article, source).
- **Adaptive cadence:** if `articles_last_fetch == 0` for 3 consecutive polls, double
  `poll_interval_seconds` (cap 6h). If it returns ≥5 articles, halve it (floor 5 min).
- Failures: increment `failure_count`, back off; deactivate at 10 consecutive failures.

Delete `source_discovery.fetch_user_sources` — it is already dead code with zero callers.

**Measured budget:** 10 feeds = 2 MB, 1.0s wall at 10 threads. Median feed ~30 KB. 2,000
feeds ≈ 65 MB/cycle at the median (~390 MB at the outlier-skewed mean, e.g. PC Gamer at
1.5 MB). Comfortably under a minute per cycle at 50 concurrency.

---

## 4. Multi-vector retrieval — the core change

**Do not build one averaged profile vector.** A user who follows "AI, gaming, and local
Bay Area news" averages into a centroid that matches none of the three. Embed each interest
separately and union the results.

**On profile save** (`/user/preferences`, `/user/preferences/complete`): populate
`user_interest_vectors` — one row per entry in `user_profile_v2.current_interests`
(`kind='primary'`), `stable_interests` (`kind='background'`, lower weight),
`interests.people` (`kind='entity'`), `utility_priorities` (`kind='utility'`). Embed the
label plus a little context, e.g. `f"{label} — news about {label}"`. Delete rows for
interests the user removed.

**On feed build**, assemble candidates from three legs and union-dedupe:

| Leg | Query | Cap |
|---|---|---|
| **Semantic** | per interest vector: `ORDER BY embedding <=> %s LIMIT 40`, filtered to last 72h | ~40 × n_interests |
| **Affinity** | most recent from sources in this user's `user_sources` | 100 |
| **Entity** | keyword/trigram match on `must_cover_entities` | 50 |

Dedupe by article id, cap the union at **300**, then hand the top **150** by blended
pre-score to the existing LLM batch scorer. `score_articles_batch` and everything downstream
of it stays as is — this stage only changes *which* articles reach it.

Fall back to pure recency when a user has no interest vectors yet (fresh account).

**Cost:** embeddings are `text-embedding-3-small` at **$0.02/M tokens** ($0.01/M batched).
50K articles/day × ~500 tokens ≈ **$0.50/day / ~$15/month**. LLM scoring spend is unchanged
— still ~3 batches of 40 per user per refresh.

---

## 5. Keep the deterministic prefilter as a *signal*

`_prefilter_candidates` currently decides which 100 of 300 the model ever sees, so an
article that doesn't contain your literal keywords is dropped before any semantic judgment.
After this change, semantic retrieval selects the candidates; keep `_score_candidate` only
for the 0.35 deterministic weight in the blend and for hard exclusion matches. Do not let it
gate.

---

## 6. Acceptance criteria

1. `_query_candidate_rows` contains no `user_sources` join.
2. A user with zero rows in `user_sources` still gets a populated feed.
3. Articles ingested by the central poller reach a feed **without** `build_feed_for_user`
   having run — this is the specific bug that makes today's global ingestion dead weight.
4. Two users with disjoint interests, on the same pool, get materially different feeds.
5. A user with 3 unrelated interests gets candidates for **all three**, not a blend of none.
   (This is the multi-vector test — assert per-interest coverage in the candidate set.)
6. Conditional GET verified: a source polled twice within its interval issues a 304 and
   parses nothing the second time.
7. `pytest tests/ -q` green. Add tests for: candidate assembly with 0 / 1 / many interest
   vectors; dedupe across the three legs; 304 short-circuit.
8. Feed build wall time does not regress at 82 feeds.

---

## 7. Explicitly out of scope

- Growing the registry past the current ~82 sources. That is **Stage B** — after this lands,
  it is a data-loading task plus the OPML/auto-discovery importer, and the poller absorbs it
  with no further code change.
- GDELT integration (Stage B).
- Any change to `score_articles_batch`, the prompt, or the blend weights (Stage C).
- The reader/render change — independent, ship whenever.
- Fixing the inert feedback loop (`not_relevant` etc. are recorded and read by nothing).
  That is Stage C; see audit §5.

---

## 8. Known traps

- **`_balance_feed_roles` reads `feed_role`** (post-`_finalize_articles`), while
  `_annotate_candidate_feed_roles` writes `_feed_role`. Correct today only because of call
  ordering. Don't reorder those calls.
- **`_load_cached_feed` truncates content to 500 chars.** The client's
  `loadFullArticleIfNeeded` checks `content.count > 500`, so it always refetches. Harmless
  now, but don't "optimize" either side without the other.
- **`source_quality` is dead** — `_apply_individual_analysis_results` reads
  `candidate["source_name"]`, but `_rows_to_candidates` writes `candidate["source"]`. It's a
  one-line fix; do it while you're in this file (audit §2.2).
- `MAX_SOURCES_PER_USER`, `MIN_FEED_SIZE`, `DETERMINISTIC_STRONG_MATCH` are defined and
  never used. Safe to delete.
