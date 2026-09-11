# The app as ten systems

Each one has a single job, a contract at its edges, its own tests, and its own
definition of "bulletproof". Work them in the order given — later systems consume
what earlier ones produce, so hardening out of order means hardening against a
moving input.

Status is measured, not aspirational. Repository analysis is refreshed through S8 on 2026-09-09;
each stage retains its own implementation, verification and production measurement boundaries below.

```
S0 evaluation ──────────────── measures every other system

S1 sources ─▶ S2 content ─▶ S3 understanding ─┬─▶ S4 events ──┐
                                              │               │
                            S5 reader model ──┴─▶ S6 retrieval├─▶ S7 ranking ─▶ S8 assembly ─▶ S9 delivery
                                     ▲                                                              │
                                     └──────────────── S10 learning ◀───────────────────────────────┘
```

---

## S0 — Evaluation & observability

**Job.** Tell you whether a change made the product better or worse.

**Contract.** in: a build of the pipeline · out: recall@N, never-rate, cost/reader, latency

**State: evaluation framework implemented; product quality gates still incomplete.**
`backend/evals/` has ten personas, three frozen snapshots, labeled relevance/events/needles,
cached model calls and a production-path replay runner. Label provenance distinguishes human,
agent and model judgments. Absolute targets below are not currently met; the latest S2 audit
also records three pre-existing S0 metric regressions. See `backend/evals/README.md` and
`tasks/s2-content-pipeline-audit.md`. S3 needs additional article-facet and cluster ground truth.

**Technology.** Golden labelled set + offline replay + CI gate. This is what everyone does
before online A/B; you are too small for A/B, so offline is the whole game.

**Bulletproof means.**
- 200+ labelled articles per persona: `must-see` / `fine` / `never`
- recall@12 on must-see ≥ 0.8, never-rate ≤ 0.05, enforced in CI
- Frozen corpus snapshot so runs are comparable across weeks
- Hard cases in the set: right-word-wrong-thing, exclusion collisions, day-three follow-ups

**Why first.** Everything below says "make it perfect". Perfect against what? Build the ruler
before the thing you measure. It is also the cheapest item on this list.

---

## S1 — Source registry & ingestion

**Job.** Know which feeds exist, poll them politely, land raw articles exactly once.

**Contract.** in: nothing · out: rows in `articles`, deduped by canonical URL

**State: P0 implemented; registry/poller work pending.** Global and per-user ingestion paths
exist, but no unified canonical source registry/conditional poller. `tasks/plan.md` retains
P1–P7 as open. The feed still gates candidates through active per-user source links, so global
pool coverage does not imply reader access. The last production audit is dated 2026-09-02;
deployment and coverage must be remeasured before claiming completion.

**Technology.**
- HTTP polling + conditional GET (`ETag` / `If-Modified-Since`). The 2026-09-02 S1 audit
  measured **45 of 76** healthy publisher feeds honoring conditional GET with a true 304.
- WebSub/PubSubHubbub push where advertised — zero polling, instant.
- Adaptive cadence per source by observed publish rate.
- Postgres for the registry. A queue (Celery/RQ or a Postgres-backed one) once you outgrow
  the asyncio loop.
- *Analog:* Google News crawl + sitemaps; Feedly's polling infra.

**Bulletproof means.**
- 2,000+ feeds, ≥99% healthy, dead ones auto-deactivated
- Measured budget: 10 feeds = 2 MB / 1.0 s at 10 threads; 2,000 ≈ 65 MB/cycle at the median
- Per-source fairness — a firehose cannot starve a niche feed out of the window
- Zero duplicate rows for the same canonical URL
- **Coverage metric:** for each feed, articles ingested ÷ articles published. Under 100% is a
  broken fetch, not a ranking problem.

---

## S2 — Content pipeline

**Job.** Turn a URL into something readable, or admit it cannot and hand off to the reader.

