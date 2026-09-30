"""Keyed protocol parser (keyed-v2) that associates verdicts by article_id.

This parser fixes the positional association defect by requiring each result
to explicitly identify its article via article_id, enabling unambiguous
association regardless of result order.
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
    """Parse response using keyed association by article_id.
    
    Each result entry must contain an 'article_id' field that matches one of the
    input articles. This enables unambiguous association regardless of result order.
    """
    # Handle error responses
    error = response.get("error")
    if error:
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))

    # Get content
    content = response.get("content")
    if content is None:
        return refuse("truncated_response", "no content returned")

    # Parse JSON
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    # Validate top-level structure
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    # Get results list
    results_list = result.get("results", [])
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Handle legacy "scores" format by converting to keyed format
    if not results_list and "scores" in result:
        scores = result["scores"]
        if not isinstance(scores, list):
            return refuse("unexpected_shape", "scores is not a list")
        if len(scores) != len(articles):
            return refuse("count_mismatch", f"{len(scores)} scores for {len(articles)} articles")
        # Convert legacy scores to keyed results using positional mapping
        results_list = [
            {"article_id": article["id"], "relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for article, s in zip(articles, scores)
        ]

    # Check count match
    if len(results_list) != len(articles):
        return refuse("count_mismatch", f"{len(results_list)} results for {len(articles)} articles")

    # Build expected ID set from input articles
    expected_ids = {article["id"] for article in articles}
    
    # Process results and validate keyed association
    verdicts = []
    seen_ids = set()
    
    for entry in results_list:
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Extract article_id
        article_id = entry.get("article_id")
        if article_id is None:
            return refuse("missing_id", "result entry missing article_id field")
        
        # Validate article_id is a string
        if not isinstance(article_id, str):
            return refuse("invalid_type", "article_id is not a string")
        
        # Check for duplicates
        if article_id in seen_ids:
            return refuse("duplicate_id", f"duplicate article_id: {article_id}")
        seen_ids.add(article_id)
        
        # Check article_id is in expected set
        if article_id not in expected_ids:
            return refuse("unknown_id", f"unknown article_id: {article_id}")
        
        # Extract and validate score
        score_raw = entry.get("score", 0.5)
        score = finite_unit_score(score_raw)
        if score is None:
            return refuse("score_out_of_range", f"invalid score: {score_raw}")
        
        # Extract relevant (default based on score)
        relevant_raw = entry.get("relevant")
        if relevant_raw is None:
            relevant = score >= 0.5
        elif isinstance(relevant_raw, bool):
            relevant = relevant_raw
        else:
            return refuse("invalid_type", f"relevant is not boolean: {type(relevant_raw).__name__}")
        
        # Extract reason
        reason = entry.get("reason", "")
        if not isinstance(reason, str):
            reason = str(reason)
        
        verdicts.append(verdict(article_id, relevant, score, reason))
    
    # Check all expected IDs were present
    missing = expected_ids - seen_ids
    if missing:
        return refuse("missing_id", f"missing results for articles: {sorted(missing)}")
    
    return ok(verdicts)
