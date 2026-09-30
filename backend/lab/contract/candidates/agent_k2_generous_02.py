"""Keyed protocol parser (keyed-v2) - eliminates positional association defects.

Each verdict must explicitly identify its article via article_id.
This allows out-of-order responses and detects mismatches unambiguously.
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


VERSION_ID = "keyed-v2"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse a keyed response where each verdict contains article_id.
    
    Refuses when:
    - Response has an error
    - JSON is malformed
    - Response shape is unexpected
    - Count mismatch (fewer or more verdicts than articles)
    - Duplicate article_ids in response
    - Unknown article_ids (not in input)
    - Missing article_ids (input article not in response)
    - Invalid score values
    """
    # Handle response-level errors
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

    # Parse JSON
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    # Validate top-level shape
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    results_list = result.get("results", [])
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Build expected article ID set
    expected_ids = {a["id"] for a in articles}
    
    # Check count first (fast path for obvious mismatches)
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )

    # Process results and validate associations
    verdicts_by_id: dict[str, dict[str, Any]] = {}
    
    for idx, entry in enumerate(results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry at index {idx} is {type(entry).__name__}")
        
        # Extract article_id (required for keyed protocol)
        article_id = entry.get("article_id")
        if article_id is None:
            return refuse("missing_id", f"entry at index {idx} missing article_id")
        
        if not isinstance(article_id, str):
            return refuse("invalid_type", f"article_id at index {idx} is not a string")
        
        # Check for duplicates
        if article_id in verdicts_by_id:
            return refuse("duplicate_id", f"duplicate article_id: {article_id}")
        
        # Check for unknown IDs
        if article_id not in expected_ids:
            return refuse("unknown_id", f"unknown article_id: {article_id}")
        
        # Validate score
        score_raw = entry.get("score")
        if score_raw is not None:
            score = finite_unit_score(score_raw)
            if score is None:
                return refuse("score_out_of_range", f"invalid score for {article_id}")
        else:
            score = 0.5  # default when missing
        
        # Validate relevant boolean
        relevant = bool(entry.get("relevant", score >= 0.5))
        
        # Extract reason
        reason = str(entry.get("reason", ""))
        
        verdicts_by_id[article_id] = verdict(article_id, relevant, score, reason)
    
    # Check for missing articles
    missing_ids = expected_ids - set(verdicts_by_id.keys())
    if missing_ids:
        return refuse("missing_id", f"missing verdicts for: {', '.join(sorted(missing_ids))}")
    
    # Build output in same order as input articles
    verdicts = []
    for article in articles:
        article_id = article["id"]
        v = verdicts_by_id.get(article_id)
        if v is None:
            # Should not happen due to missing_ids check above
            return refuse("missing_id", f"missing verdict for {article_id}")
        verdicts.append(v)
    
    return ok(verdicts)