**Contract.** in: canonical article identity + source policy · out: a provenance-backed native
body or an explicit original-source reading destination

**State: repository complete; production rollout pending.** The additive implementation now keeps
canonical metadata, display artifacts, and private ranking context separate; resolves presentation
with a default-deny audited source policy; binds feed rights to an exact reviewed feed URL; and
uses durable leased jobs with version fencing. The iOS client routes from the typed server contract,
opens source-only stories directly in Safari, and keeps account-scoped, version-fenced native text
only as a bounded offline fallback. See `tasks/s2-content-pipeline-audit.md` for proof and rollout.
The last production coverage measurement remains **26%** of seven-day articles at >=400 characters;
it describes the old deployment, not this unshipped repository implementation.

**Technology.**
- `trafilatura` primary, BeautifulSoup fallback (already).
- `SFSafariViewController` with `entersReaderIfAvailable = true` — already in the codebase.
  The fetch happens on the user's device, so it is the reader reading the page, not you
  republishing it. This is the lower-risk default for unlicensed/unknown text; publisher terms
  and licenses still require review.
- *Analog:* Firefox Readability.js, Safari Reader.

**Bulletproof means.**
- Editorial selection is independent from whether native full text is available
- 0 publisher/body provenance mismatches and 0 synthetic text under a publisher byline
- Native text only when identity, completeness, and source display policy allow it
- ≥99.5% of visible cards have a valid one-tap native or original-source destination
- Paywalls and deterministic blocks go straight to the source; transient failures retry with backoff
- Extraction state, attempt budgets, leases, and telemetry remain correct under races and restarts

**Before production can claim this:** finish S1's canonical source registry/poller, review every
native-display policy and exact feed URL, run the dry-run/canary/full backfill with constraint
validation, deploy by build SHA, and pass the live mismatch/destination/latency canary thresholds.

---

## S3 — Article understanding

**Job.** Describe what each article's evidence supports, once per semantic revision, in a
form every reader can be matched against.

**Contract.** in: canonical identity + versioned evidence bundle · out: validated embedding,
evidence-backed facets (`kind`, topics, entities, place roles, commercial/unknown), explicit
readiness/abstention states and separately versioned same-development story membership.
Event gravity and development novelty belong to S4; reader-relative novelty belongs downstream.

**State: guarded runtime implemented; quality validation and production rollout pending.**
The new independent worker has revision/eligibility-fenced jobs, budget reservations, validated
facets/embeddings, a current-result loader and correctable story membership. It supports
title/summary evidence and excludes unverifiable legacy bodies. Required hosted PostgreSQL
tests cover publication/expiry/correction/revocation and spending races. Provider pilot results
are operational evidence, not labeled accuracy. Entity candidates remain caller-supplied and
the provisional grouping recipe stays singleton until calibration. Search/chat adoption is
implemented but disabled; the legacy worker/consumers remain active by default. Feed retrieval
still needs S6 adoption. Production activation has not occurred.

**Implementation specification:** `tasks/s3-understanding-audit.md`. Its technology references,
schema, failure handling, acceptance targets and rollout gates supersede the earlier S3
proposals in `tasks/filtering-architecture-plan.md`.
Operating instructions: `backend/app/data/understanding/OPERATIONS.md`.

**Technology.**
- PostgreSQL jobs/results/outbox and a separate supervised Python worker.
- `text-embedding-3-small`, 1,536 dimensions, as the initial evaluated pgvector baseline;
  token-aware evidence input, compatible vector spaces and filtered ANN recall checks.
- Strict structured-output facet extraction, one article/request initially; evaluate pinned
  4.1 mini against the existing 4o mini baseline before selecting a production recipe.
- Versioned topic definitions and entity/place linking with evidence and abstention.
- Conservative persistent story membership with singleton fallback and merge/split correction.

**Bulletproof means.**
- Every retained article has an accounted-for state; supported inputs meet measured readiness
  and freshness targets without requiring a native-display body.
