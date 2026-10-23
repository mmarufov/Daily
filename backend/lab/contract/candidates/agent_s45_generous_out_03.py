"""Keyed association parser that refuses ambiguous responses.

This parser supports both positional-v0 and keyed-v2 protocols. It refuses to
guess associations when the response is ambiguous rather than silently assigning
incorrect verdicts.

For positional responses: refuses if count != len(articles).
For keyed responses: uses article_id to associate, refuses on duplicate/missing/unknown IDs.
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


VERSION_ID = "keyed-v2"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    """Parse response and associate verdicts with articles.
    
    Supports both positional-v0 and keyed-v2 protocols.
    Refuses when association is ambiguous rather than guessing.
    """
    # Handle explicit error responses
    error = response.get("error")
    if error:
        # Propagate harness signals rather than degrading to zeros
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
    if finish_reason and finish_reason != "stop":
        return refuse("truncated_response", f"finish_reason={finish_reason}")

    # Parse JSON
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    # Extract results list
    results_list = result.get("results", [])
    
    # Support legacy "scores" format
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

    # Determine protocol based on whether results contain article_id
    # Check first non-empty result for article_id presence
    is_keyed = False
    for entry in results_list:
        if isinstance(entry, dict):
            is_keyed = "article_id" in entry
            break

    if is_keyed:
        return _parse_keyed(articles, results_list)
    else:
        return _parse_positional(articles, results_list)


def _parse_positional(
    articles: list[dict[str, Any]], 
    results_list: list[Any]
) -> dict[str, Any]:
    """Parse positional protocol responses (no article_id in results)."""
    
    # Strict count check - no partial results allowed
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
        raw_score = entry.get("score")
        score = finite_unit_score(raw_score)
        if score is None:
            if raw_score is None:
                # Default to 0.5 if score is missing
                score = 0.5
            else:
                return refuse("score_not_finite" if isinstance(raw_score, (int, float)) else "invalid_type",
                            f"score value: {raw_score}")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        out.append(verdict(article["id"], relevant, score, str(entry.get("reason", ""))))
    
    return ok(out)


def _parse_keyed(
    articles: list[dict[str, Any]], 
    results_list: list[Any]
) -> dict[str, Any]:
    """Parse keyed protocol responses (article_id present in results)."""
    
    # Build article ID set
    article_ids = {a["id"] for a in articles}
    
    # Parse all results and build ID->verdict mapping
    result_map: dict[str, dict[str, Any]] = {}
    
    for entry in results_list:
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        
        # Extract article_id
        article_id = entry.get("article_id")
        if not isinstance(article_id, str):
            return refuse("invalid_type", "article_id missing or not a string")
        
        # Check for duplicate
        if article_id in result_map:
            return refuse("duplicate_id", f"article_id {article_id} appears multiple times")
        
        # Check for unknown ID
        if article_id not in article_ids:
            return refuse("unknown_id", f"article_id {article_id} not in request")
        
        # Extract and validate score
        raw_score = entry.get("score")
        score = finite_unit_score(raw_score)
        if score is None:
            if raw_score is None:
                # Default to 0.5 if score is missing
                score = 0.5
            else:
                return refuse("score_not_finite" if isinstance(raw_score, (int, float)) else "invalid_type",
                            f"score value: {raw_score}")
        
        relevant = bool(entry.get("relevant", score >= 0.5))
        reason = str(entry.get("reason", ""))
        
        result_map[article_id] = {
            "relevant": relevant,
            "score": score,
            "reason": reason
        }
    
    # Check that all articles received verdicts
    if len(result_map) != len(articles):
        missing = article_ids - set(result_map.keys())
        if missing:
            return refuse("missing_id", f"no verdict for: {', '.join(sorted(list(missing))[:5])}")
        # This shouldn't happen given earlier checks, but be defensive
        return refuse("count_mismatch", f"{len(result_map)} results for {len(articles)} articles")
    
    # Build output in article order
    out: list[dict[str, Any]] = []
    for article in articles:
        article_id = article["id"]
        v = result_map[article_id]
        out.append(verdict(article_id, v["relevant"], v["score"], v["reason"]))
    
    return ok(out)
