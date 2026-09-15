# Plan — news filtering architecture

How every article gets from a feed into (or out of) each reader's edition, without
missing a major event and without paying to re-decide the same thing for every user.

Companion docs: `personalization-audit.md` (what's broken), `source-architecture.md`
(where articles come from), `stage-a-global-pool-spec.md` (the pool refactor this assumes).
Working proof: `backend/evals/`.

---

## 0. What is already measured

Not projections — these came out of runs against 1,328 live articles from 51 feeds.

| Finding | Evidence |
|---|---|
| Today's scoring is keyword-only in production | OpenAI key had no credits → every batch fell to the deterministic fallback |
| Keyword matching passes 31–66% of the whole corpus | Ray 416/1328, Wei 882/1328 |
| Substring matching is the root cause | `"ai" in "entertainment"` → True; Ukraine classified as an AI interest |
| Typed intents + hybrid retrieval + LLM judge works | Wei 0/12 → 12/12 on target |
| Full pipeline is cheap | **$0.0145** for three readers, event detection included |
| Global event detection is nearly free | **$0.0007**, one call, shared by all readers |
| Title-token clustering cannot find a war | 19 Iran headlines → 17 clusters, max breadth 2 |
| Semantic clustering can | 7 articles / 6 outlets at cosine 0.55 |
| Breadth ≠ importance | A telescope launch (6 tech blogs) outscored a war |

### Prior art — what the incumbents actually do

Checked before designing, because being novel here is a warning sign, not a feature.

- **TikTok, Google Discover, YouTube** all use the same two stages: **candidate generation**
  (fast approximate-nearest-neighbour over a *shared* index, millions → ~100) then
  **ranking** (expensive per-user model on those ~100 only). TikTok picks ~100 videos from
  hundreds of millions this way. Not one of them runs a search per user.
- **Artifact** (Instagram founders' AI news app) bucketed each reader into a **persona**,
  used a transformer to select articles, and fine-tuned continuously with reinforcement
  learning. Systrom's framing: the shift from a *follow graph* to an **inferred graph** —
  the system learns what you want from behaviour rather than asking.
- **Artifact shut down anyway**, and Systrom's postmortem blamed **market size, not
  technology**. An elite ML team with better retrieval than we will build was not saved by
  it. Read that as: retrieval sophistication is table stakes, not the differentiator.

The architecture below is the same two-stage shape, which is the point.

---

## 1. The core reframe: classify once, match many

Today the shape is **pull**: a user refreshes, we search the pool, then an LLM judges ~150
articles *for that user*. Every article gets re-judged from scratch for every user who
retrieves it. The work is duplicated exactly as many times as you have readers.

The fix is to split the judgment into the part that is the same for everybody and the part
that isn't:

| User-independent — do once, at ingest | User-dependent — per reader, no LLM |
|---|---|
| What is this about? (topics, entities, places, kind) | Does it match this reader's intents? |
| How important is it? (gravity tier) | Does it hit an exclusion? |
| Which story is it part of? (cluster) | Is their home press covering it? |
| How substantial is it? (depth, quality) | Where does it rank against their other candidates? |

Once an article carries a structured **facet card**, matching a reader to it is arithmetic
— vector similarity plus rule checks. The expensive semantic understanding happens once and
is amortised across every reader.

### What this is worth

Modelled on measured per-call token counts, `gpt-4o-mini`, hourly refresh, 50K articles/day:

| Readers | Per-user judge (today's shape) | Classify-once | |
|---|---|---|---|
| 100 | $428/mo | **$50/mo** | 8.6× |
| 1,000 | $4,277/mo | **$348/mo** | 12× |
| 10,000 | $42,768/mo | **$3,100/mo** | 14× |

The remaining cost is dominated by per-user *adjudication*. §4 cuts that further by only
invoking it on genuinely borderline articles rather than every refresh — most refreshes
resolve deterministically and cost nothing.

### The second benefit: freshness

Pull means a reader sees breaking news at their next refresh, bounded by a 60-minute cache.
Push means the moment an article is carded we know who wants it. **Standing queries**: each
reader's intent vectors sit in an index; a new article is matched against *readers* instead
of readers searching *articles*. Breaking news lands in seconds, and the staleness problem
in the current cache design disappears.

---

## 2. The article facet card

One structured record per article, written once, reused by every reader forever.

```jsonc
{
  "article_id": "…",
  "cluster_id": "evt_…",             // which story this belongs to
  "kind": "report|analysis|opinion|roundup|listicle|promo|obituary",
  "topics":   ["monetary policy", "trade"],   // controlled vocabulary
  "entities": [{"name": "Emomali Rahmon", "type": "person"},
               {"name": "NJ Transit",     "type": "org"}],
  "places":   [{"name": "Tajikistan", "scope": "country"},
               {"name": "Dushanbe",   "scope": "city"}],
  "is_about": "one sentence: what actually happened",
  "novelty":  0.0,                   // 0 = follow-up, 1 = first report of a new development
  "depth":    "brief|standard|deep",
  "commercial": false                // sponsored / affiliate / casino spam
}
```

Why each field earns its place — every one of these fixes a failure I actually observed:

- **`kind`** — `NJ.com`'s *"Highest RTP slots to play at the best NJ online casino"* ranked
  #1 for Ray under today's scoring. `kind: promo` + `commercial: true` kills it with a rule,
  no model call.
- **`entities`** — "Mikal Bridges" matched a flood story about *bridges*. Resolved entities
  don't do substring collisions.
- **`places` with scope** — separates "about New Jersey" from "mentions a Chelsea jersey",
  and lets home-press logic work on structure instead of a hand-written source map.
- **`topics` from a controlled vocabulary** — a Zelda mod does not get tagged
  `software engineering` however similar its embedding looks.
- **`novelty`** — the 5th follow-up on a story a reader already saw should not displace
  something new. Today there is no signal for this at all.
- **`is_about`** — the honest source for the "why this story" line, replacing today's
  template string.

**Cost:** ~25 articles per call. Card lazily — only when an article first enters *some*
reader's candidate set — then cache permanently. At 1,000 readers that's ~20K cards/day,
**$31/mo**. Cards never expire; an article is only ever carded once.

---

## 3. Where each stage runs

```
  ┌─ GLOBAL, CONTINUOUS ──────────────────────────────────────────────┐
  │  poll sources ─▶ dedupe ─▶ embed ─▶ cluster ─▶ facet card         │
  │                                        │                          │
  │                                        ▼                          │
  │                              breadth gate (arithmetic)            │
  │                                        │                          │
  │                                        ▼                          │
  │                              gravity call (1 per cycle)           │
  └───────────────────────────────────────┬───────────────────────────┘
                                          │  event tiers, shared by all
  ┌─ PER READER, ON ARRIVAL OR REFRESH ───▼───────────────────────────┐
  │  intent match (vectors + card rules)  ── no LLM                   │
  │  confident keep ──┐         confident drop ──┐                    │
  │  borderline band ─┴─▶ adjudication (small)   │                    │
  │                                              ▼                    │
  │  assemble: world-critical first, cluster dedupe, intent quotas,   │
  │            home-press selection, novelty decay ── no LLM          │
  └───────────────────────────────────────────────────────────────────┘
```

Only two things call a model: **facet carding** (shared) and **gravity** (shared). The
per-reader path is arithmetic except for a narrow adjudication band.

---

## 4. Matching without an LLM

For each reader intent × candidate article:

```
score = 0.55 · cosine(intent_vector, article_vector)      // meaning
      + 0.25 · facet_match(intent, card)                  // entity/place/topic overlap
      + 0.10 · source_affinity(reader, source)            // learned + home region
      + 0.10 · freshness(published_at)
      − penalties: exclusion hit, kind ∈ {promo, roundup}, novelty < 0.3, already_seen
```

Three bands:

- **≥ 0.62 → keep.** Deterministic. No call.
- **≤ 0.38 → drop.** Deterministic. No call.
- **between → adjudicate.** Batch across the reader's borderline set, one call, ~15 articles.

The bands get calibrated against labelled ground truth (§9) — they are not guesses to be
left at whatever I typed. The goal is that the borderline band holds under ~15% of
candidates, so most refreshes make zero model calls.

**This is where the earlier design was wasteful:** it sent all 150 candidates to the judge,
including ones scoring 0.9 and 0.05. Those never needed a model.

---

## 5. Major-news detection — the two-key rule

Your constraint is the hard part: **never miss a genuinely major event, never manufacture
one.** Those pull in opposite directions, so the design requires two independent keys and
neither can open the door alone.

### Key 1 — measured breadth (objective, no model)

Computed from the pool. A model cannot inflate it.

```
spread = distinct_outlets + 2·distinct_verticals + 2·distinct_regions
```

Cross-vertical and cross-region spread are what separate a real event from one section's
obsession. A story in world + business + local press across four countries is structurally
different from six tech blogs on the same launch. **Only clusters clearing the gate are
ever shown to the model.** A single-source scoop cannot become "major" no matter how
dramatic its headline.

### Key 2 — gravity (model, one call, shared)

Given only the shortlist, classify into an explicit taxonomy — broadened past the war
example to what you actually meant:

| `world_critical` | `major` | `routine` |
|---|---|---|
| Armed conflict between states; attacks | National election in a mid-size country | Sports results |
| **Head of state or government changes** (election result, resignation, removal, coup) | Significant regional politics | Business as usual |
| **Institutional rupture** — alliance collapse, treaty exit, sanctions regime, bloc realignment | Big product launch | Features, opinion |
| Market/currency/banking crisis with cross-border reach | Notable scientific result | Follow-ups |
| Mass-casualty disaster, pandemic | Major industry consolidation | Roundups |

### Guarding against invented importance

1. **Both keys required.** Breadth gate is arithmetic; gravity is judgement. Either alone is
   insufficient. This is the structural guarantee.
2. **Zero is the expected answer.** The prompt states most days have none, and returning an
   empty list is correct. Verified behaviour on this corpus: of **98** multi-source events,
   exactly **1** came back `world_critical`; 2–3 `major` and the remaining ~95 `routine`
   across runs. Note the run-to-run variance in the `major` band — the tier boundary is
   soft, which is another reason `world_critical` needs the breadth gate under it rather
   than resting on the model alone.
3. **Rate monitor.** Track `world_critical` per day. Sustained > 2/day means the classifier
   has drifted — alert, don't silently over-inject.
4. **Cap per edition.** At most 2 forced slots per reader, ever. A feed cannot become a
   generic front page even if detection misfires.
5. **Fail closed.** If the gravity call errors, nothing is `world_critical`. Failing open
   would override every reader's preferences on an API hiccup — the worst possible failure.
6. **Decay.** An event stays forced for a bounded window (~12h) and only surfaces once per
   reader. Day-three follow-ups compete on merit like everything else.

### Delivery

`world_critical` is injected at position 1 and **the per-reader matcher cannot reject it**.
This is deliberate: the judge rejecting a war for Ray as *"not about New Jersey"* is a
correct relevance judgement that produces the wrong feed. Relevance and importance are
different questions, and only relevance is the reader's to decide.

Which *copy* they get is chosen by home-press preference gated on centrality — strict
(0.95) for world-critical so clarity wins, looser (0.82) for regional so local framing
survives. Measured: this is what stopped a US reader being handed *"Oil rises 1% after US
forces strike Iranian rockets"* instead of *"US strikes Iranian launchers in the strait of
Hormuz"*.

---

## 6. Data model

```sql
CREATE TABLE article_facets (
    article_id   UUID PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    cluster_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    topics       JSONB NOT NULL DEFAULT '[]',
    entities     JSONB NOT NULL DEFAULT '[]',
    places       JSONB NOT NULL DEFAULT '[]',
    is_about     TEXT,
    novelty      REAL DEFAULT 0.5,
    depth        TEXT,
    commercial   BOOLEAN DEFAULT false,
    carded_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON article_facets (cluster_id);
CREATE INDEX ON article_facets USING gin (topics jsonb_path_ops);
CREATE INDEX ON article_facets USING gin (entities jsonb_path_ops);

CREATE TABLE story_clusters (
    cluster_id     TEXT PRIMARY KEY,
    centroid       vector(1536),
    first_seen     TIMESTAMPTZ NOT NULL,
    last_seen      TIMESTAMPTZ NOT NULL,
    outlets        INTEGER DEFAULT 0,
    verticals      INTEGER DEFAULT 0,
    regions        INTEGER DEFAULT 0,
    spread         INTEGER DEFAULT 0,
    tier           TEXT DEFAULT 'routine',   -- world_critical | major | routine
    what           TEXT,
    tier_set_at    TIMESTAMPTZ
);
CREATE INDEX ON story_clusters (tier, last_seen DESC);

-- Standing queries: match articles to readers, not readers to articles.
-- (user_interest_vectors is defined in stage-a-global-pool-spec.md)
CREATE TABLE reader_matches (
    user_id      TEXT NOT NULL,
    article_id   UUID NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    score        REAL NOT NULL,
    matched      JSONB NOT NULL DEFAULT '[]',   -- which intents, for "why this story"
    band         TEXT NOT NULL,                 -- keep | borderline | drop
    forced       BOOLEAN DEFAULT false,
    created_at   TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (user_id, article_id)
);
CREATE INDEX ON reader_matches (user_id, score DESC) WHERE band <> 'drop';
```

---

## 7. Rejected: per-user agentic deep search

Worth writing down, because it is the intuitive design and the numbers kill it.

**The idea:** skip the pipeline. A few times a day, run an agentic web search per reader
that figures out exactly what they want and pulls those articles.

**Published costs:** `o4-mini-deep-research` ≈ **$0.41** per typical query,
`o3-deep-research` ≈ **$1.45** (up to $30). One team spent **$100 on ten queries** with o3.
Each query fires 10–30 web searches, adding $0.10–0.30 in search fees on top.

Against a $9.99 subscription (≈$8.49 net after Apple's 15%):

| runs/day | $/query | $/user/mo | % of net revenue |
|---|---|---|---|
| 1 | 0.41 | 12.30 | **145%** |
| 3 | 0.41 | 36.90 | **435%** |
| 3 | 1.45 | 130.50 | **1537%** |
| — | pipeline | **0.35** | **4.1%** |

**Even one run per day loses money before any other cost.** Break-even at 3 runs/day needs
$0.038/query — 10× cheaper than the cheapest tier available.

Three further problems, independent of price:

1. **It cannot detect major news.** Knowing a story is "everywhere" requires seeing
   everywhere *at once*. A per-reader search sees only its own results. The requirement we
   care most about is the one this design structurally cannot meet.
2. **Latency.** Deep research takes minutes; a feed opens in under a second. You would
   pre-compute anyway — at which point it is a pipeline with a worse engine.
3. **Inherited staleness.** Measured: Google News RSS has a **6.6-day median item age**,
   only 7.6% under six hours. Search indexes lag breaking news; publisher feeds do not.

### What survives — cache at the interest level, not the user level

The instinct is right, the granularity was wrong. Readers' interests overlap enormously.
A hundred readers who care about "AI engineering" should trigger **one** search, not a
hundred. Fire it only where the pool measurably fails:

```
for each interest across all readers:
    if pool_candidates(interest, last_24h) < threshold:
        result = agentic_search(interest)     # once, cached by interest
        serve to every reader holding that interest
```

If ~10% of interests need this, it lands near **$0.25/reader/month** — deep-search quality
exactly where the pipeline is blind, at pipeline economics.

Three more places it is the right tool, all bounded:
- **Cold start** — one bootstrap run for a new reader.
- **"Tell me more"** — reader-initiated, so latency is expected and cost is capped.
- **Source discovery** — finding feeds not yet in the registry (`source-architecture.md`).

---

## 8. Implementation phases

Each phase is independently shippable and independently verifiable.

**Phase 1 — Close the feedback loop.** *Moved to first.* `not_relevant` / `more_like_this` /
`less_like_this` currently write to `reading_events` and are read by nothing, so a
correction changes nothing and the article returns next refresh. Make them edit the
reader's intent weights and rubric. Smallest change on this list, and the only one that
makes the app feel like it is learning.
*Verify:* marking an article not-relevant demonstrably changes the next edition.

Why first: every other phase improves *retrieval*. Artifact had better retrieval than we
will build and still shut down. What makes a feed feel like mind-reading is the loop — the
shift Systrom described from a follow graph to an **inferred graph**, where the system
learns what you want from behaviour instead of asking. Ours is disconnected.

**Phase 2 — Global pool.** Per `stage-a-global-pool-spec.md`. Drop the `user_sources` join
gate, central poller, multi-vector retrieval. *Everything below assumes a shared pool.*

**Phase 3 — Clustering + events.** Port `evals/global_events.py` to production:
`story_clusters`, semantic clustering on the existing `articles.embedding`, breadth
scoring, one gravity call per ingest cycle. Ship the six guards from §5.
*Verify:* seed a known major event, confirm it is detected and that a quiet corpus yields zero.

**Phase 4 — Facet cards.** `article_facets`, lazy carding, controlled topic vocabulary.
*Verify:* casino spam is `kind: promo`; a Zelda mod is not tagged software engineering.

**Phase 5 — Deterministic matching.** Replace the per-user judge with banded scoring plus
narrow adjudication. Calibrate the bands against labels.
*Verify:* feed quality holds at ≥ the Phase-3 baseline while model calls per refresh drop
from 6 to ≤1.

**Phase 6 — Push.** Standing queries; write `reader_matches` at ingest instead of on
refresh. Feed read becomes a plain indexed SELECT.
*Verify:* p95 publish-to-feed latency under 5 minutes.

**Phase 7 — Interest-cached agentic search.** The gap-filler from §7, triggered by measured
pool misses. Needs Phase 2's coverage metrics to know when to fire.
*Verify:* cost per reader-month stays under $0.60 all-in.

### Cold start — borrowed from Artifact

Artifact classified each new reader into a **persona** with a standard constellation of
interests, then refined individually from behaviour. That is a clean answer to the problem
where a fresh account has no vectors and no history: assign the nearest persona, serve its
feed immediately, and let the loop specialise it. Cheap, and it means the first session
already looks personalised. Fold into Phase 1.

---

## 9. How we will know it works

The harness exists; what it lacks is labels. Before Phase 4 tuning, hand-label a few hundred
corpus articles per persona `must-see` / `fine` / `never`. Then, as a CI gate:

| Metric | Target |
|---|---|
| recall@12 on `must-see` | ≥ 0.8 |
| `never`-rate in delivered feed | ≤ 0.05 |
| major-event delivery (when one exists) | 1.0 |
| false-major rate (forced slots on a quiet day) | 0 |
| model calls per reader-refresh | ≤ 1 |
| p95 publish → feed | ≤ 5 min |
| cost per reader-month | ≤ $0.40 |

Include the hard cases already found: right-word-wrong-thing (Chelsea *jersey*), exclusion
collisions, routine coverage of a secondary interest, and day-three follow-ups.

---

## 10. Risks

- **Facet cards inherit model error.** A miscarded article is wrong for every reader
  forever, not just one. Mitigation: cards are cheap to recompute — version them and
  re-card on schema change. Spot-check card accuracy as part of the CI gate.
- **Controlled vocabulary drifts.** Free-text topics will fragment ("AI" / "artificial
  intelligence" / "machine learning"). Fix the vocabulary, map synonyms at card time.
- **Clustering threshold is corpus-sensitive.** 0.55 was tuned on 1,328 articles. Re-tune at
  10× volume; over-merging silently inflates breadth and is the most likely path to a
  false major event.
- **Push amplifies bugs.** A bad match writes to every affected reader immediately with no
  refresh boundary to catch it. Ship Phase 5 behind a flag with a kill switch.
- **Cold start.** A new reader has no intent vectors and no learned affinity. Fall back to
  gravity + broad recency until the profile is built.
