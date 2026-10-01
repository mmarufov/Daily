"""Candidate parser that refuses on ambiguous associations.

This parser detects truncated responses, count mismatches, and reordered results,
refusing to associate when the response cannot be unambiguously matched to articles.
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


VERSION_ID = "agent-keyed-guard"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse response and associate verdicts with articles, refusing on ambiguity.
    
    Handles both positional-v0 and keyed-v2 protocols. Refuses when:
    - Response is truncated
    - Count doesn't match (positional)
    - IDs are missing, unknown, or duplicated (keyed)
    - Data types or values are invalid
    """
    # Handle execution errors
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

    # Check for truncation via finish_reason
    finish_reason = response.get("finish_reason")
    if finish_reason and finish_reason != "stop":
        return refuse("truncated_response", f"finish_reason: {finish_reason}")

    # Parse JSON
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    # Extract results list, with fallback for "scores" format
    results_list = result.get("results", [])
    if not results_list and "scores" in result:
        scores = result["scores"]
        if not isinstance(scores, list):
            return refuse("unexpected_shape", "scores is not a list")
        results_list = [
            {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for s in scores
        ]
    
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    # Detect protocol by checking if results contain article_id
    has_article_ids = any(
        isinstance(entry, dict) and "article_id" in entry
        for entry in results_list
    )

    if has_article_ids:
        # Keyed protocol (keyed-v2)
        return parse_keyed(articles, results_list)
    else:
        # Positional protocol (positional-v0)
        return parse_positional(articles, results_list)


def parse_positional(
    articles: list[dict[str, Any]], 
    results_list: list[Any]
) -> dict[str, Any]:
    """Parse positional response where results[i] corresponds to articles[i]."""
    
    # Refuse on count mismatch - this is the core defect we're fixing
    if len(results_list) != len(articles):
        return refuse(
            "count_mismatch",
            f"{len(results_list)} results for {len(articles)} articles",
        )

    out: list[dict[str, Any]] = []
    for article, entry in zip(articles, results_list):
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Extract and validate score
        raw_score = entry.get("score", 0.5)
        score = finite_unit_score(raw_score)
        if score is None:
            # Try clamping for backwards compatibility, but validate
            try:
                score = max(0.0, min(1.0, float(raw_score)))
                if not _math.isfinite(score):
                    return refuse("score_not_finite", f"score is {raw_score}")
            except Exception:
                return refuse("invalid_type", "score is not numeric")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(article["id"], relevant, score, reason))
    
    return ok(out)


def parse_keyed(
    articles: list[dict[str, Any]], 
    results_list: list[Any]
) -> dict[str, Any]:
    """Parse keyed response where each result contains an article_id field."""
    
    # Build article ID set for validation
    article_ids = {article["id"] for article in articles}
    
    # Build results map by article_id
    results_map: dict[str, dict[str, Any]] = {}
    for entry in results_list:
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        aid = entry.get("article_id")
        if not aid:
            return refuse("missing_id", "result missing article_id")
        
        aid = str(aid)
        
        # Check for duplicates
        if aid in results_map:
            return refuse("duplicate_id", f"duplicate article_id: {aid}")
        
        # Check for unknown IDs
        if aid not in article_ids:
            return refuse("unknown_id", f"unknown article_id: {aid}")
        
        results_map[aid] = entry
    
    # Check that all articles have results
    missing_ids = article_ids - set(results_map.keys())
    if missing_ids:
        return refuse("missing_id", f"missing {len(missing_ids)} article(s)")
    
    # Build verdicts in article order
    out: list[dict[str, Any]] = []
    for article in articles:
        aid = article["id"]
        entry = results_map[aid]
        
        # Extract and validate score
        raw_score = entry.get("score", 0.5)
        score = finite_unit_score(raw_score)
        if score is None:
            # Try clamping for backwards compatibility, but validate
            try:
                score = max(0.0, min(1.0, float(raw_score)))
                if not _math.isfinite(score):
                    return refuse("score_not_finite", f"score is {raw_score}")
            except Exception:
                return refuse("invalid_type", "score is not numeric")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        out.append(verdict(aid, relevant, score, reason))
    
    return ok(out)
