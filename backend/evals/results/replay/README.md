# Positional vs id-keyed batch scoring: every number, and how it was made

Machine for everything below: Darwin 27.0.0 arm64 (macOS 27.0.1), Python 3.12.13, Node 25.8.1.
Date: 2026-09-30 (UTC times in each file). Model: gpt-4o-mini, priced at the repo's
`evals/llm_cache.py` table, $0.15 per million input tokens and $0.60 per million output tokens.

Feed quality is not good yet, on either build. Nothing below changes that; recall@12 is about
0.23 against a target of 0.8, and eval labels have no human review.

## 1. The Lab's quoted numbers (pinned in CI by PR #80)

`web/tests/unit/lab-headline-numbers.test.ts`, run by `npm test` in the artifacts workflow.
Merged at `053d6728`. Every pin has an in-test control on doctored input.

| Quoted | Recomputed from | Pinned |
|---|---|---|
| 64 cases | `backend/lab/cases/{observed,synthetic}.json` | 64 |
| positional | `backend/lab/records/positional-v0.json` through `evaluate()` | 0/52 |
| count guard | `count-guard-v1.json` | 48/52 |
| id-keyed | `keyed-v2.json` | 60/60 |
| agent runs | `web/public/lab-artifacts/agent-*.json` | 31 |
| accepted for review | same, `verdict` field | 2 (`agent-k2-generous-out-02`, `-06`, each regraded 60/60 from its own records) |

Hand negative controls, run once and restored: turning one refusal in `count-guard-v1.json`
into a parse, and flipping `agent-k2-generous-out-01` to accepted, failed `count guard: 48/52`
and `accepted exactly 2`.

## 2. How often the positional build misattributed

`score_articles_batch` asked for verdicts "same order" with no id, then paired
`results_list[i]` with `articles[i]` even when the counts differed.

    python -m evals.replay_diff --base origin/main --head HEAD
    # base 94a25809, head 934fa6e0, fully offline, 0 cache misses on either side

| Snapshot | Scoring calls | Applied by position after a count mismatch | Verdicts in those batches |
|---|---:|---:|---:|
| 2026-08-31 | 30 | 20 | 720 |
| 2026-08-31-quiet | 30 | 16 | 520 |
| 2026-09-02 | 30 | 21 | 700 |
| total | 90 | 57 | 1,940 |

A count mismatch does not say which verdicts moved, only that every verdict after the first
gap may belong to another article; 1,940 is the number applied without any way to check.

**PR #59's "63 malformed batches" is 63 guard trips, which is 21 batches times 3 attempts.**
Its guard retries a mismatched batch, and a cached replay returns the same response each time.
Reproduced on its head `81b20198`, counting its "discarding the batch" warning per snapshot:
60, 48 and 63 (`EVAL_OFFLINE=1`, `evals.run.evaluate('prod', snapshot, write=False)` on a
`git archive` of that commit). The 63 is snapshot 2026-09-02, where main has 21 mismatched
batches.

Self-diff control: `--base origin/main --head origin/main` moves 0 verdicts, 0 feeds, every
metric delta 0.0000, on all three snapshots.

## 3. What the id-keyed build does with the same inputs

Same command and file (`replay-diff-94a25809-934fa6e0.json`).

- Calls applied by position: **0 of 90**. Verdicts applied to an article other than the one they
  name: **0**.
- Calls refused whole (every attempt refused, batch left to the deterministic fallback):
  **76 of 90**. By first failing check, per call: missing id 31, unknown id 31 (a mistyped
  UUID), duplicate id 12, truncated at the 4,096-token cap 2.
- Articles without a model verdict: **989 of 3,000 before, 2,700 of 3,000 after**.
- Verdicts moved (relevance flipped): **377 of 3,000**. Top 12 changed for 9, 6 and 10 of 10
  personas; 203 articles entered a top 12.

Why so many refusals: keyed responses to 40-article batches mostly carry 29 to 39 entries. The
model drops articles. Short ids would fix the 31 unknown-id calls at most, not the missing ones.

**Quality got worse on most metrics.** Head minus base, per snapshot:

| Metric | 2026-08-31 | 2026-08-31-quiet | 2026-09-02 |
|---|---:|---:|---:|
| recall@12 | 0.2397 → 0.2422 | 0.2250 → 0.3083 | 0.2098 → 0.1866 |
| never-rate (lower is better) | 0.2097 → 0.3583 | 0.2917 → 0.3500 | 0.3950 → 0.4250 |
| lookalike rate (lower is better) | 0.05 → 0.25 | 0.15 → 0.25 | 0.10 → 0.25 |
| needle recall | 0.60 → 0.55 | 0.65 → 0.65 | 0.65 → 0.45 |
| recall at retrieval (control) | 0.3889 → 0.3889 | 0.4195 → 0.4195 | 0.3211 → 0.3211 |

Pooled over the 30 persona-snapshot pairs: recall@12 0.2249 → 0.2457 (the matrix's clean runs on main and here), never-rate
0.2988 → 0.3778. Retrieval recall is identical, which is the control: only scoring changed.

## 4. Re-recorded baseline, and what the degradation matrix says

    EVAL_OFFLINE=1 python -m evals.run --runner prod --all-snapshots   # 934fa6e-prod-llm-*.json
    # baseline-prod-llm.json rebuilt from those three scorecards
    EVAL_OFFLINE=1 python -m pytest tests/test_eval_gate.py   # 3 passed, 4 skipped, 59 subtests
    cd backend && EVAL_OFFLINE=1 python -m evals.degrade --write   # at 9d1699a0, git_dirty false

The pre-registered faults in `evals/degrade.py` were all met on the positional build. On the
keyed build 4 of 9 miss their declared targets: `rotate_verdicts`, `all_relevant`,
`swap_labels`, `no_diversity`. With 90% of articles on the fallback, faults that act on model
verdicts have little to act on, so the metrics stop detecting them. The declarations and their
pinned sha256 are unchanged, so `tests/test_eval_degradation.py` fails 4 cases. That is the
only failing backend test: 4 failed, 2,768 passed, 185 skipped (`EVAL_OFFLINE=1 pytest tests/`).

## 5. What it cost

    89 new cache entries: 392,061 input tokens, 165,270 output tokens, $0.158 at the rates above.

30 responses came from the OpenAI API. Then the account returned 429 `insufficient_quota`
("You have no credits remaining"), and the other 59 came through the Vercel AI Gateway with
the same model name and request bytes, so every cache key is what production sends. Each live
process ran under `Meter` with a $1.00 cap. The first cap fired after $0.058 of real spend,
because `Meter` also charges replayed cache hits (every retry of a refused batch) at list price.
Production's Fly logs show the same 429 on embeddings, so production's LLM path is currently
falling back on every call, whichever scorer is deployed.
