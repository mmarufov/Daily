"""Candidate parser that refuses when association is ambiguous.

This parser handles both positional-v0 and keyed-v2 protocols:
- For positional-v0: Refuses if count mismatch or truncated; associates by position if count matches
- For keyed-v2: Refuses if article_ids don't match exactly; associates by article_id
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


VERSION_ID = "refuse-ambiguous-v2"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse response and associate verdicts with articles, refusing if ambiguous."""
    
    # Handle error responses
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
    
    # Check if response was truncated
    finish_reason = response.get("finish_reason")
    if finish_reason == "length":
        return refuse("truncated_response", "response was truncated due to length")
    
    # Parse JSON
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))
    
    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")
    
    # Extract results list
    results_list = result.get("results", [])
    if not results_list and "scores" in result:
        # Legacy format with just scores
        results_list = [
            {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for s in result["scores"]
        ]
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")
    
    # Determine protocol based on whether first result has article_id
    protocol_is_keyed = False
    if results_list:
        first_entry = results_list[0] if isinstance(results_list[0], dict) else {}
        if "article_id" in first_entry:
            protocol_is_keyed = True
    
    if protocol_is_keyed:
        # KEYED PROTOCOL: Associate by article_id
        return _parse_keyed(articles, results_list)
    else:
        # POSITIONAL PROTOCOL: Associate by position
        return _parse_positional(articles, results_list)


def _parse_positional(articles: list[dict[str, Any]], results_list: list) -> dict[str, Any]:
    """Parse positional protocol (no article_id in results)."""
    
    # Count mismatch in positional protocol is ambiguous
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
            if isinstance(raw_score, bool):
                return refuse("invalid_type", "score is a boolean")
            if not isinstance(raw_score, (int, float)):
                return refuse("invalid_type", "score is not numeric")
            value = float(raw_score)
            if not _math.isfinite(value):
                return refuse("score_not_finite", f"score is {value}")
            return refuse("score_out_of_range", f"score is {value}")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        out.append(verdict(article["id"], relevant, score, str(entry.get("reason", ""))))
    
    return ok(out)


def _parse_keyed(articles: list[dict[str, Any]], results_list: list) -> dict[str, Any]:
    """Parse keyed protocol (article_id in results)."""
    
    # Build article ID set
    article_ids = {a["id"] for a in articles}
    
    # Extract result IDs and build lookup
    result_map = {}
    for entry in results_list:
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        article_id = entry.get("article_id")
        if not article_id:
            return refuse("missing_id", "result missing article_id")
        
        article_id = str(article_id)
        
        if article_id in result_map:
            return refuse("duplicate_id", f"duplicate article_id: {article_id}")
        
        if article_id not in article_ids:
            return refuse("unknown_id", f"unknown article_id: {article_id}")
        
        result_map[article_id] = entry
    
    # Check all articles have results
    if len(result_map) != len(articles):
        missing = article_ids - set(result_map.keys())
        return refuse("missing_id", f"missing results for {len(missing)} articles")
    
    # Build output in article order
    out: list[dict[str, Any]] = []
    for article in articles:
        article_id = article["id"]
        entry = result_map[article_id]
        
        # Extract and validate score
        raw_score = entry.get("score", 0.5)
        score = finite_unit_score(raw_score)
        if score is None:
            if isinstance(raw_score, bool):
                return refuse("invalid_type", "score is a boolean")
            if not isinstance(raw_score, (int, float)):
                return refuse("invalid_type", "score is not numeric")
            value = float(raw_score)
            if not _math.isfinite(value):
                return refuse("score_not_finite", f"score is {value}")
            return refuse("score_out_of_range", f"score is {value}")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        out.append(verdict(article_id, relevant, score, str(entry.get("reason", ""))))
    
    return ok(out)
