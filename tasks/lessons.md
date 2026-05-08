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
