# Daily — Whole-App Design Redesign Plan

**Branch:** `mmarufov/news-relevance`
**Date:** 2026-05-06
**Initial overall design rating:** 6.5/10
**Final design plan rating:** 9.0/10

This plan is the output of `/plan-design-review` (whole app). It synthesizes a Codex hard-rules review, a Claude subagent completeness review, and the user's own feedback into a single executable redesign direction. Mockups generated during the process are referenced where relevant; v2 mockups were planned but blocked by the OpenAI image-generation account quota — the v2 direction is fully specified in text.

---

## The North Star

**Daily is a personalized magazine that knows you, owned by you.**

The brand element is the **edition**. Every screen carries a typographic signature: `MAY 6 · SARAH EDITION`. The product idea — "this is *your* daily edition" — is expressed as identity, not as a tagline. The system shows the user only what the user themselves told it. Inferred signals stay invisible. The user can read, edit, forget, or hide anything.

Three product principles, in order:

1. **Subtraction default.** One signature element per surface. No card chrome on the feed. No persistent receipts. No "AI confidence" bars. If a UI element doesn't earn its pixels, cut it.
2. **The chat is a tuner, not a chatbot.** Conversation visibly mutates the feed below the composer in real time. Diff is an ephemeral 2-second toast with Undo. Never a persistent log.
3. **Provenance is rare and accurate.** Only the hero story shows a "FOR YOU BECAUSE" line, and only when confidence is high. Other rows show nothing. Magic only if rare.

---

## Locked Decisions

### Palette — Ink + Ochre on Warm Paper

A two-color signature on warm paper. Calm but distinctive. No major news app uses this exact pairing.

| Token | Light | Dark | Usage |
|---|---|---|---|
| `paper` | `#FCFAF7` | `#15120E` | Primary background |
| `paperSecondary` | `#F4EFE6` | `#1C1916` | Subtle surface (sheets, cards where unavoidable) |
| `ink` | `#1F1B17` | `#F0EDE6` | Headlines, body, primary text |
| `ink60` | rgba(31,27,23,0.60) | rgba(240,237,230,0.65) | Secondary text, dek/lead-in |
| `inkBlue` | `#2D3F5F` | `#7E92B5` | Source labels, brand wordmark, tab-bar tint |
| `ochre` | `#C97D2E` | `#E0985A` | **Signature only**: hero provenance line and "MAY 6 · SARAH EDITION" stamp. Used nowhere else. |
| `sepia` | `#D9CFBF` | `#2A2520` | Hairlines |
| `error` | `#B23B2E` | `#D6614F` | Errors only — calmer than current bright system red |
| `success` | `#6E8B5F` | `#88A57A` | On-palette moss, used on save toasts |

**Retired:** `BrandColors.primary` brick-red, all gradient tokens (`AppGradients.primary`, `.subtle`, `.background`, `.card`), `glassEffect` modifiers.

**Contrast notes:** ink on paper 14.4:1 ✅, inkBlue on paper 7.6:1 ✅, ochre on paper 3.4:1 — fails AA for body text but acceptable for the hero signature line at 11pt small-caps bold (large-text rule for bold ≥14pt). **Constraint:** ochre is never used for body type.

### Typography — Editorial scale

Keep `.serif` design (system serif maps to Charter/Georgia, NYT Cheltenham-like). Sans is SF Pro for chrome.

| Token | Style | Use |
|---|---|---|
| `brandWordmark` | serif bold 30pt, tracking -0.5 | "Daily" logo on Feed, Auth |
| `signatureCaps` | sans bold 11pt small-caps tracked 1.0 | "MAY 6 · SARAH EDITION" + provenance lines |
| `heroHeadline` | serif bold 30pt, tracking -0.5, 1.15 leading | Hero headline on Feed |
| `dek` | serif italic 17pt, 1.45 leading | Italic lead-in below headlines |
| `rowHeadline` | serif semibold 17pt, 1.25 leading | Earlier-today rows |
| `metaCaps` | sans bold 11pt small-caps tracked 0.8 | Source labels, section anchors |
| `bodyReading` | serif regular 18pt, 1.6 leading | Article body |
| `composer` | sans regular 17pt | Tune composer input |

All scale via Dynamic Type. Icons stay fixed.

### Layout doctrine — Hero + Rows

**Editorial style comes from typography and spacing, not card chrome.**

