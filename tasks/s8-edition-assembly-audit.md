# S8 Edition assembly: analyse and challenge

2026-09-09. Read-only runtime audit of `mmarufov/sydney-v7`, HEAD `b667985`, including the
existing uncommitted S1–S7 implementation. HEAD alone does not contain this implementation.
No product code, provider, hosted database or activation was changed in this audit.

## Outcome

S8 needs an explicit selection contract, not another relevance scorer. S7 decides which
ordinary articles deserve consideration; S8 chooses a useful, non-repetitive ordered edition.
The new S7 publication machinery is reusable, but its current composition hook is deliberately
minimal. The old system-map description incorrectly suggests a working category cap and a
single assembly path. Neither is true in the current checkout.

```text
default legacy: shortlist -> score -> save rows -> dedupe -> diversity(no-op) -> role reorder -> limit
S7 enabled:    full S6 -> RankBatch -> accepted[:limit] -> optional S4 composition -> atomic edition
                                          ^ too early for general S8 selection/refill
```

S4 remains independently authorized significance, not proof of personal relevance. S8 must
not admit an ordinary rejected/unknown article because its publisher, image or topic quota
looks attractive. It also cannot guarantee all important world news when S1/S6 missed it.

## Findings, with current-code evidence

### P0: the mobile handoff has prerequisites, even before diversification

`ranking_service._public` (286) stamps each article with a feed request ID but not its reader
generation/revision. `_ordinary` (264) puts those only on the envelope. The Swift FeedResponse
does not decode those envelope fields (`BackendService.swift:538`), while NewsArticle decodes
per-article readerGeneration (`NewsArticle+EventDelivery.swift:127`). ReaderFeedbackStore submits
the article value (`ReaderFeedbackStore.swift:38`); `reader_feedback.py:126` rejects a missing
generation. Synthetic serialization confirms envelope generation=1 and no article generation.
Thus default-off S7 feedback integration needs an actual wire-contract test, not only mocked
Python receipt tests. This is not a claim that activated production was observed failing.

`BackendService.swift:531` recognizes ready/needs_build/needs_discovery/needs_reader_review.
S7 additionally returns building/unavailable (`ranking_service.py:451,471`). Raw-value enum
decoding has no handling for these responses. Plan a compatible response contract and explicit
UI states before enabling the path. Do not convert failure into an authoritative empty ready feed.

### P1: early slicing loses the very alternatives S8 needs

`ranking_service.py:269` serializes `ranked.ordered_ids[:limit]` before `_compose` (292).
No ordinary clustering, diversity or novelty selection happens first. Four accepted fixture
articles produce a three-card prefix containing only one distinct URL. Adding dedupe later
without moving the slice merely creates a short edition even when safe alternatives exist.

The existing S4 selector already exposes the problem: with two ordinary copies belonging to
the selected critical development and a third distinct candidate, pre-slicing to two returns
one item; passing the whole pool returns two. S8 must receive the whole accepted pool and
apply the requested limit after constraints and representative selection.

### P1: legacy diversity is a no-op, while roles override relevance

`feed_service._enforce_diversity` (1264) partitions overflow, then appends ALL overflow and
resorts by the original score. Probe: 14 in, 14 out, technology occupies all first five cards.
The claimed 40% cap does not hold at the displayed prefix or full-list level.

`_balance_feed_roles` (1423) concatenates fixed role blocks for its first 20 positions.
Probe: a 0.40 life-impact article lands at position 10, ahead of the eleventh 0.95 direct match
at position 11. These are legacy scores, not calibrated probabilities or current S7 grades.
Do not port the role-block algorithm into S8. Relevance cost must be declared and measured.

### P1: legacy duplicate representation can erase an accepted story

`_select_best_duplicate_representative` (691) prioritizes image and text lengths before score.
`get_personalized_feed` (236) collapses before filtering relevant results. Probe: an accepted
0.95 copy loses to a rejected 0.10 copy with an image; the subsequent relevance filter removes
the entire story. Ordinary representatives must have their own S7 acceptance. Never transfer
another article's verdict, intent IDs or explanation through a cluster.

### P1: title similarity and a headline hash are not story identity

`_normalize_title_for_dedupe` (628) removes non-ASCII letters; `_articles_are_near_duplicates`
(650) uses SequenceMatcher/token overlap, and `_collapse_duplicate_coverage` (705) joins by
similarity to any prior member. This admits similarity bridges rather than an independently
verified partition. Probes: identical Chinese headlines at different URLs are not merged;
headlines changing a policy rate from 5.0 to 5.5 are merged. These are synthetic counterexamples,
not measured error rates. `_make_cluster_id` (1345) is a title hash, not S3 identity.

Reuse S3's conservative specific-development membership, with its limitations:
`story_clustering.py:19,61` requires supported actor/action/object/date/place agreement plus
a configured cosine threshold; unknowns remain singleton. Assignment checks all existing
members (not one similarity bridge). This is provisional semantic evidence, not perfect grouping.
Event identity, development identity, article identity and editorial angle are different.
An oil-market consequence should not be silently treated as the direct military-event report.

### P1: current S6/S7 freshness does not cover future assembly membership

`understanding_repository.load_current_batch` (402) defaults `include_membership=False`.
`reader_retrieval._s6_hydrate` (364) uses that default, and `_s6_evidence_stamp` (424) covers
facets/embeddings but not membership. S6 publication (670) locks articles/artifacts/results,
not an S8 story partition/history/configuration. That is correct for its current contract,
but simply reading `cluster_id` inside S8 would introduce an unfenced decision dependency.
An S3 split/reassignment can change which representative should survive without changing
the article's text. S8 needs its own bounded manifest, presence/absence fencing and tests.

