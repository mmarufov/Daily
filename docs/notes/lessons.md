# Lessons — Daily Redesign

Self-corrections, scope notes, and pending follow-ups discovered mid-execution.
Append a line whenever the user pushes back or a phase surfaces something the next phase needs to remember.

## 2026-09-07 — S5 implementation budget

When the user approves implementation but explicitly defers further reviews and paid proof,
implement the agreed architecture without another review loop or paid evaluation. Keep cheap
targeted correctness tests, distinguish deferred quality/live evidence, and never turn
"bulletproof" into an unverified guarantee or a reason to spend unapproved API credits.

---

## 2026-05-07 — Phase 2

**ContextMenu actions dropped from the feed.** Phase 2 replaced `.contextMenu` (7 actions) on feed cards with `.onLongPressGesture` → `WhyThisStorySheet` (3 corrective actions: Less of this / Wrong reason / Hide this story).

Lost from the feed:
- **Bookmark** — still reachable from `ArticleDetailView` toolbar.
- **Share** — still reachable from `ArticleDetailView`.
- **Discuss with AI** — still reachable from `ArticleDetailView` Discuss button.
- **More Like This** — *not currently reachable from anywhere on the feed.*

**Action for Phase 4 (Tune):** re-introduce a "more like this" positive-feedback affordance, either in the Tune surface or as an additional row in `WhyThisStorySheet`. The backend action code already exists (`viewModel.submitFeedback(action: "more_like_this")`).

---

## 2026-05-07 — Phase 4 (backend follow-ups)

Phase 4 rebuilt the Chat surface as Tune (composer top, live feed below, ephemeral diff toast, 10-min Undo). Three pieces depend on backend work the iOS side scaffolded but cannot drive alone.

1. **`weight_diff` streaming events.** iOS now decodes `StreamingEvent.weightDiff(WeightDiffPayload)` and routes them to `TuneViewModel.pendingDiff` → `DiffToast`. **Backend must emit `weight_diff` events** in the streaming response for tuning turns that change taste signals. Until then, the toast never appears (which matches the "zero-diff turns produce no toast" spec, but means the magic moment is invisible). Payload shape (Swift mirror — backend can match):
   - `summary: String` — short two-line description, e.g. "National news ↓ · Startups ↑ · Erlang +"
   - `topic_deltas: [{topic: String, direction: "up"|"down"|"added"|"removed", magnitude: Double}]`
   - `timestamp: ISO 8601` — optional

2. **Undo endpoint.** `TuneViewModel.tapUndo()` is a no-op that just clears the pill. **Backend must expose an endpoint** that reverses the last weight-diff for a given user. Once it ships, replace the `TODO(backend)` block with a real call. The `PersistedUndo.diff` carries the full payload so the request can include the original delta.

3. **Status stage labels.** The streaming `.status(StatusPayload)` event currently sends arbitrary strings ("Scanning your feed"). DESIGN.md specifies three named stages: "Reading your feed…" → "Adjusting taste model…" → "Pulling new stories…". **Backend should emit these three stages** (in order) for tuning turns. iOS already falls back to "Reading your feed…" when no status has arrived, so the cold-start experience is correct without backend changes — but the mid-stream stages depend on backend cooperation.

**iOS-side TODOs left in code:** search `TODO(backend)` in `Daily/Features/Tune/Models/ChatV2Models.swift` and `Daily/Features/Tune/ViewModels/TuneViewModel.swift`.

---

## 2026-08-04 — Authenticated job-board research

**Do not infer that an internal job board is empty from its anonymous public view.** For USFWorks, the public-facing student board showed zero results while the authenticated student task contained 184 listings. When a user supplies a logged-in export or session, treat that as the authoritative inventory and clearly separate public-access limitations from actual job availability.

**Preserve explicit work-authorization facts instead of repeatedly reintroducing a visa assumption.** The user has a green card, is a domestic applicant, and has a Federal Work-Study award. For this income search, include FWS positions and do not apply F-1/CPT restrictions unless the user says their status changed.

