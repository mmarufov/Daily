"""
Robust batch scoring parser that refuses when association is ambiguous.

This parser addresses the positional association defect by:
1. Strictly validating response structure
2. Refusing when result count doesn't match article count
3. Validating score ranges and types
4. Only returning ok() when we have unambiguous complete association
"""

from __future__ import annotations

# --- contract prelude -------------------------------------------------------
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


VERSION_ID = "candidate-robust-v1"
PROTOCOL = "positional-v0"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """
    Parse batch scoring response and associate verdicts with articles.
    
    Returns ok(verdicts) only when we have a complete, unambiguous association.
    Returns refuse(kind, detail) when the response is malformed or ambiguous.
    """
    # Handle error responses from the harness
    error = response.get("error")
    if error:
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))
    
    # Get response content
    content = response.get("content")
    if content is None:
        return refuse("truncated_response", "no content returned")
    
    # Parse JSON
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        return refuse("malformed_json", str(exc))
    except Exception as exc:
        return refuse("malformed_json", str(exc))
    
    # Validate top-level structure
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")
    
    # Extract results list
    results_list = result.get("results", [])
    
    # Handle legacy "scores" format
    if not results_list and isinstance(result, dict) and "scores" in result:
        scores = result["scores"]
        if not isinstance(scores, list):
            return refuse("unexpected_shape", "scores is not a list")
        results_list = [
            {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for s in scores
        ]
    
    # Validate results is a list
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")
    
    # Check count mismatch - this is the key fix for the positional defect
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles"
        )
    
    # Process each result entry
    out: list[dict[str, Any]] = []
    for i, (article, entry) in enumerate(zip(articles, results_list)):
        # Validate entry is a dict
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry {i} is {type(entry).__name__}")
        
        # Extract and validate score using finite_unit_score
        raw_score = entry.get("score", 0.5)
        score = finite_unit_score(raw_score)
        if score is None:
            return refuse("score_out_of_range", f"entry {i} has invalid score: {raw_score}")
        
        # Extract relevant flag
        raw_relevant = entry.get("relevant")
        if raw_relevant is None:
            relevant = score >= 0.5
        elif not isinstance(raw_relevant, bool):
            return refuse("invalid_type", f"entry {i} relevant is not boolean")
        else:
            relevant = raw_relevant
        
        # Extract reason
        raw_reason = entry.get("reason", "")
        if not isinstance(raw_reason, str):
            reason = str(raw_reason)
        else:
            reason = raw_reason
        
        # Build verdict
        out.append(verdict(article["id"], relevant, score, reason))
    
    return ok(out)
