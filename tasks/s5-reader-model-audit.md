# S5 Reader model — analyse and challenge

Reviewed 2026-09-07 against the current `mmarufov/sydney-v7` checkout, including existing
uncommitted S1–S4/backend/iOS work. Scope: analysis and implementation plan only.
No runtime fix, live database inspection, paid provider call, deployment or publication.

## Conclusion

“Partial — no interest vectors” understates the problem. Daily has useful preference
capture, scoring and feedback pieces, but not one authoritative, versioned reader model.
Adding embeddings to the current state would make conflicting or stale preferences easier
to retrieve against; it would not make those preferences correct.

Recommended order: canonical explicit state → safe mutation and consistent consumers →
trustworthy feedback → compatible per-interest vectors with a measured retrieval consumer.
For a portfolio, this is stronger engineering than imitating a large company's user tower
without the data, evaluation or operational need behind it.

The companion [implementation plan](s5-implementation-plan.md) defines concrete contracts,
file-scoped batches, acceptance tests and separate quality/production approval gates.

## What exists and should be reused

| Existing piece | Useful foundation | Current limitation |
|---|---|---|
| `profile_model.py` | v2 fields and source-selection projections | Permissive normalization, no canonical authority/revision |
| Onboarding and Settings | Explicit focus, locations, exclusions, priorities and depth | Replacement/LLM save semantics can change untouched fields |
| `evals/pipeline.py` | Typed intents and multi-leg retrieval experiment | Eval-only, compiler/label coupling, exclusion/token/cap defects |
| `feedback_signals.py` | Bounded positive/negative weights with half-life | Replay, attribution and decay-update defects |
| Pins / suggestions | Authenticated backend APIs and client data types | Separate writes; no iOS callers found |
| S3 understanding | Versioned article artifacts and embedding recipe contract | Current status document says default-off/unpromoted; not a live verification |
| S4 event delivery | Policy/provenance/versioned consumption patterns | Reader-policy adapter must adopt the same canonical authority |
| PostgreSQL / workers | Existing transactional jobs, leases and schema patterns | Reuse patterns; no need for another database or queue product |
| Auth and injected Swift tests | Generation fencing and test seams | Reader/tuning/event async work does not consistently use them |

## Current flow and loss points

```text
onboarding / Settings ── AI extraction + full replacement ──┐
suggestion acceptance ── legacy interests only ─────────────┤
entity follow ────────── separate pins ─────────────────────┤
Tune ─────────────────── general chat (no profile mutation) │
                                                         v
       ai_profile / interests / v2 / two source briefs / learned weights
          │ different consumers read different subsets; no shared revision
          ├── source discovery (profile edit deletes old associations)
          ├── candidate matching → LLM score → feed cache
          ├── S4 event inclusion / briefing / chat
          └── feed feedback → current cache attribution → additive weights

Separate eval path: fixture profile → compiler → retrieval AND labeler prompt
                                   ↑ not an independent correctness oracle
```

This is a source-confirmed architecture map, not a trace of a particular production account.

## Confirmed defects and capability gaps

Confidence is confidence in the code diagnosis, not a measured incident probability.
P0 below denotes a release gate for the proposed S5 capability; P1 denotes necessary
correctness work before claiming S5 completion, not an asserted production outage.

### 1. Competing authorities and destructive edits — P0, confidence 0.99

`backend/app/main.py:1751-1756` can replace submitted interests with an AI extraction;
`:1764-1774` independently accepts nonempty v2. Suggestion acceptance writes only
`UPDATE public.user_preferences SET interests = %s, updated_at = now()` (`:2743`).
Ranking, discovery and UI can therefore consume different meanings after the same edit.

`Daily/Features/News/ViewModels/PersonalizationSettingsViewModel.swift:90-117` constructs
a partial replacement v2 document, omitting people/industries; the normalizer fills omissions
with empty arrays and the endpoint replaces the whole document. Clearing current focus
becomes `Array(topics.prefix(4))` at `:110`, so empty does not stay empty.

