# S10 Learning — implementation status

Companion to `tasks/s10-learning-audit.md` and `tasks/s10-implementation-plan.md`. This is
Tier 0 only — the deterministic, zero-data-requirement bookkeeping tier the audit concluded
was the entire honestly-buildable scope given the production measurement (0 reading events,
0 feedback rows, 3 accounts, ever). Tier 1 (Bayesian per-intent posteriors) and Tier 2
(position-bias-corrected ranking) are unbuilt, as scoped — their evidence gates are not met.

## Implemented

- [x] **A — legacy loop correctness fixes (L1–L7).** `feed_service.py`: annotate-before-score
      reorder so the declared-strongest signal (`topic`, factor 1.0) reaches scoring for the
      first time (`test_annotate_runs_before_scoring_so_topic_feedback_is_reachable`,
      `test_topic_feedback_reaches_score_when_annotated_first`). `feedback_signals.py`:
      decay-before-accumulate in the UPSERT, matching the pattern the S5 path already had
      right (`test_decays_stored_weight_before_accumulating`). `main.py`: `/feed/feedback`
      validates `article_id` as a UUID before any write (400, not a 500), prefers the edition's
      own recorded receipt over a client-supplied `feed_request_id`, gates
      `apply_feedback`/cache-clear on the insert's rowcount so a retried action no longer
      compounds, and `hide_source` now also inserts a suppression event for the specific
      article (not only future ones from its source) — extended the same allowlist in
      `event_integration.py`/`ranking_events.py` for consistency. `main.py`/`feed_service.py`/
      `user_source_pipeline.py`: `feed_request_id` is minted before the build and threaded
      into `user_feed_cache` (additive `ADD COLUMN`, `COALESCE`-protected against an auxiliary
      chat/briefing call clobbering a real edition's receipt). `main.py`: migrates
      `user_feedback_signals.user_id` from bare `TEXT` (no FK) to `uuid REFERENCES
      public.users(id) ON DELETE CASCADE`, defensively (only if no orphaned rows exist);
      `reader_repository.reset_learning` simplified to one cast strategy
      (`user_id::text=%s`) for all three swept tables instead of a per-table special case.
      Tests: `test_feed_feedback_endpoint.py` (new, 8 tests), extensions to
      `test_feedback_signals.py` and `test_reader_repository.py`.

- [x] **B — event contract.** iOS: `ReadingEventTracker.logSkip(article:)` (new `"skip"` event
      type, no dwell floor — a skip's whole meaning is that dwell was short);
      `ArticleDetailView` tracks whether a qualifying (≥5s) read happened anywhere during the
      visit and, on genuine navigation-away (`.onDisappear` — never on backgrounding, which
      goes through a separate `scenePhase` path), emits a skip if the visit was under 8s and no
      qualifying read occurred. Backend: `reader_learned_signals.reward_recipe_hash` (additive
      column), stamped on every S5 learned-weight write from a versioned `REWARD_RECIPE`
      constant, mirroring the existing `ranking_recipe`/`assembly_recipe` idiom. Tests:
      `ReadingEventTrackerTests.swift` (+3), `TestRecipeVersioning` in `test_reward.py`.

- [x] **C — the one reward definition.** New `app/services/reward.py`: pure function, no
      DB/network access, the single source for `DELTAS`/`KIND_FACTORS`/`WEIGHT_FLOOR`/
      `WEIGHT_CEILING`/`ADJUSTMENT_FLOOR`/`ADJUSTMENT_CEILING`/`HALF_LIFE_DAYS` — both
      `feedback_signals.py` (legacy) and `reader_feedback.py` (S5) now import and re-export
      these instead of each hard-coding their own copy of the same six numbers. Adds
      `QUALIFIED_READ_BONUS`, `QUICK_BACK_PENALTY` (both smaller in magnitude than any
      explicit action, by an asserted test) and `impression_discount()`. No reward term is
      ever raw dwell seconds, an impression count as a positive, or a click-through rate —
      enforced by a static source-inspection test
      (`test_never_a_function_of_raw_duration_or_impression_count_as_a_positive`), not just
      documentation. Tests: `test_reward.py` (new, 19 tests) including a parity test proving
      the legacy and S5 loops now compute an identical number for the same input.

- [x] **D — passive-signal folding, never a second explicit-learning writer.** New tables
      `reader_topic_exposure` (impression counts, evolving 14-day window) and
      `reader_topic_engagement` (net qualified-read/quick-back reward, decayed like
      `reader_learned_signals`), both in `main.py`'s unconditional startup schema so they
      exist under the default (legacy) configuration, not only under S5. `reader_feedback.py`:
      `ingest_events` bumps exposure on every genuine impression and engagement on every
      qualified read / skip, keyed by the receipt's confirmed `intent_ids` — **this only
      populates for S5-receipted events**, since the legacy serving path never writes
      `reader_delivery_receipts` at all (confirmed by trace, not assumed). Both signals are
      folded into `load_learned_weights` (the one seam both S5 direct-serve and S7 ranking
      already read) — never written to `reader_learned_signals` itself, preserving the
      existing, tested invariant that passive telemetry cannot become a second writer to the
      table explicit feedback owns. Tests: 9 exposure tests + 7 wiring tests in
      `test_ranking_feedback.py`/`test_reader_integration.py`, including one that asserts no
      `reader_learned_signals` SQL is ever emitted by a passive event.

- [x] **E — reconnected the dead UI surfaces.** Pure UI wiring; zero backend change, since
      every endpoint and `BackendService` method already existed and was tested.
      `WhyThisStorySheet` extended from 3 to all 6 server-accepted verbs (added More like
      this / Important to me / I already knew this). `PersonalizationSettingsViewModel`:
      `entityPins`/`interestSuggestions` state plus `addEntityPin`/`removeEntityPin`/
      `acceptInterestSuggestion`/`dismissInterestSuggestion`, loaded only on the legacy path
      (the S5 branch in `load()` always returns before reaching this code, so it's naturally
      never reached once S5 is on — matches the fact that S5 write-blocks pins with 409 and
      `interest_evolution.check_interest_evolution` returns 0 unconditionally under S5).
      `PersonalizationSettingsView`: two new sections ("Pinned People & Companies", "Noticed a
      pattern") gated on `viewModel.reader == nil`, reusing the existing `ChipFlowView`
      component so the new UI matches house style rather than introducing a new pattern.

- [x] **F — the missing evaluation.** New `evals/learning_replay.py`: builds a persona's feed
      once through the real, unmodified `feed_service.get_personalized_feed`, applies a
      scripted feedback action through the real, unmodified
      `feedback_signals.apply_feedback`, builds again, and returns both editions for
      assertion. Extended `evals/fake_db.SnapshotConn` — previously stubbed
      `user_feedback_signals`/`reading_events` to an unconditional `[]` — to serve real,
      in-memory signals, including the actual UPSERT bound-and-clamp arithmetic. New
      `tests/test_eval_learning_replay.py` (5 tests): the "rejected article never returns"
      claim and "an unrelated article is unaffected" checked through the real pipeline (not
      only `feedback_signals.py`'s isolated unit tests); `hide_source` suppression proven
      end-to-end; the A2 topic-attribution fix proven end-to-end (a `more_like_this` on a
      topic-matched article now measurably promotes it above an otherwise-tied peer, which
      was impossible before A2). This directly closes the gap the audit named as the most
      important one: previously nothing in this repository's test suite could tell you
      whether a change to the learning system helped or hurt.

## Deliberate scope adjustments made while implementing

- **D's passive signals fold into scoring, not into `reader_learned_signals`.** The original
  plan sketch described routing qualified-read/quick-back through the same `reward()` call
  `submit_feedback` uses. Implementing it, this would have made passive telemetry a second
  writer to `reader_learned_signals` — directly contradicting a real, already-tested
  invariant in this codebase (`reader_feedback.py`'s own module docstring, and
  `test_telemetry_cannot_be_second_explicit_learning_writer`). Redesigned to fold both new
  passive signals in at read time only (mirroring how decay already works), via two new,
  separate tables. This is more correct than the original sketch, not a reduction in scope.
- **D's exposure/engagement tracking is S5-receipt-scoped, not legacy-scoped**, because the
  legacy serving path never writes `reader_delivery_receipts` at all — there is no
  intent-attributed receipt to key a passive signal against under legacy serving. This was
  discovered during implementation, not assumed in the plan; it means D's passive-signal
  half only takes effect once S5 is enabled, while A/B/C/E's fixes are legacy-active today.
- **`already_knew` was added to `WhyThisStorySheet`** alongside `more_like_this`/`important`,
  per the plan, after confirming no other, more natural surface for it exists anywhere in the
  app (checked via grep — zero prior wiring).
- **The pre-existing interval-accumulation dwell bug** (sub-5-second intervals across an
  app-switch are not summed — audit §3) was **not fixed**. It was flagged in the audit as a
  correctness issue independent of the learning architecture, but was never assigned to a
  named batch (A–F), and fixing it changes existing, working read-duration behavior in a way
  that deserves its own scoped review rather than a side-effect of this pass.
- **Length-normalized dwell** (the other half of batch D per the original audit) was not
  implemented. It requires plumbing an article length/word-count signal to the client's dwell
  gate — a product-facing UX change to what counts as a "read," not a backend correctness fix
  — and was judged out of scope for a single implementation pass focused on wiring existing
  and lightly-extended mechanisms rather than changing reader-facing read semantics.
- **Tier 1/2 were not built**, as scoped in the plan: their evidence gates (≥20 events per
  reader-intent pair; ≥1,000 receipted impressions per position bucket from ≥50 accounts) are
  nowhere close to met (0 real events, 3 accounts).
- **The S5-path equivalent of the synthetic-replay harness (batch F) was not built.** S5 has
  its own, different fake-DB shape (`test_ranking_feedback.py`'s `DB` class, not
  `SnapshotConn`) and its own already-extensive test suite (70+ tests) directly exercising
  `reader_feedback.py`. Building a second, S5-specific `SnapshotConn`-equivalent replay
  harness was judged lower priority than the six committed batches, given the time available.

## Verification actually run

**Backend** (`EVAL_OFFLINE=1 python -m pytest tests/`): 1,884 passed, 143 skipped, 235
subtests passed. The only failures are the same three pre-existing S0 snapshot-quality gaps
every prior S3–S9 status document also reports unchanged (`followup_recall_mean`,
`never_rate_mean`, `event_delivery_mean` against the `prod-llm`/`2026-09-02` baseline) —
confirmed unrelated to this work by baseline diffing before and after each batch, not asserted.

**iOS**: `xcodebuild build` for the `Daily` scheme — **BUILD SUCCEEDED** (whole app, including
every S10 change). `xcodebuild test -only-testing:DailyTests` on an iPhone 17 Pro simulator —
**TEST SUCCEEDED**, 121 passed, 0 failed, run after every Batch B1/E edit was in place, not
before. One real bug found and fixed during this verification, unrelated to app logic: two of
the three new `ReadingEventTrackerTests` crashed with SIGABRT until made `async`, matching
every pre-existing test in that file — a synchronous test method on an `@MainActor` XCTestCase
apparently isn't safe to invoke directly under this toolchain; noted here in case it recurs.

**Eval replay** (`evals.learning_replay`): ran directly, not only under pytest — both the
"reject an article" and "endorse a topic" scenarios visibly change the second build's edition
relative to the first, using the real production scoring pipeline. Two genuine production
behaviors were discovered and worked around while building the fixtures, not assumed:
`MIN_CANDIDATE_TEXT_LENGTH = 40` drops any candidate whose title+summary is shorter than that
(a real quality filter, not a harness bug), and a persona with no stated interest at all
(`has_preferences == False`) takes a "no profile available" fast path that marks every
candidate relevant unconditionally and never calls the suppression/scoring machinery at
all — meaning **the learning system, as it exists today, cannot do anything for a reader who
hasn't stated at least one preference**, cold-start or not. This is consistent with the
audit's characterization of cold start as a genuine strength of the explicit layer, but it
sharpens the boundary: it's a strength only once onboarding has captured *something*.

## Not done / explicitly out of scope

- Tier 1 (Bayesian per-intent posteriors) and Tier 2 (position-bias-corrected ranking) — gated
  on evidence thresholds nowhere close to being met; see the plan's appendix for the exact
  gate-check queries to run before ever starting either.
- The interval-accumulation dwell bug and length-normalized dwell (noted above).
- Account deletion and server-side sign-out revocation — real, pre-existing gaps the audit
  surfaced, but account-lifecycle features bigger than S10's scope, not owned by this plan.
- No commit, push, deploy, hosted SQL migration, or production data change of any kind was
  performed. Every schema change here is written as additive DDL
  (`ADD COLUMN IF NOT EXISTS`/`CREATE TABLE IF NOT EXISTS`) inside the same `_ensure_tables`/
  `reader_feedback_schema.sql` startup paths this codebase already uses, matching the
  established S5–S9 pattern; none of it has been run against a real database, including the
  stale production deployment described in `project_prod_deployment_state.md`.
