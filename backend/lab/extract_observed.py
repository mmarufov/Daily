"""Extract real article-to-response pairs from Daily's committed recordings.

Nothing here is authored. Every case is a batch the production scorer actually
sent during an offline replay, paired with the response actually recorded for
it in `backend/evals/.cache/llm`.

How the pair is recovered
-------------------------
The recordings store `messages_sha256` and a 200-character preview, not the
articles, so the batch cannot be read back from the cache alone. Instead the
harness is replayed with two wrappers installed:

  * `score_articles_batch` publishes the batch it was handed into a
    `ContextVar`;
  * the cached client records `(messages, content, finish_reason, usage)` for
    every chat completion.

`asyncio.to_thread` copies the context, so the two correlate correctly even
though `feed_service` fans batches out concurrently behind a semaphore.

    python -m lab.extract_observed --snapshot 2026-09-02 --out lab/cases/observed.json

Run from `backend/` with `EVAL_OFFLINE=1`. No network, no provider key.
"""

from __future__ import annotations

import argparse
import contextvars
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

CURRENT_BATCH: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "lab_current_batch", default=None
)

MAX_ARTICLE_CHARS = 180


def _trim(article: dict[str, Any]) -> dict[str, Any]:
    """Keep only what a parser needs, so cases stay reviewable in a diff."""
    return {
        "id": str(article.get("id", "")),
        "title": str(article.get("title") or "")[:MAX_ARTICLE_CHARS],
        "source": str(article.get("source") or article.get("source_name") or "")[:80],
    }


def extract(snapshot: str, personas: list[str] | None, limit: int | None) -> list[dict[str, Any]]:
    os.environ.setdefault("EVAL_OFFLINE", "1")

    from app.services import openai_service as osvc
    from evals import openai_backend, run as eval_run

    records: list[dict[str, Any]] = []

    original_score = osvc.OpenAIService.score_articles_batch

    async def traced_score(self, articles, *args, **kwargs):  # type: ignore[no-untyped-def]
        token = CURRENT_BATCH.set(list(articles))
        try:
            return await original_score(self, articles, *args, **kwargs)
        finally:
            CURRENT_BATCH.reset(token)

    client = openai_backend.client()
    original_create = client.chat.completions.create

    def traced_create(**kwargs):  # type: ignore[no-untyped-def]
        response = original_create(**kwargs)
        batch = CURRENT_BATCH.get()
        if batch is None:
            return response
        try:
            choice = response.choices[0]
            content = choice.message.content
            finish_reason = getattr(choice, "finish_reason", None)
            usage = getattr(response, "usage", None)
            records.append(
                {
                    "articles": [_trim(a) for a in batch],
                    "content": content,
                    "finish_reason": finish_reason,
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "snapshot": snapshot,
                }
            )
        except Exception as exc:  # never let extraction corrupt the replay
            print(f"  ! could not record a batch: {exc}", file=sys.stderr)
        return response

    osvc.OpenAIService.score_articles_batch = traced_score  # type: ignore[assignment]
    client.chat.completions.create = traced_create  # type: ignore[assignment]
    try:
        eval_run.evaluate(
            "prod",
            snapshot,
            persona_keys=personas,
            k=12,
            needles=True,
            verbose=False,
            write=False,
        )
    finally:
        osvc.OpenAIService.score_articles_batch = original_score  # type: ignore[assignment]
        client.chat.completions.create = original_create  # type: ignore[assignment]

    return records[:limit] if limit else records


def classify(record: dict[str, Any]) -> dict[str, Any]:
    """Derive the expectation from the recording itself — never from an opinion.

    The only assertions made about an observed case are ones the recording can
    settle on its own:

      * a completion that stopped for `length`, or that is not valid JSON, has
        no recoverable association;
      * a response whose entry count differs from the batch size has no
        recoverable association either — which entry belongs to which article
        is not recorded anywhere, and guessing is the defect under study;
      * an equal-length response is *parseable*, and that is all. This suite
        never claims its positional association was semantically correct.
    """
    content = record.get("content")
    n_articles = len(record["articles"])

    if record.get("finish_reason") not in (None, "stop"):
        return {
            "expect": "refuse",
            "association": None,
            "refusal_kinds": ["truncated_response", "malformed_json"],
            "why": f"completion stopped for {record['finish_reason']!r}",
            "n_results": None,
        }

    try:
        parsed = json.loads(content or "")
        entries = parsed.get("results") if isinstance(parsed, dict) else None
        if not isinstance(entries, list):
            raise ValueError("no results array")
    except Exception:
        return {
            "expect": "refuse",
            "association": None,
            "refusal_kinds": ["malformed_json", "truncated_response", "unexpected_shape"],
            "why": "recorded response is not parseable as {results: [...]}",
            "n_results": None,
        }

    if len(entries) != n_articles:
        return {
            "expect": "refuse",
            "association": None,
            "refusal_kinds": ["count_mismatch"],
            "why": f"{len(entries)} verdicts recorded for {n_articles} articles",
            "n_results": len(entries),
        }

    return {
        "expect": "parse",
        # Deliberately null. The recording settles that the response is
        # readable; it cannot settle which article each verdict was about, and
        # guessing that is the defect under study.
        "association": None,
        "refusal_kinds": [],
        "why": "entry count matches the batch; association is parseable but unverified",
        "n_results": len(entries),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", default="2026-09-02")
    ap.add_argument("--persona", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "cases" / "observed.json"))
    args = ap.parse_args()

    print(f"replaying prod-llm against {args.snapshot} (offline) …")
    records = extract(args.snapshot, args.persona, args.limit)
    print(f"captured {len(records)} scoring batches")

    cases = []
    for index, record in enumerate(records):
        expectation = classify(record)
        cases.append(
            {
                "case_id": f"observed-{args.snapshot}-{index:03d}",
                "group": "observed",
                "origin": "recorded-replay",
                "protocol": "positional-v0",
                "snapshot": record["snapshot"],
                "articles": record["articles"],
                "response": {
                    "content": record["content"],
                    "finish_reason": record["finish_reason"],
                    "error": None,
                },
                "completion_tokens": record["completion_tokens"],
                # A truncated, malformed or miscounted response must be refused
                # by ANY parser, whatever protocol it speaks — so these cases
                # score every candidate. A parse expectation is protocol-bound:
                # only a parser that speaks positional-v0 can be asked to read a
                # positional-v0 response.
                "family": (
                    "universal-refusal"
                    if expectation["expect"] == "refuse"
                    else "protocol-association"
                ),
                "expectation": expectation,
            }
        )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_suite_version": 1,
        "group": "observed",
        "generated_from": "backend/evals/.cache/llm via offline replay",
        "snapshot": args.snapshot,
        "n_cases": len(cases),
        "cases": cases,
    }
    out.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"wrote {out} ({len(cases)} cases)")

    from collections import Counter
    print("expectations:", dict(Counter(c["expectation"]["expect"] for c in cases)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