**Required boundary:** one writer, explicit patch semantics and deterministic projections;
direct structured changes must not be reinterpreted by a provider.

### 2. Lost updates and stale publication — P0, confidence 0.99

The database pool uses `autocommit=True` (`backend/app/main.py:363`). Preference upsert,
feed deletion and source deletion are separate statements (`:1797-1823`). No reader revision
or mutation idempotency precondition exists. Suggestion accept is a read-modify-write race.

Feed loads preferences at `feed_service.py:150`, awaits scoring at `:218`, then publishes at
`:227`. Cache rows use `created_at=now()` (`:1624`); freshness compares preferences to that
publication time (`:1554-1557`). An old build published after an edit can appear fresh.
Source discovery has the same read/await/write shape; briefings have no reader version.

**Required boundary:** atomic state transitions, operation receipts and input-revision-fenced
publication. Deleting a cache does not cancel an older writer.

### 3. Hiding a source is not durable — P0, confidence 0.99

`hide_source` only sets `user_sources.active=false` (`main.py:2436-2450`). Profile saves
delete those rows (`:1365-1367` and callers); discovery can recreate them active
(`source_discovery.py:776,793`). This also couples every edit to source availability:
feed can return empty without active sources (`feed_service.py:164-165`).

**Required boundary:** durable canonical publisher blocks, independent of discovery membership;
incremental or atomic desired-set reconciliation that preserves usable sources during failure.

### 4. AI failure can be saved as successful onboarding — P0, confidence 0.99

`openai_service.py:384-391` builds a transcript from user and assistant turns. Failure uses
`fallback_ai_profile = transcript[:800]` (`:464`) and returns a derived profile; the endpoint
marks it complete (`main.py:1917-1926`). This can omit late corrections and include assistant
suggestions. The branch exists; specific model-generated mistakes were not tested live.

The client also returns normally on missing token (`OnboardingChatViewModel.swift:87-91`),
while its caller posts completion and dismisses (`OnboardingChatView.swift:330-337`).

**Required boundary:** evidence-backed proposals, explicit confirmation/typed saves and a
truthful failure state. Schema-valid output is not proof of faithfully captured preferences.

### 5. Tune does not currently tune — P0 for enabling Tune, confidence 0.99

`TuneViewModel.swift:263-310` sends a general chat turn and refreshes the feed. Backend
`chat_service.py:462-498,593-640` generates/persists an answer, not a reader mutation;
no backend `weight_diff` emission was found. `ChatV2Models.swift:293-294` acknowledges the
missing event. The current Tune view does not render the generated answer.

Undo at `TuneViewModel.swift:230-235` says “just clear the pill so the user feels the action”
and makes no backend change. It is presently latent because the backend emits no diff;
this is not evidence users currently encounter that pill in production.

**Required boundary:** proposal/review/apply through the canonical writer, then a real revised
feed. Implement a safe inverse or omit Undo; do not simulate mutation with a refresh/toast.

### 6. Event loss and cross-account misattribution — P0, confidence 0.99

`ReadingEventTracker.swift:62-74` drains the whole queue. Backend rejects batches over 100
(`main.py:2383-2385`), but `BackendService.swift:886-889` returns normally on non-2xx.
Thus a 101-event batch, or 429/500 response, is treated as success and lost.

If A's suspended request fails after logout/B login, its catch prepends A's events to the
shared queue. The next flush uses B's token. `discardPending()` does not fence in-flight
failure handlers. This is a code-supported schedule, not a reproduced production incident
or a demonstrated server authorization bypass.

**Required boundary:** stable IDs, bounded acknowledged batches, account+generation fencing,
classified retries and truthful durability guarantees before using telemetry for learning.

### 7. Feedback is neither replay-safe nor consistently decayed — P1, confidence 0.99

`main.py:2452-2473` inserts an event with `ON CONFLICT DO NOTHING`, then calls additive
`apply_feedback` even for duplicates. Attribution comes from current article fields and
mutable `user_feed_cache` (`feedback_signals.py:60-104`), which the first feedback may clear.
A retry can therefore change weights again with different reasons.

