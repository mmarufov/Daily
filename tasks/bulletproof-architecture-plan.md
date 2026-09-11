# Daily — bulletproofing the whole architecture: verified findings and a phased plan

Analysis and planning only, per instruction — nothing in this document has been implemented,
committed, pushed, or deployed. Every claim below was either (a) verified directly by me —
live Fly.io/GitHub/production-database queries, or a real local Postgres run of the six opt-in
test suites — or (b) verified by one of five parallel read-only research agents, each of which
re-checked its assigned system's audit claims against **current code**, ran the actual test
commands, and reported file:line evidence rather than trusting prior documents. Where something
couldn't be verified (e.g., an agent had no production DB access), that's stated explicitly
rather than assumed. This is the single most heavily fact-checked document in `tasks/`.

## 0. The verdict, in one paragraph

The engineering across S1–S10 is genuinely good — careful contracts, real locking discipline,
fail-closed defaults, honest "unmeasured" labels instead of fabricated quality claims. That is
not the problem. The problem is that **none of it has ever touched reality**: none of it is
committed to git (191 untracked + 64 modified files, branch never pushed), the CI that's
supposed to gate it has executed exactly once, for one system, on a throwaway branch; and
production has been frozen on an April-13 build for five months — predating essentially all of
S2 through S10. Layered on top of that foundational gap, this pass found a specific, concrete
list of real bugs (some live today, some landmines waiting for activation) that a "make it
bulletproof" effort has to fix regardless of the deployment question. The plan below is
sequenced accordingly: **ship the foundation before touching the activation order.**

---

## 1. The foundational problem (verified directly, multiple independent ways)

### 1a. Nothing is in git

- `git status --porcelain` (repo root): 191 untracked (`??`) files + 64 modified-but-uncommitted
  files. Every S2–S10 service module, every `test_*_postgres.py`, all four `manage_s*.py`
  scripts, `.github/workflows/backend-tests.yml`, and every `tasks/s*.md` document — including
  this one — are either untracked or modified relative to `HEAD`.
- Current branch `mmarufov/sydney-v7` has **no tracking ref** (`git branch -vv` shows no
  `[origin/...]`) — it has never been pushed. `HEAD` is `b667985` (2026-09-02, "test: add
  production feed evaluation system").
- Independently confirmed by three of the five research agents (S2, S3, S4/S5-S9), each
  discovering this on their own before I told them anything about it.

### 1b. Production is frozen five months in the past

Verified directly by me, four independent ways:
- `fly releases --app daily-backend`: last release is **v95, April 13 2026, 07:24 UTC**. Two
  machines: one `started` (running v95 since that date), one `stopped` since Aug 21.
- Live production database, connected read-only via the documented Supabase pooler
  (`aws-1-us-east-1.pooler.supabase.com:6543`, per `project_prod_deployment_state.md`, since
  the direct host is IPv6-only and unreachable from here): `public.articles` has **no
  `created_at` or `content_quality` column at all**; `feed_build_log` doesn't exist;
  `article_source_links` has 0 rows; **none of** `article_content_artifacts`
  (S2), `understanding_results` (S3), `event_developments` (S4), `reader_profiles` (S5),
  `ranking_control` (S7), `assembly_control` (S8) exist as tables. `user_feedback_signals`
  doesn't exist. `reading_events` has 0 rows. 3 users total, most recent signup 2026-03-31.
- `curl https://daily-backend.fly.dev/healthz` → `{"detail":"Not Found"}`. The endpoint's own
  docstring says it exists specifically so "a stale deploy is visible without guessing" — the
  deployed build predates the very diagnostic built to catch this problem.
- The iOS app's hardcoded default backend (`Daily/AppConfig.swift:22`,
  `https://daily-backend.fly.dev`) is this exact same stale host — there is no staging/newer
  environment the client could be pointed at instead (`fly apps list` shows no other relevant
  app).
- Two Fly secrets are set simultaneously: `NEON_DATABASE_URL` (dead, leftover from a prior
  database provider) and `DATABASE_URL` (current, Supabase) — evidence of unremediated infra
  migration debt.

### 1c. CI has essentially never run

- `gh api repos/mmarufov/Daily/actions/workflows` / `gh api .../actions/runs`: **exactly one**
  workflow has ever executed on this repository's GitHub Actions — a one-off,
  narrowly-scoped `S3 isolated database verification` (`.github/workflows/s3-verification.yml`,
  not present in this working tree at all), run twice, both `success`, 2026-09-06, on a
  throwaway branch `codex/s3-verification-20260906`.
