# S10 Learning — analyse and challenge

Reviewed 2026-09-10 against `mmarufov/sydney-v7`, including the uncommitted S1–S9 worktree.
Scope: analysis, literature review and implementation plan only. No runtime change. One
read-only production query was run (below); no write, deploy or paid provider call was made.

Four independent read-only agents traced, respectively: the iOS client signal-capture path,
the backend signal-ingestion/reader-update path, the S5–S8 module contracts (reader state,
`CandidateBatch`, judgments, receipts), and the S0 evaluation harness. Findings below cite
`file:line` from their reports; I re-verified the highest-leverage ones directly (grep/read)
rather than taking every line on faith. Literature claims were checked against primary
sources via live search where marked "verified 2026-09-10"; the rest draws on established,
widely-reproduced results I'm confident of independent of search. Nothing here invents an
API, a schema, or a paper that doesn't exist — where I wasn't sure, I say so.

## Conclusion

**systems.md's "explicit half done" undersells the discovery-worthy part of the problem and
mischaracterizes the reachable part.** The real state is:

1. **Three parallel candidate learning systems exist in the repository, not one.** Legacy
   (`feedback_signals.py`, default-on), S5 (`reader_feedback.py`, default-off), and S7's
   consumption of S5's `learned` dict (default-off). None of the three is what a reader would
   recognize as "S10" — there is no dedicated module, no OPERATIONS.md, no schema file named
   for it. The learning logic is smeared across the S5 codebase and one legacy service file.