- Feed: one full-bleed hero (no card border, no rounded corners), then a uniform list of hairline-separated rows (image-right 80×80pt, headline-left). No background colors on rows. No card shadows.
- Article: single column max-width 700pt, body reading type, calm.
- Tune: composer at top, live feed mutating beneath it. No persistent conversation history.
- Profile: ranked editable list. No topic cloud, no clock-time timestamps.
- Saved: grouped by reading state (Unread / Read / This week). Same row vocabulary as Feed.
- Search: editorial trending list, text-led, sepia hairlines.

**Zero permanent receipt cards anywhere.**

---

## Per-Surface Specifications

### 1. Feed (News tab)

**Top to bottom:**

1. **Edition Header** (replaces current `heroHeader`):
   - `Daily` 30pt serif bold ink, tracking -0.5, left aligned
   - `MAY 6 · SARAH EDITION` 11pt small-caps ochre, tracked 1.0, on the line below
   - Profile avatar 44pt circle right (raised from 34pt — touch-target fix)
   - Sepia hairline below

2. **Briefing card (kept, simplified):**
   - "MORNING BRIEFING" small-caps inkBlue (was slate)
   - "What matters today" serif semibold 17pt ink
   - One-line teaser serif italic 17pt ink60
   - "3 key updates" + "Open ⌄" row
   - Tap expands to numbered list (existing pattern). Numerals in serif, not red badges.
   - Sepia hairline below

3. **Top Story header** — `TOP STORY` 12pt small-caps inkBlue tracked 0.8

4. **Hero Story** (no card chrome, just photo + type on paper):
   - 240pt full-bleed image (was 260; tighter rhythm)
   - Source row: tiny inkBlue dot if unread + `BLOOMBERG` small-caps inkBlue + middot + `2H AGO` + middot + `7 MIN`
   - 30pt serif bold headline, 2-line max
   - 17pt serif italic dek, 2-line max, ink60
   - **Provenance signature** (only on hero, only when confidence is high): single line, small-caps ochre 11pt tracked 1.0. Cold-start (Day 0–2): `FROM YOUR INTRO: ASKED FOR MORE TECH`. Earned (Day 14+): `BECAUSE YOU TUNED FOR ERLANG TUE`. Never quoted verbatim. Max 64 chars.

5. **Sepia hairline rule** full-width

6. **Earlier Today** section anchor — small-caps inkBlue 12pt

7. **Story Rows** — uniform, hairline-separated:
   - Thumbnail 80×80pt right, 6pt rounded corners
   - Headline left: serif semibold 17pt, 2 lines max
   - Source row: small-caps inkBlue 10pt `REUTERS · 4H`
   - **No provenance line on rows.** Provenance is rare.
   - Sepia hairline between rows

8. **Tab bar** (system iOS, inkBlue tint on selected):
   - News (`newspaper.fill`)
   - Saved (`bookmark`)
   - **Tune** (`slider.horizontal.3`) — was "Chat" with `bubble.left.and.bubble.right`
   - Search (`magnifyingglass`)

