# S1 — Sources & ingestion audit

Read-only research, 2026-09-02. Evidence: code on this branch, a live probe of all 82 seed
feeds, and read-only queries against the production database. No code changed.

## Verdict

Ingestion is running, but almost nothing it produces can reach a reader, and the deployed
backend is months behind this branch. The pool is 69% Google News redirect stubs. The one
table that connects articles to a user's feed is empty. No user has a cached feed. Every
3 minutes the loop refetches ~13 MB of feeds with no conditional GET, extracts, enriches and
(tries to) embed articles that no feed query can return.

Fixing S1 is less about adding sources and more about making the pipeline honest: one
registry, one poller, one link from article to reader, and metrics that would have caught
all of the below.

## What production is actually doing (measured 2026-09-02)

| fact | value | where it came from |
|---|---|---|
| deployed schema | `articles` has no `content_quality`, `users` has no `last_active_at`, no `feed_build_log` | `information_schema` |
| ⇒ deployed build predates | PR #43 (2026-04-14, quality pipeline) | `git log -S` |
| articles in pool | 34,525 (14-day GC works: oldest 08-19) | `articles` |
| ingested per day | 1,000–3,500 | `articles.ingested_at` |
| Google News redirect stubs | **23,892 / 34,525 (69%)**, all with unresolved `news.google.com` URLs | `articles.url` |
| top "sources" last 7 days | `"football" - Google News` 2,490 · `"AI" - Google News` 1,983 · `Top stories - Google News` 1,521 · `"technology" - Google News` 1,492 | `articles.source_name` |
| `article_source_links` rows | **0** — every article is unreachable by the feed join | `article_source_links` |
| `user_feed_cache` rows | **0** — nobody is being served a feed | `user_feed_cache` |
| `user_sources.last_fetched_at` | 2026-04-13 for all 15 rows (one user) | `user_sources` |
| `reading_events` | none | `reading_events` |
| articles with a body (≥400 chars), 7 days | 3,829 / 14,991 (26%) | `articles.content` |
| articles with any image, 7 days | 5,191 / 14,991 (35%); Unsplash 1, generated 3 | `articles.image_url` |
| enrichment attempts, 7 days | 7,237 articles exhausted all 3 attempts | `articles.enrichment_attempts` |
| embeddings | **0 / 34,525** | `articles.embedding` |
| duplicate titles, 7 days | 302 | `lower(title)` |
| users / completed onboarding | 3 / 2 | `users`, `user_preferences` |

So the 3-minute loop has been feeding a pool that no reader can see since at least April,
and spending extraction, enrichment and embedding calls on it.

## Seed feed probe (all 82, live, 2026-09-02)

| measure | value |
|---|---|
| healthy (200 + entries) | 76 / 82 |
| dead | ZDNet 403 · OpenAI Blog 404 · AI News 502 · IEEE Spectrum AI 404 · The Batch 404 · IGN (200, 0 entries) |
| **AI category** | **5 of 9 alive** — the most-requested category is 44% dead |
| send ETag or Last-Modified | 48 / 76 |
| honour conditional GET with a true 304 | **45 / 76** — the code never sends one |
| advertise a WebSub hub | 2 |
| bytes per full fetch cycle | 13 MB (every 3 min ⇒ ~6 GB/day for the global list alone) |
| entries per cycle | 3,730; 0 undated |
| feeds carrying full text (>50% of entries) | 18 / 76 |
| how far back one fetch reaches (p25 / p50 / p75) | 25 h / 110 h / 527 h |
| feeds that only reach back <6 h | 6 (The Verge, TNW, Techmeme, DEV, Hollywood Reporter, Bloomberg) |

Composition problems in the list itself: gaming is 10 of 82 seeds (12%) while nobody in the
persona set asked for it; 7 NYT and 8 Guardian section feeds are separate rows, so a broad
reader can spend half a 20-source budget on two mastheads; FT, Bloomberg, Economist and
Nature are paywalled; Google News homepage RSS is seed #1 at tier `premium`; several "AI"
seeds are stale blogs (Lilian Weng last post years ago, Google AI Blog span 1,490 h). There is
no region, language or country dimension, so a Newark, Singapore or Dushanbe reader gets
nothing local from the catalog and relies entirely on Google News search feeds.

