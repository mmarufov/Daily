## What this changes

<!-- One or two sentences. What behaviour is different after this merges? -->

## Why

<!-- The problem, bug report, or measurement that motivated it. Link the issue. -->

## How it was verified

<!-- Proof, not intent. Paste the failing-then-passing test, the log line, the
     scorecard diff, or the screenshot. "Should work" is not verification. -->

- [ ] `cd backend && EVAL_OFFLINE=1 python -m pytest tests/ -q` passes
- [ ] Touched a pipeline stage? The S0 eval gate still passes
      (`EVAL_OFFLINE=1 python -m pytest tests/test_eval_gate.py`)
- [ ] Touched the iOS app? It builds in Xcode and the affected previews render
- [ ] No secrets, tokens, or real user data in the diff

## Risk and rollback

<!-- What could this break, and how is it turned off? Name the feature flag or
     env var if the change is gated. -->