- No stale/wrong-article evidence or mixed-space vectors can be published or consumed.
- Held-out facet, entity/place, promotion and cluster precision/recall gates pass, including
  adversarial cases and each declared language/evidence tier.
- Leases, retries, deletion, revisions, model changes and downstream invalidation survive faults.
- Spend is bounded and measured per unique revision, with explicit retry/backfill costs.

**Why pivotal.** Shared article understanding removes duplicated reader-independent work.
S6/S7 still need separate adoption and evaluation before feed quality or cost savings are proven.

---

## S4 — Event detection

**Job.** Identify bounded events and material developments, assess their evidence-supported
consequences and scope, and keep those decisions current as reporting changes.

**Contract.** in: current S3 evidence/developments + versioned source-independence metadata +
history · out: stable event/development identities, versioned significance/scope, explicit
unknown/error states, source-linked material changes, expiry and invalidation events.

**State: guarded runtime and independent evaluation tooling implemented; hosted lifecycle,
semantic quality and reader activation gates remain open.** See `tasks/s4-implementation-status.md`
for current evidence and remaining engineering. `tasks/s4-event-detection-audit.md` records the earlier evaluation-only detector,
reproduced identity/breadth/validation failures, circular model-seeded labels, omitted shared
costs and missing production lifecycle/consumer wiring. The quiet derivative's retained 0.18
false-major metric is feed-slot contamination, not independently measured event false-positive
probability. S3's current default is singleton-only and unpromoted; its tests do not prove S4
event recall. No production S4 detector or delivery override has been enabled.

**Technology.**

- PostgreSQL/pgvector and a separate durable Python worker; bounded hybrid candidates,
  evidence-verified event relationships and revision-fenced assessments.
- Separate distribution reach, independent reporting origins and primary-authority evidence.
  Feed sections, syndicated copies and publisher geography cannot establish corroboration.
- One bounded structured assessment per event revision as the initial baseline, with explicit
  consequence rubric, uncertainty, factual delta and calibrated supported slices. Measure
  total shared/retry/reassessment cost; no fixed per-event price is established.
- S4 proposes significance. S6 recalls candidates; S8 applies reader policy, direct-support
  representative selection and bounded edition slots; S9/S10 track seen developments.

**Bulletproof means.**

- Independent event-family/time-split labels; measure identity, significance, novelty,
  representative correctness and reader delivery separately, with sample sizes/uncertainty.
- Outages and missing evidence remain visible, not relabeled routine. Stale/revoked/expired
  decisions cannot authorize priority, even if invalidation delivery is delayed.
- Corrections, source-origin changes, deletion, recipe changes and merge/split lineage survive
  concurrent workers and retries with bounded spend.
- S8 respects hard reader/source/access policies, at most two reserved slots and total edition
  size. Detection itself is not capped at two events; sustained volume triggers investigation.
- Held-out semantic gates, required hosted database fault tests, production prerequisites and
  a shadow canary all pass before controlled delivery. Targets are specified in the S4 audit.

---

## S5 — Reader model

**Job.** Hold what this person wants, in a form retrieval can query and feedback can edit.

**Contract.** in: explicit onboarding/edits + reviewed proposals + attributable signals ·
out: canonical versioned reader state, typed intents, explicit policies, compiled rubric,
compatible per-interest query vectors and a bounded learned overlay.

**State: guarded repository implementation; not activated in production.** Canonical v3
reader state, versioned/idempotent edits, reviewed Tune mutations, attributed feedback,
reset fencing, lexical retrieval and optional compatible per-interest embedding jobs are
implemented. Revisionless writers are rejected when S5 is enabled. Semantic serving and
paid workers remain default-off; production SQL/concurrency and quality gates are unproven.
See [S5 audit](s5-reader-model-audit.md), [plan](s5-implementation-plan.md) and
[implementation evidence and limitations](s5-implementation-status.md).

