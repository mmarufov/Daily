"""Keyed association parser - matches verdicts to articles by article_id.

This parser implements the keyed-v2 protocol where each result entry must contain
an article_id field. Association is performed by matching IDs rather than by
array position, which eliminates the positional association defect.

The parser refuses when:
- JSON is malformed
- Response has unexpected shape
- Results count doesn't match articles count
- Duplicate article_ids exist in results
- Unknown article_ids exist in results (not in input articles)
- Missing article_ids exist (articles without corresponding results)
- Score values are invalid (not finite or outside [0, 1])
"""

from __future__ import annotations

# --- contract prelude -------------------------------------------------------
# Inlined rather than imported. A candidate is ONE self-contained file with no
# project imports and no third-party dependencies.

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


VERSION_ID = "keyed-v2-strict"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse response using keyed association by article_id.
    
    Each result entry must contain an 'article_id' field that matches
    one of the input articles. Results are matched by ID, not by position.
    """
    # Handle error responses
    error = response.get("error")
    if error:
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))

    content = response.get("content")
    if content is None:
        return refuse("truncated_response", "no content returned")

    # Parse JSON content
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    # Validate top-level structure
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    # Extract results list
    results_list = result.get("results", [])
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Build set of valid article IDs from input
    valid_article_ids = {article["id"] for article in articles}
    
    # Check count match
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )

    # Process results and build verdicts by article_id
    verdicts_by_id: dict[str, dict[str, Any]] = {}
    
    for i, entry in enumerate(results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry {i} is {type(entry).__name__}")
        
        # Extract article_id from result entry
        entry_article_id = entry.get("article_id")
        if entry_article_id is None:
            return refuse("missing_id", f"entry {i} missing article_id")
        
        if not isinstance(entry_article_id, str):
            return refuse("invalid_type", f"entry {i} article_id is not a string")
        
        # Check for duplicate article_ids in results
        if entry_article_id in verdicts_by_id:
            return refuse("duplicate_id", f"duplicate article_id: {entry_article_id}")
        
        # Check for unknown article_id
        if entry_article_id not in valid_article_ids:
            return refuse("unknown_id", f"unknown article_id: {entry_article_id}")
        
        # Validate and extract score
        raw_score = entry.get("score")
        score = finite_unit_score(raw_score)
        if score is None:
            return refuse("score_out_of_range" if raw_score is not None else "invalid_type", 
                         f"entry {i} has invalid score: {raw_score}")
        
        # Extract relevant (default based on score)
        relevant = bool(entry.get("relevant", score >= 0.5))
        
        # Extract reason
        reason = str(entry.get("reason", ""))
        
        # Store verdict
        verdicts_by_id[entry_article_id] = verdict(entry_article_id, relevant, score, reason)
    
    # Check for missing article_ids (articles without corresponding results)
    missing_ids = valid_article_ids - set(verdicts_by_id.keys())
    if missing_ids:
        return refuse("missing_id", f"missing results for article_ids: {sorted(missing_ids)}")
    
    # Build output in the same order as input articles
    out: list[dict[str, Any]] = []
    for article in articles:
        article_id = article["id"]
        if article_id in verdicts_by_id:
            out.append(verdicts_by_id[article_id])
        else:
            # This should not happen due to the check above, but handle defensively
            return refuse("missing_id", f"missing result for article_id: {article_id}")
    
    return ok(out)