## Findings, by severity

### Critical — the pipeline cannot deliver

1. **Global ingestion is unservable.** `fetch_rss_feeds` and `fetch_topic_feeds` write only
   `articles`; the feed query inner-joins `articles ⋈ article_source_links ⋈ user_sources`.
   Confirmed in code (`news_ingestion.py:349,471`; `feed_service.py:437-471`) and in data
   (0 link rows). Audit §2.1 stands.
2. **Production is a stale deployment.** The schema lacks columns added in April; the per-user
   refresh loop cannot run (`users.last_active_at` missing). Everything on `main` since then,
   including the quality pipeline and feedback signals, is not live. Whatever S1 ships must
   come with a deploy, or it changes nothing.
3. **No reader has a feed.** `user_feed_cache` is empty, per-user fetches last ran 2026-04-13.
4. **69% of the pool is Google News redirect stubs.** `fetch_topic_feeds` builds one Google
   News search feed per unique interest term across all users, every 3 minutes, and stores the
   `news.google.com/rss/articles/...` URL unresolved (redirect resolution exists only for the
   per-user path). Stubs have no body, no image, no canonical URL, and duplicate the same story
   the publisher feed already delivered. They also carry the lowest possible extraction
   yield, which is where the 26% body rate comes from.

### High — correctness

5. **Dates parsed in local time.** `_parse_date` uses `time.mktime` on feedparser's UTC
   struct and labels the result UTC (`news_ingestion.py:170-181`). Off by the host offset
   on any non-UTC machine: +7 h on a Pacific laptop, which is exactly the 217 future-dated
   articles found in the S0 corpus. The production image is UTC, so prod is unaffected today
   by luck, not design. Fix is `calendar.timegm`.
6. **Dead feeds are recorded as healthy.** `_fetch_single_feed` swallows every error and
   returns `[]`; the per-user path then writes `failure_count = 0, last_fetched_at = now()`.
   A 404 can never trip the 5-strike deactivation. Non-200s go to `print`, not a log or a
   counter.
7. **Dedupe is exact raw URL.** No canonicalisation on the global path (`utm_*` variants
   become separate rows), no cross-feed story dedupe at write time. 302 duplicate titles in a
   week.
8. **`ingested_at` reset on conflict** in the per-user upsert defeats the 14-day GC and
   re-queues old articles for extraction. `rowcount == 1` counts updates as inserts, so every
   "inserted N new" log line is wrong.
9. **Any preference edit wipes the source graph** (`_clear_user_source_graph` at three call
   sites), including every `hide_source` the reader ever chose, then forces a fresh discovery
   with 12–20 validation fetches and an LLM call.

### Medium — efficiency and politeness

10. **No conditional GET**, although 45 of 76 feeds would answer 304. `etag` and
    `last_modified` columns exist on `user_sources` and are never read or written.
11. **Flat 3-minute cadence for everything**, including feeds whose publish interval is days.
    No adaptive cadence, no jitter, no per-host throttle, no `Retry-After`, no robots.txt.
    The only backoff logic lives in `fetch_user_sources`, which has zero callers.
12. **One DB connection held across all HTTP I/O** for the whole 3-minute cycle, from a pool
    of 10; `_ensure_tables` runs full DDL every cycle and on ~10 request handlers.
13. **Enrichment spends on a pool nobody reads.** Up to Tavily + page scrape + Unsplash + a
    GPT image-selection call + a Gemini image generation per article, three attempts; 7,237
    articles exhausted all three attempts last week and the yield was 1 Unsplash image and 3
    generated ones. 65% of last week's articles still have no image.
14. **Embeddings are 0 in production** even though the loop has an embedding step. Either the
    key had no credits or the step fails silently; nothing measures it.