**Technology.**
- One authoritative typed reader document in PostgreSQL; deterministic projections and
  transactional, retry-safe edits. Explicit choices outrank inferred/learned preferences.
- Independently retrievable interests with optional cached vectors in the compatible S3
  space; retain lexical/identity legs. Compare a centroid baseline instead of asserting it
  can never work. No new vector database or trained user tower is justified yet.
- Separate hard policies from similarity scores and bounded decayed feedback.
- Cold start uses explicit choices and an honestly generic fallback, not assignment to the
  ten evaluation personas. Portfolio evidence comes from measured end-to-end behavior.

**Bulletproof means.**
- Edits survive reload, conflicts/retries, provider failure and account changes without loss.
- Three unrelated interests retain candidate opportunities when eligible relevant articles
  exist; quotas never require irrelevant filler. Measure coverage after every truncation.
- Changes reconcile sources without wiping useful associations or durable publisher blocks.
- Every writer/consumer uses one revision; old jobs/cache builds cannot republish removed taste.
- Tune applies a real reviewed change, feedback learns once from immutable attribution, and
  reset cannot relearn old observations. Semantic quality is independently evaluated.

**Dependencies.** Canonical state can be built alongside upstream work; semantic serving
requires compatible approved S3 article artifacts, S4 policy/receipt integration and a narrow
S6 consumer. S5 must not mutate article understanding or claim full S6/S7/S8 completion.

---

## S6 — Candidate retrieval

**Job.** Narrow the ingested eligible pool to a few hundred candidate opportunities for S7,
maximizing measured recall without letting one interest or blocked first page consume the budget.

**Contract.** in: versioned reader + time-bounded pool + retrieval recipe · out: ≤300 unique
eligible candidates with per-interest/per-leg provenance, current-evidence stamps and shortfall diagnostics.

**State: repository implementation complete; default-off shadow, live adoption gated.**
S6 now builds a strict CandidateBatch with independent lexical/identity/cached-dense legs,
policy-before-allocation refill, batched S3 evidence, fair deduplicated attribution, bounded
exclusive-connection execution and fresh reader/content/recipe authorization after ranking.
The full batch reaches an injected ID-keyed S7 adapter without legacy prefilters or a 100-row cap.
Existing feed behavior remains unchanged by default; the S7 adapter is implemented but not activated.
Unsupported language/sector hard policies fail closed with explicit unknown diagnostics.
Live SQL, held-out recall and latency gates are not passed. See [S6 audit](s6-retrieval-audit.md),
[implementation plan](s6-implementation-plan.md) and [actual status](s6-implementation-status.md).

**Technology.**
- PostgreSQL native lexical GIN + independently available current identity matches + compatible
  cached S5 vectors. Exact dense baseline first; filtered pgvector ANN only after measured gates.
- Policy-aware bounded refill, batch current-evidence validation and per-interest allocation.
- Distinct S6 CandidateBatch → S7 judgment; no new search cluster or trained model initially.

**Bulletproof means.**
- Missing/stale vectors do not remove otherwise eligible reporting; hard-policy unknowns are explicit.
- Per-interest opportunity coverage is checked after filtering/dedup, with truthful budget limits.
- No stale reader/article/recipe evidence authorized after the defined publication boundary.
- Proposed known-positive recall@300 ≥0.95 and retrieval p95<200ms require a frozen labelled
  corpus, supported slices, declared hardware/load and uncertainty. Neither is measured today.
- ANN-versus-exact recall is separate from product recall; S1 corpus gaps remain separate too.

---

## S7 — Ranking & judgment

**Job.** Judge reader relevance, accept/reject/abstain, and order candidates for S8.

**Contract.** in: S6 candidates + versioned reader + current bounded evidence · out:
one identity-bound judgment per candidate, confirmed intent attribution and base ranked order.
S8 owns final edition composition; publication authorizes the actual selected set.

