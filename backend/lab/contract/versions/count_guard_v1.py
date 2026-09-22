"""The count-mismatch guard, transcribed from PR #59 (head 81b2019).

Source: backend/app/services/openai_service.py on
`mmarufov/batch-scoring-alignment`:

    if len(results_list) != len(articles):
        logger.warning("... discarding the batch rather than assigning "
                       "verdicts by position")
        continue                              # retry, then report unscored

That commit also stops swallowing the harness's stop signals:

    except Exception as exc:
        if type(exc).__name__ in {"CacheMiss", "BudgetExceeded"}:
            raise

Both are reproduced. The guard is a real improvement over positional-v0 and
this experiment is expected to show that — and also to show its ceiling: it
compares *lengths*, so an equal-length reordered response still passes through
and is still associated by position.
"""

from __future__ import annotations

# --- contract prelude -------------------------------------------------------
# Inlined rather than imported. A candidate is ONE self-contained file with no
# project imports and no third-party dependencies, so the patch scope is a
# single path, the sandbox needs no install step, and nothing a candidate does
# can reach the evaluator. The canonical definitions live in
# lab/contract/types.py, and tests/test_contract_prelude.py asserts that every
# copy still agrees with it.

import math as _math


def ok(verdicts):
    return {"ok": True, "verdicts": verdicts}


def refuse(kind, detail=""):
    return {"ok": False, "refusal": {"kind": kind, "detail": str(detail)[:400]}}


def verdict(article_id, relevant, score, reason):
    return {"article_id": article_id, "relevant": bool(relevant),
            "score": float(score), "reason": str(reason)[:500]}


def finite_unit_score(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not _math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value
# --- end prelude ------------------------------------------------------------

import json
from typing import Any


VERSION_ID = "count-guard-v1"
PROTOCOL = "positional-v0"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    error = response.get("error")
    if error:
        # CacheMiss / BudgetExceeded propagate instead of degrading to zeros.
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))

    content = response.get("content")
    if content is None:
        return refuse("retries_exhausted", "no content returned")

    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    results_list = result.get("results", [])
    if not results_list and "scores" in result:
        results_list = [
            {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for s in result["scores"]
        ]
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )

    out: list[dict[str, Any]] = []
    for article, entry in zip(articles, results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        try:
            score = max(0.0, min(1.0, float(entry.get("score", 0.5))))
        except Exception:
            return refuse("invalid_type", "score is not numeric")
        relevant = bool(entry.get("relevant", score >= 0.5))
        out.append(verdict(article["id"], relevant, score, str(entry.get("reason", ""))))
    return ok(out)
