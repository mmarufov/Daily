"""Candidate parser that refuses when association is ambiguous.

This parser addresses the defect where positional-v0 silently misassociates
verdicts when counts differ or responses are reordered. It:
1. Detects truncated JSON responses via finish_reason
2. Refuses on count mismatches instead of padding with zeros
3. Supports keyed-v2 protocol for explicit article_id matching
4. Validates scores are finite and in range [0, 1]
"""

from __future__ import annotations

# --- contract prelude -------------------------------------------------------
# Inlined from lab/contract/types.py. These must match exactly.

import math as _math


def ok(verdicts):
    return {"ok": True, "verdicts": verdicts}


def refuse(kind, detail=""):
    return {"ok": False, "refusal": {"kind": kind, "detail": str(detail)[:400]}}


def verdict(article_id, relevant, score, reason):
    return {
        "article_id": article_id,
        "relevant": bool(relevant),
        "score": float(score),
        "reason": str(reason)[:500],
    }


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
    """Parse response with explicit refusal on ambiguous associations."""
    
    # Handle execution failures
    error = response.get("error")
    if error:
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))

    # Check for content
    content = response.get("content")
    if content is None:
        return refuse("retries_exhausted", "no content returned")

    # Check for truncation before parsing
    finish_reason = response.get("finish_reason")
    if finish_reason == "length":
        return refuse("truncated_response", "response was truncated due to length")

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
    if not results_list and "scores" in result:
        # Handle alternative format with just scores
        try:
            results_list = [
                {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
                for s in result["scores"]
            ]
        except Exception:
            return refuse("invalid_type", "scores is not a list of numbers")
    
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Check count match - this is critical for refusing ambiguous associations
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )

    # Build article ID map for keyed association
    article_map = {a["id"]: a for a in articles}
    
    # Try to parse as keyed protocol first (with article_id in each result)
    has_article_ids = all(
        isinstance(entry, dict) and "article_id" in entry 
        for entry in results_list
    )
    
    if has_article_ids:
        # Use keyed association
        return _parse_keyed(articles, results_list, article_map)
    else:
        # Use positional association (but only if counts match, which we verified above)
        return _parse_positional(articles, results_list)


def _parse_keyed(
    articles: list[dict[str, Any]], 
    results_list: list[Any],
    article_map: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Parse with explicit article_id keys."""
    
    # Check for duplicate IDs
    result_ids = [entry.get("article_id") for entry in results_list]
    if len(result_ids) != len(set(result_ids)):
        return refuse("duplicate_id", "duplicate article_id in results")
    
    # Check for unknown IDs
    unknown_ids = set(result_ids) - set(article_map.keys())
    if unknown_ids:
        unknown_sample = list(unknown_ids)[:3]
        return refuse("unknown_id", f"unknown article_id: {unknown_sample}")
    
    # Check for missing IDs
    missing_ids = set(article_map.keys()) - set(result_ids)
    if missing_ids:
        missing_sample = list(missing_ids)[:3]
        return refuse("missing_id", f"missing article_id: {missing_sample}")
    
    # Build verdicts in the order of input articles
    out: list[dict[str, Any]] = []
    result_map = {entry["article_id"]: entry for entry in results_list}
    
    for article in articles:
        article_id = article["id"]
        entry = result_map[article_id]
        
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Parse score with validation
        score_raw = entry.get("score")
        score = finite_unit_score(score_raw)
        if score is None:
            if score_raw is None:
                score = 0.5  # Default when missing
            elif isinstance(score_raw, (int, float)):
                value = float(score_raw)
                if not _math.isfinite(value):
                    return refuse("score_not_finite", f"score is {value}")
                if value < 0.0 or value > 1.0:
                    return refuse("score_out_of_range", f"score is {value}")
                score = max(0.0, min(1.0, value))  # Defensive clamp
            else:
                return refuse("invalid_type", "score is not numeric")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(article_id, relevant, score, reason))
    
    return ok(out)


def _parse_positional(
    articles: list[dict[str, Any]], 
    results_list: list[Any]
) -> dict[str, Any]:
    """Parse with positional association (count already verified to match)."""
    
    out: list[dict[str, Any]] = []
    
    for article, entry in zip(articles, results_list):
        article_id = article["id"]
        
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Parse score with validation
        score_raw = entry.get("score")
        score = finite_unit_score(score_raw)
        if score is None:
            if score_raw is None:
                score = 0.5  # Default when missing
            elif isinstance(score_raw, (int, float)):
                value = float(score_raw)
                if not _math.isfinite(value):
                    return refuse("score_not_finite", f"score is {value}")
                if value < 0.0 or value > 1.0:
                    return refuse("score_out_of_range", f"score is {value}")
                score = max(0.0, min(1.0, value))  # Defensive clamp
            else:
                return refuse("invalid_type", "score is not numeric")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(article_id, relevant, score, reason))
    
    return ok(out)