**State: repository implementation complete; default-off, activation gated.** S7 consumes the
whole S6 batch, separates accept/reject/abstain from ordering, and uses bounded permitted
evidence. Optional async judgments are identity-checked and budget-reserved; failures abstain.
Atomic publication includes the current minimal composition/S4 order and confirmed-intent receipts. Cache reads
revalidate reader, content, recipe, epoch and event dependencies without paid ranking calls.
Legacy serving remains unchanged while S7 is off; its known weaknesses are not retroactively fixed.
The pinned transport model and narrow central-identity capability are not calibrated quality claims.
No live/provider/semantic quality verification was performed. See [S7 audit](s7-ranking-audit.md),
[implementation plan](s7-implementation-plan.md) and [actual status](s7-implementation-status.md).
The S8 implementation additionally closes the client status-decoding, per-card reader-generation
and immutable receipt-position gaps identified by its audit; live adoption remains gated.

**Technology.**
- Strict Pydantic contracts, pure versioned features and separate acceptance versus utility.
- Optional bounded async structured judgment; unknown/refusal/failure remains abstention.
- ID-complete batches, current evidence/reader/recipe fences and final-only attributed receipts.
- PostgreSQL account-scoped atomic result cache/build claims and provider spend reservations.
- Cross-encoder is a measured challenger; learning-to-rank waits for trustworthy graded,
  exposure-aware data. Clicks alone and high retrieval scores are not sufficient labels.

**Bulletproof means.**
- No misassigned verdicts or stale/prohibited publication; every candidate has an explicit outcome.
- Token/attempt/dollar/deadline limits include failures, retries and ambiguous spend.
- Unknowns cannot be promoted by pins, feedback, presentation quality or a fallback score.
- Frozen independent labels measure precision, graded order, coverage and per-interest losses;
  cost savings and selective-scoring bands require measured evidence, not a fixed 15% assumption.
- GET and refresh preserve the same valid published order; no provider calls on reads.

---

## S8 — Edition assembly

**Job.** Choose a useful, non-repetitive ordered edition without inventing relevance.

**Contract.** in: whole accepted S7 pool + current identity/history + independently authorized
S4 critical opportunities + assembly recipe · out: immutable ordered selections, explicit
dispositions/shortfalls and final-only attributable receipts.

**State: repository implementation complete; default-off, activation gated.** S8 now selects
from the full accepted pool with grade-protected interest coverage, verified deduplication,
bounded critical slots and recorded variety relaxations. Membership/history/configuration
are reauthorized before atomic publication. History-only rebuilds reuse valid S7 judgments;
GET preserves the immutable selected order. Native-body read hashes fence acknowledged novelty;
source-web and changed-body evidence remain unknown. Client status, generation and receipt-position
contracts are fixed, with explicit version negotiation. Legacy scoring is unchanged while off.
No live SQL or semantic-quality verification was performed. See [S8 audit](s8-edition-assembly-audit.md),
[implementation plan](s8-implementation-plan.md) and [verification/open gates](s8-implementation-status.md).

**Technology.**

- Pure bounded Python/Pydantic selection over the full accepted pool; no new paid model,
  embedding service or optimizer. Grade-protected interest scheduling and soft variety targets.
- Current approved S3 identity, conservative unknown singletons and representative selection
  requiring each ordinary copy's own acceptance. No title-only or inferred home-press authority.
- Receipt-backed novelty separate from taste learning; delivery does not establish reading,
  and a version bump does not establish a meaningful new development.
- Reuse PostgreSQL/S7 claims and result publication; separately version assembly/history and
  reauthorize membership dependencies. Reuse valid judgments for history-only reassembly.
- Preserve independently authorized S4 critical slots (at most two and within capacity),
  never bypassing hard reader, source, evidence or expiry policy. MMR remains an optional,
  unevaluated challenger; no new paid assembly model was added.

**Bulletproof means.**

