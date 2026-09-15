# S10 Learning — implementation plan

Companion to `docs/stages/s10-learning-audit.md`; read that first. This plan scopes **Tier 0 only**
— the deterministic, zero-data-requirement bookkeeping tier the audit concluded is the entire
honestly-buildable scope given the production measurement (0 reading events, 0 feedback rows,
3 accounts, ever). Tier 1 (Bayesian per-intent posteriors) and Tier 2 (position-bias-corrected
ranking) are scoped as gated future work at the end, each with a runnable evidence-check query
— not built here, not approved here. **Nothing in this plan has been implemented.** It is a
blueprint for a future pass, file-scoped per this repo's convention.

## Outcome and scope

Ship the version of "S10" `docs/architecture/systems.md` originally described — telemetry that
demonstrably changes the next edition, entity pins and interest suggestions reachable in the
UI, implicit signals feeding the model, a reader able to see/undo what's been learned — **plus**
the structural bugs the audit found that make the existing 70-test-covered S5 learning
machinery inert even when switched on, **plus** the one piece that was missing from the
original S10 scope entirely: a way to prove any of it works before claiming it does.

Out of scope, explicitly: any bandit, any position-bias correction, any sequence/session
model, any new infrastructure (queue, vector DB, embedding table), any LLM/model call. All
rejected in the audit (§2b) with citations; none are justified by the current data volume.

## Ownership and invariants — do not regress these while implementing anything below

From audit §4, restated as engineering rules, each with the test that must exist to enforce it:

1. **Explicit beats learned, always.** No learned delta may promote a candidate across a
   grade/acceptance boundary an explicit judgment already set. *Test:* a candidate S7 abstains
   or rejects must remain absent from the edition regardless of any `reader_learned_signals`
   value, including the maximum `+0.8`.
2. **Hard policy beats everything.** No learned delta may re-admit an excluded publisher/
   article/lexical/subject. *Test:* set a policy exclusion and a maximally positive learned
   weight on the same article's matched intent; article must not appear.
3. **Provenance beats convenience.** A "read" without a native-body-hash match (source-web,
   preview, mismatched hash) must never contribute the qualified-read reward bonus, only (at
   most) the base explicit-action delta if the reader also gave one. *Test:* a source-only
   article dwelled on for 60s produces no qualified-read bonus in the reward calculation.
