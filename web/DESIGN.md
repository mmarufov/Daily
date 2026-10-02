# Daily Lab: design

The product is the instrument. The news pipeline is what it measures.

## The rule

An instrument is grey; only its readings have colour. Every surface, rule, control and piece of
navigation is exactly neutral (R = G = B). Red marks a measured failure or loss, slate marks a
measurement that could not be made, and nothing that worked is coloured. `tests/unit/palette.test.ts`
parses `app/globals.css` and enforces both halves, plus every contrast pair text sits on.

Light by default, dark by `prefers-color-scheme`, never forced.

## Type

- Geist: interface, headings, prose. Headlines 600 with tight tracking.
- Geist Mono: data a reader might copy (ids, hashes, code, timestamps, small tabular figures).
- Fraunces: article text from the frozen corpus, and nothing else.

Labels are sentence case at reading size. No tracked capitals, no section numbers on content that is
not a sequence, no badge above a headline.

## One unit

The cell. An article in the sieve, a case in the Lab, a miss in the attribution, a verdict in the
defect batch are all the same rounded square, so the figures read as one instrument at four scales.
Ink is survived or correct, red is lost or wrong, ghost grey is removed earlier, an open outline is
not run yet, hatched slate is unknown.

## Pages

- `/`: the console on a recorded production run, then one idea per screen: the sieve, the ranking
  ceiling with its switch, the 40-to-254 batch with its guard toggle, and the method.
- `/lab`: the same console with an editor, the hashed question and criteria, and every run.
- `/evidence`, `/engineering`, `/reader`, `/lab/[run]`: the same tokens and type, denser by design.

## Honesty in the interface

- A recorded run is labelled recorded. Pressing Run starts a real one, and nothing animates to look
  like progress: the timeline is the run's own events, the stopwatch is the browser's clock, and the
  64 cells change only when a graded result exists.
- Every homepage figure is read from a committed file by `lib/home.ts` and pinned by
  `tests/unit/home-evidence.test.ts`. A missing source removes its section; nothing is filled in.
- Text that is evidence (corpus headlines, case descriptions, hashed spec text) is marked
  `data-verbatim` and is exempt from house style.

## Motion

Strong ease-out, 150 to 300 ms for anything the pointer touches. Data reveals sweep in under half a
second. The sieve plays once when it enters view and any interaction takes over. Disclosures animate
their height through `AnimatedDetails` and stay native without JavaScript. Reduced motion gets the end
state immediately.