- Unique article IDs and at most one selected verified-equivalent unit; measure false merges
  and missed duplicates rather than claiming perfect semantic identity.
- No rejected/unknown ordinary item or weaker representative promoted to fill a diversity quota.
  Concentration is conditional on relevant alternatives; sparse editions explain shortfalls.
- Whole-pool refill precedes final truncation; all selection and soft-target relaxations are explicit.
- Current membership/history/configuration is fenced at publication; cached edition IDs preserve
  order and per-card receipt identity across client cache, hides and background refresh.
- New developments/corrections are distinguished from acknowledged identical repeats only with
  supported evidence. No silent weakening of existing already-knew blocks.
- Required SQL race tests, Swift wire fixtures and independent final-edition quality/latency
  gates precede activation. S8 remains default-off until those gates pass.

---

## S9 — Delivery & reading

**Job.** Get the edition on screen fast, and make reading an article feel good.

**Contract.** in: assembled edition · out: rendered feed + article reader

**State: repository implementation verified (2026-09-10); rollout and measured budgets pending.**
Versioned editions, account-safe saved launch, explicit native offline permissions, coordinated
refresh/invalidation, ordered publication checks, bounded images and adaptive reading are
implemented. Late writes and reader retries/expiry have regression tests. Source-only cards
retain one-tap publisher routing; saved editions do not claim current authorization.

**Technology.** Retain FastAPI, PostgreSQL, SwiftUI, URLSession and SFSafariViewController.
S7 cached reads are provider-free but perform current evidence/reader/S8 authorization, not
merely one indexed SELECT. S9 uses a versioned delivery envelope, one feed coordinator,
serialized account storage, bounded native-body permissions and viewport-sized image work.

**Acceptance goals (not current measurements).**

- Cold saved-edition first frame p95 ≤ 1 s on a defined Release/device benchmark, independent
  of network availability and without claiming the saved session is server-authenticated.
- Current, saved/stale, authoritative empty, building, review-required and unavailable states
  remain distinct; old responses and sign-out-era writes cannot resurrect invalid content.
- Native/source presentation preserves provenance and clear fallback; offline full text is
  limited to permitted, unexpired saved native bodies. Publisher availability is not guaranteed.
- Foreground revalidation, bounded networking/images, adaptive accessible reading and genuine
  exposure measurement. Background refresh/push are best-effort, not a five-minute SLA.

See `tasks/s9-implementation-status.md` for evidence and refinements. Final combined iOS:
119 unit + five isolated reader UI tests passed. Full backend: 1,833 passed, 143 skipped,
235 subtests passed, with three pre-existing S0 failures. No physical-device performance/
accessibility audit, live SQL, source-policy grant, provider calls, deployment or activation.

---

## S10 — Signal capture & learning

**Job.** Notice what the reader does and change what they see next.

**Contract.** in: impressions, taps, reads, explicit feedback · out: updated reader model

**State: Tier 0 repository implementation verified (2026-09-10); Tier 1/2 not started, gated
on evidence.** Three parallel candidate systems exist, not one: legacy `user_feedback_signals`
(`feedback_signals.py`, default-on), the S5 bounded learned overlay
(`reader_learned_signals`/`reader_feedback.py`, default-off, the best-engineered of the
three), and S7's consumption of it (default-off, subordinate to grade). Both loops now share
one reward definition (`reward.py`) instead of two independently-maintained copies of the same
six numbers. Fixed: the declared-strongest legacy signal (`KIND_FACTORS["topic"]=1.0`) now
reaches scoring (an annotate/score reorder in `feed_service.py`); `/feed/feedback` no longer
compounds a retried action or 500s on a malformed `article_id`; `hide_source` now suppresses
the specific article, not only future ones from its source; `user_feedback_signals.user_id`
now has a real FK. Added, both gated behind the same passive-telemetry-cannot-write-taste
invariant the S5 path already enforces: a client-side quick-back/skip signal, and a bounded
repeated-impression discount + net qualified-read/quick-back engagement term, both folded into
scoring at read time only — receipt-scoped, so only live once S5 is on. Entity pins and
interest suggestions are reachable in the UI for the first time (legacy-serving only); all six
server-accepted feedback verbs are reachable from `WhyThisStorySheet` (was 3). Direct
production measurement (2026-09-10, read-only): **0 rows, ever**, in `reading_events`; 3
accounts total — governs why nothing beyond Tier 0 was attempted. Full trace, source-backed
literature review, staged architecture, implementation and verification evidence are in
[S10 audit](s10-learning-audit.md), [implementation plan](s10-implementation-plan.md) and
[implementation status](s10-implementation-status.md).