4. **Receipts are append-only, forever.** S10 code may `INSERT` new learned-signal/event rows
   and `SELECT`/reference existing receipts by key; it must never `UPDATE` or `DELETE` a
   `reader_delivery_receipts` row (retention sweeps on the *owning* table are fine; mutating a
   receipt's content is not). *Test:* static grep-based CI check, matching this repo's existing
   `git diff --check` style gate — assert no `UPDATE public.reader_delivery_receipts` appears
   in `backend/app/services/*.py`.
5. **Retrieval stays explicit-only.** S6 candidate retrieval must continue to never consume
   `reader_learned_signals` or any new Tier-0 signal. *Test:* `reader_retrieval.py` must have
   zero references to `learned`/`reader_learned_signals`/the new event types — same style as
   the existing `test_reader_integration.py` assertions that telemetry can't be a second
   learning writer.
6. **Impressions must be real before they're negative.** Any new implicit-negative signal
   (quick-back, repeated-impression discount) must be keyed off a genuine viewport impression
   (`VisibleImpressionModifier`-gated) or an explicit receipted delivery-then-return, never off
   delivery alone. *Test:* a card delivered but never visible cannot accumulate a
   repeated-impression discount.

## A — Fix the legacy loop's structural bugs (L1–L7, audit §1a)

These are correctness bugs independent of any new feature; fix regardless of whether Tier 1/2
ever ship, because they currently make the *existing, tested* legacy math produce wrong
numbers in the one configuration that's actually on by default.

**Files:** `backend/app/main.py` (`/feed/feedback` legacy branch, ~`:2613-2657`;
`_ensure_tables` `user_feedback_signals` DDL, `:1044-1059`), `backend/app/services/
feedback_signals.py`, `backend/app/services/feed_service.py`
(`_annotate_candidate_feed_roles`/`_apply_individual_analysis_results` ordering, `:229-230`).

1. **L1 — idempotency.** Add a stable client-supplied `event_id` requirement (mirror the S5
   `reader_feedback_events` idempotency ledger's shape, but table-scoped to the legacy path —
   or, cheaper and preferred: validate `article_id` as UUID and gate the `apply_feedback` call
   on `cur.rowcount == 1` from the `reading_events` insert, so a duplicate insert (now that L4
   below makes `feed_request_id` real and non-null, making the existing unique index actually
   fire) is a true no-op, not a compounding one.
2. **L2 — the dead `topic` signal.** Move the `_annotate_candidate_feed_roles` call (which
   populates `matched_profile_signals`) to run *before* `_apply_individual_analysis_results`
   in `feed_service.py`, or thread `matched_profile_signals` through the scoring call
   explicitly. This is the single highest-leverage one-line-class fix in the whole plan: it
   activates the strongest declared weight (`KIND_FACTORS["topic"] = 1.0`) for every reader
   who has ever given feedback, with no schema change.
3. **L4 — attribution.** Persist `feed_request_id` per article in `user_feed_cache` (it's
   already inserted per-build; add the column and a value) so legacy telemetry can bind to a
   real edition instead of always sending `null`. This is the prerequisite for L1's rowcount
   gate to mean anything, and for any future audit of "what was shown when this feedback
   fired."
4. **L5 — account isolation gap.** Migrate `user_feedback_signals.user_id` from bare `TEXT` to
   `uuid REFERENCES public.users(id) ON DELETE CASCADE`, matching every other reader-owned
   table. Additive migration (new column, backfill, swap, drop old) — follow the exact pattern
   `reader_feedback_schema.sql`'s `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` already uses
   elsewhere in this codebase.
5. **L6 — decay-before-not-after.** Change the legacy UPSERT in `feedback_signals.py:131-144`
   to decay the *stored* weight to current time before adding the new delta, matching the
   fixed SQL pattern `reader_feedback.py:191-200` already uses. Copy that CASE-expression
   shape; do not reinvent it.
6. **L7 — `hide_source` suppression.** Make the legacy `hide_source` branch
   (`main.py:2620-2634`) also insert a `reading_events` row for the specific article, not only
   deactivate the source — so the article itself joins the suppression list immediately, not
   only future articles from that source.

**Acceptance tests (new, `backend/tests/test_feedback_signals.py` and
`backend/tests/test_main_feedback.py` or equivalent):**
- Retapping the same feedback action on the same article twice produces exactly one
  `user_feedback_signals` weight change, not two (L1).
- A candidate with `matched_profile_signals` set by the production annotation call (not
  hand-constructed, unlike the existing dead test at `test_feedback_signals.py:260-295`) shows
  a nonzero `topic`-weighted score delta (L2).
- Feedback submitted against a specific `feed_request_id` is retrievable joined to that
  edition's `user_feed_cache` rows (L4).
- Deleting a user cascades `user_feedback_signals` (L5) — extend the existing (currently
  nonexistent, since delete doesn't exist yet) user-lifecycle test scaffold, or add a
  standalone FK-cascade SQL test alongside the existing opt-in Postgres suites.
- A stored weight of −0.8 updated 60 days ago, then hit with +0.2, lands at the correctly
  decayed-then-added value (≈ −0.05), not −0.6 (L6) — mirror
  `test_reader_integration.py::test_decay_before_addition_and_future_time_is_bounded`,
  applied to the legacy table.
- `hide_source` on article X immediately suppresses X itself on the next build, not only
  future articles from its source (L7).

## B — Event contract: quick-back/skip and reward versioning

**Files:** `Daily/Services/ReadingEventTracker.swift` (new `logSkip`/quick-back call and wiring
into `ArticleDetailView`'s existing `reconcileReadingInterval`/`finishReadingInterval`),
`Daily/Features/News/Views/ArticleDetailView.swift` (detect <8s open→return, call the new
tracker method instead of nothing), `backend/app/services/reader_feedback.py`
(`ingest_events` already accepts `"skip"` at `:229` — no server change needed for acceptance,
only for consumption in C), `backend/app/services/reader_feedback_schema.sql` (add
`reward_recipe_hash text` column to `reader_learned_signals`, additive `ALTER TABLE ... ADD
COLUMN IF NOT EXISTS`, matching every other migration in that file).

1. Client: when a native-body detail view's active-read interval
   (`ArticleDetailView.swift:432-447`) ends with duration < 8s **and** the dwell floor (5s)
   was not reached, emit `type: "skip"` instead of nothing. Reuse the existing `ReadingEvent`
   struct — this is a new value for an existing field, not a new wire shape.
   Distinguish this from a genuine <5s glance that isn't a "back" (e.g., backgrounding the
   app) — only fire on an actual reader-initiated navigation-back gesture, not on
   `scenePhase` changes, to avoid conflating "I left the app" with "I didn't want this."
2. Backend: no new endpoint. `ingest_events` already validates and inserts `"skip"` rows into
   `reading_events` (it's already in the `allowed` set at `reader_feedback.py:229`). Confirm
   with a new test that a `skip` event round-trips correctly when S5 is enabled.
3. Reward versioning: add `reward_recipe_hash` to `reader_learned_signals`, populated from a
   `REWARD_RECIPE` constant (mirroring `RECIPE`/`ranking_contract.RECIPE`'s
   `version` pattern) and written on every weight update in `submit_feedback`'s UPSERT. This
   lets a future reward-formula change be distinguished from reader-behavior change when
   reading historical weights, exactly as `ranking_recipe`/`assembly_recipe` already do for
   their respective layers.

**Acceptance tests:**
- Opening then returning from a native article in <8s without reaching the 5s dwell floor
  emits exactly one `skip` event, with the correct `feed_request_id`/`position`.
- Backgrounding the app (not a reader-initiated back navigation) during a <8s view does **not**
  emit `skip` (invariant 6 above — don't conflate app-lifecycle with reader intent).
- `reader_learned_signals.reward_recipe_hash` is set on every write and changes only when
  `REWARD_RECIPE` changes, never on an ordinary decay-and-accumulate update with the same
  recipe.

## C — Reward function and wiring

**Files:** new `backend/app/services/reward.py` (pure function, no DB access — matches this
codebase's existing separation of pure contract/compute modules like `ranking_contract.py`
from I/O modules like `ranking_service.py`), `backend/app/services/reader_feedback.py`
(`submit_feedback`/`ingest_events` call the new function instead of the inline `DELTAS.get`
lookup), `backend/app/services/feedback_signals.py` (legacy path calls the same function for
parity — one reward definition, two consumers, not two definitions).

```python
# reward.py — sketch, not final code; implementation batch writes the real thing
REWARD_RECIPE = {"version": "s10-reward-v1"}

def reward(action: str | None, *, qualified_read: bool = False,
           quick_back: bool = False, repeated_impressions: int = 0) -> float:
    """Deterministic, versioned. Never raw dwell seconds, never impression/open count,
    never click-through rate — only explicit actions and qualified/negative implicit ones."""
    delta = DELTAS.get(action, 0.0)
    if qualified_read:
        delta += QUALIFIED_READ_BONUS   # small, e.g. 0.05 — tune only against the replay harness
    if quick_back:
        delta -= QUICK_BACK_PENALTY     # small, e.g. 0.05
    delta -= impression_discount(repeated_impressions)  # Lee et al. 2014-style counter, capped
    return max(ADJUSTMENT_FLOOR, min(ADJUSTMENT_CEILING, delta))
```

`qualified_read` is computed by the caller from the existing S8 hash-verification machinery
(`assembly_integration._native_content_hash` equality check) plus a length-normalized dwell
threshold (Yi et al. 2014) — not a flat 5s cutoff. `repeated_impressions` comes from a new
bounded per-(user, topic) counter (D below), not a new join at reward-compute time.

**Acceptance tests:**
- `reward()` is a pure function: same inputs → same output, no DB/network access (assert via
  a test that mocks nothing and calls it directly with plain arguments).
- Every documented reward component (`QUALIFIED_READ_BONUS`, `QUICK_BACK_PENALTY`,
  `impression_discount`) has an explicit unit test asserting its sign and bound.
- The legacy path (`feedback_signals.py`) and the S5 path (`reader_feedback.py`) call the
  *same* `reward()` for the same logical input and get the same number — a parity test, so the
  two loops can never silently diverge on what an action is worth.
- `reward()` never appears in the same expression as a raw `duration_seconds` or an impression
  *count* anywhere in the codebase — a grep-based CI check mirroring invariant 4's style.

## D — Repeated-impression discount (topic fatigue) and length-normalized dwell

**Files:** `backend/app/services/reader_feedback.py` (`ingest_events`, add a bounded counter
update alongside the existing insert), new column or small table
`reader_topic_exposure(user_id, topic_id, window_start, count)` — additive schema in
`reader_feedback_schema.sql`, `backend/app/services/feed_service.py` (legacy: analogous counter
keyed on the same `articles.category` join `source_quality.py` already uses, for parity).

1. On each genuine viewport impression (already gated correctly client-side, §4 invariant 6),
   increment a bounded per-(user, topic, rolling window) counter. Cap the window (e.g., 14
   days, matching `interest_evolution.py`'s existing lookback) and the count (no unbounded
   accumulation — clamp like every other learned quantity in this codebase).
2. `impression_discount(n)` in `reward.py` is a small monotonic function of that count
   (log-scaled or step-capped — tune only against the replay harness in E, not by feel).
3. Length-normalized dwell: compute the qualified-read threshold as a function of the
   article's known length/word-count (already available from S2/S3 content artifacts) rather
   than a flat 5 seconds — e.g., `max(5, words / reading_speed_wpm * normalization_factor)`.
   This directly implements Yi et al. 2014's actual contribution instead of the current flat
   floor.

**Acceptance tests:**
- A topic shown 10 times with zero engagement produces a measurably larger negative
  `impression_discount` than one shown twice, and the discount is bounded (never exceeds
  `ADJUSTMENT_FLOOR` alone).
- A card delivered but never visible (viewport gate never fires) does not increment the
  exposure counter (invariant 6, restated as a test here specifically).
- A long article read for 15s is **not** treated as a qualified read if 15s is below its
  length-normalized threshold, while the same 15s **is** qualified for a short blurb —
  differentiates from the current flat-5s behavior explicitly.

## E — Reconnect the dead UI surfaces (entity pins, interest suggestions, "why this story" verbs)

**Files:** `Daily/Services/BackendService.swift` (no change — the ten dead methods already
exist and are correct per the trace), new `Daily/Features/News/Views/EntityPinsView.swift` or
a section within `Daily/Features/News/Views/PersonalizationSettingsView.swift`, new
`Daily/Features/News/ViewModels/PersonalizationSettingsViewModel.swift` methods wrapping the
existing `fetchEntityPins`/`createEntityPin`/`deleteEntityPin`/`fetchInterestSuggestions`/
`acceptInterestSuggestion`/`dismissInterestSuggestion` calls, `Daily/Features/News/Views/
Components/WhyThisStorySheet.swift` (add `more_like_this`/`important`/`already_knew` as
additional verbs — the backend already accepts all six; only three reach the UI today).

This batch is pure wiring — zero backend change, since every endpoint and `BackendService`
method already exists and is tested. It directly closes the "entity pins... no view calls
them" gap `docs/architecture/systems.md` names, and the L3 gap (§A) this audit re-confirmed.

1. Add a settings section listing pinned entities with add/remove, calling the existing
   `fetchEntityPins`/`createEntityPin`/`deleteEntityPin` — no new backend contract.
2. Surface pending `interest_suggestions` (confidence-scored topic suggestions from
   `interest_evolution.py`) as a reviewable list with accept/dismiss, calling the existing
   endpoints — matches this repo's established "reviewable proposal" pattern already used for
   Tune (`reader_proposals`), so it's consistent with house style, not a new interaction model.
3. Extend `WhyThisStorySheet` (currently 3 of 6 server-accepted verbs) with `more_like_this`
   (closes the `docs/notes/lessons.md` 2026-05-07 note: *"the backend action code already exists...
   not currently reachable from anywhere on the feed"* — still true today per the iOS trace),
   `important`, and `already_knew`.
4. **Note interest_evolution.py's `check_interest_evolution` returns `0` unconditionally when
   `S5_READER_ENABLED` is true** (`interest_evolution.py:21-25`) — this UI batch is only fully
   meaningful in the legacy (S5-off) configuration until interest suggestions get an S5-native
   equivalent, which is out of scope for Tier 0. Ship the UI regardless (it's correct and
   useful for the default-on legacy path today); document the S5-mode gap rather than silently
   building a suggestion generator that doesn't yet exist for that mode.

**Acceptance tests:**
- iOS: adding/removing an entity pin round-trips through the real endpoint and appears/
  disappears in the settings list (extend existing `PersonalizationSettingsViewModel` test
  coverage).
- iOS: accepting an interest suggestion calls the accept endpoint and the suggestion leaves
  the pending list; dismissing calls dismiss and does not re-surface it (respecting the
  existing `MAX_DISMISS_COUNT = 5` suppression server-side).
- iOS: `more_like_this`/`important`/`already_knew` from `WhyThisStorySheet` produce the correct
  server-side weight delta (extend `NewsViewModel.submitFeedback` tests already covering the
  other three verbs).
- Backend regression: no change to any existing endpoint contract — full existing backend
  suite stays green (these are additive UI-only consumers of already-shipped, already-tested
  server code).

## F — Evaluation: the synthetic-session replay harness (build alongside, not after)

Per this repo's own standing instruction (`docs/stages/s9-implementation-plan.md:252`: *"Add
deterministic tests as each phase lands, not a separate optional cleanup at the end"*) — this
batch should land incrementally with A–E, not after them. Scoped separately here only for
file-scoping clarity.

**Files:** new `backend/evals/learning_replay.py` (mirrors `evals/ranking.py`/
`evals/retrieval.py`'s existing frozen-replay pattern), new fixtures under
`backend/evals/labels/` or a dedicated `backend/evals/learning_fixtures/` directory, extend
`backend/evals/personas/*.json` with an optional `scripted_feedback` field (additive — existing
personas without it behave exactly as today), `backend/tests/test_eval_learning_replay.py`.

1. Given a frozen snapshot and a persona, script a sequence of feedback actions
   (`not_relevant` on article X, `more_like_this` on a topic) via the real `submit_feedback`/
   `ingest_events` functions against the eval's existing `SnapshotConn`-style fake DB
   (`fake_db.py` currently stubs these tables to `[]` unconditionally — this batch is what
   finally makes that stub return real data instead of empty, closing the S0 gap the audit
   flagged as the most important one).
2. Run the pipeline once before the scripted actions, apply them, run again, assert:
   - The `not_relevant`-marked article is absent from the second run's feed (never-return
     guarantee, checkable per-persona now instead of only by isolated unit test).
   - Candidates matching the `more_like_this` topic rank measurably higher in the second run.
   - No article the reader never interacted with changes rank by more than a documented
     tolerance (regression guard against the reward function having unintended global effects).
3. Wire into the existing `evals/compare.py` diffing so a future PR can show "before/after
   this reward-recipe change" exactly like existing scorecard diffs.

**Acceptance tests:** the harness *is* the acceptance test suite for A–D's reward logic; no
separate list. Add it to the required (non-skippable) CI job alongside the existing S0 gate,
matching `test_eval_gate.py`'s blocking pattern — this is deterministic and offline, so there's
no reason for it to be optional.

## Recommended implementation sequence

A → (B, D's schema half) in parallel → C → D's logic half → F alongside every batch from A
onward → E last (E is pure UI wiring with no dependency on A–D and can genuinely land anytime,
but sequencing it last keeps the PR series reviewable: backend correctness first, then reward
logic, then the UI that exposes it). Do not batch E before A — shipping visible entity-pin UI
while the topic-weight ordering bug (L2) is still live would surface a control that appears to
work but silently contributes nothing, which is precisely the "impressive-looking architecture
with no evidence it improves recommendations" failure mode this whole exercise was commissioned
to avoid.

## Rollback

Every batch is additive-only (new columns via `ADD COLUMN IF NOT EXISTS`, new functions, new
event type values accepted by an existing allowlist). No batch requires a schema rollback plan
beyond what `reader_feedback_schema.sql`'s existing migrations already establish. The one
behavior-changing fix with real rollback weight is A.2 (the `topic`-weight ordering fix) —
because it activates a previously-dead signal for the first time, wrap it behind a narrow,
independently toggleable check (not a new env flag family — reuse the fact that
`KIND_FACTORS` is already a plain module constant; rolling back means reverting the one-line
ordering change, not disabling a feature flag) so if the newly-live topic signal produces worse
feeds than the status quo (measurable via F's harness before it ever reaches production), it
can be reverted with a single-commit revert, not a flag flip that leaves the bug's absence
half-configured.

## References checked for this plan

Full literature discussion and verification status is in `docs/stages/s10-learning-audit.md`. The
citations that directly justify specific engineering choices in this plan: Yi, Hong, Zhong, Liu
& Rajan 2014 (RecSys, dwell-time normalization → batch D); Lee et al. 2014 (KDD, impression
discounting → batch D); Hu, Koren & Volinsky 2008 (ICDM, confidence-weighted implicit feedback
→ batch C's `qualified_read` framing); Chaney, Stewart & Engelhardt 2018 and Jiang et al. 2019
(RecSys/feedback loops → invariant 5, "retrieval stays explicit-only"). [Google Rules of ML](
https://developers.google.com/machine-learning/guides/rules-of-ml) is already cited in
`s5-implementation-plan.md:443-444` for the same reason it applies here: establish metrics and
serving/data correctness before escalating learned-model complexity — this plan follows that
rule by construction (Tier 0 has no model at all).

---

## Appendix: Tier 1/2 — gated future work, not scoped for implementation here

Per audit §5. Each gate is a query, not a feeling — run it before starting the corresponding
tier; do not start on a promise that traffic is "probably enough by now."

### Tier 1 — Bayesian per-(reader, intent) posterior

**Gate check** (run against production before starting):
```sql
SELECT user_id, intent_id, COUNT(*) AS informative_events
FROM public.reader_feedback_events  -- or the successor event log
GROUP BY user_id, intent_id
HAVING COUNT(*) >= 20;   -- MIN_EVENTS_THRESHOLD precedent, interest_evolution.py:10
```
Do not start Tier 1 until this returns rows for a meaningful fraction of active (user, intent)
pairs — one row does not justify replacing a working flat-weight system with a posterior.
Scope when gated: Beta(α,β) per (reader, intent) seeded from `ReaderIntent.priority`,
Thompson-sampled only within S7's existing within-grade reordering (never across grade,
preserving invariant 1 above), no retrieval change (preserving invariant 5).

### Tier 2 — position-bias-corrected ranking signal, session-aware short-term boost

**Gate check:**
```sql
SELECT final_position, COUNT(*) AS n
FROM public.reader_delivery_receipts
WHERE created_at > now() - interval '28 days'
GROUP BY final_position
HAVING COUNT(*) >= 1000;  -- order-of-magnitude floor per stratum, audit §5
```
Require this from **≥50 distinct active accounts**, not concentrated in a handful of heavy
users, before starting. Scope when gated: a shallow-tower-style bias feature (Zhao et al. 2019)
inside S7, fed by real click data corrected for the now-available position strata (Joachims
2017 / Wang 2018); a session-scale fast-decay column alongside the existing 30-day one (audit
§3's interest-drift row). Given the current production account count (3), this tier should be
assumed multi-year-or-never for a portfolio project and documented as such rather than aimed at.

### Explicitly not gated at all — rejected regardless of future traffic within this app's scope

Two-tower learned retrieval, Monolith-style collisionless embedding infrastructure, HSTU
sequential transducers, full LinUCB continuous-context bandits. See audit §2b for the citation-
backed reasoning on each; none are the right shape for this application's item catalog size or
plausible user count, independent of how much traffic accumulates.