### P1: ordinary novelty is missing; receipt is not “read”

S7's order uses relevance/priority/frozen age, not reading history. Current S4 seen queries
(`ranking_events.py:134`) join event receipts to tap/read/already_knew records and track
development versions; ordinary stories have no equivalent assembly input.

`reader_feedback.ingest_events` (191) verifies account/request/article receipts when supplied,
but accepts unreceipted legacy telemetry and does not advance an assembly history revision.
Impression, delivered receipt, tap, read and already-knew are not interchangeable. Only
receipt-attributed evidence should affect a new novelty policy; legacy unknown stays unknown.
The app's five-second read event is a proxy, not proof of comprehension.

`process_feedback` (173) currently turns already_knew into a durable article block. S8 must
respect existing blocks. Do not silently undo them or claim a new version can override them.
Also, `event_delta.py:47` returns material_candidate/correction_candidate requiring adjudication;
an S4 version bump or changed timestamp alone is not a proven meaningful update.

### P1: immutable order and fresh history need separate ownership

S7 already atomically caches final articles and writes final-only receipts. GET re-composes and
compares against the stored final list (`ranking_service.py:396`), returning needs_build on drift.
Adding current novelty to this recomposition would invalidate an edition after each read.
Today rebuilding calls ranking again. A history-only change must be able to rebuild the edition
from a still-valid RankBatch without paying to judge the same articles again. GET must not
silently issue a different order under the old feed request ID.

The client preserves backend order (`NewsViewModel.swift:367`, `NewsView.swift:194`) and uses
the first item as hero. It locally removes feedback items, then logs shifted array positions.
ReadingEventTracker uses a mutable global feed request ID (`ReadingEventTracker.swift:43`);
receipt validation rejects mismatched final positions (`reader_feedback.py:217`). New assembly
receipts need immutable per-card edition ID/original position, separate from current UI index,
including cached feeds, article detail and background refresh. No visual redesign is required.

### P2: S4 major handoff and editorial provenance remain incomplete

`event_feed.apply_event_feed` returns major_candidates and decisions; `ranking_events.py:153`
keeps only `.payload`. This does not prove every major event is absent from S6 (it may already
be retrieved), but no dedicated S4-major recall path is wired here. S8 must not bypass S7 by
injecting majors after ranking. Reuse only already-accepted candidates; a missing major leg
is a separate bounded S6/S7 integration dependency, not an assembly filler rule.

S4's independently gated maximum of two critical reservations remains the starting policy.
“Ranking cannot veto criticals” must never mean “critical ignores blocks, rights, expiry,
representative centrality, capability or output capacity.” Overflow is a documented selection
outcome, not failed detection. Same-event different developments are not automatically duplicates.

The old source-quality adjustment reads domain scores but derives a domain from source_name
(`feed_service.py:1126,1234`). Do not carry that mechanism or guessed publisher nationality into
S8. The canonical reader model has no authoritative home-press preference. Image availability
must remain presentation, not semantic authority.

## Product promises to challenge

1. **“Never two copies.”** Guarantee unique article IDs and at most one item per *verified*
   equivalent coverage unit. Report identity-unknown coverage; do not merge unknown stories
   merely to make a duplicate metric look good.
2. **“Never one topic dominates.”** Impossible alongside “only relevant items” for a reader
   following one subject or a pool with only one eligible subject. Concentration targets are
   conditional on relevant alternatives. Report infeasible/relaxed constraints honestly.
3. **“Old follow-ups never displace new.”** A new development/correction can matter more than
   a fresh rewrite. Use acknowledged evidence and supported deltas, not publication age alone.
4. **“Home press chooses the copy.”** Only after eligibility, own relevance and centrality;
   without explicit publisher preferences, use a stable tie-break instead of inferring nationality.
5. **“Use MMR and it is solved.”** MMR trades relevance against similarity; S7's ordinal grades
   and retrieval scores are not an automatically compatible numeric scale. Default to a small,
   deterministic constrained selector; evaluate MMR as a challenger, not dedupe truth.

## Technology check

No new model, vector service, search engine or optimizer is needed for ≤300 ordinary candidates.
Reuse Python/Pydantic, existing PostgreSQL publication/claims and S3/S4 identity evidence.
The original [MMR paper](https://www.cs.cmu.edu/afs/cs/Web/People/jgc/publication/MMR_DiversityBased_Reranking_SIGIR_1998.pdf)
defines a tunable relevance/redundancy trade-off. This supports evaluating that approach, not
asserting a universal weight or semantic-equivalence threshold for Daily.

PostgreSQL's [isolation documentation](https://www.postgresql.org/docs/current/transaction-iso.html)
distinguishes coherent reads from serializable execution; application retries can be necessary.
Our design inference: extend the existing explicit writer/publication lock protocol and stamp
checks, rather than claiming a repeatable-read snapshot alone prevents stale publication.

Learned diversity is an alternative research direction, not an immediate dependency:
[LeaDivRec](https://arxiv.org/abs/2204.00539). Its reported experiments are not evidence for
Daily's model, corpus, reader distribution or cold-start behavior.

## Verification and limits

- `.context/s8-probes.py` / `.context/s8-probes.json`: seven read-only synthetic probes, all assertions pass.
- `.context/s8-baseline-tests.log`: **267 passed, 68 subtests passed**, covering current feed,
  S4 selection, S7 ranking/cache/evaluation/feedback and S3 clustering.
- No real PostgreSQL race tests, iOS build, live feed observation, paid ranking or new semantic
  benchmark was run. Existing tests passing does not refute the reproduced uncovered cases.
- The prior S7 full-suite report still has three legacy S0 quality failures; no gate was changed.

Next: [bounded implementation plan](s8-implementation-plan.md). Implementation requires approval.