The update adds delta to stored weight and resets time (`feedback_signals.py:133-140`);
decay happens only on reads (`:55-63,173`). Example: weight −1 after two half-lives means
−0.25 now; adding +0.2 should yield −0.05, not revive the stored −1 into −0.8.

**Required boundary:** immutable receipt attribution; apply an event once in a transaction;
decay before addition and at read time; stale events cannot resurrect deleted/reset interests.

### 8. Learned-data lifecycle is incomplete — P1, confidence 0.98

`user_feedback_signals.user_id TEXT NOT NULL` lacks a user FK (`main.py:918-925`), unlike
other reader-owned tables. No account-delete/reader-reset endpoint was found in `main.py`.
Deleting a user is not guaranteed to remove learned rows. Separately, behavior recomputation
returns when it finds no recent events and can leave old `behavior_cache` influence
(`:2482-2536`). This is a retention/expiry gap, not evidence of an actual deletion request.

**Required boundary:** explicit reset/delete ownership, retention, expiring learned state,
generation fencing and tests that late jobs cannot repopulate removed data.

### 9. Pins and briefings are disconnected from fresh reader state — P1, confidence 0.99

Pin creation/deletion does not invalidate feeds (`main.py:2597-2618`); feed cache returns
before pins load (`feed_service.py:174-204`). Pins only boost already retrieved candidates
(`:1211-1221`), so they do not reliably follow a newly requested entity. Client API declarations
exist, but no iOS callers were found. Briefings use a four-hour age-only cache
(`main.py:2634-2665`), unaffected by reader corrections.

**Required boundary:** define follows as explicit intents; all consumers bind to a reader
snapshot; “follow” must affect acquisition as well as scoring.

### 10. The prototype compiler cannot simply move into production — P1, confidence 1.00

Offline reproductions in `.context/s5-diagnostics.py` confirmed:

- The normalizer accepts `[None, False, {"topic": "AI"}]` as string interests
  (`profile_model.py:43-59`), and drops unknown canonical-policy fields.
- `compile_rubric` uses `x in low` (`evals/pipeline.py:123`): excluding “ai” removes “retail”.
- The ASCII tokenizer (`:55`) returns no tokens for `Новости Таджикистана`.
- Legacy-only `interests.topics` produces no intents when v2 is empty.

It also deduplicates by label across kinds, uses fixed priority assumptions, and globally
sorts/truncates after per-leg retrieval (`:295-335`), so quotas do not guarantee surviving
minority-interest coverage. Production matching itself ignores v2 positive intents except
through legacy inputs (`feed_service.py:903-935`).

**Required boundary:** strict production compiler with independent expectations, Unicode-aware
matching, typed scopes and cap-aware retrieval. Preserve the old prototype as a frozen baseline.

### 11. Exclusion semantics and evaluation need independent proof — P1, confidence 0.99

Production exclusions search body/source/category strings and can reject after two generated
expansion matches (`feed_service.py:951` onward). That is not equivalent to “this article is
about the topic the reader excluded”; incidental mention, ambiguity and exceptions matter.
S4 canonical policy fields cannot be trusted to survive a v2 normalizer that drops them.

The labeler imports `compile_rubric` and gives its output to the relevance judge
(`backend/evals/label.py:231-237`). Evaluating a new compiler against labels derived from that
same compiler can hide information loss. Existing labels remain regression assets, not an
independent oracle for original reader intent.

**Required boundary:** separate exact policy rules from uncertain semantic predicates; define
unknown handling and measure false blocks as well as misses. Label from original user intent
blind to system output. Never claim perfect semantic bans from similarity thresholds.

## Architectural challenge: choices worth rejecting or qualifying