## Personalization: substring matching is never right for interest terms (2026-08-31)

**What broke.** A user typing `AI` got Ukraine, Entertainment, Chairman, Maintaining
and Thailand — every string containing the letters `a-i`. Three separate sites did raw
`term in text`:
`feed_service._categories_for_terms`, `_score_candidate`'s phrase/keyword loops, and
`source_discovery._categories_for_terms`. The worst effect was silent: `"ai" in
"entertainment"` is `True`, so *entertainment* was classified as an AI interest.

**Rule.** Interest terms match on word boundaries, always — `_word_in()` in
`feed_service`. Never `in`. Boundaries are `[a-z0-9]` lookarounds, not `\b`, so terms
containing punctuation (`c++`, `.net`, `covid-19`) still anchor.

**Corollary.** Word-boundary matching then *under*-matches: `AI` no longer hits
`OpenAI`. That gap is not fixable lexically — it is what dense retrieval is for. Lexical
and semantic retrieval are complements, not alternatives.

## Exclusions must be subtracted before anything positive is built (2026-08-31)

A profile saying "not interested in entertainment or gaming" ended up with `gaming` in
the **positive** keyword set *and* `gaming` as an inferred **preferred category**, because
`_extract_prompt_terms` scrapes both polarities from the same free text and nothing
subtracts the negatives afterwards. Compile exclusions first, then filter every positive
structure through them.

## A quota is a ceiling, never an obligation (2026-08-31)

Per-interest quotas guarantee coverage, but filling an underfed intent's remaining slots
with whatever ranked next actively makes the feed worse. Measured on the eval corpus:
candidates ≥1.0 were almost all on target, under ~0.7 almost all noise. Quotas need a
score floor. A short honest feed beats a padded one.

## Verify the model tier, don't assume cheapest works (2026-08-31)

`gpt-4.1-nano` and `gpt-4o-mini` scored identically on a 6-case relevance probe, but nano
kept 8/65 candidates where mini kept 17/65 — nano over-rejects, collapsing feeds to 3
articles. Same accuracy, very different recall. Cost difference was $0.0017 vs $0.0028 per
persona, i.e. irrelevant. Measure recall, not just precision, before picking the cheaper model.

## Breadth is not gravity (2026-08-31)

An active US-Iran war sat in the eval corpus across 8 outlets and reached none of three
readers. Two independent causes, and fixing either alone would not have worked:

1. **Title-token clustering cannot group real coverage.** "US strikes Iranian launchers",
   "Battle for Hormuz" and "Iran war: Larak Island" share almost no tokens — 19 headlines
   became 17 clusters with max breadth 2. Semantic clustering groups them; lexical cannot.
2. **Counting outlets ranks a telescope launch above a war.** Breadth shortlists
   candidates; a model call decides gravity. One global call serves every user ($0.0007).

**Rule.** `world_critical` items are force-injected and the per-user judge gets no vote.
The judge rejecting a war as "not about New Jersey" is a *correct* judgement that produces
the *wrong* feed — relevance and importance are different questions.

## Home-press preference must be gated on centrality (2026-08-31)

Preferring a reader's own outlets for the same story is right, but naive "pick any home
copy" handed a US reader *"Oil rises 1% after US forces strike Iranian rockets"* instead of
*"US strikes Iranian launchers in the strait of Hormuz"*. Same cluster, wrong story.
Gate the swap on how close the home copy sits to the cluster centroid — strict for
world-critical (0.95, clarity wins), looser for regional (0.82, local framing is worth
something).

**Test trap:** a two-member cluster cannot express this. The centroid sits exactly between
the pair, so both score identically central. Fixtures need >=3 members.

## Feedback needs somewhere to go (2026-08-31)

`not_relevant` wrote a row to `reading_events` and every consumer of that table filtered it
out. The feed was rebuilt from the identical profile, so the article scored the same and
came back. The client removed it from the local array, which hid the failure until the next
refresh — the worst kind of bug, because it looks like it works.