2. **The default-on legacy path has never executed against a real signal in production.**
   Direct query against the deployed database (below) shows **0 rows, ever**, in
   `reading_events`; the table doesn't even carry a `client_event_id` column in production
   (the additive S5 migration hasn't run there). `source_quality` — the only production table
   with any accumulated numbers — has 120 impressions and 0 taps/reads/duration across 9 rows,
   because nothing has ever tapped through to it. **The learning system's entire lifetime
   production dataset is zero labeled examples.** This is the fact that must govern every
   architectural decision below, not an afterthought to mention once.
3. **The systems.md "+0.2 entity boost... has never fired for anyone" claim is correct in
   effect but wrong in mechanism.** The code path IS reachable — `feed_service.py:1220-1229`
   runs in the default (legacy, S5/S7 off) configuration — but the boost is *structurally*
   unreachable because its only inputs, `entity_pins`, are populated by an endpoint with
   **zero iOS call sites** (`BackendService.swift:950-1029`, ten routes, confirmed dead by
   both the iOS and backend trace agents independently). Separately and more subtly, the
   *strongest declared* legacy signal — `KIND_FACTORS["topic"] = 1.0` in
   `feedback_signals.py:40` — is dead for a different reason: `_annotate_candidate_feed_roles`
   (which populates `matched_profile_signals`) runs at `feed_service.py:230`, **one call
   after** `_apply_individual_analysis_results` at `feed_service.py:229` already scored the
   candidate. The topic-weighted path (the one meant to matter most) has silently never fired
   for any reader, ever, independent of the entity-pin UI gap. Two separate, independently
   discovered defects, both landing on "the biggest lever doesn't move."
4. **The bounded S5 learned overlay (`reader_learned_signals`, `reader_feedback.py`) is the
   best-engineered piece of this whole system** — semantic-hash-fenced attribution, decay
   applied before accumulation (not after, unlike the legacy table), generation-fenced reset,
   immutable delivery receipts, `test_ranking_feedback.py`'s 15 tests specifically exercising
   this path (decay-before-add, semantic-hash fencing, reset, receipt-proof requirements),
   plus a feedback-relevant subset of `test_reader_integration.py`'s 20 and
   `test_reader_repository.py`'s 8 (allocation, replay, pre-reset rejection — those two files
   also cover general reader-mutation correctness unrelated to learning, so their full counts
   aren't all "learning" tests). It is also completely inert:
   `S5_READER_ENABLED=false` by default, and even if enabled, **S6 retrieval explicitly
   refuses to consume it** (`docs/stages/s6-implementation-plan.md:133`: *"Do not apply S10 learned
   weights here initially: keep the retrieval comparison independent of learning"*), and S8
   assembly doesn't reference it at all. In the fully-enabled S5+S7 configuration, the only
   place learning can act is a ±25%/−50% multiplier on an *already-accepted* candidate's
   priority within its *already-assigned* grade tier (`ranking_service.py:129-131`) — it
   cannot rescue an abstained or rejected article, cannot affect what enters the candidate
   pool, and cannot affect diversity/slot allocation in S8. **Even switched fully on, "S10"
   today can only nudge order among things S7 already decided to show. It cannot yet change
   what is retrieved or whether something is shown at all.**
5. **The evaluation harness cannot see any of this.** `evals/fake_db.py:160-162` returns `[]`
   for `user_feedback_signals`, `reading_events`, `entity_pins`, `source_quality`
   unconditionally. All 10 personas are static preference documents with **zero behavior,
   zero session, zero click model** (confirmed by the S0 trace agent — zero hits for
   propensity/click-model/session machinery anywhere in `backend/evals/`). **There is
   currently no way, even in principle, for this repository's test suite to tell you whether
   a change to the learning system helps or hurts.** That is the single most important gap
   this audit identifies, and it is cheaper to close than any of the modeling work everyone's
   instinct reaches for first.

The instinct this task's framing invites — "what would TikTok/YouTube/Instagram do" — is the
wrong first question for a system with these numbers. The right first question is: *what is
the smallest, most honestly-evaluable thing that turns zero examples into the first hundred,
without breaking anything upstream that already works?* Sections 2 and 5 below answer that
directly, and reject (with citations, not vibes) the parts of the "impressive architecture"
brief that don't fit a 3-user portfolio app.

---

## Production measurement (ground truth, 2026-09-10)

Read-only query via the Supabase pooler (`SET default_transaction_read_only = on`), against
the same database `project_prod_deployment_state.md` describes as stale relative to `main`.

| table | rows |
|---|---:|
| `users` | 3 (created 2026-03-15, 03-21, 03-31 — no signups since March) |
| `user_preferences` | 2 |
| `reading_events` | **0** (`min/max(created_at)` both `NULL`) |
| `user_feed_cache` | 0 |
| `entity_pins` | 0 |
| `interest_suggestions` | 0 |
| `articles` | 27,922 (11,049 in the last 7 days — ingestion is alive) |
| `source_quality` | 9 rows, **120 impressions / 0 taps / 0 reads / 0.0 avg_duration total**, last touched 2026-04-13 |

Production `reading_events` doesn't have the `client_event_id` column the repository's S5
migration adds — confirming the additive S5/S7/S8 schemas have never been applied there.
`user_feedback_signals` doesn't exist as a table in production at all (it's created by
`_ensure_tables` at app startup, `main.py:1044`, so it would exist on any process that has
actually booted against this DB — its absence plus 0 `reading_events` rows is consistent with
the app having run against this database only during initial setup, not under real usage).

**Every subsequent recommendation in this document is written against three real users and
zero real behavioral examples**, not against an assumed "portfolio project with modest
traffic." That's a materially harder constraint, and it's the one the "impressive learning
architecture" brief has to survive contact with.

---

## 1. The loop, traced precisely

Requirement: *"Trace the existing action → telemetry → reader model → retrieval → ranking →
next-edition loop and identify missing or incorrect links."*

Two loops exist, gated by `S5_READER_ENABLED` / `S7_SERVING_ENABLED` / `S8_SERVING_ENABLED`
(all default `false`). I trace both; the legacy one is what actually runs today.

### 1a. Legacy loop (default-on — this is what production runs)

```
tap/read/not_relevant ──POST /feed/feedback (main.py:2592)────────┐
                                                                    │ article_id NOT UUID-validated (main.py:2613-2657)
                                                                    │ position unvalidated
                                                                    │ dedup index NULLs feed_request_id → always distinct → DUPLICATE ROWS
                                                                    │ apply_feedback() called UNCONDITIONALLY, not gated on rowcount →
                                                                    │   every retap COMPOUNDS the weight (no idempotency at all)
                                                                    ▼
                                                     reading_events (INSERT, ON CONFLICT DO NOTHING that never conflicts)
                                                     user_feedback_signals (feedback_signals.py:131, UPSERT, decay-AFTER-not-before)
                                                                    │
                                                                    │ user_id TEXT, NO FOREIGN KEY (main.py:1044-1059)
                                                                    │ → orphaned forever on any future user delete
                                                                    ▼
                                          feed_service._prepare_scoring_context (feed_service.py:1147)
                                                    loads feedback_signals + entity_pins + source_quality
                                                                    │
                     ┌──────────────────────────────────────────────┼───────────────────────────────────────┐
                     │ entity_pins: reachable, but entity_pins table has 0 rows (no UI writes it)             │
                     │ feedback_signals: `topic` weight (factor 1.0, the strongest) is DEAD —                 │
                     │   matched_profile_signals is populated at feed_service.py:230, ONE LINE AFTER          │
                     │   scoring already ran at feed_service.py:229. Only `source`(0.6)/`category`(0.35) live.│
                     └──────────────────────────────────────────────┬───────────────────────────────────────┘
                                                                    ▼
                                               blended_score adjustments, in this exact order
                                               (feed_service.py:1195-1261):
                                               suppress(−∞) → behavior(±0.15 cap) → entity(+0.2 flat) →
                                               source_quality(±0.10) → feedback(−0.50..+0.25, LAST) →
                                               content_quality multiplier → gate at 0.35
                                                                    │
                                                                    ▼
                                                     user_feed_cache (OVERWRITTEN every build,
                                                     no position column, no request id — cannot
                                                     reconstruct "what was shown, in what order,
                                                     with what score" for any past edition)
                                                                    │
                                                                    ▼
                                          feed_request_id minted (main.py:2320) but NEVER PERSISTED
                                          per-article — the client gets a top-level field it can't
                                          bind to any card, so `deliveryReceipt` is always nil for
                                          legacy feeds → client sends feed_request_id: nil on every
                                          telemetry event → the receipt-gate in ingest_events can
                                          never reject anything → unattributed telemetry is silently
                                          accepted with no verification it was ever actually delivered
                                                                    │
                                                                    ▼
                              client renders feed; impressions require real ≥50%-visible/≥1s
                              viewport gate (ArticleRemoteImage.swift:34-83) — this part is solid
                                                                    │
                                                                    ▼
                                                     back to top: next /feed build re-reads the
                                                     SAME feedback_signals row (decayed only at
                                                     READ time, so an old −1.0 stored weight
                                                     still floors new positive deltas — see §3)
```

**Missing/incorrect links in the legacy loop, ranked by how much they matter:**

| # | Link | What's broken | Evidence |
|---|---|---|---|
| L1 | telemetry → reader model | Duplicate/compounding writes: no server-side idempotency on `/feed/feedback`'s legacy branch | `main.py:2613-2657`, dedup index has `feed_request_id` nullable so `NULL != NULL` never conflicts |
| L2 | reader model → retrieval/ranking | The declared-strongest signal (`topic`, factor 1.0) never reaches a candidate because of a one-line ordering bug | `feed_service.py:229-230` |
| L3 | action → telemetry | Entity pins (`+0.2`, the single largest boost in the blend) have no UI writer anywhere in the app | `BackendService.swift:950-1029`, 0 call sites |
| L4 | edition → telemetry attribution | `feed_request_id` is minted but never stored per-article, so legacy telemetry is structurally unattributable to a specific edition/position | `main.py:2320`, `2361`, `2439` |
| L5 | account isolation | `user_feedback_signals.user_id` has no FK; orphaned on delete (moot today — delete doesn't exist either, see §4) | `main.py:1044-1059` |
| L6 | reader model decay | Decay applied at read time only, not before accumulation — a year-old −1.0 doesn't relax before a new delta lands on top of it | `feedback_signals.py:131-144` vs. the S5 version which fixed exactly this |
| L7 | negative signals | `hide_source` writes no `reading_events` row, so the specific article isn't added to the suppression list, only future ones from that source | `main.py:2620-2634` |

### 1b. S5→S7 loop (default-off — the well-built one nobody has switched on)

```
tap/read (dwell≥5s + native-hash match) / not_relevant / more_like_this / hide_source
                    │
                    ▼
     POST /reading-events, POST /feed/feedback  (S5 branch: reader_feedback.py)
     — idempotent (event_id + payload digest), generation-fenced, receipt-gated
                    │
                    ▼
     reader_learned_signals: weight ∈ [-1, +0.8], decay-BEFORE-accumulate (SQL CASE),
     semantic-hash-fenced (a reused intent UUID whose meaning changed cannot inherit
     old weight) — reader_feedback.py:191-200
                    │
                    ▼
     ══════ S6 candidate retrieval: DOES NOT READ learned weights, BY DESIGN ══════
     (docs/stages/s6-implementation-plan.md:133 — deliberately keeps retrieval independent
      of learning "to preserve the overlay for S7")
                    │
                    ▼
     S7 ranking: learned weight enters ONLY as a bounded multiplier on an
     ALREADY-GRADED candidate's priority — ranking_service.py:129-131:
        priority *= (1 + clamp(learned, -0.5, +0.25))
     Sort key is (-grade, -priority, age, id) — grade dominates; learning cannot
     promote a candidate across a grade tier, only reorder within one.
                    │
                    ▼
     ══════ S8 assembly: DOES NOT READ learned weights AT ALL ══════
     (grade + priority scheduling only; assembly_contract.py has no `learned` field)
                    │
                    ▼
     reader_delivery_receipts: immutable, append-only, position+recipe+intent-attribution
     stored — genuinely reconstructable "what/where/why" (see the S5-S8 trace, §8 there)
     BUT: no ArticleJudgment.reason, no grade, no retrieval leg/score is ever persisted —
     only lives 15 minutes in ranking_results.envelope before being overwritten
                    │
                    ▼
     client renders; S9's real viewport-visibility impressions + native-body-hash-verified
     reads feed back into reader_edition_reads (novelty) and, via ingest_events, can
     eventually reach reader_learned_signals again — but ONLY through the explicit-feedback
     path. Passive dwell/impression/skip telemetry NEVER writes reader_learned_signals
     (reader_feedback.py:1, module docstring: "Passive telemetry never rewrites S5 taste")
```

**This loop has no incorrect links — it's careful, tested, and fences almost every failure
mode this audit went looking for.** Its gap is a design choice, clearly documented, not a bug:
**it only closes the loop for six explicit verbs.** Nothing implicit (dwell quality, skip,
quick-back, repeated non-engagement) ever updates `reader_learned_signals`. That is a
legitimate, defensible MVP boundary — and also exactly the boundary requirement 3 (implicit
signals, noisy dwell, accidental clicks) asks me to push on. §5 proposes where to push it and
where not to.

### 1c. What's missing from *both* loops

- **No durable negative/exposure log.** Once an article is scored and rejected/abstained, or
  delivered-but-never-opened, no row records that anywhere with rank/score/reason attached.
  `ranking_results.envelope` is the only place a rejection's reason ever exists, and it's
  gone in 15 minutes. You cannot train or even *audit* against negatives you don't keep.
- **No session or sequence concept anywhere.** Every signal is a single (user, article,
  action) tuple. There is no notion of "this is the third article this reader opened in this
  sitting" in any table.
- **No quick-back / skip signal client-side**, despite the server already accepting `"skip"`
  (`reader_feedback.py:229`) — the client never sends one (confirmed: 0 hits for
  scroll/dismiss/skip semantics anywhere in `Daily/`).
- **No online metric can currently be computed**, because nothing is ever compared to a
  counterfactual (what would have been shown instead) or even to itself over time — there is
  no time-series of any learning-relevant metric anywhere in the repo.

---

## 2. Literature review and architecture recommendation

Requirement: *"Evaluate contextual bandits, controlled exploration, short-term versus
long-term interests, sequential models, online updates and learning-to-rank. Recommend a
coherent architecture... Research primary sources and explain which techniques genuinely fit
Daily."*

I checked the load-bearing citations below live on 2026-09-10 (marked ✓verified); the rest I'm
confident of from established, widely-reproduced results. Full bibliography in §7.

### 2a. What's actually public, and what isn't

**TikTok / ByteDance.** The one substantive public engineering paper is *Monolith: Real Time
Recommendation System With Collisionless Embedding Table* (Liu et al., ORSUM workshop @
RecSys 2022, arXiv:2209.07663 ✓verified). It solves a specific systems problem: hash-collision
loss in embedding tables at parameter counts and DAU where collisions are inevitable, plus an
online/streaming-training parameter-server architecture with "expirable embeddings and
frequency filtering." **It says nothing about TikTok's ranking objective, reward function, or
what "For You" actually optimizes.** The widely-repeated claims about TikTok's specific reward
shaping (e.g., completion-rate weighting, re-watch signals) trace to journalism (leaked
internal documents reported by press, not a paper) — I have not verified those as primary
source and will not present them as one. **Nothing in Monolith is the right shape for Daily.**
It's an infrastructure paper about surviving billions of daily active users' embedding
collisions; Daily has 3 users and no embedding table with a collision problem. Citing it in an
architecture doc for this app would be exactly the "sound frontier, add complexity" failure
mode the brief warned against.

**YouTube / Google.** This is the best-documented cluster, and the most genuinely useful one,
though still mostly for what to reject:
- *Deep Neural Networks for YouTube Recommendations* (Covington, Adams & Sargin, RecSys 2016,
  pp.191-198 ✓verified) — two-tower candidate generation over a catalog of ~10⁷ videos, plus a
  ranking model trained with **expected-watch-time-weighted logistic regression** (positive
  examples weighted by observed watch time, so the learned odds approximate expected watch
  time rather than click probability). *That specific idea* — weight a positive label by a
  quality proxy instead of treating all positives as equal — is the one piece of this paper
  that transfers to Daily's reward-shaping question in §6, independent of scale. The two-tower
  neural retrieval architecture itself needs an item catalog and interaction volume many
  orders of magnitude past Daily's; not recommended.
- *Recommending What Video to Watch Next: A Multitask Ranking System* (Zhao et al., RecSys
  2019 ✓verified) — Multi-gate Mixture-of-Experts for multi-objective ranking, plus a
  **shallow tower**: a small side-model that consumes only position/device (bias-only
  features) during training and is zeroed out at serving time, so the main model's learned
  relevance signal is trained free of the exposure bias those features encode. **This is the
  single most transferable idea in the entire brief**, because it names the exact failure mode
  Daily's own S7 ordering loop is set up to reproduce the moment learning starts influencing
  order (§3). It doesn't need billions of examples to matter *conceptually* — even a
  much-simplified version (log position as a feature, don't let a future learned-relevance
  signal see it) is applicable at any scale, including zero. The full MMoE multi-objective
  architecture is not — Daily has one objective (usefulness), not competing ones to arbitrate.
- *Values of User Exploration in Recommender Systems* (Chen et al., RecSys 2021) — makes the
  case, with production A/B evidence, that explicit exploration (showing items the model is
  uncertain about) measurably improves long-term satisfaction beyond what pure exploitation
  achieves. Relevant to justify *why* Daily should reserve any capacity for uncertain-but-
  plausible items once it has any learned uncertainty to explore — not applicable literally
  (their evidence is a live A/B at YouTube scale) but useful for choosing the *shape* of the
  eventual exploration policy in Tier 1 below.
- *Top-K Off-Policy Correction for a REINFORCE Recommender System* (Chen et al., WSDM 2019) —
  policy-gradient correction for training a recommender on data logged by a different, older
  policy. Needs a full RL training loop and a logging policy with known propensities at scale;
  not applicable to Daily now or in any near tier. Mentioned only to reject it explicitly,
  since "REINFORCE for recommendations" is exactly the kind of headline that invites over-
  reach here.
- The oft-cited "70% of watch time comes from recommendations" is Neal Mohan's 2018 CES
  remark, reported by CNET/Tubefilter/Quartz (✓verified as a press claim) — **not a paper**,
  and not a technique. Flagged here only so it isn't mistaken for one.

**Meta / Instagram.** *Powered by AI: Instagram's Explore recommender system* (Instagram
Engineering blog, 2019 ✓verified) documents a three-stage funnel (candidate generation →
lightweight ranking → final ranking) processing "65 billion features and 90 million model
predictions every second" — a scale statement, not a transferable algorithm; the post is a
systems/infra description, not a reward-function or bias-handling paper. *Deep Learning
Recommendation Model for Personalization and Recommendation Systems* (Naumov et al., 2019,
arXiv:1906.00091 ✓verified) — DLRM's embedding-plus-MLP architecture for sparse categorical
features at Criteo-ad-click scale; not applicable without the feature cardinality and training
volume it assumes. *Actions Speak Louder than Words: Trillion-Parameter Sequential Transducers
for Generative Recommendations* (Zhai et al., ICML 2024, arXiv:2402.17152 ✓verified) — HSTU,
treating a user's action history as a token sequence for a transformer-style model, reported
scaling "as a power-law of training compute... up to GPT-3/LLaMA-2 scale," deployed at
"billions of users." The *framing* — a reader's actions are an ordered sequence, not a bag of
independent weights — is the right long-term direction (it's the actual answer to "sequential
models" in the brief), but the HSTU architecture requires hundreds of sequential actions per
user to define a meaningful sequence at all. Daily has zero. Not recommended at any tier
defined in this document; flagged as the honest answer to what a *real* future upgrade path
looks like once there's enough sequence data to define a session.

**Bandits.** This cluster is the one that actually fits Daily's regime — small item universe
per reader (≤24 typed intents, not thousands of items), strong informative priors (explicit
declared priority), heavy cold start.
- *A Contextual-Bandit Approach to Personalized News Article Recommendation* (Li, Chu,
  Langford & Schapire, WWW 2010 ✓verified) — LinUCB, proven on Yahoo's Today Module over 33M
  events, 12.5% click lift over a context-free bandit. The context vector in LinUCB requires
  fitting a (d×d) ridge-regression matrix per arm reliably — this needs enough data per arm
  that estimating it on Daily's volume would be numerically unstable for a long time. The
  *reduction* (treat recommendation as sequential decision-making under uncertainty per
  context) is right; the specific linear-context estimator is not yet justified.
- *An Empirical Evaluation of Thompson Sampling* (Chapelle & Li, NeurIPS 2011 ✓verified) —
  shows a simple Beta-Bernoulli Thompson Sampling posterior is competitive with, and often
  beats, more sophisticated bandits, and is trivial to implement. **This is the technique that
  actually fits Daily's scale**: a Beta(α,β) posterior per (reader, intent) — not per article —
  keeps the arm count at O(10) per reader, matches the granularity Daily's explicit-priority
  model already operates at, and degrades gracefully to "trust the declared priority" when
  α=β=prior. This is the honest, sourced version of "contextual bandits for Daily": not
  LinUCB over article-level context vectors, but Thompson Sampling over interest-level
  posteriors, gated behind a real evidence threshold (§5).
- *Explore, Exploit, and Explain: Personalizing Explainable Recommendations with Bandits*
  (McInerney et al., Spotify, RecSys 2018 ✓verified) — bandits over a small set of
  *explanations/slots*, not the full item catalog, jointly learning which framing a user
  responds to. The structural parallel to Daily is exact: Spotify's bandit arms are a handful
  of curated slot types, not millions of tracks — same granularity argument as above, from an
  independent industrial source.
- *Unbiased Offline Evaluation of Contextual-Bandit-based News Article Recommendation
  Algorithms* (Li, Chu, Langford & Wang, WSDM 2011 ✓verified) — the **replay method**: you can
  get a provably unbiased offline estimate of a new policy's performance from logged data,
  *if* the logging policy's action was chosen uniformly at random (or with known propensity)
  at serve time. This is the methodological point that should most influence Daily's near-term
  engineering, independent of when any bandit actually ships: **if Daily ever wants to
  evaluate a future exploration policy offline, the logging has to start now**, because you
  cannot retroactively reconstruct propensities for actions that already happened
  deterministically. This directly motivates a concrete, cheap, zero-model event-contract
  requirement in §6.

**Unbiased learning-to-rank / position bias.** The second cluster that matters immediately,
for the same reason as the shallow tower above:
- *Unbiased Learning-to-Rank with Biased Feedback* (Joachims, Swaminathan & Schnabel, WSDM
  2017 ✓verified) — inverse-propensity-weighted counterfactual LTR; clicks alone,
  un-corrected, train a ranker that's biased toward whatever positions historically got
  clicked, independent of relevance.
- *Recommendations as Treatments* (Schnabel et al., ICML 2016) — the causal-inference framing
  of the same problem for recommendation specifically, propensity-scored matrix factorization.
- *Position Bias Estimation for Unbiased Learning to Rank in Personal Search* (Wang, Bendersky,
  Metzler & Najork, WSDM 2018) — regression-EM to estimate position propensities directly from
  click logs without randomized position intervention. All three need real click volume,
  stratified by position, to fit anything — Daily has none. **None of these are implementable
  today.** What they establish is the *shape of the correctness requirement*: any future
  learned-ranking signal built from click/read data must condition on or correct for position,
  or it will systematically prefer "whatever was already ranked first." Given S7's sort key
  already privileges grade and priority over any learned term (§1b), Daily's current design
  accidentally already avoids the worst version of this failure — but the moment a future tier
  lets learning influence *candidate inclusion* rather than just *within-grade order*, this
  literature's warning becomes actionable, and the event contract needs rank/position captured
  from day one so a correction is even *possible* later.

**Implicit feedback and dwell time.**
- *Beyond Clicks: Dwell Time for Personalization* (Yi, Hong, Zhong, Liu & Rajan, Yahoo,
  RecSys 2014 ✓verified) — item-level dwell time as a relevance proxy, with client+server-side
  timing and **explicit normalization across device/content-length context**. Daily's existing
  5-second flat floor (`ReadingEventTracker.swift:49-53`) is directionally the right idea this
  paper validates, but skips the paper's actual contribution (normalization) — a 5-second read
  of a 50-word blurb and a 5-second read of a 2,000-word feature are not the same signal, and
  Daily currently can't tell them apart.
- *Collaborative Filtering for Implicit Feedback Datasets* (Hu, Koren & Volinsky, ICDM 2008
  ✓verified) — the foundational reframe of implicit actions as **confidence-weighted votes**
  rather than direct labels. This is the right mental model for how Daily should treat
  `read` vs `impression` today: a native-body-hash-verified, ≥5s read is high confidence; a
  bare impression is near-zero confidence either way. Daily's S8 already half-builds this
  (the hash-verification machinery for novelty, §1b) but doesn't yet extend the same
  confidence framing to negatives, which don't exist as a class at all currently.

**News-specific.** *MIND: A Large-scale Dataset for News Recommendation* (Wu et al., ACL 2020
✓verified) — 1M users, 160k articles from Microsoft News click logs. *Google News
personalization: scalable online collaborative filtering* (Das, Datar, Garg & Rajaram, WWW
2007) — the closest historical analog to Daily's actual problem (implicit click-only
personalization over a fast-decaying, high-cardinality news pool), at a scale Daily will not
reach as a portfolio project. Borrow the **task decomposition** both papers use — separate
candidate generation from ranking, treat cold start as a first-class case rather than an edge
case — which Daily's S5→S6→S7→S8 pipeline already structurally does. Do not borrow trained
models or expect comparable data volume.

**Diversity, calibration, feedback loops.** This cluster is the outlier: genuinely
**immediately** applicable, with **zero data requirement**, because it's deterministic
post-processing over whatever relevance signal already exists:
- *The Use of MMR, Diversity-Based Reranking for Reordering Documents and Producing Summaries*
  (Carbonell & Goldstein, SIGIR 1998) — already cited and scoped as an "optional, unevaluated
  challenger" in `docs/stages/s8-implementation-plan.md:160,320`. Nothing new to add architecturally;
  correct as scoped.
- *Calibrated Recommendations* (Steck, RecSys 2018 ✓verified) — a recommended list should
  reflect a reader's *proportions* of interest, not just rank by top predicted score (a reader
  who reads 70% politics / 30% sports should see roughly that split, not 100% politics because
  politics scores highest). **This is a clean, sourced upgrade to how S8 already thinks about
  its topic/publisher-share soft targets** (`assembly.recipe.example.json`:
  `topic_share: 0.6, publisher_share: 0.5, source_streak: 2` — currently flat constants, not
  calibrated against anything per-reader). Calibrating against *declared* priority (which
  Daily has) rather than *inferred* watch history (which it doesn't) is a faithful, achievable
  version of Steck's idea at zero data cost — reframe existing hand-tuned constants as
  calibration targets derived from `ReaderIntent.priority`, not new machinery.
- *How Algorithmic Confounding in Recommendation Systems Increases Homogeneity and Decreases
  Utility* (Chaney, Stewart & Engelhardt, RecSys 2018 ✓verified) and the related *Degenerate
  Feedback Loops in Recommender Systems* (Jiang et al., 2019) — simulation evidence that a
  recommender trained on its own historically-served items homogenizes behavior without
  increasing utility. **This is the central cautionary result for Daily specifically**,
  because S6's explicit refusal to let retrieval consume learned weights
  (`docs/stages/s6-implementation-plan.md:133`) is *exactly* the guardrail these papers motivate —
  it means Daily's candidate pool today is generated from **explicit** interests only, never
  from what was previously served, so the classic confounding loop can't start. This is worth
  stating as a thing to actively **preserve**, not fix, and worth an explicit regression test
  (§4, §6) so a future well-intentioned change ("let's use learned weights to fetch more
  candidates too") doesn't reintroduce the exact failure this literature documents.

### 2b. Recommended architecture: a coherent staged design, not a grab-bag

Given the production reality (§0) and the literature above, the coherent architecture is a
**three-tier design where each tier is gated on stated, checkable evidence, and no tier is
built before its gate is met**:

**Tier 0 — deterministic bookkeeping, ships regardless of traffic.** Fix the loop (§1's
defects), extend the event contract for signals the literature says you'll regret not having
logged (position, quick-back), add one new asymmetric-weighted negative
(quick-back/skip-discount, cf. Lee et al. 2014 KDD "impression discounting", Yahoo — the
closest primary source for "repeated non-engagement should discount future exposure of similar
items," a pure counter mechanism, not ML). No bandit, no propensity correction, no sequence
model, no new infrastructure — this *is* "S10" as originally scoped, done correctly, wired to
where it can actually act (fixing L1–L7 above). This is buildable and fully testable today,
against zero real users, via the synthetic-replay harness proposed in §6.

**Tier 1 — Bayesian per-(reader, intent) confidence, gated on evidence.** Replace the flat
additive delta table with a Beta(α, β) posterior per (reader, intent), seeded from declared
`ReaderIntent.priority` as an informative prior (Chapelle & Li 2011's central result: this
beats fancier bandits at small N and is trivial to implement). This buys two things a flat
weight can't: **principled uncertainty** (new intents start uncertain, not zero) and a natural
**explore/exploit knob** (Thompson-sample the posterior when the intent's true value is still
uncertain, per McInerney et al. 2018's Spotify pattern of bandits over a small slot set, not
the full catalog). Gate: do not build this until there is a real per-reader, per-intent event
count worth fitting a posterior to — see the concrete number in §5.

**Tier 2 — position-bias-corrected ranking signal and session-aware short-term intent,
explicitly deferred, gate stated as a number, not a feeling.** A shallow-tower-style bias
feature (Zhao et al. 2019) folded into S7, feeding it real click-through data corrected for
position (Joachims 2017 / Wang 2018) — and only after that, a light sequence-aware "what has
this reader engaged with *today*" boost distinct from the 30-day decay. This needs real,
sustained, multi-user, multi-week traffic; the gate in §5 states the number and why.

**Explicitly rejected, with reasons:**
- Two-tower learned retrieval / trained user embeddings — S5's own audit already reached this
  conclusion (`s5-reader-model-audit.md`: *"A trained multi-interest/user tower — Requires
  suitable behavioral data and independent evaluation... defer learned towers"*); this audit
  agrees and the zero-row production measurement makes the case harder, not softer, than it
  was when that audit was written.
- Monolith-style real-time collisionless embedding infrastructure — wrong problem shape
  entirely (§2a); Daily has no embedding-collision problem to solve.
- HSTU/generative sequential transducers — needs hundreds of sequential actions per user to
  define a session; Daily has zero.
- Full contextual bandits with continuous context vectors (LinUCB proper) before Tier 1's
  simpler per-intent Bayesian arms prove out — LinUCB's ridge-regression context matrix needs
  enough samples per arm to invert reliably; Tier 1's Beta-Bernoulli arms need an order of
  magnitude less data and were shown competitive by the very paper (Chapelle & Li 2011) that
  is the strongest citation for "bandits genuinely fit this problem."

### 2c. Claims commonly repeated about these companies with no primary source (do not repeat)

- TikTok's specific reward-shaping formula (completion rate weighting, re-watch multipliers,
  time-since-last-video decay) — traces to press reporting on leaked internal documents, not
  a published paper. Flagged, not cited as fact, anywhere in this document.
- "YouTube's algorithm is a single deep neural network" — Covington et al. 2016 describes two
  separate models (candidate generation + ranking); production YouTube ranking has evolved
  substantially since 2016 per Zhao et al. 2019 and later work, and nothing public post-2019
  fully documents the current system end-to-end.
- Any claim about Instagram Explore's exact ranking weights or the "trillion-parameter" scale
  of HSTU as *currently deployed unchanged in production* — the 2024 paper reports research
  results and an initial deployment; treat as a research claim with reported production
  validation, not an ongoing guarantee of the exact same system today.

---

## 3. Bias, noise, cold start, drift and feedback loops — current status, per failure mode

Requirement 3, addressed against what the trace found (not hypothetically):

| Failure mode | Status today | Evidence | Sourced mitigation | Tier |
|---|---|---|---|---|
| **Position/exposure bias** | **Not handled.** No propensity, rank-considered-but-unshown, or pool-size is ever logged. | S8 receipts store `final_position` but nothing about the alternatives at that slot, and `ranking_results.envelope` (the only place candidate-level scores/positions exist) is overwritten within 15 minutes — S5-S8 contract trace §4, §8 | Log position + pool size + "was truncated" in the event contract now (near-zero cost); do **not** attempt IPW correction (Joachims 2017, Wang 2018) until per-position volume exists | 0 (log) / 2 (correct) |
| **Noisy dwell time** | **Partially handled.** 5s floor + native-body-hash match is real and better than most naive implementations, but flat, unnormalized, and the interval-accumulation logic drops sub-5s intervals across an app-switch entirely (a genuine bug, not a design choice) | `ArticleDetailView.swift:432-447`; iOS trace §5 "Consequence: intervals are not accumulated" | Yi et al. 2014's actual contribution — normalize by content length/device; fix the interval-accumulation bug regardless of learning architecture | 0 |
| **Accidental clicks / quick-back** | **Not handled at all.** Server already accepts `"skip"`; client never sends one or any quick-back signal | `reader_feedback.py:229` accepts it; 0 hits for scroll/dismiss/skip in `Daily/` | Add client-side quick-back (open→return in <8s) as an explicit negative; well-precedented in search/news satisfaction literature | 0 |
| **Delayed feedback** | **Mostly handled.** 30-day receipt retention + generation fencing correctly attribute late-arriving explicit feedback within the window | `reader_feedback.py:178-181` | No change needed; not worth further engineering at 0 real traffic | — |
| **Negative signals** | **Partially handled** for explicit negatives (asymmetric, correctly weighted per Hu/Koren/Volinsky-style confidence reasoning). **Entirely missing** for implicit negatives — nothing not clicked, or clicked-then-abandoned, is ever a confirmed negative anywhere | `DELTAS`/`FEEDBACK_DELTAS` tables (both loops); 0 rows anywhere recording an unopened-after-N-impressions pattern | Zhao et al. 2019's point about selection bias applies directly: absence of a click is not evidence of dislike without a confirmed impression to condition on — Daily already has the real-viewport-impression machinery (§1) to build this correctly once quick-back exists | 0 |
| **Topic fatigue** | **Not handled** as a learned signal. S8 has editorial variety *targets* (streak caps), not personalized fatigue from repeated reader disengagement | `assembly.recipe.example.json`: `source_streak: 2` is a fixed editorial constant, not reader-specific | Lee et al. 2014 KDD "impression discounting" (Yahoo) — repeated non-click impressions discount future exposure of similar items; a counter, not a model | 0 |
| **Diversity** | **Architecturally present, not calibrated.** S8's topic/publisher-share soft targets are flat constants (`topic_share: 0.6`), not calibrated against the reader's own declared priorities, and by design don't consume learned weights at all | `assembly_contract.py:21` `s3_membership_enabled: false`; §2b Steck discussion | Reframe existing constants as calibration targets derived from `ReaderIntent.priority` (Steck 2018) — zero new data required | 0 |
| **Cold start** | **A genuine strength, partially undermined.** Explicit typed-intent onboarding with declared priority is a *better* cold-start signal than most industrial systems get implicitly — but the learned overlay treats "brand new intent" and "intent nobody has engaged since decay" identically (both simply absent = 0 in `reader_learned_signals`) | `reader_contract.py:25-70` (typed intents exist); no distinguishing logic in `reader_feedback.py` | Bayesian formulation (Tier 1, §2b) fixes this for free — a Beta prior seeded from declared priority *is* a principled cold-start answer, not a bolt-on | 1 |
| **Interest drift (short vs long term)** | **Not handled distinctly.** Both loops use a single 30-day exponential half-life for the learned overlay, despite Daily's own *explicit* profile already modeling `stable_interests` vs `current_interests` as two tiers (`profile_model.py:26-27, 91-92, 142, 187-204`) | Single `HALF_LIFE_DAYS = 30.0` constant in both `feedback_signals.py:52` and `reader_feedback.py:92-94` | Two decay columns (fast: session/day-scale, slow: 30-day) blended at read time — stays entirely within existing Postgres/no-ML-infra constraints, mirrors the two-tier structure the explicit layer already has | 0 (schema) / 1 (use) |
| **Feedback loops** | **Actively avoided by current design**, and this must be *preserved*, not "fixed." | `docs/stages/s6-implementation-plan.md:133` — retrieval explicitly excludes learned weights | Chaney et al. 2018 / Jiang et al. 2019 — make "retrieval never consumes learned weights" an explicit regression test (§4, §6), so a future change can't silently reintroduce the exact confounding loop this literature documents | guardrail, all tiers |

---

## 4. Preservation constraints

Requirement 4: *"Preserve explicit user preferences, source exclusions, S2 content
provenance, S8/S9 immutable receipts, account isolation and genuine visibility signals."*
Each mapped to the specific existing guarantee, with what must never regress:

| Constraint | Current guarantee | Where it lives | Must-hold acceptance rule for any S10 change |
|---|---|---|---|
| **Explicit preferences outrank learned** | Feedback is applied *last* in the legacy blend and is explicitly weaker in range than a hard gate; S7's sort key puts `grade` (explicit-evidence-derived) ahead of any learned multiplier | `feed_service.py:1240-1242` comment; `ranking_service.py:125-136` | No learned delta may ever promote a candidate across a grade/acceptance boundary an explicit judgment set |
| **Source exclusions** | Hard policy blocks (`ReaderPolicy` kind=`publisher`) are enforced independently of and prior to any score; the learned overlay only ever touches intent *weights*, never policies | `reader_compiler.policy_allows()` (`reader_compiler.py:30-67`) | No learned delta may re-admit a hard-excluded publisher/article/lexical/subject policy, ever, under any weight |
| **S2 content provenance** | Native-body novelty acknowledgment requires an exact content-hash match between what was *displayed* and the verified original-body artifact; source-web/preview reads are conservatively never treated as verified reads | `assembly_integration._native_content_hash()`, `assembly_repository.candidate_evidence()` (§6 of the S5-S8 trace) | S10 may never treat a source-only or hash-mismatched "read" as equivalent evidence to a verified native read when computing reward |
| **S8/S9 immutable receipts** | No `UPDATE` statement exists anywhere against `reader_delivery_receipts`; it is strictly append-only, PK-guarded, `ON CONFLICT DO NOTHING` | Confirmed by grep across the whole S5-S8 trace, §5 there | S10's write path may only **insert** new `reader_learned_signals`/event rows and **reference** existing receipts by key; it must never write to a receipt table |
| **Account isolation** | Generation/revision fencing at every S5+ write path; the one real gap is `user_feedback_signals.user_id TEXT NOT NULL` with no FK | `reader_repository.publication_guard()`; `main.py:1044-1059` for the gap | Tier 0 must close this specific FK gap as a correctness fix, independent of the learning architecture (it's a data-integrity bug today, not a future risk) |
| **Genuine visibility signals** | Impressions require real ≥50%-visible/≥1s continuous viewport time via `ContinuousClock`, gated on active scene — not `onAppear` | `ArticleRemoteImage.swift:34-83`, `VisibleImpressionModifier` | Any new implicit signal (quick-back, fatigue-discount) must be built **on top of** a genuine impression, never inferred from delivery alone; a delivered-but-never-visible card must never become a negative signal |

Two related but genuinely orthogonal gaps the trace surfaced that this plan flags but does
**not** propose to own, because they're bigger than S10: **there is no account-deletion
endpoint anywhere in the application** (`is_deleted` is read in several places, never set —
backend trace §7), and **there is no sign-out session revocation server-side** (client-only).
Both matter for privacy (§6) but are account-lifecycle features, not learning-system features;
noted here so they aren't silently assumed solved by anything below.

---

## 5. Small-data techniques vs. traffic-gated techniques — concrete gates

Requirement 5: *"Separate what works with a small portfolio-project dataset from techniques
requiring substantial traffic. Provide a practical first implementation and evidence-based
upgrade gates."*

| Tier | Works at N=0? | Concrete gate to next tier | Why this number |
|---|---|---|---|
| **0 — deterministic bookkeeping** | **Yes.** Every fix in §1's tables, the event-contract additions in §6, and the calibration reframe in §3 are pure code/schema/SQL changes, testable via frozen-snapshot replay (§6) with zero real users. | N/A — this is the floor | Matches the repo's own precedent: S5's `reader_learned_signals` shipped fully tested with 0 production rows, correctly, because it's deterministic |
| **1 — Bayesian per-(reader, intent) posterior** | No — needs *some* real signal to be worth fitting. | ≥20 informative events (feedback or verified reads) **per reader per intent**, sustained, before that intent's posterior is trusted over its prior | Reuses the exact threshold this codebase already chose for an analogous problem: `interest_evolution.py:10` `MIN_EVENTS_THRESHOLD = 20` — not arbitrary, an internal precedent for "this many events before we trust an inference," and small enough that a single active user could plausibly reach it for their top 2-3 intents in weeks, not never |
| **2 — position-bias-corrected ranking, session-aware short-term boost** | No — this tier's own literature (Joachims 2017, Wang 2018, Li et al. 2011's replay method) needs volume stratified by position to fit anything. | ≥1,000 receipted, position-attributed impressions **per position bucket**, sustained for ≥4 weeks, from ≥50 active accounts | Order-of-magnitude floor for any of the cited position-bias estimators to be numerically stable per stratum; nowhere near the 33M-event Yahoo dataset LinUCB was proven on, but a real floor, not "eventually." Given 3 production users, this tier is not realistic for a portfolio project and should be documented as explicitly deferred, not attempted |
| **rejected, no tier** | — | — | Two-tower retrieval, Monolith-style infra, HSTU sequential transducers, full LinUCB context vectors — see §2b for citations on why each needs orders of magnitude more data/items than Daily will plausibly have |

**Practical first implementation = Tier 0, entirely.** Nothing else is honestly buildable
today. The implementation plan (`docs/stages/s10-implementation-plan.md`) scopes Tier 0 as concrete,
file-scoped batches; Tiers 1–2 are documented as gated future work with their evidence
thresholds stated as code (a query the app can actually run to check whether the gate is met),
not prose.

---

## 6. Reward, event contracts, lifecycle, evaluation, exploration, privacy, cost, failure

Requirement 6, each addressed concretely and scoped to Tier 0 (with Tier 1/2 noted where the
answer differs):

### Reward definition

A single, versioned, pure function — no model, no training job. Explicitly **not** raw dwell
seconds, not impression count, not click-through rate (the user's own instruction: *"optimize
usefulness and reader satisfaction — not addictive engagement or clicks alone"*):

```
reward(event) =
    explicit_delta(action)                      # existing DELTAS/FEEDBACK_DELTAS tables, unchanged
  + qualified_read_bonus                          # small positive: dwell ≥ length-normalized
                                                    # threshold AND native-body-hash verified
                                                    # (reuses S8's existing hash machinery)
  − quick_back_penalty                             # small negative: open→return < 8s (NEW)
  − repeated_impression_discount(topic, n_shown)   # Lee et al. 2014-style counter, NOT a model
```

No term is ever raw duration or raw open-count; every term is either an explicit action or a
*qualified* (hash-verified, threshold-gated) implicit action. This directly encodes the "not
addictive engagement" instruction as code, not policy.

### Event contract additions (Tier 0, additive only — no breaking change to existing schemas)

- `skip` / `quick_back`: client emits when a native-body detail view is opened and backgrounded
  in under 8 seconds without reaching the dwell floor. Reuses the existing `ReadingEvent`
  shape (`type`, `article_id`, `feed_request_id`, `position`) — just a new `type` value,
  already accepted server-side (`reader_feedback.py:229`).
- **Fix, don't add**: the legacy `feed_request_id`-not-persisted-per-article bug (L4, §1a) —
  this is the actual root cause of "unattributed telemetry accepted," and fixing it is a
  prerequisite for the S5 receipt-gate to mean anything in the legacy configuration too.
- Position and candidate-pool-size are **already** captured in S5/S7/S8 receipts
  (`final_position`, implicitly bounded by `CandidateBatch.candidates` ≤300) — no new field
  needed there, just the note that this is the exact data the position-bias literature (§2a)
  will eventually need, so it must not regress.
- Reward-function version: stamp a `reward_recipe_hash` alongside the existing
  `ranking_recipe`/`assembly_recipe` pattern already used on receipts
  (`reader_delivery_receipts.ranking_recipe`), so a future change to the reward formula is
  distinguishable from a change in reader behavior when interpreting historical
  `reader_learned_signals` — reuses the existing hash-versioning idiom, invents nothing new.

### Model/update lifecycle

Tier 0/1 have **no model artifact and nothing to deploy** beyond code — the "model" is a
transactional Postgres UPSERT, exactly as `reader_learned_signals` already works. This is a
deliberate, sourced contrast with Monolith's online-training-parameter-server pattern (wrong
shape, §2a): at this scale, the database *is* the online update, and that's not a compromise,
it's correct engineering for the data volume.

### Evaluation — the actual missing piece

The single highest-leverage Tier 0 deliverable, because nothing above can be honestly claimed
to work without it:

1. **Add a synthetic-session replay harness to `evals/`.** Script a fixed sequence of
   feedback actions against a frozen snapshot persona, run the pipeline once, apply the
   actions, run it again, and assert the second edition reflects them (the rejected article
   is absent; a `more_like_this` topic's candidates rank higher). This is a direct extension
   of the frozen-replay pattern `evals/ranking.py` and `evals/retrieval.py` already use for S6
   and S7 — no new infrastructure, just a new harness file plus fixtures. **This is testable
   today, with zero real users**, and should be the actual gate for "does S10 work," not
   anything requiring production traffic.
2. **Add a "reader-expressed-negative" label class to S0.** The current 3-way
   `must_see`/`fine`/`never` taxonomy has no way to represent "this specific reader said no to
   this specific article" — extend personas with an optional scripted feedback history so the
   never-return guarantee (`docs/architecture/systems.md` S10 bulletproof line: *"the rejected article
   never returns"*) can be checked as a metric per persona, not just asserted by unit test.
3. **Name the real online metric for later, honestly**: qualified-read rate per cohort — not
   engagement, not session length, not DAU. State plainly that this requires real users Daily
   doesn't have; do not fabricate a target number.

### Exploration safeguards

Tier 0 has **no exploration** — there's nothing to explore yet (no bandit). The safeguard at
this tier is a preserved invariant, not a new mechanism: retrieval must keep excluding learned
weights (§2a's Chaney/Jiang point), enforced by an explicit regression test (§6 of the plan).
At Tier 1, bound any Thompson-sampled exploration to a small, capped number of slots per
edition and require the synthetic-replay gate above to pass before it ships — McInerney et al.
2018 and Chen et al. 2021 both argue for *bounded, explainable* exploration over unbounded,
which is the shape to copy when Tier 1 is actually built (not now).

### Privacy

Learned signals are already per-account and covered by the existing reset/deletion machinery
(`POST /user/reader/reset-learning`) when S5 is on. Tier 0's real privacy work is closing the
`user_feedback_signals` FK gap (§4) so a future account-deletion feature (which doesn't exist
yet, and isn't this document's to build) has something correct to cascade against.

### Cost limits

Zero. Tier 0/1 add no LLM or embedding spend — pure SQL. If a future tier ever needs a model
call (none proposed here do), reuse the existing `ranking_control.daily_usd` /
`account_daily_usd` budget-reservation pattern S7 already implements rather than inventing a
new one.

### Failure handling and rollback

Reuse the exact pattern already proven five times over (S5 through S9 in this repo): additive-
only schema changes, env-flag default-`false`, `_invalidate()`-driven cache busting on any
reader mutation, generation fencing, and a `manage_s10_learning.py` dry-run-by-default CLI
matching `manage_s5_reader.py`'s shape. No new deployment pattern is justified or proposed.

---

## 7. Corrected claims vs. `docs/architecture/systems.md`

Requirement 7 (source-backed audit): concrete corrections to the current S10 blurb, each with
file:line evidence, so the systems.md update in this same change is traceable to this audit
rather than asserted.

| systems.md claim | Correction | Evidence |
|---|---|---|
| "`user_feedback_signals` + attribution + decay + suppression, 27 tests" | The "27 tests" figure is accurate for `test_feedback_signals.py`'s test-function count, but describes only the **legacy** math. It does not count `test_ranking_feedback.py`'s 15 tests covering the separately-implemented S5 path, nor does it disclose that the legacy path has **zero tests for `interest_evolution.py` or `source_quality.py`**, and zero production rows to have ever exercised any of the 27. | `wc`/grep counts above; iOS+backend trace §9 |
| "the `+0.2` entity boost... has never fired for anyone" | True in effect, wrong mechanism as stated — it's reachable code, blocked by a missing UI, and a **second, independent** dead-signal bug (the stronger `topic` weight) exists in the same scoring function and wasn't previously identified | `feed_service.py:229-230`, `:1220-1229` |
| "Implicit signals (dwell, skip, scroll-past) feed the model, not just taps" listed as a "bulletproof means" not yet met | Confirmed still not met, more specifically than before: dwell is captured but unnormalized with an interval-accumulation bug; skip/scroll-past do not exist client-side at all despite server support | §1c, §3 |
| "A reader can see and undo what the system has learned about them" listed as not yet met | Confirmed: `reader_repository._snapshot()` advertises `capabilities.undo = False` explicitly; no UI surfaces `reader_learned_signals` to a reader anywhere | S5-S8 trace §7 |

---

## Bibliography (all citations used above)

Verified live 2026-09-10 (primary source located and confirmed): Covington, Adams & Sargin
2016 (RecSys); Zhao et al. 2019 (RecSys); Li, Chu, Langford & Schapire 2010 (WWW, LinUCB); Li,
Chu, Langford & Wang 2011 (WSDM, replay); Joachims, Swaminathan & Schnabel 2017 (WSDM); Liu et
al. 2022 (arXiv:2209.07663, Monolith); Steck 2018 (RecSys, Calibrated Recommendations); Chaney,
Stewart & Engelhardt 2018 (RecSys); Wu et al. 2020 (ACL, MIND); Yi, Hong, Zhong, Liu & Rajan
2014 (RecSys, Yahoo); Zhai et al. 2024 (ICML, arXiv:2402.17152, HSTU); Chapelle & Li 2011
(NeurIPS, Thompson Sampling); McInerney et al. 2018 (RecSys, Spotify); Instagram Engineering
2019 (Explore); Naumov et al. 2019 (arXiv:1906.00091, DLRM); Hu, Koren & Volinsky 2008 (ICDM).

From established knowledge, not re-verified live this session (well-known, long-standing
results I'm confident of): Chen et al. 2019 (WSDM, Top-K Off-Policy Correction); Chen et al.
2021 (RecSys, Values of User Exploration); Schnabel et al. 2016 (ICML, Recommendations as
Treatments); Wang, Bendersky, Metzler & Najork 2018 (WSDM, position bias regression-EM);
Carbonell & Goldstein 1998 (SIGIR, MMR — already cited in this repo's `s8-implementation-plan.md`);
Jiang et al. 2019 (Degenerate Feedback Loops); Das, Datar, Garg & Rajaram 2007 (WWW, Google
News personalization); Lee et al. 2014 (KDD, Yahoo impression discounting); Hu/Koren/Volinsky
2008 confidence-weighting extended discussion.

Explicitly flagged as **not** a primary source (press/folklore, not cited as fact anywhere
above): TikTok's specific reward-shaping internals; the "70% of YouTube watch time" figure
(Neal Mohan, CES 2018, reported by press).

This audit's companion implementation plan is `docs/stages/s10-implementation-plan.md`.