| Proposal | Challenge | Recommendation |
|---|---|---|
| Add embeddings first | Retrieves against unstable meaning and stale publication | Fix state authority first; vectors are derived artifacts |
| One averaged user vector can never work | Too absolute; centroid usefulness depends on corpus/query | Keep it as an equal-budget baseline, not the only multi-interest path |
| A trained multi-interest/user tower | Requires suitable behavioral data and independent evaluation | Explicit multi-intent retrieval now; defer learned towers |
| Assign a nearest persona for cold start | Fixture identities are not validated user segments | Ask specific interests; label generic fallback honestly |
| Copy the eval compiler | Known semantic/token defects and coupled labels | Extract a tested production contract, preserve independent oracle |
| Similarity determines hard exclusions | Semantic closeness cannot prove policy compliance | Explicit scoped rules and evidenced predicates with unknown handling |
| Add a vector database/feature store/queue | Existing PostgreSQL and workers cover the current needs | Reuse current stack; optimize from measurements |
| Done when vectors are stored | No effect on the user's actual feed | Include a narrow disabled S6 consumer and end-to-end evidence |
| Hardening S5 is independent of S3 | Query/article space, facets and provenance are dependencies | Compile state independently; gate semantic serving on compatible S3 artifacts |

These are design recommendations, not evidence that any technology universally wins.
Official API/database sources and specific deployment/evaluation gates are in the plan.

## Verification and remaining unknowns

Executed offline against the current checkout:

```sh
EVAL_OFFLINE=1 backend/venv/bin/python -m pytest \
  backend/tests/test_preferences.py backend/tests/test_feedback_signals.py \
  backend/tests/test_chat_service.py backend/tests/test_feed_service.py \
  backend/tests/test_user_source_pipeline.py backend/tests/test_eval_runners.py -q
PYTHONPATH=backend EVAL_OFFLINE=1 backend/venv/bin/python .context/s5-diagnostics.py
```

Result: **94 passed** in the selected baseline suites; diagnostic assertions reproduced the
five normalization/compiler behaviors above. The decay example is arithmetic illustrating
the inspected SQL, not a real-Postgres update test. These checks make no network/provider calls.

Passing tests do not contradict this audit: `test_preferences.py:80-109` only searches source
text for timeout handling; the selected tests do not prove concurrent updates, HTTP delivery,
account schedules or semantic quality. No hosted PostgreSQL race test, device run, production
comparison or paid embedding benchmark was performed in this planning phase.

Unknowns to resolve before relevant implementation/activation gates: real legacy conflict
frequency, active client versions, supported languages, production S3 cohort status, realistic
eligible corpus scale, acceptable inference budget, retention periods and independent relevance
labels. The plan provides engineering defaults where safe, not invented production measurements.

## Review provenance and disposition

Three independent read-only agents inspected backend writers/consumers, iOS lifecycle, and
architecture/evaluation respectively. They then challenged the draft implementation plan.
This is independent in-host review, not a claim of cross-model validation. Their notes are
in `.context/s5-backend-audit.md`, `.context/s5-client-audit.md` and
`.context/s5-architecture-challenge.md`; durable conclusions are captured here and in the plan.

The architecture reviewer rechecked the revised plan and confirmed all five of its targeted
gaps were addressed, with no remaining blocking contradictions within that rereview scope.

No runtime bug was fixed during this analysis. Existing S1–S4 changes remain untouched.
Implementation approval, semantic-quality approval and production activation are separate.

## GSTACK REVIEW REPORT

| Review | Runs | Status | Findings |
|---|---:|---|---|
| Architecture / alternatives | 1 + draft challenge | Complete with proposed decisions | Canonical authority, minimal derived vectors, no persona/tower requirement |
| Code / lifecycle | Backend + client passes | Complete | Mutation/cache races, hidden Tune gap, feedback ownership and replay defects |
| Tests / evaluation | Baseline + pure reproductions + review | Complete for planning | 94 baseline passes are not S5 proof; independent semantic oracle required |
| Performance / operations | Design review | Measurements pending | Bounded work, no per-feed embeddings, hosted benchmark/activation gates |

VERDICT: **DONE_WITH_CONCERNS** — analysis and proposed plan complete; implementation not
approved or performed, and quality/live claims remain unverified. Unresolved decisions are
listed in the implementation plan's approval-gates section, not silently treated as accepted.
