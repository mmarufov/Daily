# Source Architecture — how to actually get everything

Answer to: *what sources, from where, and how do we fetch them so the AI can filter
through them ALL properly.*

Companion to `tasks/personalization-audit.md`. Everything marked **[measured]** was
verified live from this machine on 2026-08-31.

---

## 0. The reframe

"Get every news" is not one problem, it's three. The current app fails all three because it
tries to solve them with one mechanism (a small per-user RSS list).

| Problem | What it means | Wrong tool | Right tool |
|---|---|---|---|
| **Depth** | If you follow The Verge, see **100%** of what The Verge publishes | Aggregator APIs | Direct RSS/Atom |
| **Breadth** | Catch the story from a site you've never heard of | A fixed 82-feed seed list | A firehose + targeted queries |
| **Shape** | The pool must be **global**, not per-user | `user_sources` as a *gate* | `user_sources` as a *boost* |

The third one is the actual root cause. Today every user has a private 12–20 feed pool and
the candidate query can only see articles linked to *their* sources. Personalization must be
a **ranking over a shared pool**, not a **filter on a private pool**. Fix that and the
sourcing question gets much easier, because you're building one pool instead of N.

---

## 1. Recommended stack

### Layer 1 — Core RSS backbone (~2,000–5,000 feeds) — *the workhorse*

This is where ~90% of articles should come from. Free, complete per source, 1–15 min latency,
no vendor risk, no rate limits you don't control.

**[measured] Feasibility** — polled 10 real publisher feeds:

```
feed                                    KB    sec  ETag  LMod  revalidate
feeds.arstechnica.com/arstechnica/...   76   0.25  False True  304 NOT MODIFIED
www.theverge.com/rss/index.xml          31   0.16  True  False 304 NOT MODIFIED
techcrunch.com/feed/                    17   0.10  True  True  304 NOT MODIFIED
www.theguardian.com/world/rss          148   0.22  True  False 304 NOT MODIFIED
www.polygon.com/rss/index.xml           19   0.82  False False n/a
feeds.bbci.co.uk/news/rss.xml           27   0.44  False False n/a
rss.nytimes.com/.../HomePage.xml        38   0.13  False False n/a
feeds.npr.org/1001/rss.xml              15   0.47  False False n/a
www.wired.com/feed/rss                  46   0.13  False False n/a
www.pcgamer.com/rss/                  1586   1.00  False False n/a
---------------------------------------------------------------------------
10 feeds, 2001 KB, 1.0s wall @ 10 threads
```

- **4/10 support conditional GET and returned real `304 Not Modified`.** Store `ETag` /
  `Last-Modified` per feed and send `If-None-Match` / `If-Modified-Since`. Those fetches
  become ~300 bytes instead of ~40 KB.
- For the 6/10 that don't, hash the body and skip parsing when unchanged.
- Median feed ≈ 30 KB; `pcgamer.com` at 1.5 MB is the fat-tail outlier to watch.
- **2,000 feeds ≈ 65 MB/cycle at the median, ~390 MB at the (outlier-skewed) mean.**
  At 50 concurrency that's well under a minute per cycle. This is not a hard problem.

**Where to get 2,000+ feeds** (seed once, then grow):
- Public OPML directories — `plenaryapp/awesome-rss-feeds` (~500 recommended + 250+ country
  sources, per-category OPML), `fuxiaoai/tidings-rss` (718 live-verified sources across 14
  categories), `sg-s/science-journal-feeds` (4,700+ academic/journal feeds).
  *(Identified via search; GitHub raw is blocked from this sandbox so not fetched live.)*
- **RSS auto-discovery** — for any domain, parse `<link rel="alternate" type="application/rss+xml">`
  plus common paths (`/feed`, `/rss`, `/index.xml`, `/atom.xml`). This is how you turn "a
  publisher name" into "a feed URL" automatically.
- **News sitemaps** — for publishers with no feed. Google's news sitemap spec caps entries at
  48 hours old, which makes them a clean recency stream. Google's own guidance is to use
  sitemaps *and* feeds: sitemaps for complete URL inventory, feeds for update signal.
- Keep the existing LLM feed-suggestion step, but write results to the **global** registry
  instead of one user's `user_sources`. Every user's discovery permanently improves the pool.

**Polling cadence** — tier by observed publish rate, not a flat 15 min:
`hot` (wires, high-volume) 5 min · `normal` 15 min · `slow` (weekly blogs) 6 h.
Auto-demote feeds that 304 repeatedly.

**Optional upgrade — WebSub/PubSubHubbub.** Publishers that support it (most WordPress sites
via the WebSub plugin) will *push* you updates instantly via webhook. Zero polling, zero
latency. Subscribe where advertised, fall back to polling elsewhere.

---

### Layer 2 — GDELT, the free global firehose — *breadth*

**[measured] It works and it's live.** `https://api.gdeltproject.org/api/v2/doc/doc`
returned HTTP 200 with clean JSON, newest item stamped `20260831T001500Z` (~15 min old):

```json
{"url": "...", "title": "...", "seendate": "20260831T001500Z",
 "socialimage": "https://...", "domain": "makeuseof.com",
 "language": "English", "sourcecountry": "United States"}
```

That payload is enough to **score a candidate without fetching the page** — and it even
carries `socialimage`, which would solve the app's image-hydration problem for free.

Two access modes:
- **DOC 2.0 API** — full-text search, rolling 3-month window, 65 languages,
  `domain:` / `sourcelang:` / `sourcecountry:` / `theme:` / `tone` operators, JSON output.
  Free. **Constraints:** `maxrecords` caps at 250 with *no offset or cursor*, and it's
  aggressively rate limited — **[measured]** I got connection resets at ~1 req/6s, so budget
  ~1 request per 5–10s and cache hard.