- `backend-tests.yml` — the general-purpose workflow this whole repo's testing story depends
  on, including the `postgres-contracts` job that would run all six `test_*_postgres.py` files
  against a real `pgvector/pgvector` service container with zero-skip enforcement — **is itself
  only a working-tree modification**. `git show HEAD:.github/workflows/backend-tests.yml` shows
  the committed version is 181 lines shorter: just `pip install` + one offline `pytest tests/`
  step. `gh run list --workflow=backend-tests.yml` → `404: workflow not found on the default
  branch`. **It has never executed on GitHub's infrastructure in its current form, not once.**

### 1d. But — the thing CI would have verified turns out to work

I installed `pgvector` locally (`brew install pgvector`, 0.8.6), pointed all six
`S{2,3,4,6,7,8}_TEST_DATABASE_URL` variables at my already-running local Postgres 17
(`postgresql:///postgres`, exactly the invocation the test files' own header comments
document), and ran them for real:

```
$ EVAL_OFFLINE=1 pytest tests/test_article_content_postgres.py tests/test_understanding_postgres.py \
    tests/test_event_postgres.py tests/test_retrieval_postgres.py tests/test_ranking_postgres.py \
    tests/test_assembly_postgres.py -v
============================= 138 passed in 6.37s ==============================
```

**All 138 tests pass, against a real database, covering S2/S3/S4/S6/S7/S8's real-concurrency,
real-locking, real-transaction behavior.** This is more current than the one prior real
execution on record (the Sept 6 GitHub run covered only S2+S3, and predates ~150 lines of
`understanding_repository.py` that S4/S6/S7/S10 have since been built on top of). **As far as
this repository's history shows, this is the first time S4/S6/S7/S8's live-database contracts
have ever been verified against a real Postgres server, by anyone.** This is genuinely good
news: the code that looked riskiest on paper (real transactions, real locking) is the part that
just got the most direct evidence behind it. (One test database's disposable databases clean
up correctly after themselves — verified no leftover state.)

---

## 2. Per-system verified state

