# Daily — documentation

Daily is built as a chain of numbered stages. Each one has three documents written in
this order: an **audit** that challenges the existing design and states what is
actually broken, an **implementation plan** that commits to a specific fix, and a
**status** file that records what landed and what is still open.

The audits are deliberately unflattering. They exist so that decisions are traceable
to evidence rather than to taste.

## Start here

| Document | Read it for |
|---|---|
| [`architecture/systems.md`](architecture/systems.md) | **The best single overview.** The whole app described as ten systems, with the contract each one owes the next. |
| [`DESIGN.md`](DESIGN.md) | The visual source of truth — color tokens, type scale, motion timings, provenance rules. Referenced by name from the SwiftUI components. |
| [`../backend/evals/README.md`](../backend/evals/README.md) | How feed quality is measured, and the numbers it currently reports. |

## Architecture

| Document | Scope |
|---|---|
| [`architecture/systems.md`](architecture/systems.md) | The app as ten systems |
| [`architecture/bulletproof-architecture-plan.md`](architecture/bulletproof-architecture-plan.md) | Verified findings across the whole architecture, with a phased hardening plan. The most heavily fact-checked document here. |
| [`architecture/filtering-architecture-plan.md`](architecture/filtering-architecture-plan.md) | The news filtering architecture, and the absolute quality targets the eval gate checks against (§9) |
| [`architecture/source-architecture.md`](architecture/source-architecture.md) | How sources are discovered, scored, and kept |
| [`architecture/stage-a-global-pool-spec.md`](architecture/stage-a-global-pool-spec.md) | Global article pool and scalable retrieval |
| [`architecture/personalization-audit.md`](architecture/personalization-audit.md) | Why the feed didn't work — the audit that started the rebuild |
| [`architecture/design-redesign-plan.md`](architecture/design-redesign-plan.md) | The whole-app design redesign that produced `DESIGN.md` |

## Stages

| Stage | What it owns | Audit | Plan | Status |
|---|---|---|---|---|
| **S0** | Evaluation — the ruler everything else is measured with | [`backend/evals/README.md`](../backend/evals/README.md) | — | — |
| **S1** | Sources and ingestion | [audit](stages/s1-ingestion-audit.md) | — | — |
| **S2** | Article content, provenance, and reading rights | [audit](stages/s2-content-pipeline-audit.md) | — | — |
| **S3** | Article understanding — topics and structured meaning | [audit](stages/s3-understanding-audit.md) | [plan](stages/s3-implementation-plan.md) | [status](stages/s3-implementation-status.md) |
| **S4** | Event detection — clustering stories into events by gravity | [audit](stages/s4-event-detection-audit.md) | [plan](stages/s4-implementation-plan.md) | [status](stages/s4-implementation-status.md) |
| **S5** | Reader model — the durable profile of a person | [audit](stages/s5-reader-model-audit.md) | [plan](stages/s5-implementation-plan.md) | [status](stages/s5-implementation-status.md) |
| **S6** | Retrieval — getting the right candidates in front of the ranker | [audit](stages/s6-retrieval-audit.md) | [plan](stages/s6-implementation-plan.md) | [status](stages/s6-implementation-status.md) |
| **S7** | Ranking — judging candidates against a reader | [audit](stages/s7-ranking-audit.md) | [plan](stages/s7-implementation-plan.md) | [status](stages/s7-implementation-status.md) |
| **S8** | Edition assembly — turning a ranking into an edition | [audit](stages/s8-edition-assembly-audit.md) | [plan](stages/s8-implementation-plan.md) | [status](stages/s8-implementation-status.md) |
| **S9** | Delivery and reading | [audit](stages/s9-delivery-audit.md) | [plan](stages/s9-implementation-plan.md) | [status](stages/s9-implementation-status.md) |
| **S10** | Learning — folding reading behaviour back into the profile | [audit](stages/s10-learning-audit.md) | [plan](stages/s10-implementation-plan.md) | [status](stages/s10-implementation-status.md) |

One extra note worth reading on its own:
[`stages/s6-lexical-cache-limitation.md`](stages/s6-lexical-cache-limitation.md) — the real
reliability limitation in lexical retrieval, and the several things it is commonly
mistaken for.

## Working notes

These are logs rather than specifications. They are kept because the reasoning behind a
decision is usually more useful later than the decision itself.

| Document | Scope |
|---|---|
| [`notes/plan.md`](notes/plan.md) | The active plan and its checklist |
| [`notes/lessons.md`](notes/lessons.md) | Mistakes worth not repeating, and the rule each one produced |
| [`notes/session-summary-2026-09-02.md`](notes/session-summary-2026-09-02.md) | What S0 and S1 Phase 0 actually delivered |

## Conventions

House style for both humans and coding agents is in [`../AGENTS.md`](../AGENTS.md);
contribution mechanics are in [`../.github/CONTRIBUTING.md`](../.github/CONTRIBUTING.md).
