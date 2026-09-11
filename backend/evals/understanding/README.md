# S3 evaluation evidence

`review_queue.json` contains 600 distinct frozen articles awaiting independent
adjudication. It is sampling metadata, not ground truth. Reviewers must establish
facets, language, evidence eligibility, and same-development story membership
before splitting. The evaluator rejects incomplete labels, leaked story groups,
and unsupported predictions. Unknown outcomes remain in recall denominators.

`acceptance.json` defines targets, not achieved results. The user authorized a
USD 5 aggregate pilot; benchmark and production spending remain unset.

## Capped operational pilot

From the workspace root, an authorized paid run is:

```sh
backend/venv/bin/python backend/scripts/pilot_s3_understanding.py --paid --budget-usd 5
```

Omit `--paid` to replay the cache without provider requests. The script uses
`OPENAI_API_KEY` from the environment or `backend/.env` (`--env-file` overrides
the file path). Credentials and provider response error text are never printed.
There is no production database connection or model promotion.

The default sample is 20 deterministic, distinct articles from the verified
2026-09-02 snapshot, distributed across source/language/evidence buckets. Only
snapshot titles and summaries are submitted: legacy body text has no verified
S2 provenance. Each article gets both pinned classifier calls and one shared
embedding call. This measures bounded transport, contract outcomes and spend;
it does not establish semantic accuracy, entity resolution quality, clustering,
or production readiness.

Results persist after every request in `.context/s3/pilot.json`, and responses
and failures replay from `.context/s3/pilot-cache`. These are private artifacts.
The separate fixed `.context/s3/pilot-ledger/pilot-budget.json` reserves before
submission and reconciles actual usage. Changing output/cache paths, sample
size, or restarting cannot reset the cap. The budget cannot increase beyond
USD 5 or change within an existing ledger. No retry is automatic. A crash or
unknown bill keeps its reservation and blocks duplicate paid submission pending
operator reconciliation. Do not delete the ledger to recover from an error.

`usage_usd` in a replayed result is historical request cost, not new spend.
The report's durable `budget.spent_usd` and `reserved_usd` describe aggregate
billing and outstanding worst-case charges. `contract_valid` means that the
provider adapter accepted the response, not that an independent reviewer found
its classifications correct. Cache latency is explicitly marked and must not
be used as provider latency evidence.