**Technology.**
- Attribution over the recorded reasons an article was shown, weighted by kind.
- Asymmetric deltas, bounded accumulation, 30-day decay, one shared reward definition.
- *Analog:* implicit feedback in every recommender. ByteDance's Monolith paper (arXiv:2209.07663)
  solves collisionless embedding hashing at billions of DAU — a different problem shape than
  this app has at any traffic it will plausibly reach; Postgres aggregation is correctly scoped
  here, not a lesser substitute for it. See the audit for what *does* transfer (Thompson
  Sampling per interest, calibrated diversity, position-bias-aware logging) and what doesn't.

**Bulletproof means.**
- Tapping "not relevant" demonstrably changes the next edition ✅ *(done, now also proven via
  offline pipeline replay — `evals/learning_replay.py` — not only unit tests)*
- The rejected article never returns ✅ *(done)*
- Implicit signals (dwell, skip, scroll-past) feed the model, not just taps ✅ *(skip/quick-back
  now exists client-side and folds into scoring; scroll-past and length-normalized dwell do
  not — see status doc)*
- Entity pins and suggestions are reachable in the UI ✅ *(done, legacy-serving only)*
- A reader can see and undo what the system has learned about them — still not done;
  `capabilities.undo=False` is explicit in the reader contract; no UI surfaces learned weights

---

## Order, and why

| # | System | Why here |
|---|---|---|
| 1 | **S0 Evaluation** | You cannot perfect what you cannot measure. Cheapest item; unblocks judging everything else. |
| 2 | **S1 Sources** | Nothing downstream can be better than its input. Also kills the dead-end where ingested articles reach no feed. |
| 3 | **S2 Content** | Repository complete; run the staged source-policy, migration, deploy, and live canary gates before production claims it. |
| 4 | **S3 Understanding** | The pivot. Every system from S4 on consumes embeddings, facets or clusters. |
| — | **S5 Reader model** | Canonical state can run parallel with 1–4; semantic serving needs compatible S3 artifacts and a narrow S6 consumer. See the S5 audit/plan. |
| 5 | **S6 Retrieval** | Needs S3 + S5. Currently the weakest link — no amount of ranking fixes a candidate set that already dropped the story. |
| 6 | **S7 Ranking** | Needs S6. Tuning a ranker over a bad candidate set optimises the wrong thing. |
| 7 | **S4 Events** | Needs S3. Independent of S5–S7, joins the pipeline at S8. Slot it wherever there is room. |
| 8 | **S8 Assembly** | Needs S4 + S7 both feeding it. |
| 9 | **S9 Delivery** | Repository implementation verified; reuses S2/S8 contracts. Measured device/SQL/deployment gates remain. |
| 10 | **S10 Learning** | Needs S9 for signals. Explicit half already shipped; the rest closes the loop back into S5. |

**The one rule:** never harden a system whose input is about to change. That is why S6 waits
for S3, and why S7 waits for S6 — otherwise you tune a ranker against a candidate set you are
about to replace, and throw the tuning away.

**If you only do three:** S0, S3, S6. Evaluation makes progress legible, understanding makes
it cheap, retrieval is where the feed is actually broken.
