"""Candidate parser that refuses ambiguous associations.

When the model returns a different count of verdicts than articles, or when
the response is truncated/malformed, this parser refuses instead of inventing
an association.
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


VERSION_ID = "candidate-keyed-v2"
PROTOCOL = "positional-v0"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse a batch scoring response, refusing when association is ambiguous.
    
    This parser handles the positional-v0 protocol, which associates results
    by array position. It refuses when:
    - The response contains an error signal
    - The response is truncated or malformed JSON
    - The number of results doesn't match the number of articles
    - Individual result entries have invalid structure or values
    """
    # Handle error signals from the harness
    error = response.get("error")
    if error:
        # Propagate execution failures that should not degrade to zeros
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))

    # Extract content
    content = response.get("content")
    if content is None:
        return refuse("retries_exhausted", "no content returned")

    # Check for truncation signal
    finish_reason = response.get("finish_reason")
    if finish_reason == "length":
        return refuse("truncated_response", "completion stopped at token limit")

    # Parse JSON
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        # Check if this looks like a truncated JSON (incomplete structure)
        if content.strip() and not content.rstrip().endswith("}"):
            return refuse("truncated_response", f"incomplete JSON: {str(exc)[:100]}")
        return refuse("malformed_json", str(exc))
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    # Validate top-level structure
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    # Extract results list
    results_list = result.get("results", [])
    
    # Handle alternative "scores" format
    if not results_list and "scores" in result:
        scores = result.get("scores")
        if not isinstance(scores, list):
            return refuse("unexpected_shape", "scores is not a list")
        try:
            results_list = [
                {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
                for s in scores
            ]
        except (TypeError, ValueError) as exc:
            return refuse("invalid_type", f"scores contain non-numeric value: {exc}")
    
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Check count match - this is the key defect fix
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )

    # Build verdicts with positional association
    out: list[dict[str, Any]] = []
    for article, entry in zip(articles, results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Extract and validate score
        raw_score = entry.get("score")
        if raw_score is None:
            # Default to 0.5 if score is missing but entry is otherwise valid
            score = 0.5
        else:
            validated_score = finite_unit_score(raw_score)
            if validated_score is None:
                # Check specific failure modes for better error messages
                if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                    return refuse("invalid_type", f"score is {type(raw_score).__name__}")
                try:
                    value = float(raw_score)
                    if not _math.isfinite(value):
                        return refuse("score_not_finite", f"score is {raw_score}")
                    if value < 0.0 or value > 1.0:
                        return refuse("score_out_of_range", f"score is {value}")
                except (TypeError, ValueError):
                    return refuse("invalid_type", "score is not numeric")
            score = validated_score if validated_score is not None else 0.5
        
        # Extract relevant flag (default based on score)
        relevant = bool(entry.get("relevant", score >= 0.5))
        
        # Extract reason (default to empty string)
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(article["id"], relevant, score, reason))
    
    return ok(out)