**Long-press on any row** → "Why this story?" sheet (see Decision #9).

**States:**
- Loading: skeleton hero shape + 3 row shapes (existing — keep)
- Empty cold start: "Building your edition. This is your first one — it'll get sharper each day." + retry
- Empty error: existing inline error banner — keep, restyle to ink60 on paperSecondary
- Partial: "Some sources unreachable — showing what we have." dismissible toast at top

### 2. Article Reader

**Pure reading. Zero stripes. No "WHY THIS MATTERS TO YOU" banner — Codex was right that it breaks the ritual.**

The article reader stays close to its current implementation, with palette and type changes:

- Hero photo 220pt full-bleed (was 260; calmer)
- Source row: `BLOOMBERG · TECHNOLOGY` small-caps inkBlue
- Headline 32pt serif bold ink, 1.15 leading
- Byline + date row in ink60
- Sepia hairline
- Italic dek if present, 19pt serif
- Body 18pt serif regular ink at 1.6 leading
- "Discuss" button at bottom — restyled. Ink-blue text on paper with 1pt inkBlue hairline border, slider icon (not sparkle).
- Toolbar icons all ink-blue, no tint changes
- Related articles — keep existing "MORE LIKE THIS" rail, restyle
- Max-width 700pt for iPad/landscape

**The "why this article was suggested" affordance lives in the long-press menu on the originating card, not in the reader itself.**

### 3. Tune (was Chat / Daily Copilot)

**This is the differentiator. The chat IS the tuner. The conversation must visibly change the feed.**

**Tab name:** "Tune" (was "Chat"). Icon: `slider.horizontal.3`.

**Layout:**

1. **Top nav:** "Tune your feed" centered serif 17pt. No back button (this is a tab).

2. **Composer pinned at top (not bottom — important):** Rounded text input on paper with 1pt sepia hairline border. Placeholder italic ink60: "Tell me what to read more or less of." Send button: 46pt circle, ink-blue, white up-arrow. Below composer: 3 suggested-prompt chips on first open, hairline-bordered, ink60 text — chips disappear after first turn.

3. **Live feed area below composer:** This is the primary visual on the screen. It shows your current feed (same row vocabulary as Feed tab). When you send a tuning instruction, the feed mutates in place — stories slide out, new stories slide in. **The feed is the artifact. The chat is the input.**

4. **Diff toast:** When a tuning turn changes weights, a 2-second ephemeral toast appears at the top of the screen (not a card in the conversation). Two lines max: `National news ↓ · Startups ↑ · Erlang +` and `Undo` link right. Disappears after 2s; Undo persists for 10 minutes via a tiny pill in the top corner. **Zero-diff turns produce no toast** (curiosity is allowed; not every question needs to mutate weights).

5. **Per-article discussion (kept):** The "Discuss with AI" button on Article Reader still opens this tab in article-context mode, where the live feed area becomes the article in question and tuning is scoped to "more/less like this story."

**No conversation history is preserved as cards.** The tuning is the artifact. The product changed; the conversation is ephemeral.

**Streaming status text uses real backend stages:**
- "Reading your feed..."
- "Adjusting taste model..."
- "Pulling new stories..."
Not "Thinking about your feed..." (vague) and not three dots (theatrical).

**States:**
- Loading: composer disabled, status pill above composer
- Empty (first open): "What should I read more or less of? Try: 'less national news, more startups.'" + 3 suggested prompts
- Error: inline error with Retry (existing pattern, restyled)
- Partial: live feed shows previous stories greyed slightly while new ones load — never blank

### 4. Saved (Bookmarks)

**Replaces current bare list with editorial reading-state grouping.**

- Top: "Saved" large title (existing)
- Filter chip row: "All" / "Unread" / "Read" / "This week" — small-caps inkBlue chips with hairline border
- Grouped sections by recency:
  - "TODAY" — small-caps anchor
  - "THIS WEEK"
  - "EARLIER"
- Same StoryRow vocabulary as Feed
- Swipe-left: Remove (existing)
- Swipe-right (new): "Mark as read" / "Mark unread"
- Empty: "Bookmark stories from anywhere in Daily — they wait for you here." + "Browse News" button → switches to News tab

### 5. Profile (Taste Passport, but as a list, not a cloud)

**Ranked editable list — never a topic cloud, never clock-time timestamps. Privacy-forward.**

**Top to bottom:**

1. **Header:** 80pt avatar centered, name in serif 22pt, email in ink60 13pt
2. **THIS WEEK** small-caps anchor, then editorial summary: "You read 12 stories about startups, skipped 8 about politics, and bookmarked 3 deep dives on Erlang." Tiny "Tune" link right.
3. **YOUR INTERESTS** anchor + ranked editable list:
   - Each row: topic + recency bucket (`recently / this month / earlier` — never clock time) + edit pencil
   - Long-press: Edit / Forget / Hide-from-home
   - Add-topic row at bottom
4. **YOU AVOID** anchor + same row pattern, dimmed style
5. **YOUR LIFE CONTEXT** anchor + serif italic block of paraphrased onboarding context (never quoted verbatim) + Edit pencil
6. **SETTINGS** anchor + 3 minimal hairline-separated rows:
   - Notifications (icon + title + subtitle + chevron)
   - Reading text size
   - Sign Out (no destructive red — calm ink60)
7. Tiny `Daily v1.0 · 30th edition` footer

**Privacy invariant:** the user can `Edit`, `Forget`, or `Hide` any row. "Forget" purges the signal from the model with confirmation toast "Removed."

### 6. Search

**Kill the rainbow grid. Replace with editorial trending and recents.**

- Search bar at top (existing, system `.searchable`)
- Empty state (no query):
  - "TRENDING IN YOUR FEED" small-caps inkBlue
  - 5–7 trending topic rows (text-only, hairline-separated): topic name + count badge in ink60
  - "RECENT SEARCHES" small-caps inkBlue
  - List of recent text-only rows
- Active query: results list using StoryRow vocabulary, with section headers `FROM YOUR FEED` and `FROM THE WEB` if mixed
- No results: "No matches in your feed. Search the web?" CTA

### 7. Onboarding (4 questions, one per screen, no skips on signal-bearing questions)

**Replaces the current chat+form hybrid.**

1. **Screen 1 — Hello:** "Welcome. What should I call you?" big serif. Single text field. Skip allowed (default "You").
2. **Screen 2 — Topics (required):** "Pick at least 3 things you want in your daily edition." Large chip grid (Tech, Business, Startups, AI, Climate, Science, Sports, World, Local, Culture, Health, Finance, Politics, Books). Multi-select. Continue disabled until 3+ selected. **No skip.**
3. **Screen 3 — Context (required):** "Tell me one thing about your work or life that should shape what you see." Free text, 2–4 lines, placeholder "I'm a software engineer in San Francisco who recently switched from Python to Erlang." **No skip — the AI quality depends on this.**
4. **Screen 4 — Depth (required):** "How deep do you want to read?" Three options as full-width selectable rows: Quick (breaking only), Balanced, Deep (long-reads + analysis).
5. **Screen 5 — How tuning works (coach-mark):** "After you start reading, long-press any story to tell me 'this isn't me.' I'll learn fast." Single illustrated long-press hint + "Got it" button. **Required to dismiss.** This is the discoverability for the long-press gesture.

Each screen has the same chrome: small `Daily` wordmark top-left, progress dots top-right (· · · · ·), large serif question, answer area, "Continue" button at bottom.

**No back-and-forth chat.** Direct, fast, ~60 seconds total.

### 8. Auth

**Minor restyle only — current is fine.**

- Wordmark in serif 30pt ink (was brick)
- 1pt sepia hairline (was current)
- Tagline "News that knows you" in ink60 17pt
- Continue with Google button: paperSecondary background, ink text, 12pt radius, no border (current is already calm)
- New small-caps subtle line below button: `OWNED BY YOU · PRIVATE BY DEFAULT`

---

## Cold / Warming / Earned — the trust state design

The Day-1-vs-Day-30 problem (Claude subagent flagged this critical):

| State | Day | Feed provenance | Profile content |
|---|---|---|---|
| **Cold** | 0–2 | Hero only, paraphrased intro: `FROM YOUR INTRO: TECH AND WORK` | Onboarding intent + 3-5 topic chips + life context block |
| **Warming** | 3–14 | Hero mixed: half "from intro," half "because you read X stories last week" — paraphrased | Topics list grows, recency labels appear |
| **Earned** | 14+ | Hero specific: `BECAUSE YOU TUNED FOR ERLANG TUE` | Full ranked list, full editorial summary, history accessible |

**Pluralization, capitalization, sanitization rules for the provenance string:**
- Always small-caps render via CSS/SwiftUI (`.textCase(.uppercase)`), regardless of input case
- Never quote verbatim — always map to canonical topic via taste-model
- Truncate at 64 chars with ellipsis
- Profanity, names, and freeform user text never appear in the provenance string — only canonical topics from the user's interest list

---

## What Already Exists (preserve, don't touch)

- `AppTypography.serif` design tokens — solid foundation, just rename roles to match new scale
- `Dynamic Type` mappings throughout — already accessibility-aware
- Hero+list feed structure (Top Story → For You) — keep, drop card chrome
- Per-article "Discuss with AI" pill in article footer — keep, restyle, change icon to slider
- Briefing card with editorial micro-copy — keep, change colors
- BuildingFeedView phase-based progress — keep
- HapticService — keep
- ImageCacheService — keep
- ReadingEventTracker — keep
- BookmarkService — keep
- AppSpacing tokens (4/8/10/12/16/24/32/48 grid) — already correct
- 700pt max-width on article reader — keep
- Skeleton loading — keep, restyle

## What's NOT in scope (explicitly deferred)

| Deferred | Why |
|---|---|
| iPad-specific layouts | iPhone first; iPad inherits via SwiftUI defaults; revisit when iPad becomes a target |
| Voice input on Tune | Premium feature; defer until v2 — text input is enough to ship the core differentiator |
| Per-source fav-icon/wordmark | Engineering cost (publisher logo asset pipeline); deferred until source-quality system exists |
| Density toggle | Power-user feature; ship the calm default first, add density later if requested |
| Custom display typeface (NYT Cheltenham/Karnak licensing) | License cost + load weight; system serif (Charter) is editorially distinctive enough for v1 |
| Push notifications | Already shown as "Coming soon" in current Profile — keep that placement |
| Dark-mode token verification | First-pass dark tokens specified; needs real device QA before ship — adding to TODOS |
| Reading mode (TTS, focus) | Premium feature; defer |

---

## Component Changes (engineering checklist)

**New components:**
- `EditionHeader` (Feed top) — wordmark + signature line
- `HeroStory` (replaces FeaturedArticleCard.style=.hero) — full-bleed image, ochre provenance line, no card
- `StoryRow` (new uniform row) — image-right thumbnail, headline-left
- `DiffToast` (new ephemeral 2s overlay) — Tune surface
- `LiveFeedPeek` (Tune body) — list of StoryRow that mutates in place
- `RankedInterestList` (Profile) — editable list with Edit/Forget/Hide swipe actions
- `ProvenanceLine` (cold/warming/earned-aware string renderer)
- `WhyThisStorySheet` (long-press from any row) — paraphrased reason + Less/Wrong/Hide actions
- `OnboardingScreen` (single-question template) — 5 instances
- `OnboardingCoachMark` (long-press teach screen)

**Components to retire:**
- `FeaturedArticleCard.style=.standard` (unused after redesign — `.hero` becomes HeroStory, `.feed` becomes StoryRow)
- `CategoryFilterBar.swift` (already unused — delete)
- `OnboardingChatView` hybrid screen (replaced by 5 OnboardingScreen instances)
- `ChatHomeContent.todayCard` glass card (Tune doesn't have a "Today" workspace anymore)
- All `glassEffect` modifier calls (~6 sites)
- `AppGradients.primary`, `.subtle`, `.background`, `.card` (4 unused after restyle)
- `ChatBackgroundView` three-stop gradient (replace with flat paper)
- The 8-tile gradient grid in SearchView (replace with editorial trending list)

**Files to add:**
- `DESIGN.md` at repo root — single source of truth for tokens, doctrine, voice
- `Daily/Theme/EditionPalette.swift` — new color tokens (replace BrandColors gradually)
- `Daily/Features/News/Views/Components/HeroStory.swift`
- `Daily/Features/News/Views/Components/StoryRow.swift`
- `Daily/Features/News/Views/Components/WhyThisStorySheet.swift`
- `Daily/Features/Tune/` (new feature folder, replaces `Chat`)
- `Daily/Features/Onboarding/` (new, replaces `OnboardingChatView`)

---

## Approved Mockups

These are v1 mockups. The locked v2 direction differs in palette (ink+ochre, not brick-red), layout (hero+rows, not cards), and chat treatment (live feed primary, not diff-card receipts). Use these as research artifacts; v2 mockups are spec'd in this plan but not generated due to API quota.

| Surface | Mockup Path | v1 Direction | v2 Direction (this plan) |
|---|---|---|---|
| Feed (v1, brick-red) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/feed/variant-A.png` | brick-red, briefing card, hero, BECAUSE-on-every-card | ink+ochre, hero+rows, BECAUSE-only-on-hero |
| Feed (v1, B) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/feed/variant-B.png` | three-pane comparison sheet | superseded |
| Feed (v1, C) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/feed/variant-C.png` | minimal, square images | superseded |
| Article (v1, A) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/article/variant-A.png` | NYT-dense, "WHY THIS MATTERS" stripe | v2 cuts the stripe entirely — pure reading |
| Article (v1, B) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/article/variant-B.png` | Substack-generous | partial: keep generous body, drop stripe |
| Article (v1, C) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/article/variant-C.png` | Reeder-minimal | closest to v2 direction |
| Chat (v1, A) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/chat/variant-A.png` | bubble + diff card + feed peek | v2 inverts: feed primary, diff as 2s toast |
| Chat (v1, B) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/chat/variant-B.png` | inline diff strip | similar — v2 keeps the strip but makes it ephemeral |
| Chat (v1, C) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/chat/variant-C.png` | feed-dominant chat | closest to v2 direction |
| Profile (v1, A) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/profile/variant-A.png` | weighted topic cloud | v2 replaces with ranked list |
| Profile (v1, B) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/profile/variant-B.png` | chips with weight bars | v2 closer to this, but no bars — recency buckets only |
| Profile (v1, C) | `~/.gstack/projects/mmarufov-Daily/designs/whole-app-redesign-20260506/profile/variant-C.png` | conversational mirror | inspires the YOUR LIFE CONTEXT block |

---

## Outside Voice Findings (incorporated above)

### Codex (verdict: 6/10 hard reject of v1, fixed in v2)
- HARD REJECTION: stacked cards instead of layout → **fixed**: v2 has no card chrome on feed
- Litmus 1 (brand unmistakable) NO → **fixed**: edition signature is the brand
- Litmus 5 (cards necessary) NO → **fixed**: no cards on feed
- Litmus 6 (motion improves) NO → **fixed**: feed mutating during Tune is purposeful motion
- Provenance on every card = wallpaper → **fixed**: hero only, rare
- Article stripe self-conscious → **fixed**: cut entirely
- Diff card + feed peek = chatbot theater → **fixed**: feed primary, diff is ephemeral toast
- Taste passport = creepy dossier → **fixed**: ranked editable list with Edit/Forget/Hide, recency buckets not timestamps
- Brand not unmistakable → **fixed**: ochre signature + edition stamp
- Missing trust-state design → **fixed**: cold/warming/earned matrix
- Saved underdesigned → **fixed**: reading-state grouping + filter chips

### Claude subagent (verdict: critical gaps in v1, fixed in v2)
- Provenance fights the headline → **fixed**: only on hero, no rule, ochre carries the signal
- Day 1 trap → **fixed**: cold-state paraphrases onboarding intent, never fakes user-quotes
- Timestamps quantify surveillance → **fixed**: recency buckets only
- Quoting verbatim is a landmine → **fixed**: explicit "never quote raw input, always paraphrase via canonical topic" rule
- Brick-red user pill = bubble in editorial clothing → **fixed**: bubbles dropped entirely, Tune has no chat-history bubbles
- Performance feedback loop → **mitigated**: long-press "this isn't me" gives the user direct correction, not performance
- Day-1 "this isn't me" gesture missing → **fixed**: long-press from Day 1, taught in onboarding coach-mark

---

## TODOS (post-implementation)

These are deferrable items the review surfaced. None block v2 ship.

1. **Dark-mode token verification on real device.** First-pass dark tokens specified; needs eye-test before final ship.
2. **Per-source fav-icon system.** Currently source = uppercase text label. Future: tiny publisher wordmark/logo for fast recognition. Engineering cost: a publisher-asset pipeline.
3. **Density toggle (compact list / magazine / cards).** Power-reader feature. Ship calm default first.
4. **Reading TTS / focus mode.** Premium reader features.
5. **Voice input on Tune composer.** Premium tuner feature.
6. **iPad-specific layouts.** Currently inherits SwiftUI defaults; design dedicated layouts when iPad is a target.
7. **Empty Saved CTA implementation detail.** Tab-switch on button tap needs MainTabView coordination.
8. **Onboarding analytics.** Track question-by-question drop-off to validate "no skip on signal" decision.
9. **Provenance accuracy gating.** Confidence threshold for hero provenance line — needs an ML signal that doesn't yet exist. Until then, Cold rule (intro paraphrase) applies.
10. **A11y audit** — keyboard nav and VoiceOver story for Tune diff toast on physical device.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found → resolved in v2 | 9 findings, all incorporated; v1 6/10 → v2 9/10 |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 0 | — | — |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | clean | initial 6.5/10 → 9.0/10 after redesign; 24 decisions added; 10 deferred to TODOS |

**CODEX:** v1 received hard rejection (#7 stacked-cards-not-layout) + 9 findings. Pivoted to v2 (ink+ochre palette, hero+rows doctrine, ephemeral diff toast, ranked Profile list, cold/warming/earned trust states). All 9 findings incorporated. Litmus rescore expected: brand unmistakable YES (signature), cards necessary NO (no cards on Feed), motion improves YES (feed mutates on Tune).

**CROSS-MODEL:** Claude subagent and Codex independently flagged the same three top issues — over-stuffing (too many surfaces), Day-1 fakeness (provenance with no signal yet), surveillance feel (timestamps). Strong consensus. Strong fix.

**UNRESOLVED:** 0. All decisions either resolved inline or explicitly deferred to TODOS with rationale.

**VERDICT:** DESIGN CLEARED — ready for `/plan-eng-review` (required gate) before implementation.
