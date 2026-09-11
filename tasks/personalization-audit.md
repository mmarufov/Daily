# Personalization Audit — why the feed doesn't work

Investigation of the full path: onboarding → profile → source discovery → ingestion →
candidate retrieval → scoring → delivery. Read-only audit; no code changed.

---

## 1. The pipeline as actually built

| Stage | Where | What happens |
|---|---|---|
| Onboarding chat | `main.py:1675` `/chat/interests` | gpt-4o-mini asks for specificity. Saves nothing. |
| Profile build | `openai_service.py:378` `build_complete_user_preferences` | One LLM call turns the transcript into `ai_profile` (free text), `interests` (topics/people/locations/industries/excluded), `user_profile_v2` (stable vs current interests, life_context, depth, tone, utility priorities), `source_selection_brief`. |
| Source discovery | `source_discovery.py:655` | Candidates = 82 curated seeds matched by category + ≤6 Google News query feeds + ≤10 AI-suggested URLs. Validated by live fetch, scored, then **capped to 12 / 16 / 20 sources** (specific / mixed / broad). Written to `user_sources`. |
| Ingestion (global) | `main.py:43` `_ingestion_loop`, every 3 min | 38 hardcoded RSS feeds + one Google News search per unique user topic → `articles`. |
| Ingestion (per-user) | `user_source_pipeline.py:184` | Fetches that user's 12–20 sources → `articles` **+ `article_source_links`**. |
| Candidate retrieval | `feed_service.py:345` | `articles ⋈ article_source_links ⋈ user_sources(active)`, last **72h**, **300 rows ordered by recency**. |
| Prefilter | `feed_service.py:930` | Deterministic keyword score. Drops exclusion matches. Sorts by score, **takes top 100**. |
| LLM scoring | `openai_service.py:505` | 3 batches × 40 articles, gpt-4o-mini, returns `{relevant, score, reason}` positionally. |
| Blend | `feed_service.py:1032` | `0.65·model + 0.35·keyword`, +behavior ≤0.15, +entity 0.2, ±source-quality 0.10, then `× (0.5 + 0.5·content_quality)`. Kept if `model_relevant AND blended ≥ 0.35`. |
| Delivery | `feed_service.py:1108–1250` | Near-dup collapse → 40% category cap → role balance (direct_match 10 / life_impact 5 / worth_knowing 3 / serendipity 2) → cache 60 min. |

---

## 2. Confirmed bugs

Each of these was verified by executing the real code, not by reading.

### 2.1 The global ingestion loop can never reach any feed — CONFIRMED

`fetch_rss_feeds` and `fetch_topic_feeds` insert into `articles` but never write
`article_source_links`. The feed's candidate query **requires** that join.

```
fetch_rss_feeds        writes article_source_links? False
fetch_topic_feeds      writes article_source_links? False
fetch_user_sources     writes article_source_links? False
feed candidate query REQUIRES the link table: True
```

Every 3 minutes the backend fetches 38 feeds plus a Google News search per user topic,
extracts content, generates embeddings, and runs the expensive enrichment stage on the
results — and **none of it can appear in anybody's feed.** It only feeds `/search/semantic`
and chat. This is the single largest source of both wasted spend and missed coverage.

### 2.2 Source-quality scoring is dead code — CONFIRMED

`_rows_to_candidates` (`feed_service.py:427`) stores the publisher under key `"source"`.
`_apply_individual_analysis_results` (`feed_service.py:1093`) reads `candidate.get("source_name", "")`.

```
candidate['source']          = 'The Verge'
candidate.get('source_name') = None
_extract_domain(...)         = ''      -> dict lookup never hits
```

The whole `source_quality` table — recomputed every 30 minutes from aggregate reading
events — has zero effect on ranking.

### 2.3 Fresh articles are silently penalized 50% — CONFIRMED

`_rows_to_candidates` sets `content_quality` to `row.get("content_quality") or 0.0`, so a
NULL (not-yet-enriched) article gets `0.0`, not the intended `0.5` default — the
`candidate.get("content_quality", 0.5)` fallback at line 1101 can never fire because the
key always exists.

