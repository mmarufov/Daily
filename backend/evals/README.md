# S0 — Evaluation

Answers one question with evidence: **did a change make the feed better or worse, and if a
story went missing, which stage lost it?**

```bash
# everything below is free and deterministic once the cache is warm
EVAL_OFFLINE=1 python -m evals.run --runner prod  --snapshot 2026-08-31   # real production path
EVAL_OFFLINE=1 python -m evals.run --runner proto --snapshot 2026-08-31   # prototype pipeline
python -m evals.compare --latest prod-llm 2026-08-31                       # diff two scorecards
EVAL_OFFLINE=1 python -m pytest tests/test_eval_gate.py                    # the regression gate
```

## How it fits together

```
snapshots/<date>.json.gz   frozen corpus (1,328 articles, 51 feeds), content-hashed, committed
personas/<key>.json        10 readers; 7 built through the production profile builder
labels/<date>/             must_see / fine / never per persona · events.json · needles.json
.cache/llm/                every model response, keyed by request hash, committed
runners.py                 ProductionRunner (real get_personalized_feed) · PrototypeRunner
metrics.py                 recall, never-rate, event delivery, loss-by-stage, judge P/R
results/<sha>-<runner>-<snapshot>.json   scorecards; baseline-*.json is what CI compares to
```

| File | What it does |
|---|---|
| `snapshot.py` | `freeze` corpus.json into a dated, hashed snapshot; `derive` a quiet-day variant |
| `llm_cache.py` | `CachingOpenAI`: drop-in for the SDK client. Cache hit = no network. `EVAL_OFFLINE=1` turns a miss into a failure. Hard `EVAL_BUDGET_USD` cap. |
| `fake_db.py` | `SnapshotConn`: answers production's SQL from the snapshot. Unknown SQL raises. |
| `runners.py` | One `build(persona, pool, frozen_now)` interface; per-article stage trace |
| `label.py` | Pooled two-pass model labelling, human review CLI, event bootstrap, needles |
| `metrics.py` / `run.py` / `compare.py` | Score, write scorecards, diff them |
| `pipeline.py` / `global_events.py` / `openai_backend.py` | The prototype under test |
| `build_corpus.py` / `feeds.py` | Fetch a fresh corpus through the production RSS parser |

## The runner measures the real product

`ProductionRunner` calls `feed_service.get_personalized_feed` itself. It fakes only the
database (an in-memory connection serving the snapshot, with `now()` frozen to the snapshot
time) and routes the production scorer's OpenAI client through the cache. Candidate loading,
the 300-row recency window, the keyword prefilter, the 40-article batch scorer, the score
blend, dedupe, diversity and role balancing all run unchanged. `mode="fallback"` forces the
deterministic path production takes when the model is unavailable.

Every article in the pool gets a trace row:

```
{"stage_reached": "scored", "dropped_at": "blended", "score": 0.31, "reason": "...", "rank": null}
```

Production stages: `lookback → loaded → prefilter (:cap | :excluded) → scored → blended → dedup →
diversity → roles → feed → rank`. Prototype stages: `recall → triage → judge → assemble → rank`.

## Ground truth

**Labels.** For each persona, the union of what four retrievers surface (BM25, dense, hybrid,
production prefilter) plus a random slice, about 350 articles, is labelled by `gpt-4.1-mini`;
the contested set (must-sees, low confidence, hard-case tags, retriever top-30 called never)
is re-labelled by `gpt-4.1`. Disagreements are flagged `contested`. Cost for ten personas:
**$1.40**, cached. Then a human reviews (`python -m evals.label review`) every `must_see` and
every contested row; human rows override all other rows. Codex-assisted editorial passes use
`source=agent`, never pretend to be human, and override only the bootstrap model rows.

Tags carry the hard cases: `need_to_know` (affects life, money, safety, work — never a hobby),
`exclusion_collision`, `lookalike` (right word, wrong thing), `background_routine`, `followup`,
`major_event`, `promo`.

**Events.** `events.json` is seeded by semantic clustering plus one gravity call. The independent
Codex editorial pass is recorded as `source=agent`; product-owner confirmation remains separate.
On 2026-08-31 it found two `world_critical`, six `major`, and three `routine` clusters.

**Needles.** `needles.json` plants two must-see articles and two lookalikes per persona into the
pool at run time (e.g. an NJ Transit shutdown for Ray; a *Newark, Delaware* story as the
lookalike). `needle_recall` and `lookalike_rate` are the sharpest "never miss / never junk"
signals because the answer is known by construction.

## Metrics

| Metric | Definition |
|---|---|
| `recall_at_k` | must-see in top-k ÷ min(must-see, k). `raw_recall_at_k` divides by all must-see. |
| `recall_at_retrieval` | must-see that reached the scorer (prod) / triage (proto) ÷ must-see |
| `need_to_know_recall` | `recall_at_k` restricted to `need_to_know` |
| `followup_recall` | `recall_at_k` restricted to must-sees tagged `followup`; use later snapshots for day-three coverage |
| `never_rate` | `never`-labelled ÷ top-k |
| `loss_by_stage` | for every missed must-see, the stage that dropped it |
| `event_delivery` | world-critical clusters with a member in top-k ÷ clusters |
| `false_major_rate` | forced/major-story items not in a ≥major cluster (quiet snapshots only) |
| `judge_precision/recall` | the model verdict alone, over labelled candidates it saw |
| `needle_recall` / `lookalike_rate` | planted must-sees found / planted lookalikes shown |
| `calls`, `cost_usd`, `latency_s`, `cache_misses` | efficiency |

