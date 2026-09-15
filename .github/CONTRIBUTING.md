# Contributing to Daily

Thanks for looking. A few things about this project shape how changes land.

## The one rule: feed quality is measured, not argued

Daily's whole point is deciding which stories a person actually needs. That is a
claim you can be wrong about, so the repository carries an evaluation harness
(`backend/evals/`, "S0") built specifically to answer *did this change make the
feed better or worse, and if a story went missing, which stage lost it?*

If your change touches ingestion, understanding, retrieval, ranking, or assembly,
the diff is only half the work. The other half is the scorecard.

```bash
cd backend
EVAL_OFFLINE=1 python -m evals.run --runner prod --snapshot 2026-08-31
python -m evals.compare --latest prod-llm 2026-08-31
```

`EVAL_OFFLINE=1` means every model call is replayed from the committed cache, so
this costs nothing and returns the same answer every time. See
[`backend/evals/README.md`](../backend/evals/README.md) for what each metric means.

## Getting set up

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # fill in DATABASE_URL and OPENAI_API_KEY
uvicorn app.main:app --reload --port 8080
```

For the iOS app, open `Daily.xcodeproj` in Xcode 16+ (iOS 17 deployment target),
sign the target with your own team and bundle ID, and point `AppConfig.swift` or the
`DAILY_BACKEND_URL` Info.plist key at your backend.

## Before you open a pull request

```bash
cd backend
EVAL_OFFLINE=1 python -m pytest tests/ -q            # what CI runs
EVAL_OFFLINE=1 python -m pytest tests/test_eval_gate.py   # the regression gate
```

CI additionally runs the Postgres contract suites against a disposable
`pgvector/pgvector:0.8.0-pg16` service, and rejects runs where a required
deterministic test was skipped rather than executed. A suite that silently
skips is treated as a failure, not a pass.

If you changed a prompt, a model, or batch composition, cache keys change and the
gate will fail with `CacheMiss`. Re-warm it with an API key and commit the result:

```bash
python -m evals.run --runner prod --all-snapshots
python -m evals.llm_cache gc     # drop entries no scorecard references
```

## Conventions

**Commits** use `type: short description`, lower case, imperative:

| Type | For |
|---|---|
| `feat` | new user-facing behaviour |
| `fix` | a bug fix |
| `refactor` | restructuring with no behaviour change |
| `perf` | a measured performance improvement |
| `docs` | documentation only |
| `test` | tests only |
| `chore` / `build` / `ci` | tooling, dependencies, pipelines |

**Feature gates.** New pipeline stages ship dark. Add the env var to
`backend/.env.example` defaulting to `false`, with a comment saying what evidence
is required before it may be turned on. Nothing personalization-related should
become live because a default changed.

**Two product rules that are not negotiable**, because they are what makes Daily
feel different from a news aggregator:

1. **Never expose scoring.** No match percentages, no "because you read X"
   receipts, no ranking internals in the UI. Provenance appears only when it is
   rare and high-confidence. The personalization should be felt, not displayed.
2. **Never put a model call in the hot path.** Personalization is batch-first. The
   edition a reader opens is pre-built and cached. Latency and cost are features.

**SwiftUI.** Prefer `@State` / `@Binding` / `@Observable` / `@Environment` over view
models where plain value state will do, keep views small and composed, load with
`.task` rather than in `body`, and never reach for `AnyView` to paper over a type
mismatch. The full house style is in [`AGENTS.md`](../AGENTS.md).

**Design changes** must trace back to [`docs/DESIGN.md`](../docs/DESIGN.md), which is
the visual source of truth — color tokens, type scale, motion timings, and the
one-signature-element-per-surface rule.

## Documentation layout

| Path | What lives there |
|---|---|
| [`docs/DESIGN.md`](../docs/DESIGN.md) | The design system |
| [`docs/architecture/`](../docs/architecture/) | How the system is meant to work, and why |
| [`docs/stages/`](../docs/stages/) | Per-stage audits, plans, and honest status |
| [`docs/notes/`](../docs/notes/) | Working notes and session logs |
| [`AGENTS.md`](../AGENTS.md) | House style, also read by coding agents |