- **Raw 15-minute firehose** — **[measured]** `http://data.gdeltproject.org/gdeltv2/lastupdate.txt`
  is currently serving `20260831011500.gkg.csv.zip` at **2.4 MB compressed per 15 min**.
  GKG carries URL, `<PAGE_TITLE>` (in the `Extras` field since Sept 2019), themes, persons,
  organizations, locations, and tone across 500K–1M articles/day. No rate limit — it's just
  file downloads. This is the real firehose.

**[measured] The critical caveat — GDELT is thin on niche publishers:**

```
domain            articles/24h
polygon.com                 14
theverge.com                 3
arstechnica.com              2
```

The Verge publishes 30–50/day; Ars ~15–20. So GDELT is capturing roughly **5–15%** of what
niche tech publishers put out. **It is a mainstream/world-news firehose, not a completeness
layer.** Use it for breadth only. This measurement is precisely why Layer 1 cannot be skipped.

---

### Layer 3 — Targeted entity queries — *never miss X*

For pinned entities ("Anthropic", a specific team, a person), run GDELT DOC queries centrally,
deduped across users, cached. One query serves every user who cares about that entity.

**Retire Google News RSS.** The app currently ranks Google News query feeds *highest* in
discovery (`score += 0.8` vs `0.55` for curated seeds) and builds one per user topic. Per a
July 2026 sampling of 48 queries, Google News RSS has:

- ~**100 item cap**, no `page` / `offset` / `limit`
- **≈6.6-day median item age; only 7.6% of items ≤6 hours old**
- `news.google.com` redirect URLs, not publisher URLs
- no thumbnails, frequently no snippets, no SLA

The app's candidate window is **72 hours**. So its highest-scored discovery sources are
structurally delivering content that is mostly *already outside the retrieval window* — and
the redirect URLs are what force the `_resolve_redirect_urls` HEAD-request workaround. This
single choice explains a large share of "the feed is empty / stale / missing things."

---

### Layer 4 — Commercial API, only if a measured gap remains

Don't buy until Layers 1–3 are running and you can point at what they miss.

| Provider | Free tier | Notes |
|---|---|---|
| **Newsdata.io** | 200 credits/day, commercial use allowed | 100K+ sources, 206 countries, 89 languages, 10-yr archive. Best free tier. |
| **Perigon** | Free plan listed at $0; paid from **$250/mo** | 200K+ sources, entity knowledge graph, bias + paywall labels, up to 1M articles/day. Explicitly built for AI agents. Strongest fit if you pay. |
| **NewsAPI.ai** (Event Registry) | Token-based, limited | ~150K publishers, **full article text**, 12+ yr archive, event clustering. |
| **Webz.io** | Limited | Enterprise compliance/multilingual. |
| **GDELT** | Free, unlimited files | Already Layer 2. |

---

## 2. The change that makes broad ingestion affordable

Ingesting 20K–60K articles/day means you **cannot** LLM-score them per user. You don't have to
— and the app already has the missing piece sitting unused.

```
1. Embed every article once, globally          ← already happening, unused by the feed
2. Embed each user profile once per change
3. Retrieve per user by vector similarity + recency + source affinity   ← pgvector HNSW index already exists
4. LLM-score only the top ~150
```

**Cost:** `text-embedding-3-small` is **$0.02/M tokens** ($0.01/M via Batch API).
50K articles/day × ~500 tokens = 25M tokens/day ≈ **$0.50/day, ~$15/month.**

LLM scoring spend stays **flat** — same ~3 batch calls per user per refresh — but over a
candidate set drawn from millions of articles instead of 300 recency-ordered rows from 12
feeds. That is the entire trick: bandwidth is cheap, embeddings are cheap, and the expensive
model only ever sees a pre-filtered shortlist.

It also retires the deterministic keyword prefilter that is currently the real gatekeeper
(audit §3d) — the thing that drops relevant articles before the LLM ever sees them.

---

## 3. Order of operations

1. **Global pool.** Make `user_sources` a ranking boost, not a join gate. Fixes the
   `article_source_links` dead-end (audit §2.1) and unblocks everything below.
2. **Kill Google News RSS** as a discovery source; replace with GDELT DOC queries.
3. **Grow the registry** 82 → 2,000+ feeds; poll centrally with conditional GET + tiered cadence.
4. **Switch retrieval** from keyword prefilter to embedding + recency hybrid.
5. **Add the GDELT GKG firehose** for breadth beyond the registry.
6. **Then** evaluate a paid API against a measured gap — not before.

---

## 4. How to know it's working

"Not missing anything" needs a number, or it's a vibe. Track:

- **Recall probe** — keep a rolling list of stories you *know* mattered for a profile
  (hand-picked, or scraped from a vertical's front page). Measure: what % entered the pool
  within 1 h? Reached the shortlist? Made the feed?
- **Pool coverage** — for each registry feed, articles ingested vs articles the feed published.
  Anything well under 100% is a broken fetch, not a ranking problem.
- **Time-to-pool** — p50/p95 minutes from publish to ingested.
- **Shortlist yield** — of the ~150 sent to the LLM, how many survive? Too high means the
  retrieval is too narrow; too low means you're burning tokens.

---

*Sources: GDELT DOC 2.0 API docs + live queries; GDELT GKG codebook; cloro.dev Google News RSS
July-2026 sampling; provider pricing pages; OpenAI embeddings pricing. Full links in the chat
response accompanying this document.*