## The gate (`tests/test_eval_gate.py`)

Always: fully offline (zero cache misses), calls bounded, and **no per-snapshot metric—including
quiet-day false-major rate—worse than `results/baseline-*.json` by more than 0.05**. Under
`EVAL_GATE_STRICT=1`, false-major must be zero, world-critical events must reach every prototype
feed, and the absolute targets from `tasks/filtering-architecture-plan.md §9` apply
(recall@12 ≥ 0.8, ≤ 1 call). Production does
not meet them today; the scorecard reports the gap every run so S6/S7 can close it.

## Re-warming

Changing a prompt, a model or batch composition changes cache keys. CI then fails with
`CacheMiss` and the key. Re-warm with a key and commit the cache:

```bash
python -m evals.run --runner prod --all-snapshots && python -m evals.run --runner proto --all-snapshots
python -m evals.llm_cache gc          # drop entries no scorecard references
```

Retrying an identical request returns the identical cached response, including cached
failures. That keeps runs reproducible; it also means the eval slightly over-penalises
production, where a retry of a runaway batch might succeed.

## Adding a snapshot

```bash
python evals/build_corpus.py && python -m evals.snapshot freeze            # named by built_at
python -m evals.label events --snapshot <date>
python -m evals.label bootstrap --snapshot <date>                            # ≈$1.40, budget-capped
python -m evals.label review --snapshot <date> --persona ray                 # human pass
python -m evals.snapshot derive <date> <date>-quiet --clusters ev-01 --quiet # clones/prunes labels too
```

## Results — 2026-08-31 snapshot, 10 personas, k = 12

Means over ten personas. Every queued must-see/contested row has an independent Codex editorial
override with honest `source=agent` provenance; product-owner human review remains outstanding.
Treat absolute values as provisional; deltas between runs are what the default gate enforces.

| metric | prod (keyword fallback) | **prod (LLM scorer)** | prototype |
|---|---|---|---|
| recall@12 on must-see | 0.18 | **0.23** | 0.41 |
| must-see reaching the scorer | 0.40 | **0.40** | 0.76 |
| need-to-know recall | 0.11 | **0.18** | 0.48 |
| day-three/follow-up recall | 0.09 | **0.10** | 0.10 |
| never-rate in top 12 | 0.41 | **0.22** | 0.08 |
| world-critical event delivered | 0.20 | **0.20** | 0.55 |
| planted needles found | 0.35 | **0.55** | 0.70 |
| lookalikes shown | 0.20 | **0.10** | 0.10 |
| judge precision / recall | – | **0.59 / 0.56** | 0.84 / 0.69 |
| model calls per reader | 0 | **≤ 5** | ≤ 27 |
| cost, all ten readers | $0 | **$0.14** | $0.035 |

Where production loses its must-sees: **63 at the recency window** (never loaded), 6 at the
100-candidate prefilter cap, 14 rejected by the scorer, 4 ranked below 12. Where the
prototype loses them: 28 at retrieval, 25 at the judge, 19 in assembly. Every one of these is
listed by title in the scorecard under `per_persona.<key>.losses`.

Two things to read from this table. Retrieval, not ranking, is production's problem: two of
many must-see stories never reach the scorer, which is the S6 finding in a single
number. And the LLM scorer's own precision of 0.59 says the S7 batching bug (runaway,
misaligned verdicts) is costing real quality on top of that.

The registered snapshot matrix now also includes a 1,234-article quiet derivative with all
agent-reviewed major-or-higher clusters removed, plus a second 1,358-article live capture from
2026-09-02 (50+ hours after the first). On the quiet derivative, prototype false-major rate is
**0.18**; this is now a real regression metric rather than a vacuous assertion.

## Findings the harness surfaced while being built

- **Production's batch scorer runs away.** With no `max_tokens` and positional output,
  `gpt-4o-mini` looped ("The article discusses a music festival…" hundreds of times) until the
  16k output-token limit on two of Ray's three 40-article batches, timed out the 45 s guard,
  and silently fell back to keyword scoring. Measured, cached, reproducible. Fix in S7.
- **217 of 1,328 corpus articles are dated after the fetch**, up to 8.8 h ahead (ESPN, NJ.com,
  BBC, Al Jazeera…). A timezone bug in feed parsing; it also skews production's recency window.
  Fix in S1/S2.
- **The 300-row recency window is the gatekeeper.** For Ray, 1,028 of 1,328 pool articles never
  reach the prefilter; of the 300 that do, 193 are cut by the 100-candidate cap. The S6 finding,
  now a number.
