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
