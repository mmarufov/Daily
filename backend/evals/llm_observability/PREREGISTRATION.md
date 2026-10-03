# LLM observability: pre-registration

Committed before any code that measures it exists, and before any measured run against
the replay or production. The thresholds live in
[`app/services/llm_health_policy.json`](../../app/services/llm_health_policy.json), which
`/llmz` loads at runtime. A test pins that file's SHA-256, so a threshold cannot move after a
result is seen without the test failing.

## The incident this answers

On 2026-10-02, read-only SQL against production found 0 of 4,504 eligible articles (those with
extracted `analysis_text`, ingested in the 14-day retention window) carrying an embedding.
`generate_embedding` catches every exception, logs a warning and returns `None`, and the
ingestion loop skips the row and retries it next tick. `/healthz` returned `"status":"ok"`
throughout. The OpenAI account has returned `429 insufficient_quota` since about
2026-09-30 19:40Z, but the missing vectors predate that, so the earlier cause is unknown until
`fly logs` are read.

## Metrics

Every OpenAI SDK call made through `OpenAIService.client` writes one row to `llm_calls`:
time, job, operation, model, a SHA-256 of the request (never its text), input and output
tokens, cost at the policy's per-token rates, latency, outcome, a fallback flag and the git
SHA. Outcomes are `ok`, `rate_limited`, `insufficient_quota`, `timeout`, `parse_error`,
`schema_invalid` and `other_error`.

The fallback flag is set only where the application swallows a failure and serves something
else (a `None` vector, keyword scores, a heuristic profile, a placeholder). The wrapper that
records the call cannot see that decision, so a site that swallows without tagging is
invisible to the fallback signal. The coverage signal exists for that case.

**Fallback signal.** Per job, over the last `window_minutes` (30): `fallbacks / calls`.
It trips when a job has at least `min_calls` (20) calls and the rate exceeds `max_rate`
(0.20). A job below 20 calls is reported as insufficient data, not as healthy or tripped.

**Embedding coverage signal.** Computed from `articles`, not from traces, so it sees a
failure even when no call is traced. Eligible: `analysis_text` is not null and `ingested_at`
falls between 24 hours and 60 minutes ago. Missing: eligible with `embedding` null or
`embedding_content_version` different from `analysis_content_version`. It trips when at
least `min_missing` (20) are missing and missing / eligible exceeds `max_missing_share`
(0.20).

**`/llmz`.** 200 when no signal trips. 503 when any signal trips, and 503 when the signals
cannot be evaluated (database error, missing table), because a monitor that cannot look must
not report healthy. `/healthz` is unchanged: Fly routes traffic on it.

## Replay: expected results

The replay runs the real `OpenAIService.generate_embedding` and the real ingestion embedding
step, with the real `openai==1.12.0` SDK over an `httpx.MockTransport`. From the switch
onward every request gets HTTP 429 with OpenAI's `insufficient_quota` error body. The clock
is frozen and advanced in 3-minute ticks (the ingestion loop's sleep). Each tick ingests
10 eligible articles, then the real embedding step attempts every pending article up to its
limit of 50, so failing ticks retry a growing backlog. Ticks start at 18:40Z and the switch
is at 19:40Z. The database is real PostgreSQL.

| Checkpoint | Expected `/llmz` | Why |
|---|---|---|
| 19:39Z | 200 | about 100 calls in the window, 0 fallbacks; coverage 0 missing |
| first 503 | between 19:40Z and 19:50Z | fallback rate passes 0.20 once three failing ticks are in the window |
| 20:10Z | 503, ingestion fallback rate 1.0 | the window holds only failing calls |
| coverage first trips | between 20:40Z and 21:10Z | 200 embedded before the switch dilute the share until about 60 are missing past the 60-minute grace |

Negative controls, each expected to change the result:

1. **Tagging removed** (the swallow site no longer marks the fallback): `/llmz` stays 200 at
   20:10Z, because only the coverage signal can see the failure, and it has not tripped yet.
   The main assertion (503 at 20:10Z) fails under this control.
2. **No switch** (every call succeeds): 200 at every checkpoint, both signals clear.
3. **Too few calls** (fewer than 20 calls in the window, all failing): the fallback signal
   reports insufficient data and does not trip.
4. **Unevaluable** (the `llm_calls` table is missing): 503.

## Production predictions

Recorded before the first deploy of this code:

1. Before embeddings are restored, `/llmz` returns 503 with the ingestion fallback rate at
   or above 0.99 and the coverage signal tripped with a missing share at or above 0.99.
2. After embeddings are restored, `/llmz` returns 200 between 30 and 90 minutes later: the
   30-minute fallback window has to age out, and the embedding step takes the newest eligible
   articles first, 50 per tick, so the last day's backlog clears in a few ticks.
3. `count(embedding)` over `articles` rises from 0 within one ingestion tick of the restore.
4. Embedding the 4,503-article backlog costs about $0.05 at $0.02 per million tokens
   (estimate: about 550 tokens per article). The traced token counts replace this estimate.

If a prediction fails, the result is reported as it came out. The thresholds are not tuned
after any measured run.
