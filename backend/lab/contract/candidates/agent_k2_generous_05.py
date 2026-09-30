"""Keyed association parser - fixes the positional association defect.

The defect: positional-v0 and count_guard_v1 both associate results[i] with articles[i].
When the model returns results in a different order, or returns a different number of them,
articles receive wrong verdicts silently.

The fix: Use keyed association where each result includes an article_id field.
This enables unambiguous association and detects duplicates, unknown IDs, and missing IDs.
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


VERSION_ID = "keyed-v2"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse response using keyed association when article_id is present.
    
    Keyed association (preferred): Each result has an article_id field.
    - Validates exact match of article IDs
    - Detects duplicates, unknown IDs, missing IDs
    - Unambiguous even if results are reordered
    
    Positional fallback: Only when no article_id fields are present.
    - Requires exact count match
    - Associates by position (results[i] -> articles[i])
    """
    error = response.get("error")
    if error:
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

    # Extract results list
    results_list = result.get("results", [])
    if not results_list and "scores" in result:
        # Legacy scores format - convert to results dicts
        results_list = [
            {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for s in result["scores"]
        ]
    
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Build set of expected article IDs
    expected_ids = {a["id"] for a in articles}

    # Check if any result has article_id field
    has_keyed_results = any(
        isinstance(r, dict) and r.get("article_id") is not None 
        for r in results_list
    )

    if has_keyed_results:
        # Keyed association: use article_id for unambiguous matching
        return _keyed_association(articles, expected_ids, results_list)
    else:
        # Positional fallback: only when no article_id present
        return _positional_association(articles, results_list)


def _keyed_association(articles: list[dict[str, Any]], expected_ids: set[str], results_list: list) -> dict[str, Any]:
    """Associate results using article_id fields."""
    result_by_id: dict[str, dict] = {}
    
    for entry in results_list:
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        article_id = entry.get("article_id")
        if article_id is None:
            # Mixed keyed/non-keyed is ambiguous - refuse
            return refuse("unexpected_shape", "mixed entries with and without article_id")
        
        if article_id in result_by_id:
            return refuse("duplicate_id", f"duplicate article_id: {article_id}")
        
        if article_id not in expected_ids:
            return refuse("unknown_id", f"unknown article_id: {article_id}")
        
        result_by_id[article_id] = entry
    
    # Check for missing IDs
    missing_ids = expected_ids - set(result_by_id.keys())
    if missing_ids:
        return refuse("missing_id", f"missing article_ids: {sorted(missing_ids)}")
    
    # Build verdicts in article order
    out: list[dict[str, Any]] = []
    for article in articles:
        article_id = article["id"]
        entry = result_by_id[article_id]
        
        # Validate and extract score
        score_raw = entry.get("score")
        score = finite_unit_score(score_raw)
        if score is None:
            return refuse("score_out_of_range", f"invalid score for {article_id}: {score_raw}")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(article_id, relevant, score, reason))
    
    return ok(out)


def _positional_association(articles: list[dict[str, Any]], results_list: list) -> dict[str, Any]:
    """Associate results by position - only used when no article_id present."""
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )
    
    out: list[dict[str, Any]] = []
    for article, entry in zip(articles, results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Validate and extract score
        score_raw = entry.get("score")
        # Use finite_unit_score if available, else clamp
        score = finite_unit_score(score_raw)
        if score is None:
            try:
                score = max(0.0, min(1.0, float(entry.get("score", 0.5))))
            except (TypeError, ValueError):
                return refuse("invalid_type", "score is not numeric")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(article["id"], relevant, score, reason))
    
    return ok(out)
