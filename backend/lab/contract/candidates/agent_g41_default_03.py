"""Strict positional parser: refuses if result count does not match article count.
Fully inlines required contract prelude functions and constants.
"""

from __future__ import annotations
import json
import math

# --- contract prelude (must match frozen reference) -------------------------
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
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value
# --- end prelude -----------------------------------------------------------

VERSION_ID = "positional-strict-v1"
PROTOCOL = "positional-v0"

# Closed set from contract/types.py
REFUSAL_KINDS = {
    "malformed_json",
    "truncated_response",
    "unexpected_shape",
    "count_mismatch",
    "duplicate_id",
    "unknown_id",
    "missing_id",
    "invalid_type",
    "score_out_of_range",
    "score_not_finite",
    "no_recording",
    "timeout",
    "retries_exhausted",
    "cancelled",
    "unsupported_protocol",
}

def parse(articles, response):
    # Defensive parse
    try:
        data = json.loads(response["content"]) if isinstance(response, dict) and "content" in response else json.loads(response)
    except Exception as e:
        return refuse("malformed_json", f"JSON decode error: {e}")

    if not isinstance(data, dict) or "results" not in data:
        return refuse("unexpected_shape", "Top-level JSON is not an object with 'results' array")
    results = data["results"]

    if not isinstance(results, list):
        return refuse("unexpected_shape", "'results' field is not a list")

    if len(articles) != len(results):
        return refuse("count_mismatch", f"{len(results)} results for {len(articles)} articles")

    verdicts = []
    for a, r in zip(articles, results):
        # Basic structure checks
        if not isinstance(r, dict):
            return refuse("unexpected_shape", "Result entry is not a dict")
        relevant = r.get("relevant")
        score = r.get("score")
        reason = r.get("reason")
        sc = finite_unit_score(score)
        if relevant not in (True, False):
            return refuse("invalid_type", f"relevant field not bool (got {type(relevant)})")
        if sc is None:
            return refuse("score_out_of_range", f"raw score: {score}")
        if not isinstance(reason, str):
            return refuse("invalid_type", "reason not a string")
        verdicts.append(verdict(a["id"], relevant, sc, reason))
    return ok(verdicts)
