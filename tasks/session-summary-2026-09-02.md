# Session summary — 2026-09-01 → 2026-09-02

What was completed, what was measured, and what is deliberately still open.
Branch `mmarufov/sydney-v7`. Scope: **S0 (evaluation)** built end to end, **S1 (sources &
ingestion)** audited and Phase 0 shipped.

---

## 1. S0 — Evaluation system ✅ complete

Goal: a ruler. Before this, every judgement about the feed was read-the-output-and-eyeball,
and the one proxy metric had already scored a junk feed 14/14.

### What exists now (`backend/evals/`)

| Piece | File | What it does |
|---|---|---|
| Frozen snapshots | `snapshot.py`, `snapshots/` | Content-hashed, committed, gzipped corpus. `freeze` a corpus, `derive` a quiet-day variant (clones and prunes labels too). |
| Response cache | `llm_cache.py` | `CachingOpenAI`, a drop-in for the OpenAI client keyed by request hash. Cache hit = no network. `EVAL_OFFLINE=1` turns a miss into a failure. Hard `EVAL_BUDGET_USD` cap. |
| In-memory DB | `fake_db.py` | `SnapshotConn` answers production's SQL from a snapshot with `now()` frozen. Unknown SQL raises rather than silently returning empty. |
| Runners | `runners.py` | One `build(persona, pool, frozen_now)` interface. `ProductionRunner` drives the **real** `get_personalized_feed`; `PrototypeRunner` wraps the proposed pipeline. Every article gets a stage trace. |
| Ground truth | `label.py`, `labels/` | Pooled two-pass model labelling, review CLI, event labels, planted needles. |
| Metrics & reporting | `metrics.py`, `run.py`, `compare.py`, `results/` | Recall, never-rate, event delivery, loss-by-stage, judge precision/recall; scorecards tagged with the git SHA; scorecard diffing. |
| Gate | `tests/test_eval_gate.py`, `.github/workflows/backend-tests.yml` | Runs fully offline from the committed cache, enforces floors and no-regression-vs-baseline. |

**Ten personas.** The original three plus seven built through the *production* profile builder
from onboarding transcripts: broad reader, cold start, exclusion collision, non-English-named
entities, developing-story follower, background sports fan, life-context reader.

**Labels.** ~350 pooled articles per persona per snapshot, labelled `must_see` / `fine` /
`never` with hard-case tags (`need_to_know`, `lookalike`, `exclusion_collision`,
`background_routine`, `followup`, `major_event`, `promo`). Two passes: `gpt-4.1-mini` over the
pool, `gpt-4.1` over the contested set. **~$1.60 one time**, fully cached.

**Needles.** ~4 planted articles per persona (2 must-surface, 2 lookalikes) injected at run
time — e.g. an NJ Transit shutdown for Ray, with a *Newark, Delaware* story as the lookalike.

### Baseline (2026-08-31 snapshot, 10 personas, k=12)

| metric | prod (fallback) | **prod (LLM)** | prototype |
|---|---|---|---|
| recall@12 on must-see | 0.25 | **0.28** | 0.44 |
| must-see reaching the scorer | 0.37 | **0.37** | 0.76 |
| need-to-know recall | 0.18 | **0.17** | 0.36 |
| never-rate in top 12 | 0.39 | **0.21** | 0.05 |
| world-critical event delivered | 0.20 | **0.20** | 1.00 |
| planted needles found | 0.55 | **0.60** | 0.70 |
| lookalikes shown | 0.25 | **0.05** | 0.10 |
| judge precision / recall | – | **0.65 / 0.62** | 0.92 / 0.76 |
| cost, all ten readers | $0 | **$0.11** | $0.035 |

**Where production loses must-see stories:** 85 at the recency window (never loaded), 10 at the
100-candidate prefilter cap, 12 rejected by the scorer, 6 ranked below 12. Retrieval, not
ranking, is the bottleneck — the S6 finding, now a number.

### Findings the harness surfaced while being built

1. **The production scorer runs away.** With no output cap and positional (non-id-echoed)
   results, `gpt-4o-mini` loops on 40-article batches, returns up to 300 verdicts for 40
   articles or invalid JSON, times out the 45 s guard, and silently degrades to keyword
   scoring. Reproducible from cache. → S7.
2. **217 corpus articles dated after the fetch**, up to 9 h ahead — a feed-parsing timezone
   bug. → fixed in the S1 plan (Phase 2).
3. **Embeddings are 0 in production** out of 34,525 articles, and nothing notices. → S1 Phase 4.

---

## 2. S1 — Sources & ingestion 🔍 audited, Phase 0 shipped

Full audit: **`tasks/s1-ingestion-audit.md`**. Plan:
`~/.claude/plans/create-a-plan-to-adaptive-cray.md`.

### What the audit measured (read-only, production DB + live probe of all 82 seeds)