15. **Two hardcoded feed lists drift**: `RSS_FEEDS` (39) in `news_ingestion.py` and
    `SEED_SOURCES` (82) in `source_discovery.py`, plus a `seed_sources` table that is a
    read-only copy.

### Low

16. `MAX_SOURCES_PER_USER`, `next_fetch_at`, `fetch_user_sources` are dead.
17. `feedparser.parse(response.text)` bypasses encoding detection; pass bytes.
18. `_guess_category` is substring matching on the URL.

## Are we using the right sources?

Partly. The publisher backbone (BBC, Guardian, NPR, Al Jazeera, DW, Ars, Verge, TechCrunch,
Bleeping, etc.) is sound, cheap and honours HTTP caching. What is wrong is the mix and the
gaps:

- **Google News should not be a source.** It is an aggregator of the same publishers, returns
  redirect stubs, has no text, and today crowds out real articles 2:1. Its one legitimate use
  is discovery of *which publisher* covers a niche term; resolve the redirect, then subscribe
  to that publisher's own feed.
- **Local and regional coverage is absent.** The catalog has no geography. The personas that
  matter most for "never miss what affects my day" (Ray, Aisha, Farrukh) have zero curated
  local sources. `tasks/source-architecture.md` already proposes the fix: a registry with
  region and language, grown from public OPML collections and feed autodiscovery, not hand
  editing.
- **Category weights are inverted.** 10 gaming feeds, 9 AI feeds of which 4 are dead, 2
  programming feeds, 1 design, 3 health, 0 local.
- **The good news:** everything a registry needs is measurable for free. The probe above is
  the coverage metric S1 asks for; it just has to run on a schedule and write to a table.

## What "bulletproof S1" should be built from (recommendation)

Ordered so each step is independently deployable and measurable with the S0 harness.

1. **Deploy what exists.** Nothing below matters until the production build is current.
   Add the build SHA to `/healthz` so staleness is visible.
2. **One registry: `sources` table.** Columns: url, canonical home, name, category, region,
   language, tier, active, etag, last_modified, last_fetched_at, next_fetch_at,
   consecutive_failures, publish_interval_estimate, last_yield. Seed it from `SEED_SOURCES`
   plus the probe results; drop `RSS_FEEDS`. `user_sources` becomes a subscription table
   (user_id, source_id, weight, hidden) and stops duplicating fetch state per user.
3. **One central poller** that replaces `_ingestion_loop` + `_fetch_from_user_sources`:
   conditional GET, `calendar.timegm`, canonical URL dedupe, per-source adaptive cadence
   (`publish_interval_estimate` clamped 5 min – 6 h, jittered), per-host concurrency 2,
   `Retry-After`, failure counting on *any* non-200 or parse error, deactivation at N strikes,
   automatic re-probe of deactivated feeds daily. Writes `articles` **and**
   `article_source_links` for every article, every time.
4. **Retire Google News as a source.** Replace `fetch_topic_feeds` with a discovery job: run
   the search feed once per new interest term, resolve redirects, extract publisher domains,
   autodiscover their feeds, add to the registry. Never store a `news.google.com` URL.
5. **Gate enrichment on reachability and value.** Enrich only articles that at least one
   subscribed source delivered, and only after retrieval marks them as candidates. Kill the
   Gemini image generation and the GPT image-selection call unless a measured yield justifies
   them; last week's yield was 4 images.
6. **Coverage metrics in `source_health`,** written by the poller: articles seen vs. published
   per feed, 304 rate, bytes, latency, failures. Expose `/admin/sources` and alert on
   ≥5% dead. The S0 runner can then replay a day's poller output against labels.
7. **Grow the registry** per `source-architecture.md` layer 1: OPML imports and feed
   autodiscovery by region, targeting 500 feeds with local/regional coverage before 2,000.

## What S0 will measure for S1

`recall_at_retrieval` and `loss_by_stage:lookback` from the harness are the acceptance
numbers: today 85 of the prototype's missed must-sees never even load. After step 3, the
central poller's output for a frozen day can be replayed through `evals.run` and the
lookback loss should drop toward zero while `never_rate` holds.