Each row: what's genuinely solid (with evidence), what's broken or unmeasured, and the single
most important fix, per the research agent that re-verified it against current code (not
against the older audit documents' say-so).

### S1 — Sources & ingestion

**Solid, fixed since the last audit:** `_ensure_tables` DDL-thrash removed (runs once at
startup, not per-request); the stale-`last_active_at` bug that silently killed the per-user
refresh loop is fixed (`main.py:318-329`); the `ingested_at`-reset-on-conflict GC bug is fixed;
Tavily/Unsplash/Gemini enrichment calls are now opt-in and off by default (real cost
reduction); a real per-IP rate limiter exists; account isolation in this layer is clean
(parameterized queries, token-derived user_id, proper FK+unique constraints).

**Broken, newly found this pass:**
- **The core "shared pool, ranked per user" architecture still doesn't work in the default
  path.** The join gate between the global 3-minute ingestion pool and any user's personalized
  feed query is unchanged (`feed_service.py:524-536`); the no-join global branch
  (`feed_service.py:442-471`) has exactly one caller, which always supplies a real `user_uuid`
  — **it is dead code, never exercised.** A user only ever sees articles their own per-user
  pipeline fetched.
- **SSRF-safe fetching is inconsistently applied.** The safe, DNS-pinned fetcher (`safe_http.py`)
  protects article-body extraction, image fetching, and Google-News redirect resolution — but
  **not** the recurring per-feed content fetch (`_fetch_single_feed`, used by every ingestion
  path) or feed-URL validation during discovery. Candidate feed URLs can originate from an LLM
  suggestion (`_ai_suggest_feeds`) whose prompt embeds user-supplied text — a real, live gap
  worth closing regardless of anything else in this plan.
- **The `/sources/discover` duplicate-request guard is broken across the app's 2 worker
  processes.** Its advisory-lock key uses Python's `hash(user_id)`, which is randomized
  per-process (not pinned via `PYTHONHASHSEED`) while the Dockerfile runs `--workers 2` — two
  concurrent requests for the same user routed to different workers get different lock keys,
  so the "already in progress" 409 can silently fail to serialize.
- **Rate-limit and discovery-cooldown state is per-process, not shared** — same root cause,
  same consequence: a user/IP load-balanced across both workers gets roughly double the
  intended allowance.
- Dead feeds recorded as "healthy" (404s never trip deactivation); `_parse_date` has an
  unfixed local-time bug (`mktime` instead of `calendar.timegm`); exact-URL dedup (no
  canonicalization) persists in the global pool path; any preference edit still wipes the
  entire per-user source graph including undoing `hide_source`; no conditional GET despite
  `etag`/`last_modified` columns existing unused; flat 180s cadence, no backoff/jitter.
- No Postgres-integration test tier exists for this layer at all — unlike every downstream
  stage, `test_source_discovery_postgres.py`/equivalent doesn't exist.

**Single most important fix:** the join gate. Every other fix in this system is polishing a
pipeline whose central premise — that ingesting into the shared pool makes articles reachable
— is false for most of what that pool ingests, in the path that runs by default today.

### S2 — Content pipeline & provenance

**Solid, verified line-by-line against the original audit's 19 findings — every one still
holds and none regressed:** provenance-tagged artifacts with explicit precedence; a real leased
job state machine with CAS completion (`FOR UPDATE OF j SKIP LOCKED`); hardened SSRF-resistant
fetching with DNS pinning (`safe_http.py` — genuinely thorough here, closes the TOCTOU/rebind
gap); identity/paywall/completeness-aware extraction instead of length-as-correctness; one
shared serializer (`serialize_article`) across fresh/cached/detail reads; version-fenced
embeddings; a default-deny source-policy contract with an auditable CLI. Near-zero hot-path
cost today (no on-demand extraction, no request-path network calls).

**Broken / unmeasured, newly found this pass:**
- **There is no default source-policy grant anywhere in the codebase.** Grepped every write
  site to `article_source_policies`: the function itself, the human-operated CLI
  (`manage_s2_source_policy.py`), and the backfill script. **No seed data, migration, or
  startup code grants any domain `native_full_text` by default.** This means the entire
  sophisticated native-reading pipeline this system exists to gate is currently switched off
  for the whole catalog — a fresh deploy of this exact code would show `source_web`/
  `unavailable` for essentially every article until an operator manually reviews and grants
  each publisher.
- **The single highest-stakes fix (Tavily cross-source text can never become a publisher's
  own reporting) has no behavioral test** — only a source-string "does this function name
  still appear" tripwire. Given this was the audit's #1 P0 finding, this is the most
  consequential test-coverage gap found in this entire pass.
- Dead code: `feed_service._needs_on_demand_extraction` has no production caller anywhere,
  only its own tests.
- `publisher_feed` artifacts get no automated completeness check (trust-based on the human
  review, unlike `origin_extract`'s runtime paywall/length checks) — reasonable, but no
  drift detection if a publisher's feed silently starts serving teasers.

**Single most important fix:** run the human source-policy review-and-grant process against
real sources. Without it, the "native reading experience" this whole system exists for has no
path to appearing for a single real user, no matter how good the extractor is.

### S3 — Understanding (LLM article analysis)

**Solid:** the strongest-verified system in this pass. An agent independently reproduced the
two most checkable numeric claims in the prior audit (a real hosted 348-test GitHub Actions
run, and the exact `$0.09325732`/`$5.00` pilot-budget ledger) rather than trusting them. Real
adversarial contract tests (prompt-injection inertness, fabricated-evidence rejection). Careful
lease/outbox/budget machinery, independently verified against real Postgres in that one hosted
run — though that run predates ~150 lines of newer code my own local run just covered instead.
A previously-flagged cost-accounting bug (fallback to $0 for unknown model pricing) has since
been genuinely fixed (raises `UnknownModelPricing` now, reserves budget pre-flight).

**Broken / unmeasured:**
- **`DEFAULT_RECIPE` pins the model that lost the pilot.** The shipped default constant is
  `gpt-4.1-mini-2025-04-14`, which the pilot data shows rejected 6/20 facet calls; the model
  that passed 20/20 (`gpt-4o-mini-2024-07-18`) is not the default. Not live-impacting (nothing
  is promoted), but a real trap for whoever copies `DEFAULT_RECIPE` assuming it's the winner.
- **The 600-item review queue has zero reviewed labels** (`reviewed_count: 0`, verified
  directly from the data file). No language/region/evidence-tier slice has been declared
  supported. Story clustering is hard-coded to singleton-only by design until this changes.
- `entity_linker.py` — a small module specifically responsible for preventing a model from
  inventing canonical entity/place IDs — has no dedicated test file.

**Single most important fix:** not a code defect — it's that engineering has kept building
downstream consumers (S4/S6/S7/S8 already wired to consume S3's output) while zero of the
600 queued items has been reviewed by a human. The risk is well-built plumbing arriving at
"production readiness" before anyone has confirmed the thing flowing through the pipe is
accurate.

### S4 — Event detection ("seen development" / critical events)

**Solid:** genuinely deep, consistent fail-closed design — five independent gates (worker flag,
consumer flag, S7 flag, S8 flag, and a capability header the client literally cannot send
today) all currently at "off," plus DB-level `CHECK` constraints that make the database itself
reject turning on spend without a budget or delivery without an approved recipe. Provider
failure handling (typed categories, spend ledger with `UNIQUE(job_id,attempt)`, a circuit
breaker) is careful. Honest: `protocol.json` is still `"status": "draft"`, no fabricated
quality claims.

**Broken — a genuine, newly-discovered bug:**
- **"Seen development" suppression cannot actually suppress anything, in the path that would
  run if S4 consumers were ever turned on.** Traced precisely: `event_integration.compose_feed`
  mints its own `request_id` but never calls `_save_feed_cache`, so an S4-sourced article never
  gets a `user_feed_cache` row; the per-article stamping of `feed_request_id`/`delivery_position`
  only happens inside `reader_integration.finalize_feed`, which no-ops whenever S5 is off
  (the default); the client's `deliveryReceipt` is therefore always `nil` for these articles,
  so it always sends `feed_request_id: null`; the "seen" query's join
  (`ON r.feed_request_id=d.feed_request_id`) can never match `NULL` against a real UUID. Net:
  a reader who taps/reads/marks "already knew" on an S4-delivered critical update can never
  suppress it on the next build. **This is bounded (each assessment expires within 24h anyway)
  and not currently live** — S4 consumers need both an env flag and a header no client sends,
  so nobody can reach this path today — but it would silently fail to close the loop the moment
  S4 activates, and the existing test suite can't catch it because the unit tests fake the
  "seen" query's result directly instead of exercising the real join. By contrast, the same
  join done through the S7 path is correct (one `request_id` stamped consistently everywhere).
- No jitter on retry backoff, despite the implementation plan explicitly calling for it.
- The planned `rubric.json` versioned artifact doesn't exist; the rubric lives inline in a
  prompt string instead.

**Single most important fix:** the suppression join bug, before S4 consumers are ever turned
on — otherwise the exact user-facing promise this system makes ("tell us you already knew,
we'll stop showing it") silently doesn't work.

### S5 (reader model) / S6 (retrieval) / S7 (ranking) / S8 (assembly) / S9 (delivery)

**Solid:** exceptionally careful fail-closed design, verified fresh (not from the status docs)
by directly reading every `manage_s{5,6,7,8}_*.py` script and the cost/rollback code paths.
Real safety rails: S7's provider spend requires a *separate* flag from serving
(`S7_PROVIDER_ENABLED`), budgets default to `0` (unspendable) and both the DB `CHECK` and the
CLI require explicit positive numbers, and any cost overrun **automatically disables** further
spend and serving (a real circuit breaker, not just a monitoring alert). Every system re-checks
its control-table flag fresh, inside the transaction, at the moment of use — a flip-off takes
effect immediately, no race window. Shadow modes (`S6_SHADOW_ENABLED`, `S7_SHADOW_ENABLED`)
already exist, are genuinely zero-risk (log-only), and are the correct first validation step
before any real serving.

**Three concrete activation-ordering landmines found, none previously documented:**
1. **S6 cannot be turned on independently of S7.** `main.py:2359-2363`'s
   `_observe_s6_retrieval()` raises HTTP 503 for **every** legacy `/feed/build` request whenever
   `S6_SERVING_ENABLED=true` while `S7_SERVING_ENABLED=false`. The two flags must change
   together (or S7 first) — "turn them on one at a time, independently, in order" is not a safe
   instruction as stated.
2. **S8 requires the mobile client to already ship support for a header, or it locks out every
   installed app.** `main.py:788-793` returns HTTP 409 to any request lacking
   `X-Daily-Edition-Version: 1` the instant S8 serving is on. Enabling S8 is not purely a
   backend decision — it has a client-rollout dependency that must land first.
3. **S5 needs new infrastructure, not just a flag.** The per-intent embedding worker
   (`reader_worker.py`) must run as a separate deployed process; `fly.toml` today defines only
   one process group (`processes = ["app"]`), and nothing in `main.py` imports it. "Turn on
   S5" is partly a deployment-topology change, not an env var flip.

S9 has no dedicated flag or table at all — it activates automatically the moment S7 publishes.

No evidence anywhere (log, ledger, result file) that real OpenAI spend has ever happened for
S7 specifically — the cost mechanism is unused in anger, not just untested.

### S10 — Learning (this session's earlier implementation)

Already implemented and verified in a prior turn this session (see
`tasks/s10-implementation-status.md`): Tier 0 batches A–F shipped, 1,884 backend tests and 121
iOS tests passing. Same caveat as everything else here: **uncommitted**, and only meaningfully
active once S5/S7 are actually turned on in production (S10's learned-weight influence is
currently a no-op with S5/S7 both off).

---

## 3. Consolidated new-bug list (cross-cutting, this pass's original findings)

| # | Bug | System | Severity | Live today? |
|---|---|---|---|---|
| 1 | Nothing committed to git; branch never pushed | all | Critical | N/A — foundational |
| 2 | Production 5 months stale; predates S2–S10 entirely | all | Critical | Yes |
| 3 | `backend-tests.yml`'s real CI job has never executed on GitHub | all | Critical | N/A |
| 4 | No default S2 source-policy grants exist — native reading is off for 100% of the catalog | S2 | High | Yes, if deployed as-is |
| 5 | Global-pool join gate — shared ingestion pool unreachable by personalized feed queries | S1 | High | Yes |
| 6 | SSRF-safe fetch not applied to recurring feed fetch / discovery validation | S1 | High (security) | Yes |
| 7 | `/sources/discover` duplicate-guard broken across 2 worker processes (`hash()` randomization) | S1 | Medium | Yes |
| 8 | Rate-limit/cooldown state not shared across worker processes | S1 | Medium | Yes |
| 9 | S6-without-S7 503s all legacy feed traffic | S5-S9 | High (activation landmine) | Only if misconfigured |
| 10 | S8 locks out clients without the edition-version header | S5-S9 | High (activation landmine) | Only on activation |
| 11 | S4 "seen development" suppression can never fire (NULL join) | S4 | Medium (bounded, 24h) | Only if S4 activated |
| 12 | S3 `DEFAULT_RECIPE` pins the pilot's losing model | S3 | Low | No (nothing promoted) |
| 13 | Tavily-cross-source-text fix has no behavioral test, only a string tripwire | S2 | Medium (test gap) | N/A |
| 14 | The 3 pre-existing S0 eval-gate regressions have been failing, unchanged, 8+ days | eval | Medium | Yes, ongoing |
| 15 | No account deletion or server-side sign-out revocation anywhere in the app | account lifecycle | High | Yes (gap, not a regression) |
| 16 | No crash reporting or analytics anywhere in the iOS app | ops | Medium | Yes (gap) |
| 17 | No staging environment; the only Fly app is production itself | ops | Medium | Yes (gap) |

---

## 4. The corrected activation sequence

Superseding any "flip S5 → S6 → S7 → S8 in independent order" framing from earlier planning,
given landmines #9/#10/#3 above:

```
Phase 0  Commit + push everything. Get backend-tests.yml to actually run, green, on GitHub,
         at least once (offline job first, then the postgres-contracts job).
Phase 1  Deploy current main to production for the first time in 5 months (staged, see §5).
Phase 2  Fix the concrete bugs that don't depend on any flag (#5, #6, #7, #8, #13, #14).
Phase 3  S6 shadow + S7 shadow together, log-only, zero risk, watching real legacy traffic.
Phase 4  S6 serving + S7 serving together (never S6 alone — landmine #9), provider still off
         (baseline judgment only, no spend).
Phase 5  S7 provider on, with real bounded budgets — the actual "start spending money" switch.
Phase 6  Ship the iOS client update with X-Daily-Edition-Version support; only then S8.
Phase 7  S5's embeddings worker as new deployed infra, if/when semantic retrieval is wanted.
Phase 8  S10 (already implemented) becomes live the moment S5+S7 are both on.
Phase 9  Dogfood daily; only now does S0/S10 evaluation start meaning anything.
```

---

## 5. Phased implementation plan (file-scoped, for the next pass)

### Phase 0 — Land the foundation (no code changes, pure ops/git hygiene)

- **0.1** Commit the working tree in logical, reviewable chunks (not one giant commit) — e.g.
  by system (S1 fixes, S2, S3, S4, S5-S9, S10, docs) — and push to a real branch. *This is the
  single highest-leverage action available and should happen before anything else in this
  plan, including reading further.*
- **0.2** Open a PR (or push directly per house convention) and get `backend-tests.yml`'s
  offline job green on GitHub for the first time.
- **0.3** Get the `postgres-contracts` job green on GitHub for the first time — this repo has
  never seen it execute; my local run proves the tests pass, but "runs on GitHub" and "runs on
  my machine" are different facts worth establishing separately, once.
- **0.4** Take a manual Supabase/Postgres backup/snapshot before anything in Phase 1, given the
  5-month gap and however many additive migrations are about to run against real (if sparse)
  user data for the first time.

*Acceptance:* `git log` on the pushed branch shows this work; a GitHub Actions run (both jobs)
shows green; a DB backup exists and its restore path has been sanity-checked at least once.

### Phase 1 — Redeploy current `main` to production

- **1.1** Rebuild the Docker image locally first (`docker build .` or `fly deploy --build-only`
  if supported) to catch dependency/build issues before touching the live machine — note
  `requirements.txt`'s new pins (`tiktoken`, `httpcore`, `pydantic`) need to actually be in the
  image.
- **1.2** `fly deploy` with `--build-arg GIT_SHA=$(git rev-parse --short HEAD)` (the Dockerfile
  already supports this — it's just never been passed).
- **1.3** Confirm `/healthz` returns 200 with the expected `git_sha` and `/readyz` returns 200
  (not the 404s both currently return).
- **1.4** Confirm the 3-minute ingestion loop resumes and the schema migration
  (`_ensure_tables`) completes cleanly against the real, 5-months-stale production schema —
  watch logs for the first few cycles.
- **1.5** All S3–S10 flags remain at their coded defaults (`false`) through this phase — this
  step is *only* about getting current, correct legacy-path code running in production, not
  about turning anything new on yet.

*Acceptance:* `/healthz` reports the current commit; production schema has `created_at`,
`content_quality`, `feed_build_log`, and every S2–S10 table that doesn't yet exist; ingestion
resumes; no new error volume in Fly logs over 24h.

### Phase 2 — Fix the concrete, flag-independent bugs

Each is a self-contained, testable fix; sequence doesn't matter within this phase.

- **2.1** SSRF-safe fetch for the recurring feed-content fetch and discovery-time feed
  validation (`news_ingestion.py:_fetch_single_feed`, `source_discovery.py:_validate_feed`/
  `_fetch_feed_sample`) — route both through `safe_http.safe_fetch`, matching every other
  outbound fetch in this codebase.
- **2.2** Pin `PYTHONHASHSEED` (or switch the discovery advisory-lock key to a stable hash,
  e.g. `hashlib.sha256(user_id).digest()[:8]` truncated to an int) so the duplicate-discovery
  guard actually serializes across the app's 2 worker processes.
- **2.3** Move per-process rate-limit/cooldown state to a shared store (Postgres row or Redis)
  — or accept and document that the effective allowance is ~2x the stated number, if that's
  judged acceptable at current traffic.
- **2.4** Add the missing behavioral test for the Tavily cross-source-text guarantee (mock a
  Tavily response with `ENRICH_CROSS_SOURCE_ANALYSIS=True`, assert it lands in
  `record_analysis_context`/`analysis_text`, never in `updates["content"]`).
- **2.5** Fix `_parse_date`'s local-time bug (`calendar.timegm`, not `mktime`); add a test.
- **2.6** Actually investigate and fix (or explicitly, deliberately accept and re-baseline) the
  3 standing S0 eval-gate regressions — they've been failing unchanged for over a week; "known
  pre-existing" shouldn't mean "permanently ignored."
- **2.7** Swap S3's `DEFAULT_RECIPE` model constant to the pilot's actual winner
  (`gpt-4o-mini-2024-07-18`), or add a comment loud enough that nobody copy-pastes the loser.

*Acceptance:* one test per fix, all passing; no regression in the full suite.

### Phase 3 — S2: make native reading possible for at least one real source

- **3.1** Pick 3–5 real sources the 3 actual users' interests are likely to hit; run
  `manage_s2_source_policy.py grant` for each with real `--reviewed-by`/`--rights-basis`
  values, not placeholders.
- **3.2** Verify at least one real article resolves to `native_full_text` end-to-end after
  Phase 1's redeploy.

*Acceptance:* a real, current article in production actually renders as native full text on
device, not `source_web`.

### Phase 4 — S6/S7 shadow, then serving, together

- **4.1** `manage_s7_ranking.py install --apply`, then `configure --apply --recipe-file ...
  --approve` (serving/provider still false).
- **4.2** `S6_SHADOW_ENABLED=true` and `S7_SHADOW_ENABLED=true` together; watch the
  `"S6 shadow: %s"` / `"S7 shadow: %s"` log lines against real (if sparse) traffic for a
  meaningful period.
- **4.3** In one deploy, `S6_SERVING_ENABLED=true` **and** `S7_SERVING_ENABLED=true` (never S6
  alone — landmine #9), `configure --apply --serve` (provider still false — baseline judgment
  only, zero spend).
- **4.4** Only after that's stable: `configure --apply --serve --provider --daily-usd <X>
  --account-daily-usd <Y>` with real, small, deliberately-chosen budgets, and
  `S7_PROVIDER_ENABLED=true`.

*Acceptance:* shadow logs show sane candidate/judgment counts before any serving flag flips;
real spend, once enabled, stays within budget and the circuit breaker is exercised at least
once in a controlled test (deliberately trip it, confirm serving auto-disables).

### Phase 5 — S8, gated on a client release

- **5.1** Confirm (via App Store Connect / TestFlight, whichever this project uses) that the
  currently-installed iOS build already sends `X-Daily-Edition-Version: 1` — check the actual
  shipped binary's behavior, not just this worktree's source.
- **5.2** Only then: `manage_s8_assembly.py install/configure --approve --serve`,
  `S8_SERVING_ENABLED=true`.

### Phase 6 — S5, as an infrastructure project, not a flag flip

- **6.1** Add a second Fly process group for `reader_worker.py` in `fly.toml`.
- **6.2** `manage_s5_reader.py migrate/index/budget --apply`, then deploy the worker process,
  then `S5_READER_ENABLED=true`.

### Phase 7 — Foundational hardening (parallel track, not blocking on the above)

- **7.1** Account deletion endpoint + server-side sign-out/session revocation.
- **7.2** Crash reporting for iOS (Crashlytics or a lighter-weight alternative — this app
  already avoids heavy dependencies elsewhere, pick accordingly).
- **7.3** A cheap staging environment (a second, small Fly app pointed at a disposable DB) so
  Phase 1-style "first deploy in months" risk never recurs.
- **7.4** S4's suppression-join bug (bug #11) — fix before S4 consumers are ever turned on.
- **7.5** `reading_events`' de-facto 14-day retention ceiling (tied to article GC) — decide
  explicitly whether behavioral-learning signal should outlive the article it's about, rather
  than have this be an accidental side effect.

### Phase 8 — Dogfood

Once Phase 1–4 are live: use the app daily, generate the first real reading events, feedback,
and receipts this whole architecture has ever seen. This is what finally lets S0/S10's
evaluation harnesses measure something real instead of synthetic personas.

---

## 6. What I'm deliberately not recommending

Consistent with this app's own stated values (usefulness over frontier-for-its-own-sake): no
new database engine, no message queue, no Kubernetes, no rewrite of the legacy path before S5-S9
is proven, no attempt to fix S1's join-gate architecture by resurrecting the unimplemented
Stage-A spec (registry table, poller, interest vectors) — that problem is better solved by
finishing the S5/S6 activation already built, not by building a third parallel architecture.

---

## 7. Immediate next action

Given the risk profile here — **all of this work exists in exactly one place** — the single
most urgent, cheapest, lowest-risk action is Phase 0.1: a local commit (not push, unless asked)
of the current working tree, so a lost or corrupted worktree can't erase five S-systems' worth
of work. I have not done this, per "commit only when asked." Given the stakes, I'd like to flag
this explicitly rather than let it wait for the rest of Phase 0 to be scheduled — happy to do
it now if you say the word.