| fact | value |
|---|---|
| `article_source_links` rows | **0** — the feed query inner-joins through it, so every article is unreachable |
| `user_feed_cache` rows | **0** — nobody is being served a feed |
| Google News redirect stubs | **23,892 / 34,525 (69%)**, no body, no image |
| deployed schema | predates 2026-04-14 — production runs a months-old image |
| `user_sources.last_fetched_at` | frozen at **2026-04-13** |
| embeddings | 0 / 34,525 |
| seeds alive | 76 / 82 — but **only 5 of 9 AI feeds** |
| feeds honouring conditional GET | **45 of 76** (the code never sends one) |
| bytes per fetch cycle | ~13 MB, every 3 minutes, ×2 workers |
| enrichment last week | 7,237 articles exhausted 3 attempts → **4 images produced** |

### Phase 0 — shipped ✅

The root cause of the frozen pipeline, plus the guardrails that would have caught it.

1. **Fixed a loop that had never run.** `_per_user_refresh_loop` filtered on
   `users.last_active_at`, a column **no `CREATE` or `ALTER` ever added**. Every tick raised
   `UndefinedColumn` into a bare `except`, silently. The column now exists, the query falls
   back to `last_login` via `COALESCE`, and the authenticated path marks readers active
   (throttled to one write per 5 minutes).
2. **Leader election on all four background loops.** The container runs `uvicorn --workers 2`
   and Fly can run several machines, so every loop ran two or more times over. A session-level
   `pg_try_advisory_lock` now guarantees one holder cluster-wide, released automatically if the
   holder dies. The whole tick runs inside the lock.
3. **Build identity.** `/healthz` returns `git_sha`, `started_at` and `leader_of`; the
   Dockerfile takes a `GIT_SHA` build arg. A stale deploy is now visible instead of invisible.
4. **Schema DDL once per process** instead of ~100 statements on every request handler and
   every 3-minute tick.
5. **Swallowed errors replaced** with `logger.exception` in all four loops.

Files: `backend/app/main.py`, `backend/Dockerfile`, `backend/tests/test_main_loops.py`.

---

## 3. Test suite health ✅

**192 passing** (was 150 at session start), plus 60 subtests.

New test files: `test_eval_llm_cache.py`, `test_eval_snapshot.py`, `test_eval_runners.py`,
`test_eval_metrics.py`, `test_eval_gate.py`, `test_main_loops.py`, and feed-build-log cases
appended to `test_feed_service.py`.

**Also fixed a real defect in the suite itself.** Eight test modules each opened with their own
`if "openai" not in sys.modules:` stub block. Whichever pytest imported first won, so behaviour
depended on collection order and adding a file could break an unrelated import. There is now
one `tests/conftest.py` + `tests/_app_stubs.py` that installs a complete stub set before any
test module loads.

---

## 4. Known open items (deliberate, not forgotten)

| # | Item | Notes |
|---|---|---|
| 1 | **Nothing is deployed.** | Production still runs the pre-April image. Phase 0 changes nothing until: `fly deploy --build-arg GIT_SHA=$(git rev-parse --short HEAD)` |
| 2 | **Nothing is committed.** | All work is in the working tree on `mmarufov/sydney-v7`. |
| 3 | **3 eval-gate subtests fail** on the `2026-09-02` snapshot. | **Not caused by this work** — the eval path never imports `main.py`, and the current code is deterministic across 4 runs and 3 hash seeds. That snapshot's committed baseline does not reproduce against the tree; every persona's feed differs with zero cache misses. The `2026-08-31` baseline reproduces exactly. Whoever owns that snapshot should re-run and refresh, or investigate the gap. I did not refresh it, because that would erase the evidence. |
| 4 | **Labels are model-bootstrapped**, only partly reviewed. | Treat absolute metric values as provisional; the gate enforces *deltas*. `python -m evals.label review --snapshot <s> --persona <p>` |
| 5 | **S1 Phases 1–7 not started.** | Registry, central poller, Google News retirement, enrichment gating, health metrics, preference-edit reconciliation, re-measurement. |

---

## 5. Where to pick up

1. **Deploy Phase 0** and confirm `/healthz` shows the SHA, `article_source_links` becomes
   non-zero within 30 minutes, and exactly one "acquired leadership" line appears per loop.
2. **S1 Phase 1** — the `sources` registry table with region/language, seeded from the 76
   healthy seeds + 51 eval feeds, with the `source_id` backfill. Schema and data only, no
   behaviour change, safe to ship immediately after Phase 0.
3. **S1 Phase 2** — the central poller. This is the one that makes the pool reachable and
   polite: conditional GET, `calendar.timegm` dates, canonical dedupe, a link row for every
   article, adaptive cadence, real failure counting.

**Acceptance for S1, measured by S0:** `loss_by_stage: lookback` falls from 85 toward 0 while
`never_rate` does not rise.

---

## Key documents

- `tasks/systems.md` — the app as eleven systems, S0–S10
- `tasks/s1-ingestion-audit.md` — the S1 audit with all measurements
- `backend/evals/README.md` — how to run and extend the evaluation
- `tasks/plan.md` — live checklists for S0 (done) and S1 (P0 done)
- `tasks/lessons.md` — corrections and rules captured this session
- `~/.claude/plans/create-a-plan-to-adaptive-cray.md` — the approved S1 plan
