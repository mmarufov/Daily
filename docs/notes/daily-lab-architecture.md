# Daily Lab — architecture in one page

```
                                    THE TRUST BOUNDARY
                                            │
  UNTRUSTED  ─────────────────────────────  │  ───────────────────────────  TRUSTED
                                            │
  backend/lab/contract/*.py                 │   web/lib/lab/
    one self-contained file                 │     spec.ts       criteria, frozen + hashed
    stdlib only, no project imports         │     records.ts    zod schemas at the boundary
    parse(articles, response)               │     evaluator.ts  computes the verdict
         │                                  │     scope.ts      patch scope gate
         │  runs in                          │     runner.ts     where code may execute
         ▼                                  │     runstate.ts   durable event log
    vercel-sandbox   (anything novel)       │     artifact.ts   published schema
    local-known      (byte-exact committed) │
         │                                  │
         └──▶ prediction records (JSON) ────┼──▶  verdict ──▶ web/public/lab/*.json ──▶ /lab
                no field means "passed"     │
```

**Language and process are the boundary.** Candidate code is Python; the evaluator is TypeScript
in another process. There is no import a candidate could reach the evaluator through, and no
monkeypatch that would help.

**The record schema is the enforcement.** `PredictionRecordSchema` has `case_id`, `outcome`,
`association`, `refusal_kind`, `error`, `ms` — and nothing else. Zod strips unknown keys, so a
candidate emitting `{"passed": true}` produces a record that never contained it.

## The five components, and what each is actually for

| Vercel piece | Responsibility here | Status |
|---|---|---|
| **Next.js / TypeScript** | `/lab` and shareable per-run pages; the evaluator itself runs in this tier | live |
| **Vercel Blob** | the evidence artifacts the Lab is built on, published revision-scoped | live (existing integration) |
| **Vercel Sandbox** | isolated Python execution for any candidate that is not byte-identical to a committed one | implemented, **never invoked** — no `VERCEL_TOKEN`/team/project |
| **AI SDK / AI Gateway** | four typed investigator tools, one proposal, hard budget | implemented, **never invoked** — no `AI_GATEWAY_API_KEY`, no spending limit |
| **Durable orchestration** | append-only event log; recovery is a fold, publication idempotent on run id | implemented and **demonstrated** with a real SIGKILL |

The workflow piece is deliberately implemented as a plain event-sourced log rather than reached for
`@vercel/workflow` first: the property that matters is that state lives outside the process and
replay is total, and that is testable here without a deployment. Moving it onto Workflows is a
transport change, not a semantics change.

## Five invariants, each with a test that fails if it stops holding

| Invariant | Test |
|---|---|
| A candidate cannot grade itself | `lab-evaluator.test.ts` — doctored bundle, stripped keys, still rejected |
| Missing evidence is never acceptance | `lab-evaluator.test.ts` — missing record / crash / timeout → `incomplete`; vacuous criterion → `passed: false` |
| Association survives reordering | `test_lab_contract.py` — all **720** permutations, plus a negative control proving `positional-v0` is not invariant |
| Out-of-scope patches never execute | `lab-scope.test.ts` — 25 cases: traversal, symlink, absolute, NUL, backslash, forbidden areas |
| Interruption recovers, publication is idempotent | `lab-runstate.test.ts` — replay from every prefix converges; duplicate delivery cannot fork a final |

## Data flow, end to end

1. `extract_observed.py` replays the production runner offline, wrapping `score_articles_batch` and
   the cached client with a `ContextVar` so the batch and its recorded response correlate even
   under concurrent fan-out. 42 real cases.
2. `build_synthetic.py` emits 22 labelled fault injections with ground truth by construction.
3. `orchestrate.py` persists an event log, runs `harness.py` in a subprocess, and can be killed at
   any point; the next invocation folds the log and continues.
4. `harness.py` imports the candidate by path, runs every case under a per-case alarm, and projects
   whatever came back onto the fixed record shape.
5. `export-lab.ts` evaluates the records with the trusted evaluator, builds a validated artifact per
   run plus a manifest with sha256 and byte counts, and writes `web/public/lab/`.
6. `/lab` renders the committed artifacts. No Python runs at request time.
