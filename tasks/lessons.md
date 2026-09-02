# Lessons — Daily Redesign

Self-corrections, scope notes, and pending follow-ups discovered mid-execution.
Append a line whenever the user pushes back or a phase surfaces something the next phase needs to remember.

---

## 2026-05-07 — Phase 2

**ContextMenu actions dropped from the feed.** Phase 2 replaced `.contextMenu` (7 actions) on feed cards with `.onLongPressGesture` → `WhyThisStorySheet` (3 corrective actions: Less of this / Wrong reason / Hide this story).

Lost from the feed:
- **Bookmark** — still reachable from `ArticleDetailView` toolbar.
- **Share** — still reachable from `ArticleDetailView`.
- **Discuss with AI** — still reachable from `ArticleDetailView` Discuss button.
- **More Like This** — *not currently reachable from anywhere on the feed.*

**Action for Phase 4 (Tune):** re-introduce a "more like this" positive-feedback affordance, either in the Tune surface or as an additional row in `WhyThisStorySheet`. The backend action code already exists (`viewModel.submitFeedback(action: "more_like_this")`).

---

## 2026-05-07 — Phase 4 (backend follow-ups)

Phase 4 rebuilt the Chat surface as Tune (composer top, live feed below, ephemeral diff toast, 10-min Undo). Three pieces depend on backend work the iOS side scaffolded but cannot drive alone.

1. **`weight_diff` streaming events.** iOS now decodes `StreamingEvent.weightDiff(WeightDiffPayload)` and routes them to `TuneViewModel.pendingDiff` → `DiffToast`. **Backend must emit `weight_diff` events** in the streaming response for tuning turns that change taste signals. Until then, the toast never appears (which matches the "zero-diff turns produce no toast" spec, but means the magic moment is invisible). Payload shape (Swift mirror — backend can match):
   - `summary: String` — short two-line description, e.g. "National news ↓ · Startups ↑ · Erlang +"
   - `topic_deltas: [{topic: String, direction: "up"|"down"|"added"|"removed", magnitude: Double}]`
   - `timestamp: ISO 8601` — optional

2. **Undo endpoint.** `TuneViewModel.tapUndo()` is a no-op that just clears the pill. **Backend must expose an endpoint** that reverses the last weight-diff for a given user. Once it ships, replace the `TODO(backend)` block with a real call. The `PersistedUndo.diff` carries the full payload so the request can include the original delta.

3. **Status stage labels.** The streaming `.status(StatusPayload)` event currently sends arbitrary strings ("Scanning your feed"). DESIGN.md specifies three named stages: "Reading your feed…" → "Adjusting taste model…" → "Pulling new stories…". **Backend should emit these three stages** (in order) for tuning turns. iOS already falls back to "Reading your feed…" when no status has arrived, so the cold-start experience is correct without backend changes — but the mid-stream stages depend on backend cooperation.

**iOS-side TODOs left in code:** search `TODO(backend)` in `Daily/Features/Tune/Models/ChatV2Models.swift` and `Daily/Features/Tune/ViewModels/TuneViewModel.swift`.

## S0 evaluation build (2026-09-01)

**An eval that does not run the production code path measures a different product.** The
old `baseline_today.py` called only the keyword fallback over the whole corpus, never the real
batch scorer, never production's 300-row recency window. `evals/runners.ProductionRunner`
now drives `get_personalized_feed` itself with an in-memory connection. Rule: the system under
test is the function the API calls, not a re-implementation of it.

**Cache every model call by request hash, and commit the cache.** Reproducibility and a free
CI gate both fall out of it. Corollary: a retry of an identical request returns the identical
cached failure. That is the right behaviour for a regression gate — but it means the eval
slightly over-penalises production, where a retry might succeed. Say so in the README.

**gpt-4o-mini runs away on positional 40-article batches.** With no `max_tokens` and no id
echo, two of three production scoring batches for Ray looped ("The article discusses a music
festival…" repeated) until the 16k output-token limit, came back as invalid JSON, timed out
the 45 s guard, and silently fell back to keyword scoring. Every retry can repeat it. This is
the S7 "id-echoed small batches, drop unmatched verdicts" item, now measured: fix there, not
in the eval.

**Unhandled SQL in a fake connection must raise, not return empty.** Five production loaders
swallow exceptions and degrade to "no signals"; a fake that silently returns `[]` would make
the eval quietly measure a feed with no behaviour signals. `SnapshotConn` records and raises.

**Keep must-see tight and define need-to-know narrowly.** The first labelling pass tagged
Giants roster news `need_to_know`. A tag that means "affects your life, money, safety or
work" cannot also mean "you like this team", or the headline metric is meaningless.

**Anything that becomes part of a cache key is pinned in code, never read from `.env`.** The
judge model came from `EVAL_JUDGE_MODEL` in `.env`; the test suite stubs `dotenv`, CI has no
`.env`, so the same code resolved a different model, produced different keys, and the gate
failed with `CacheMiss` only when run inside the full suite. Defaults live in the module.

**Return what you stored.** Embeddings were cached at float16 but the warming run kept its
float32 copy, so the first run and every later run clustered slightly differently. The miss
path now hands back the rounded vectors.