Scoring then does `blended_score *= (0.5 + 0.5 * content_quality)`:

- `content_quality = 0.0` → **×0.5**
- `content_quality = 1.0` → ×1.0

An article the LLM scored a perfect 1.00 becomes 0.50. The relevance gate is 0.35, so
anything the LLM scored below ~0.70 gets cut purely for not having been enriched yet.
Enrichment runs 25 articles per 3-minute cycle against a much larger ingest rate, so the
newest and most urgent stories are exactly the ones carrying this penalty.

### 2.4 `fetch_user_sources` is dead — CONFIRMED

`source_discovery.py:852`, ~100 lines with its own retry/backoff/deactivation logic.
Zero callers.

### 2.5 Two learning loops are built but never surfaced — CONFIRMED

`BackendService` has working methods with no caller anywhere in the app:

```
UNUSED: fetchInterestSuggestions, acceptInterestSuggestion, dismissInterestSuggestion
UNUSED: fetchEntityPins, createEntityPin, deleteEntityPin
```

- `interest_evolution.py` runs every 6 hours, writes suggestions nobody sees.
- `entity_pins` is therefore always empty, so the `+0.2` entity boost in scoring —
  the strongest single signal in the blend — never fires for anyone.

### 2.6 Tune can't tune

`TuneViewModel` has `pendingDiff` / `persistedUndo` / `DiffToast` / `UndoPill` wired to a
`.weightDiff` stream event. Grep for `diff` or `weight` in `chat_service.py` returns
nothing — the backend never emits it. `tapUndo()` is `// TODO(backend)`. Tune is a
read-only Q&A surface; talking to it cannot change what you see.

---

## 3. Why it misses things it should show

**a. It only ever looks at 12–20 feeds.** Chosen once, at onboarding, from an 82-entry
curated list plus ≤6 Google News searches and ≤10 AI guesses. "Every source available" is
not what happens — for a `specific` profile it's 12 feeds, and `_score_candidate_source`
applies `score -= 1.0` to any general-category source, so wire services get pushed out
exactly when the profile is narrow.

**b. Retrieval is recency-ordered with no per-source fairness.** `LIMIT 300` over 72 hours
across all sources, `ORDER BY published_at DESC`. One firehose source (Google News returns
100+ items) can consume most of the window and starve a niche feed that published the one
story that mattered.

**c. The window never actually expands.** `CANDIDATE_EXPANSION_STEPS` defines 3d/7d/14d
tiers, but the loop returns as soon as it has 100 non-excluded candidates — and
`_prefilter_candidates` keeps *everything* that isn't an exclusion match, so 300 rows
essentially always yields 100. The 7-day and 14-day tiers are unreachable in practice.

**d. Keyword prefilter is the real gatekeeper, not the LLM.** Only the top 100 of ~300 by
literal keyword score reach the model. An article that matters to you but doesn't contain
your exact terms in title/summary/content is dropped before any semantic judgment happens.

**e. Embeddings exist and are paid for but are never used for the feed.** Every article
gets a `text-embedding-3-small` vector and there's an HNSW index on it. It's used by
`/search/semantic` and chat only. The core product retrieves by keyword.

---

## 4. Why it shows things it shouldn't

**a. Positional batch scoring with no alignment check.** 40 articles per call; the model
returns a bare array with no ID field. `results_list[i]` is trusted to correspond to
`articles[i]`. A length mismatch is logged but a *reordering* is undetectable — every
article silently gets another article's verdict.

**b. Role balance overrides score.** `_balance_feed_roles` fills direct_match(10),
life_impact(5), worth_knowing(3), serendipity(2) in that order. A 0.40 "life_impact"
article outranks the 11th direct match at 0.95. `life_impact` is assigned by
`_compute_life_impact`, which fires on substring hits against a hardcoded map
(`"work" → {technology, business, programming, ai}`) plus any of
`policy|regulation|lawsuit|ban|recall|security|outage` — a very loose net.