The root cause was not a missing read. It was that a *profile* is what the reader said once
during onboarding, and it has no room for "yes, but not that one". Corrections need their
own durable store.

**Rules that fell out of building it:**

- **Attribute, don't generalise.** One tap does not mean "I hate hockey". Spread a small
  bounded penalty across the reasons the article was shown — the matched interest (recorded
  in `user_feed_cache.matched_profile_signals`), the publisher, the category — weighted so
  the matched interest counts most and the category least.
- **Asymmetric weights.** Rejecting something is a stronger signal than tapping a heart.
  `not_relevant` is -0.30, `more_like_this` is +0.20; the total adjustment floor (-0.50) is
  twice the ceiling (+0.25). Negative feedback may sink an article; positive may not force
  junk to the top.
- **Decay.** 30-day half-life. Someone who disliked crypto a year ago may have changed jobs.
- **Ranking weight is not enough.** The rejected article itself must be *absolutely*
  suppressed. A reader who taps "not relevant" and sees the same headline tomorrow correctly
  concludes the button does nothing.

## S0 evaluation build (2026-09-01)

**An eval that does not run the production code path measures a different product.** The
old `baseline_today.py` called only the keyword fallback over the whole corpus, never the real
batch scorer, never production's 300-row recency window. `evals/runners.ProductionRunner`
now drives `get_personalized_feed` itself with an in-memory connection. Rule: the system under
test is the function the API calls, not a re-implementation of it.

**Cache every model call by request hash, and commit the cache.** Reproducibility and a free
CI gate both fall out of it. Corollary: a retry of an identical request returns the identical
cached failure. That is the right behaviour for a regression gate — but it means the eval
slightly over-penalises production, where a retry might succeed. Say so in the README.

