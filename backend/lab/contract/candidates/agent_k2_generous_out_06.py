"""Keyed association parser - fixes the positional association defect.

Each verdict explicitly identifies which article it applies to via article_id,
allowing unambiguous association and detection of duplicates, unknown IDs,
and missing IDs.
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
    """Parse response using keyed association.
    
    Each result entry must contain an 'article_id' field that explicitly
    identifies which article the verdict applies to. This allows verification
    of complete, unambiguous association.
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
        return refuse("retries_exhausted", "no content returned")

    # Parse JSON
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

    # Build set of expected article IDs
    expected_ids = {article["id"] for article in articles}
    
    # Process results and validate associations
    verdicts_by_id: dict[str, dict[str, Any]] = {}
    
    for i, entry in enumerate(results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry {i} is {type(entry).__name__}")
        
        # Get article_id from entry
        article_id = entry.get("article_id")
        if article_id is None:
            return refuse("missing_id", f"entry {i} missing article_id")
        
        # Check for duplicates
        if article_id in verdicts_by_id:
            return refuse("duplicate_id", f"duplicate article_id: {article_id}")
        
        # Check for unknown article_id
        if article_id not in expected_ids:
            return refuse("unknown_id", f"unknown article_id: {article_id}")
        
        # Validate and extract score
        score_raw = entry.get("score")
        if score_raw is None:
            return refuse("invalid_type", f"entry for {article_id} missing score")
        
        score = finite_unit_score(score_raw)
        if score is None:
            return refuse("score_out_of_range", f"entry for {article_id} has invalid score: {score_raw}")
        
        # Extract relevant (default based on score if not provided)
        relevant_raw = entry.get("relevant")
        if relevant_raw is None:
            relevant = score >= 0.5
        else:
            if not isinstance(relevant_raw, bool):
                return refuse("invalid_type", f"entry for {article_id} has non-boolean relevant")
            relevant = relevant_raw
        
        # Extract reason
        reason = entry.get("reason", "")
        if not isinstance(reason, str):
            reason = str(reason)
        
        verdicts_by_id[article_id] = verdict(article_id, relevant, score, reason)
    
    # Check for missing article IDs
    received_ids = set(verdicts_by_id.keys())
    missing_ids = expected_ids - received_ids
    if missing_ids:
        return refuse("missing_id", f"missing verdicts for articles: {sorted(missing_ids)}")
    
    # Check for count mismatch (shouldn't happen if we got here, but safety check)
    if len(verdicts_by_id) != len(articles):
        return refuse("count_mismatch", f"{len(verdicts_by_id)} results for {len(articles)} articles")
    
    # Build ordered list matching input article order
    out: list[dict[str, Any]] = []
    for article in articles:
        article_id = article["id"]
        out.append(verdicts_by_id[article_id])
    
    return ok(out)
