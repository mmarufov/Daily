# Web companion redesign — plan

**Goal.** Someone opens the site and asks "how did you build that." Today they don't,
because the most interesting thing Daily owns — a ten-stage pipeline with a recorded
trace for every article — is rendered as `<td>`s.

**Diagnosis of the previous attempt (`mmarufov/web-craft`).** It was a typography and
grid audit: four self-hosted fonts, an asymmetric rail, a contrast-corrected palette.
Same four routes, same components, same sections in the same order, and — on a site whose
pitch is literally "a ruler that says whether it worked" — *zero* data visualisation. The
most graphical element on the branch is a 1.5px bar hidden below `md`. It then added an
e2e test forbidding layout animation, which converted "feels flat" into a contract.

## The one idea

**Color means loss.** Everything that survived the pipeline is ink. Everything the
pipeline threw away is signal red. Everything unverifiable is slate. That rule holds on
every surface, so a glance at any chart tells you where the system failed before you read
a single label.

The corollary: the site's spine is the funnel. 1,362 candidates become 50 delivered. Every
page is a different cut of that same journey — the reader sees the output, the evidence
explorer sees the measurement, the engineering notes see the failure.

## Build list

### Design system (`app/globals.css`, `app/fonts.ts`)
- [x] Vendored variable fonts (`next/font/local`, no build-time network): Fraunces for
      editorial, Geist Mono for every number, label and identifier. Two faces, no sans —
      mono chrome against serif prose is the instrument/newspaper juxtaposition.
- [x] Palette: cool paper, true ink, vermilion signal, slate unknown. Dark mode inverts
      to a photographic plate.
- [x] A measured hairline grid instead of a centred 672px column in a 1024px frame.

### Showpieces
- [x] **The Sieve** (`/`) — all 1,362 candidates as individual marks, stepping stage by
      stage. Survivors stay ink, losses settle to ghost, and the ones lost *at the current
      stage* flash signal. Real counts from the committed artifact. Auto-plays once, then
      you drive it. Static and complete with JS off.
- [x] **Ten fixtures, no averaging** (`/evidence`) — a small-multiple per reader fixture
      showing its outcome mix. `dilshod` is almost solid red; `wei` is mostly loss. The
      average hides both.
- [x] **Slope chart** (`/evidence`) — run-vs-run metric deltas as movement, not digits.
- [x] **Trace ribbon** (`/evidence`) — one story's ten-stage track with its death point.
- [x] **The offset** (`/engineering`) — the positional-misalignment bug drawn: 40 article
      slots, 27 returned verdicts, connectors that shift. Labelled a schematic, with the
      three verified real misattributions underneath.
- [x] **Ten front pages** (`/reader`) — the same frozen corpus as nine other readers got
      it. Personalisation demonstrated without ever showing a score.

### Honesty blocks — kept, reworded, never weakened
Treated as part of the instrument rather than as a footer disclaimer, at the same visual
weight as the data:
- [x] Replay notice on `/reader` (dated, content-hashed corpus, not today's news)
- [x] Ten reader profiles are adversarial evaluation fixtures, not users
- [x] Labels are model-written with an agent editorial pass; human review outstanding;
      absolute values provisional
- [x] Live sign-in is not implemented, with all three blockers stated
- [x] Never shipped, no readers
- [x] `unknown` is written as `unknown`; three revisions kept apart; materiality is a
      fixed cutoff, not a significance test

### Gates that must stay green
`tsc --noEmit` · `npm run test` · `npm run build` · `npm run export:artifacts -- --check`
· `public/artifacts` and `public/demo` untouched · `tests/e2e/journey.spec.ts`

## Ship
Commit → rebase onto `origin/main` (PR #58 was squash-merged; branching off the old
feature branch shows 50k insertions) → push → deploy to production → URL + screenshots.
