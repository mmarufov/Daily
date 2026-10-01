"""Keyed association parser that refuses when results cannot be unambiguously matched.

This parser expects results to contain an article_id field and associates them
by matching those IDs to the articles list. It refuses when:
- The response is malformed or incomplete
- Result counts don't match article counts
- Results contain duplicate, missing, or unknown article IDs
- Score values are invalid
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


VERSION_ID = "keyed-association-v2"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse response with keyed association, refusing when ambiguous.
    
    This parser expects each result to have an article_id field that matches
    one of the input articles. It refuses rather than inventing associations.
    """
    
    # Handle error responses from the harness
    error = response.get("error")
    if error:
        # Special harness errors that should propagate as refusals
        if error in {"no_recording", "budget_exceeded"}:
            return refuse("no_recording" if error == "no_recording" else "retries_exhausted", error)
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        return refuse("retries_exhausted", str(error))
    
    # Check for content
    content = response.get("content")
    if content is None:
        return refuse("retries_exhausted", "no content returned")
    
    # Check finish_reason for truncation
    finish_reason = response.get("finish_reason")
    if finish_reason == "length":
        return refuse("truncated_response", "completion was truncated")
    
    # Parse JSON
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))
    
    # Validate top-level structure
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")
    
    # Extract results array
    results_list = result.get("results", [])
    if not results_list and "scores" in result:
        # Legacy format support - but without IDs, we can't associate
        return refuse("missing_id", "scores array lacks article_id fields")
    
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")
    
    # Check count match - even with keyed association, we expect exact count
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )
    
    # Build article ID set for validation
    article_ids = {a["id"] for a in articles}
    
    # Parse and validate each result
    result_map: dict[str, dict[str, Any]] = {}
    for i, entry in enumerate(results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry {i} is {type(entry).__name__}")
        
        # Extract and validate article_id
        article_id = entry.get("article_id")
        if article_id is None:
            return refuse("missing_id", f"entry {i} has no article_id")
        
        article_id = str(article_id)
        
        # Check for unknown IDs
        if article_id not in article_ids:
            return refuse("unknown_id", f"article_id {article_id} not in batch")
        
        # Check for duplicates
        if article_id in result_map:
            return refuse("duplicate_id", f"article_id {article_id} appears multiple times")
        
        # Validate score
        raw_score = entry.get("score")
        if raw_score is None:
            return refuse("invalid_type", f"entry {i} has no score")
        
        score = finite_unit_score(raw_score)
        if score is None:
            if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
                return refuse("invalid_type", f"score is {type(raw_score).__name__}")
            value = float(raw_score)
            if not _math.isfinite(value):
                return refuse("score_not_finite", f"score is {raw_score}")
            return refuse("score_out_of_range", f"score {value} not in [0, 1]")
        
        # Extract relevant and reason
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        result_map[article_id] = {
            "relevant": relevant,
            "score": score,
            "reason": reason,
        }
    
    # Check that all articles have results
    missing = article_ids - set(result_map.keys())
    if missing:
        return refuse("missing_id", f"{len(missing)} articles have no results")
    
    # Build output in the same order as input articles
    out: list[dict[str, Any]] = []
    for article in articles:
        article_id = article["id"]
        result_data = result_map[article_id]
        out.append(verdict(
            article_id,
            result_data["relevant"],
            result_data["score"],
            result_data["reason"]
        ))
    
    return ok(out)
