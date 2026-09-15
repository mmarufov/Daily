"""Retention windows, and the decision record for why they are what they are.

## The question (Phase 7.5)

`reading_events` has no retention policy of its own. It has
`article_id uuid NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE`
(`main.py`'s `_ensure_tables`), and the 3-minute ingestion loop deletes
articles older than 14 days. So the *effective* retention of a behavioural
event is `article.ingested_at + 14 days` -- not `reading_events.created_at +
14 days`. A tap logged five minutes ago on an article ingested fourteen days
and one minute ago is deleted with it. Nothing in the code said so.

## The decision: intentional, and now stated

Keep the coupling. Three reasons, in order of weight:

1. **Every aggregate consumer joins `articles` anyway.** `source_quality`
   (per-domain tap/read rates), `interest_evolution` (per-category engagement)
   and `_recompute_behavior_signals` (category/source affinity) all need the
   article's category or source to interpret the event at all. An event whose
   article is gone carries no usable signal for any of them; orphaning it
   would grow the table without making any consumer smarter.
2. **The 14 days was already a deliberate choice made for this reason.** The
   GC's own comment reads "Clean up articles older than 14 days (extended for
   behavioral learning)" -- article retention is longer than the feed needs
   *because* of the events hanging off it.
3. **The suppression consumers can't be rescued by orphaning either.**
   `load_suppressed_article_ids` and the S4/S7 seen-joins key on article id.
   A GC'd article that reappears is re-ingested under a *new* id, so a
   surviving event row would not match it regardless.

**If longer-horizon behavioural learning is ever wanted, the answer is to
denormalise what the consumers actually read -- category and source domain --
onto `reading_events` at write time, not to drop the foreign key.** That is a
schema change with a real migration, not a retention tweak, and it should be
driven by a learning tier that needs it (S10 Tier 1+, gated on ~20 informative
events per reader per intent) rather than done speculatively.

## Known inconsistency, deliberately not "fixed" here

`reader_delivery_receipts` declares a 30-day window in two places
(`reader_feedback.record_delivery`'s cleanup and `ingest_events`' validation)
but also cascades from `articles`, so its rows really live 14 days. The last
16 days of that window are unreachable. This is a declared-vs-enforced
mismatch rather than a live defect -- a client cannot echo a receipt for a
card it stopped holding two weeks ago -- so the honest fix is to say so
(`RECEIPT_VALIDATION_DAYS` below) rather than to restructure an append-only
receipt table that S8's `reader_edition_reads` composite-FKs onto. Flagged in
docs/architecture/bulletproof-architecture-plan.md rather than silently changed.
"""
from __future__ import annotations

#: How long an article stays in the pool. Load-bearing beyond the feed: every
#: user-signal table that references `articles` inherits this as its ceiling.
ARTICLE_RETENTION_DAYS = 14

#: The lookback the behaviour-signal consumers use. Equal to
#: ARTICLE_RETENTION_DAYS on purpose -- a longer window would silently return
#: fewer rows than it asks for, and reading a shorter one out of a longer store
#: would be the only reason to differ.
BEHAVIOR_SIGNAL_WINDOW_DAYS = 14

#: How far back `ingest_events` will honour a delivery receipt. Longer than
#: ARTICLE_RETENTION_DAYS, and therefore truncated by it in practice; see the
#: module docstring.
RECEIPT_VALIDATION_DAYS = 30

#: Diagnostics-only tables with their own independent sweep.
EXTRACTION_ATTEMPT_RETENTION_DAYS = 30
