# DESIGN.md — Daily Design System

**Last updated:** 2026-05-06 (from `/plan-design-review` — see `tasks/design-redesign-plan.md`)

This is the single source of truth for Daily's visual design. If a UI change conflicts with this file, update this file first, then ship.

---

## North Star

**Daily is a personalized magazine that knows you, owned by you.** The brand element is the *edition*. Every screen carries `MAY 6 · SARAH EDITION` as a typographic signature. The product idea — "this is *your* daily edition" — is expressed as identity, not as a tagline.

Three principles, in order:

1. **Subtraction default.** One signature element per surface. No card chrome on the feed. No persistent receipts. If a UI element doesn't earn its pixels, cut it.
2. **The chat is a tuner, not a chatbot.** Conversation visibly mutates the feed. Diff is an ephemeral 2s toast. Never persistent.
3. **Provenance is rare and accurate.** Hero only, high-confidence only. Magic only if rare.

---

## Color Tokens

| Token | Light | Dark | Usage |
|---|---|---|---|
| `paper` | `#FCFAF7` | `#15120E` | Primary background |
| `paperSecondary` | `#F4EFE6` | `#1C1916` | Subtle surface |
| `ink` | `#1F1B17` | `#F0EDE6` | Headlines, body, primary text |
| `ink60` | rgba(31,27,23,0.60) | rgba(240,237,230,0.65) | Secondary text, dek |
| `inkBlue` | `#2D3F5F` | `#7E92B5` | Source labels, brand wordmark, tab tint |
| `ochre` | `#C97D2E` | `#E0985A` | **Signature only**: hero provenance + edition stamp |
| `sepia` | `#D9CFBF` | `#2A2520` | Hairlines |
| `error` | `#B23B2E` | `#D6614F` | Errors |
| `success` | `#6E8B5F` | `#88A57A` | Save toasts (on-palette moss) |

**Invariants:**
- Ochre is used ONLY on the edition stamp and hero provenance line. Nowhere else.
- No purple, indigo, teal, pink, neon. No gradients except photo vignettes.
- One accent (ink-blue) for chrome; one signature (ochre) for personalization signals.
- Dark mode is warm-near-black (`#15120E`), never pure black.

---

## Typography

System serif (`.serif` design, maps to Charter/Georgia) for editorial. SF Pro for chrome. All scale via Dynamic Type.

| Token | Style | Use |
|---|---|---|
| `brandWordmark` | serif bold 30pt, tracking -0.5 | "Daily" logo |
| `signatureCaps` | sans bold 11pt small-caps tracked 1.0 | Edition stamp + provenance |
| `heroHeadline` | serif bold 30pt, tracking -0.5, 1.15 leading | Hero on Feed |
| `dek` | serif italic 17pt, 1.45 leading | Lead-in below headlines |
| `rowHeadline` | serif semibold 17pt, 1.25 leading | Earlier-today rows |
| `metaCaps` | sans bold 11pt small-caps tracked 0.8 | Source labels, section anchors |
| `bodyReading` | serif regular 18pt, 1.6 leading | Article body |
| `composer` | sans regular 17pt | Tune composer |

---

## Layout Doctrine — Hero + Rows

Editorial style comes from typography and spacing, not card chrome.

- **Feed:** one full-bleed hero (no card border, no rounded corners), then hairline-separated rows (image-right 80×80, headline-left). No backgrounds, no shadows.
- **Article:** single column max-width 700pt, body reading type, calm.
- **Tune:** composer pinned at top, live feed mutating beneath.
- **Profile:** ranked editable list. No cloud, no clock-time timestamps.
- **Saved:** grouped by reading state (Today / This week / Earlier).
- **Search:** editorial trending list, text-led.

**Zero permanent receipt cards anywhere.**

---

## Spacing & Radius

- Spacing grid: 4 / 8 / 10 / 12 / 16 / 24 / 32 / 48pt (existing `AppSpacing` tokens).
- Radius: thumbnails 6pt, buttons 12pt, sheets 20pt. **No full pills (no `radius: 999`)**.
- Hairlines: 1 / `UIScreen.main.scale`pt sepia.

---

## Provenance Rules

The "FOR YOU BECAUSE / FROM YOUR INTRO" line is the user-authored signal made visible.

**Where it appears:**
- Hero story on Feed: **only when confidence is high**.
- Long-press "Why this story?" sheet on any row: paraphrased reason.

**Where it never appears:**
- Earlier-today rows on Feed.
- Article reader (the article speaks for itself).
- Notifications.

**State machine:**

| State | Day | Pattern |
|---|---|---|
| Cold | 0–2 | `FROM YOUR INTRO: [paraphrased topic]` |
| Warming | 3–14 | Mix: half intro, half "BECAUSE YOU READ X" |
| Earned | 14+ | `BECAUSE YOU TUNED FOR [topic] [recency-bucket]` |

**Sanitization rules (non-negotiable):**
- Never quote raw user input verbatim.
- Always map to canonical topic via taste-model.
- Truncate at 64 chars with ellipsis.
- Profanity, names, freeform text never appear in provenance strings.
- Recency labels are buckets only (`recently / this month / earlier`), never clock time.

---

## Voice & Microcopy

- Editorial, never marketing. "Three signals worth your attention today" not "Top 3 stories curated for you."
- Direct, never apologetic. "Couldn't load article. Tap to retry." not "Oops! Something went wrong."
- Plain English. "Tune your feed" not "Optimize your personalization."
- Sentence case for body. SMALL-CAPS for section anchors. Title Case for buttons.

---

## Animation & Motion

Motion is purposeful. Never decorative.

- **Diff toast** (Tune): slide in 200ms, hold 2000ms, fade out 300ms.
- **Feed mutation** (Tune): rows slide out 250ms, new rows slide in 350ms, ease-out.
- **Briefing card** expand: snappy spring (existing `.snappy(duration: 0.38, extraBounce: 0.08)`).
- **Pull-to-refresh:** system standard.
- **Pressable buttons:** scale 0.98, opacity 0.92 on press (existing `PressableButtonStyle`).

No infinite pulses, no shimmer, no neon glows, no parallax.

---

## Accessibility

- Dynamic Type on all editorial type tokens.
- Touch targets minimum 44×44pt (audit profile button on Feed header — currently 34, must grow).
- VoiceOver: every story row combines into one swipe ("Bloomberg, 2 hours ago, 7 minute read. Erlang creators...").
- Keyboard nav: `.searchable` and standard SwiftUI focus management.
- Contrast (WCAG AA minimum): ink on paper 14.4:1 ✅. Ochre on paper 3.4:1 — passes for bold ≥14pt only; never used on body.

---

## What's Forbidden

The AI Slop Blacklist applied:

1. Purple/violet/indigo gradients
2. 3-column feature grids
3. Icons in colored circles
4. Centered hero copy
5. Bubbly large border-radius (>16pt) on cards
6. Decorative blobs, floating shapes, wavy dividers
7. Emoji as design elements (sparkles, rockets)
8. Colored left-border on cards
9. Generic hero copy ("Welcome to Daily", "Unlock the power of...")
10. Cookie-cutter section rhythm (hero → 3 features → testimonials)

---

## Source

This file is the output of `/plan-design-review` (2026-05-06), incorporating Codex hard-rules review + Claude subagent completeness review + product owner direction. Full rationale in `tasks/design-redesign-plan.md`.