**c. Exclusions are substring matches on the full blob.** `_score_candidate` searches
title+summary+content+source+category. Excluding "Tesla" also kills a story about your
actual interest that quotes Musk once.

**d. Stale profile after accepting a suggestion.** `/interests/suggestions/{id}/accept`
appends to `interests.topics` but leaves `user_profile_v2` and `source_selection_brief`
untouched — the two structures the scorer actually reads for hierarchy then disagree.

---

## 5. Why it never gets better

This is the core of "it doesn't work." **Explicit feedback is recorded and read by nothing.**

`/feed/feedback` accepts `not_relevant`, `more_like_this`, `less_like_this`, `important`,
`already_knew` and inserts them into `reading_events`. Every consumer of that table filters
to other event types:

| Consumer | Reads |
|---|---|
| `_recompute_behavior_signals` | `impression`, `tap`, `read` |
| `interest_evolution` | `tap`, `read` |
| `source_quality` | `impression`, `tap`, `read` |

So the flow is: user taps **Not relevant** → row written → feed cache cleared → feed rebuilt
**from the identical profile** → the same article scores the same → **it comes back.**
`NewsViewModel.submitFeedback` removes it from the local array, which hides the problem
until the next refresh. `hide_source` is the only feedback action with real effect.

The implicit loop that *does* work (impressions/taps/reads → `behavior_cache`) is capped at
`+0.15` and is a category/source boost only — it can never learn "I want Anthropic model
releases but not funding rounds."

Net: three of the four corrective surfaces in the app (feedback actions, Tune chat,
interest suggestions) are inert, and the fourth (Settings) nukes and re-discovers the entire
source graph on every edit.

---

## 6. Cost note

The enrichment stage — up to 3 OpenAI calls + Tavily + Unsplash + Gemini per article — runs
on `articles` with no filter on whether the article is linked to any user's sources. Given
§2.1, a large fraction of that spend goes to articles that structurally cannot appear in a
feed. Same for embedding generation.

---

## 7. Recommended direction

Ordered by impact per unit of work.

**Tier 1 — make the existing machine work (small, high payoff)**
1. Fix the `source_name` key mismatch (§2.2). One-line.
2. Fix the `content_quality` default so unenriched articles aren't halved (§2.3). One-line.
3. Make explicit feedback actually feed back (§5) — the single biggest cause of "it doesn't
   learn." Minimum viable: persist `not_relevant`/`less_like_this` as negative signals on
   (topic, source, cluster) and consume them in `_apply_individual_analysis_results`.
4. Surface interest suggestions and entity pins in the UI (§2.5) — backend and client API
   already exist; this is view work, and it turns on the `+0.2` entity boost.

**Tier 2 — fix recall (medium)**
5. Link globally-ingested articles into the candidate pool (§2.1), either by giving every
   user an implicit "global" source or by dropping the link-join in favour of a
   source-scoped OR topic-matched predicate. This is the change that makes "don't miss
   anything important" true.
6. Use the embeddings that already exist: retrieve candidates by profile-vector similarity
   *in addition to* recency, so semantically-relevant articles that miss the keywords still
   reach the model.
7. Add per-source fairness to retrieval so a firehose can't starve a niche feed (§3b).

**Tier 3 — fix precision (medium)**
8. Have the scoring model echo the article index and validate alignment; drop unmatched
   entries rather than trusting position (§4a).
9. Re-rank by score within the role quotas instead of strictly by role order (§4b).
10. Scope exclusion matching to title/summary rather than the full content blob (§4c).

**Tier 4 — structural**
11. Continuous source discovery. Today a user's source set is frozen between preference
    edits; interests drift and coverage never follows.
12. Make Tune write to the profile. Either implement the `weightDiff` event the client
    already handles, or remove the dead UI.

---

*Audit performed on branch `mmarufov/sydney-v7`. `76 passed` — the existing test suite is
all pure-function unit tests, which is why none of the integration gaps above are caught.*
