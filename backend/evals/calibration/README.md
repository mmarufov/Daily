# Judge calibration

Human adjudication of the two-pass label judge (`evals/label.py` bootstrap), scored
by `evals/calibration.py`. Each dated directory is one fixed sample.

`2026-09-29/` was drawn and committed before any human answer existed, so the
sample cannot have been chosen after seeing results. `adjudications.jsonl` is
the only file a human writes. Everything in `report.*` is recomputed from it.

```sh
cd backend
python -m evals.calibration sample --out evals/calibration/2026-09-29 --seed 20260929   # reproduces the draw byte for byte
python -m evals.calibration review --out evals/calibration/2026-09-29 --reviewer <name> # interactive terminal only
python -m evals.calibration score  --out evals/calibration/2026-09-29                   # refuses below --min-reviewed (100)
```

Only rows whose exact judge prompt can be rebuilt and matched to a cached
`messages_sha256` in `evals/.cache/llm` are eligible, so the reader profile and
article text shown are byte-identical to what the judge was sent. The judge saw
five articles per request; the reviewer sees one.

Strata are judge verdict x review path (`pass1_only`, `escalated` where both
passes agreed, `contested` where they did not). `report.md` gives the plain
sample statistics and population-weighted estimates, which weight each stratum
by population / reviewed. The sample statistics describe a hard-case-enriched
sample, not the whole label set.
