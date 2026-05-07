# Daily Redesign — Active Plan

This file tracks the **current phase** of the whole-app redesign. The full design system is in `DESIGN.md`; the per-surface execution roadmap (Phases 1–10) is in `tasks/design-redesign-plan.md`. This file is the focused checklist for what's being built right now.

---

## Phase 2 — Feed surface (NewsView)

**Status:** in progress

Phase 2 wires the Phase 1 components into `NewsView`. Substitution is mechanical (one component swap per existing card) but the visible result is large: card chrome disappears from the feed, the hero is full-bleed, the edition signature replaces the wordmark+date treatment, and long-press on any row surfaces the "Why this story?" sheet.

### Substitution map

| File / Lines | Today | After Phase 2 |
|---|---|---|
| `NewsView.swift:22` | `heroHeader` | `editionHeader` (delegates to `EditionHeader` component) |
| `NewsView.swift:63` | `Color(.systemBackground)` | `EditionPalette.paper` |
| Hero card | `FeaturedArticleCard(style: .hero)` + `.contextMenu` | `HeroStory(article:, provenance: featured.whyThisStory, isRead:)` + `.onLongPressGesture` |
| Feed rows | `FeaturedArticleCard(style: .feed)` + `.contextMenu` + `HairlineDivider` | `StoryRow(article:, isRead:)` + `.onLongPressGesture` + sepia `Rectangle` hairlines |
| `sectionLabel` helper | serif `sectionHeroTitle`/`headline`, `BrandColors.textPrimary` | small-caps `metaCaps`, `inkBlue`, tracked 0.8 |
| Profile button | 34×34pt | 44×44pt, embedded in `EditionHeader` avatar slot |
| Removed | `articleContextMenu`, `heroHeader`, `dateHeader`, `profileButton`, `formattedHeroDate`, `SectionLabelStyle` | — |
| `BriefingCard.swift` | `BrandColors.*` | `EditionPalette.ink` / `ink60` / `inkBlue` |
| `SkeletonViews.swift` | `Color(.tertiarySystemFill)`, `Color(UIColor.label).opacity(0.15)` | `EditionPalette.paperSecondary`, `EditionPalette.ink.opacity(0.10)` |

### Three judgment calls (approved before execution)

1. **Long-press swap.** `.onLongPressGesture` → `WhyThisStorySheet` (3 corrective actions). The 4 other contextMenu actions are dropped from the feed: Bookmark/Share/Discuss reachable from `ArticleDetailView`; **More Like This is lost** in Phase 2 — Phase 4 (Tune) re-introduces it. Captured in `tasks/lessons.md`.
2. **Provenance gating.** `HeroStory.provenance = article.whyThisStory` (nil → no line). Cold/Warming/Earned state machine deferred until taste-model exposes confidence. Today's behavior: hero shows provenance only when backend populates it.
3. **Section label restyle scope.** `sectionLabel` helper restyled (affects "Top Story" + "For You"). Welcome banner / error banner / loading subtitle keep their current `BrandColors` references — Phase 9 cleanup migrates them globally.

### Checklist

- [x] **2a.** `editionHeader` calls `EditionHeader(dateLabel: editionDateLabel, editionName: editionName) { profileAvatar }`. Helpers compute "MAY 7" and "SARAH".
- [x] **2b.** `ScrollView.background = EditionPalette.paper`.
- [x] **2c.** `sectionLabel` simplified to one style: `metaCaps`, tracking 0.8, `EditionPalette.inkBlue`, `.textCase(.uppercase)`.
- [x] **2d.** Hero swap: `HeroStory` + `.onLongPressGesture`. Horizontal padding dropped (full-bleed).
- [x] **2e.** Feed rows swap: `StoryRow` + `.onLongPressGesture` + sepia hairline `Rectangle` between rows.
- [x] **2f.** `@State private var selectedFeedbackArticle: NewsArticle?` + `.sheet(item:)` presenting `WhyThisStorySheet` wired to `viewModel.submitFeedback`.
- [x] **2g.** Removed dead helpers: `heroHeader`, `dateHeader`, `profileButton`, `articleContextMenu`, `formattedHeroDate`, `SectionLabelStyle` enum.
- [x] **2h.** BriefingCard palette swap (8 token replacements).
- [x] **2i.** SkeletonViews palette swap (2 token replacements).
- [ ] **2j.** Build clean (`xcodebuild ... iPhone 17 Pro`).
- [ ] **2k.** Simulator boot: tap-through Feed → ArticleDetail → back; long-press a row → WhyThisStorySheet appears with three actions; tap profile (44pt) → ProfileView.
- [x] **2l.** `tasks/lessons.md` updated with the contextMenu-loss note for Phase 4.
- [ ] **2m.** Single commit: `feat: replace feed surface with edition header + hero + story rows`.

### Out of scope

- `welcomeBanner`, `errorBanner`, "Loading your personalized feed..." text — Phase 9 global migration.
- `FeaturedArticleCard` struct stays as dead code; Phase 9 deletes it.
- Re-introducing "More Like This" affordance — Phase 4 (Tune) takes ownership.

---

## Previously shipped

- **Phase 1** — Tokens & Components Scaffolding. Commit `38b83ef`. Added `EditionPalette`, 7 typography tokens, 6 components (`EditionHeader`, `HeroStory`, `StoryRow`, `ProvenanceLine`, `WhyThisStorySheet`, `DiffToast`).
- **Foundation** — DESIGN.md and 10-phase plan. Commit `1df9f6b`.