**gpt-4o-mini runs away on positional 40-article batches.** With no `max_tokens` and no id
echo, two of three production scoring batches for Ray looped ("The article discusses a music
festival…" repeated) until the 16k output-token limit, came back as invalid JSON, timed out
the 45 s guard, and silently fell back to keyword scoring. Every retry can repeat it. This is
the S7 "id-echoed small batches, drop unmatched verdicts" item, now measured: fix there, not
in the eval.

**Unhandled SQL in a fake connection must raise, not return empty.** Five production loaders
swallow exceptions and degrade to "no signals"; a fake that silently returns `[]` would make
the eval quietly measure a feed with no behaviour signals. `SnapshotConn` records and raises.

**Keep must-see tight and define need-to-know narrowly.** The first labelling pass tagged
Giants roster news `need_to_know`. A tag that means "affects your life, money, safety or
work" cannot also mean "you like this team", or the headline metric is meaningless.

**Anything that becomes part of a cache key is pinned in code, never read from `.env`.** The
judge model came from `EVAL_JUDGE_MODEL` in `.env`; the test suite stubs `dotenv`, CI has no
`.env`, so the same code resolved a different model, produced different keys, and the gate
failed with `CacheMiss` only when run inside the full suite. Defaults live in the module.

**Return what you stored.** Embeddings were cached at float16 but the warming run kept its
float32 copy, so the first run and every later run clustered slightly differently. The miss
path now hands back the rounded vectors.

## S1 Phase 0 (2026-09-02)

**A column that is queried but never created fails silently inside a bare `except`.**
`_per_user_refresh_loop` filtered on `users.last_active_at`, which no `CREATE` or `ALTER`
ever added. Every tick raised `UndefinedColumn`, the blanket `except Exception` swallowed it,
and the loop had never run once — which is why `user_sources.last_fetched_at` was frozen at
2026-04-13 and `user_feed_cache` was empty. Rule: background loops log with
`logger.exception`, never `pass`; and a query against a column is not proof the column exists.

**Every background loop in a multi-worker server needs leader election.** The container runs
`uvicorn --workers 2` and Fly can run several machines, so all four loops ran two or more
times over. A session-level `pg_try_advisory_lock` is enough: exactly one holder cluster-wide,
released automatically when the connection dies. The whole tick must happen inside the lock,
not just the query that decides what to do.

**A test suite with no `conftest.py` has order-dependent behaviour.** Eight test modules each
opened with their own `if "openai" not in sys.modules:` stub block. Whichever pytest imported
first won, so adding a test file broke an unrelated import. The same file can also end up
loaded under two module names, so patching one instance is not enough. Fix: install the stubs
once in `tests/conftest.py`, before any test module is imported.

## S2 completion follow-through (2026-09-03)

**When the user asks to continue an audited system through completion, the audit is the input,
not the deliverable.** Turn every confirmed finding into an executable checklist, implement the
shared backend/client contract, and keep working through negative-path and full-suite verification.
Do not repeatedly hand back the same analysis while fixable repository work remains.

## S2 independent closure audit (2026-09-04)

**Rights attach to the acquisition principal, not the article domain.** A story hosted at a
publisher domain can arrive through an aggregator feed. A domain-level `publisher_feed` grant is
therefore insufficient: native display requires the exact normalized HTTPS feed URL reviewed in
the policy, and missing acquisition identity is quarantined rather than guessed.

**Choose and test one lock order for every lifecycle path.** Ingestion took article then job locks,
while completion and policy rematerialization took job then article. Each transaction was sensible
alone and deadlocked together. S2 now locks article then job everywhere and proves the ordering with
a deterministic real-PostgreSQL blocking test.

**An authoritative empty response is data.** Refusing to persist an empty ready feed resurrected
old cached stories offline. Persist empty ready results; reserve the prior cache only for a failed or
non-authoritative refresh.

**Private analysis needs an end-to-end internal contract too.** Removing untrusted text from public
`content` was correct, but every ranking consumer must migrate to `_analysis_text` and
`_analysis_summary` before the public field disappears. Strip both internal fields only at the final
response boundary.

**Offline caches must not self-renew and bypass revocation.** Revalidate a native article online
when a token is available. A matching account-scoped body may cover connection/timeout or missing
token, but returning that fallback to persistence would extend its TTL on every open.

**A resumable migration must share one counter schema across the batch and its runner.** A batch
added `outdated_origins` after the cumulative total was written; the database transaction committed,
then reporting raised `KeyError` and falsely claimed rollback. Build both dictionaries from the same
factory, accept additive counters while accumulating, and word failures honestly because earlier
batches may already be durable.

## Finish means close the review findings (2026-09-04)

**A green primary suite is not completion when the final audit reports concrete lifecycle bugs.**
Turn every late P1 finding into the active checklist immediately, implement it, and rerun the affected
negative paths before replying. Repeated “continuing” updates without landing the remaining fixes are
not progress and force the user to keep asking for the same completion.

**An authoritative cache snapshot owns membership, not just fields on rows it contains.** A late
detail response must be rejected when the newest persisted feed is empty or omits that article;
otherwise a removed story can be resurrected even though per-row mode/version fencing is correct.

**Initialize state-publishing singletons before SwiftUI evaluates view bodies.** Lazily constructing
an auth-backed view model from `body` initialized `AuthService.shared`, whose immediate restore path
published state reentrantly. Start shared auth restoration during `App.init`, and yield once at the
top of view startup tasks before mutating observable state.

## Resume the requested deliverable after interruption (2026-09-05)

When a usage limit interrupts an audit, resume from the retained findings and finish the
requested specification and verification. Progress updates are not the deliverable. A request
to continue the original analysis does not silently authorize deployment or a runtime rewrite.

## S10 learning implementation (2026-09-10)

**A synchronous test method on an `@MainActor` XCTestCase can crash with SIGABRT under this
toolchain, even though the class-level annotation looks like it should make it safe.** Three
new tests crashed until marked `async` to match every pre-existing test in the same file
(`ReadingEventTrackerTests.swift`) — nothing else about them was wrong. If a new test in an
`@MainActor` test class fails with a bare crash and no assertion message, check `async` first
before debugging the test's actual logic.

**A passive/implicit signal must never share a write path with the table an explicit, carefully
-fenced feedback writer owns — fold it in at read time instead, even if the plan sketch says
otherwise.** The S10 plan's original sketch routed quick-back/qualified-read through the same
`reward()` call explicit feedback uses, writing into `reader_learned_signals`. Implementing it
literally would have made passive telemetry a second writer to a table this codebase already
has a real, tested invariant against (`reader_feedback.py`'s own docstring, plus
`test_telemetry_cannot_be_second_explicit_learning_writer`). Caught by checking the invariant
against the plan before writing code, not after. The fix — two new tables, folded into the one
seam (`load_learned_weights`) both serving paths already read, never touching
`reader_learned_signals` — was more correct than the original sketch, not a smaller version of it.

**A synthetic eval/replay fixture needs realistic text length and at least one non-empty
declared interest, or it silently exercises an unrelated production fast-path instead of the
thing being tested.** Two real production behaviors ate a new replay harness's first attempt:
`MIN_CANDIDATE_TEXT_LENGTH = 40` drops any candidate whose title+summary is shorter (terse
placeholder titles like "Story one" fail it silently, no error); and a persona with zero stated
interests (`has_preferences == False`) takes a "no profile available" fast path that marks
every candidate relevant unconditionally and never calls the suppression/scoring machinery at
all, so a "does rejection work" test against a cold-start-shaped persona proves nothing. Debug
an empty/wrong result from a frozen-snapshot harness by printing every executed statement
before suspecting the harness's SQL-dispatch logic — the actual production code path is often
taking a documented, correct, different branch than assumed.

## Phase 7 foundational hardening (2026-09-12)

**A flag that is read in five places and written in none is not a feature, it is a comment.**
`users.is_deleted` had guards in `reader_repository`, `ranking_repository` and `reader_worker`,
and a login-path filter — and nothing ever set it. Every `ON DELETE CASCADE` pointing at
`public.users` was therefore unreachable code, and the three auth paths that mattered most
(`_get_user_id_from_token`, `/me`, the two background user enumerations) never consulted the
flag at all. When adding the writer, the work was not "write the endpoint"; it was finding every
reader that had been silently agreeing with a value that could never change.

**Prove deletion is complete by reading the schema, not a list.** A hand-maintained table of
"things to delete" is correct exactly once. `account_lifecycle.user_scoped_tables()` walks
`pg_constraint` for the transitive cascade closure of `public.users` and diffs it against every
base table carrying a `user_id`/`account` column; the test asserts the leftover set is empty.
Verified by adding an orphan table and watching it fail. The same shape applies to any
"did we handle all of X" question where the database already knows the answer.

**A bug found at the join is usually not a bug in the join.** S4's suppression was traced to
`ON r.feed_request_id = d.feed_request_id` comparing NULL to a uuid. The actual cause was four
hops upstream: `finalize_feed` stamped three of the four fields the iOS client requires before
it will build a delivery receipt, so the client sent null — which meant *no* legacy+S5 telemetry
could be attributed to an edition, not just S4's. Fixing the join's inputs fixed a much larger
problem than the one reported. Trace to the first place the data is wrong, not the first place
it is noticed.

**Batch by the limit you will actually be judged against.** The diagnostics uploader batched
crash reports five at a time; five near-maximum payloads exceed the backend's 1MB body cap,
return 413, and — because 413 is a permanent rejection — discard exactly the five biggest crash
reports. A count-based batch size is a guess; a byte-based one is the constraint. Writing a test
that *pinned* the broken relationship was the moment to notice it was broken.

**When a test passes alone and fails in the suite, suspect module identity before logic.**
`test_app_middleware.py` evicts and re-imports every `app.*` module at collection so it can use
the real FastAPI. A module-level `from app import main` in a new test binds the pre-eviction
object while the code under test resolves the post-eviction one, so `monkeypatch` lands on a
module nobody calls. Resolve `app.*` through `sys.modules` inside a fixture instead.

**Fail closed on a promise you cannot keep.** S4 could have been made to deliver critical-event
cards on a path that cannot receipt them — the reader would see the story, and the "I already
knew this" control would silently do nothing. `compose_feed` now declines to inject priority
unless something will stamp the edition. Expressed as a capability check
(`_delivery_is_attributable`), not `if S5_READER_ENABLED`, so it survives attribution moving.

**Decide the retention question in a file, not a commit message.** "Is this 14-day coupling
intentional?" has an answer that outlives whoever asks it. `app/services/retention.py` holds the
constant *and* the argument for it *and* the upgrade path if it ever stops being right — which
is what makes the next person's version of the question cheap to answer.

## Staging has to be tested cold (2026-09-13)

**A post-deploy smoke test that only runs while the machines are warm does not test the
deploy.** Staging's nine checks passed immediately after `fly deploy` and again twelve hours
later they would not have: with `min_machines_running = 0` the machines auto-stop, and on
wake every uvicorn child died on spawn, the port never opened, and Fly answered 503 after
~59s. The deploy left the machines running, so the smoke run never touched the cold path
that this configuration guarantees will be the *normal* path. Stop the machines, then smoke.

**Do not shrink staging away from production's shape to save money.** `fly.staging.toml`
opened by declaring itself "deliberately identical to production apart from the marked
lines" and then set `shared-cpu-1x` against production's `shared-cpu-2x`. Same image, same
1gb, same hardcoded `--workers 2`: two vCPUs works, one kills every worker child. The cost
lever that is actually safe is `min_machines_running`, which changes *when* you pay, not
what you are rehearsing.

**Diagnose by elimination against the known-good twin.** The 503 looked like a database
problem (new Neon project, pooled endpoint, and prior worry about transaction-mode pooling
breaking advisory locks and prepared statements). It was not: Neon connected, and
`_ensure_tables`' ~100 DDL statements completed. Nor memory — 805MB free, `oom_killed=false`.
`--workers 1` booted cleanly, which isolated it to the multiprocess path, and production
running the identical image on a bigger VM named the variable. Having a working twin to
diff against is most of the value of having staging at all.

**A build context is an exfiltration path, not just a slow upload.** `backend/` had no
`.dockerignore`, so every deploy shipped 265MB to the remote builder — 213MB of local venv,
44MB of eval corpora, and `backend/.env` containing a live `OPENAI_API_KEY`. The Dockerfile
never COPYed it, which is why nobody noticed. Now 12.6kB.

## Deploying is a test, and logging is part of the product (2026-09-13)

**A `logger.info` that nothing configured is a comment.** `app/main.py` never called
`basicConfig` or `dictConfig`, so the root logger sat at its WARNING default with no
handlers and every `logger.info` in the application was discarded in production.
`logger.exception` still came through, and the RSS progress lines are `print()`, so the
logs looked healthy rather than half-missing. The cost: S6 and S7 shadow observations are
emitted with `logger.info` and nothing else, so **shadow mode was unobservable by
construction for its entire existence** — a second cause, entirely independent of the "no
traffic has ever reached /feed/*" one everybody was working from. When a diagnostic system
appears to produce nothing, check that its output can physically reach you before
concluding the system did not run.

**The tell was the line that should have been there.** Grepping for "S6 shadow" and
finding nothing is ambiguous — maybe it never ran. Noticing that `S9 response`, which
middleware emits for *every* `/feed` request, was also missing while the uvicorn access
log line was present is not ambiguous at all. Look for the control you already know should
be present, not only the thing you are hunting.

**`CREATE INDEX IF NOT EXISTS` is not atomic.** Two sessions both see it missing, both
proceed, and the loser gets a UniqueViolation on `pg_class`. With `--workers 2` both
workers run `_ensure_tables` at startup, so every deploy introducing a new index is a coin
flip on one worker exiting with "Application startup failed". It self-heals via respawn,
which is exactly why it survived unnoticed. The codebase already had the answer in three
places — the S5/S7/S8 installers each take an advisory lock before their DDL — and
`_ensure_tables`, the one that runs on every boot, did not.

**Turning logging on has a blast radius.** Root INFO also enabled httpx's
one-line-per-request logging, and article extraction makes hundreds of requests per
ingestion cycle; the first log after the fix was screens of NYT 403s with the shadow
observations buried underneath. Fixing visibility means choosing what stays quiet too.

## Repository presentation (2026-09-14)

**A committed cache can be load-bearing.** 34 MB across 2,337 files under
`backend/evals/.cache/` looks exactly like the bloat you delete on sight — it is 85% of
every tracked file in the repo. It is also the only reason CI can run the eval gate with
`EVAL_OFFLINE=1` and no API key. Deleting it would have turned every pull request red.
Before removing anything that looks like generated waste, grep CI for it. The right fix
was `linguist-generated=true` in `.gitattributes`, which collapses the diffs on GitHub
without removing the bytes.

**`.git/info/exclude` is not `.gitignore`.** `.context/` — 909 MB of agent working notes,
logs, and a second copy of the repo — was ignored only by a machine-local exclude file.
Nothing was wrong on this machine and everything would have been wrong on the next clone.
Anything that must never be committed belongs in the tracked `.gitignore`, not in a local
exclude. The proof is `git ls-files -i -c --exclude-standard` (must be empty) plus
`git add -A` followed by inspecting what actually got staged.

**Documentation claims decay silently, and the README decays fastest.** Four separate
claims in the README were false against the code: the deployment target was `iOS 26.0` in
all four build configurations while the badge said iOS 17; "Sign in with Apple" was listed
as a shipped feature with no `AuthenticationServices` import anywhere in `Daily/`;
Swagger was advertised at `/docs` when `_DOCS_ENABLED = ENVIRONMENT != "production"` and
`ENVIRONMENT` defaults to `production`; and the Tune diff toast was described as working
when `weight_diff` has zero occurrences in `backend/`. None of these were ever lies — each
was true when written. A doc that asserts a fact needs a way to be checked: prefer
"`grep` says X" claims over remembered ones, and check every number before publishing.

**`PRODUCTION_READINESS.md` was worse than having no such document.** Its top Critical item
was "Using `print()` statements throughout" (logging was configured at `main.py:29`); it
also claimed no health check (`/healthz`, `main.py:719`), no CORS (`main.py:615`), no rate
limiting (`main.py:646`), and empty test files (822 test functions). Every "Current State"
line was false, and a section header read "Structured Loggin". Deleted rather than
rewritten — git history keeps it. A stale checklist actively misinforms; an absent one only
omits.

## A contrast sweep is not an accessibility audit (2026-09-21)

The web redesign shipped with a self-audit that reported "0 text nodes below WCAG AA in light
and dark across all six routes, 0 horizontal overflow at five widths." Both true, both verified,
and it still shipped three components with malformed definition lists.

Each rendered a `<div>` inside a `<dl>` containing `<dt>`, `<dd>` and then a `<p>` for the
caption. The spec allows only `<dt>` and `<dd>` inside that wrapper, so every stat readout on
the site — the elements carrying most of its numbers — was structurally unpairable by assistive
technology. A Lighthouse pass caught it in one run; the hand-rolled audit could not, because it
only measured colour and geometry.

Two rules out of that:

1. **An audit you wrote yourself only finds the classes of defect you thought of.** Colour
   contrast and overflow are the two easiest things to compute from `getComputedStyle`, which is
   exactly why a hand-rolled sweep converges on them. Structure, naming, roles and focus order
   are the harder half and get skipped silently — the report reads clean either way.
2. **Run a real engine before claiming accessibility.** `chrome-devtools-mcp`'s
   `lighthouse_audit` is installed and takes one call. It found `definition-list` plus
   `agent-accessibility-tree` on a build that a bespoke checker had just passed.

Related: the same session's other failure was a verified-green branch that was never pushed, so
the deployed site showed none of the work and looked like the redesign had failed. Verification
and delivery are separate steps and reporting the first as if it implied the second wastes
somebody's afternoon.
