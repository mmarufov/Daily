# Daily Redesign — Active Plan

This file tracks the **current phase** of the whole-app redesign. The full design system is in `DESIGN.md`; the per-surface execution roadmap (Phases 1–10) is in `tasks/design-redesign-plan.md`. This file is the focused checklist for what's being built right now.

---

## Phase 1 — Tokens & Components Scaffolding

**Status:** in progress
**Goal:** Add the new visual primitives (color tokens, typography tokens, six new SwiftUI components) without changing any user-visible behavior.

After Phase 1, the app builds and runs **identically** to today. Phase 2+ can swap `FeaturedArticleCard.style=.hero` → `HeroStory` (etc.) with one-line view replacements.

### Codebase facts that shape this phase

- `Daily/Theme/AppTheme.swift` (327 lines) is the single theme file. It exposes `BrandColors`, `AppTypography`, `AppSpacing`, `AppCornerRadius`, `AppShadows`, `AppGradients`, `GlassCardModifier` and a private `dynamicColor(light:dark:)` helper at `AppTheme.swift:10` (returns SwiftUI `Color`).
- `FeaturedArticleCard` is inline in `Daily/Features/News/Views/NewsView.swift:357+`, not a separate file. `CardStyle` enum has `.standard`, `.feed`, `.hero`.
- `Daily/Features/Chat/` exists; **no `Tune/` or `Onboarding/` folder yet**.
- `Daily.xcodeproj` uses `PBXFileSystemSynchronizedRootGroup` (Xcode 16+). New files under `Daily/` are auto-discovered — **no pbxproj edits needed**.
- `CategoryFilterBar.swift` is currently wired up in NewsView despite the briefing claiming "already unused". Phase 9 must un-wire before deletion.
- Image loading uses `AsyncImage(url:)` with phase switching; `URLCache.shared` is configured by `ImageCacheService` (`Daily/Services/ImageCacheService.swift:35`) so AsyncImage benefits from a 50MB/200MB cache transparently.
- News article model is `NewsArticle` (not `Article`) at `Daily/Features/News/Models/NewsArticle.swift`.

### Three judgment calls (deviating from briefing's literal text)

1. **DiffToast placement.** Briefing puts all six new components under `News/Views/Components/`, but DiffToast is a Tune-surface component per `DESIGN.md` and `design-redesign-plan.md`. Placing it at `Daily/Features/Tune/Views/Components/DiffToast.swift` — also creates the new Tune feature folder.
2. **Empty `Onboarding/` folder.** Briefing wants it created in Phase 1, but no Onboarding files are in scope until Phase 8 and empty folders don't survive `git`. Deferred to Phase 8.
3. **`AppTypography.heroHeadline` collision.** Existing `heroHeadline = .system(.largeTitle, design: .serif, weight: .bold)` already matches DESIGN.md spec semantically (serif bold, scales via Dynamic Type). Reusing the existing token; not adding a parallel `editionHeroHeadline`. New `brandWordmark` is a semantically-named alias.

All three confirmed before execution.

### Checklist

- [ ] **1a.** Create `Daily/Theme/EditionPalette.swift` — 9 ink+ochre tokens + `hairlineWidth`. Reuses existing `dynamicColor()` helper.
- [ ] **1b.** Append new editorial-scale tokens to `AppTypography` in `Daily/Theme/AppTheme.swift`: `brandWordmark`, `signatureCaps`, `dek`, `rowHeadline`, `metaCaps`, `bodyReading`, `composer`. Additive only; no existing token mutated.
- [ ] **1c.** Create five new components in `Daily/Features/News/Views/Components/`: `EditionHeader.swift`, `HeroStory.swift`, `StoryRow.swift`, `ProvenanceLine.swift`, `WhyThisStorySheet.swift`. Each pure presentation with `#Preview` blocks.
- [ ] **1d.** Create `Daily/Features/Tune/Views/Components/DiffToast.swift` — pure presentation, two-line diff + Undo (caller owns visibility).
- [ ] **1e.** Verify build — `xcodebuild -project Daily.xcodeproj -scheme Daily -destination 'platform=iOS Simulator,name=iPhone 15 Pro' build` clean (no warnings, no errors).
- [ ] **1f.** Confirm `Daily.xcodeproj/project.pbxproj` is unchanged in `git diff`.
- [ ] **1g.** Single commit: `feat: add edition palette and scaffold redesign components`.

### Token specifications

#### EditionPalette (1a)

| Token | Light | Dark | Usage |
|---|---|---|---|
| `paper` | `#FCFAF7` | `#15120E` | Primary background |
| `paperSecondary` | `#F4EFE6` | `#1C1916` | Subtle surface |
| `ink` | `#1F1B17` | `#F0EDE6` | Headlines, body, primary text |
| `ink60` | rgba(31,27,23,0.60) | rgba(240,237,230,0.65) | Secondary text, dek |
| `inkBlue` | `#2D3F5F` | `#7E92B5` | Source labels, brand wordmark, tab tint |
| `ochre` | `#C97D2E` | `#E0985A` | Edition stamp + hero provenance ONLY |
| `sepia` | `#D9CFBF` | `#2A2520` | Hairlines |
| `error` | `#B23B2E` | `#D6614F` | Errors |
| `success` | `#6E8B5F` | `#88A57A` | Save toasts |

#### Typography additions (1b)

| Token | Definition | Use site |
|---|---|---|
| `brandWordmark` | `.system(.largeTitle, design: .serif, weight: .bold)` | "Daily" logo |
| `signatureCaps` | `.system(.caption2, design: .default, weight: .bold)` | Edition stamp + provenance |
| `dek` | `.system(.body, design: .serif, weight: .regular)` | Lead-in below headlines (italicized at use site) |
| `rowHeadline` | `.system(.body, design: .serif, weight: .semibold)` | Earlier-today rows |
| `metaCaps` | `.system(.caption2, design: .default, weight: .bold)` | Source labels, section anchors |
| `bodyReading` | `.system(.body, design: .serif, weight: .regular)` | Article body |
| `composer` | `.system(.body, design: .default, weight: .regular)` | Tune composer |

Tracking, italic, line spacing, and `.textCase(.uppercase)` are applied at the use site, not baked into the token.

### Out of scope for Phase 1

Phases 2–10 cover: NewsView wiring; Article reader restyle; Tune (Chat → Tune rename + composer-on-top + DiffToast wiring + LiveFeedPeek + backend diff payload); Profile rebuild; Saved grouping; Search trending; Onboarding (5 screens); cleanup (delete unused, migrate from `BrandColors`/`AppGradients`/`glassEffect`/`sparkles`); verification sweep.

### Lessons captured

See `tasks/lessons.md` (created on first user correction).
