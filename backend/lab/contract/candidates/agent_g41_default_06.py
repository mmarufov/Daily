"""
Candidate parser to fix association defect.
Only associates by positional index if count matches. Refuses otherwise.
"""

from __future__ import annotations

# --- contract prelude -------------------------------------------------------
import math as _math

def ok(verdicts):
    return {"ok": True, "verdicts": verdicts}

def refuse(kind, detail=""):
    return {"ok": False, "refusal": {"kind": kind, "detail": str(detail)[:400]}}

def verdict(article_id, relevant, score, reason):
    return {"article_id": article_id, "relevant": bool(relevant), "score": float(score), "reason": str(reason)[:500]}

def finite_unit_score(raw):
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not _math.isfinite(value) or value < 0.0 or value > 1.0:
        return None
    return value
# --- end prelude ------------------------------------------------------------

VERSION_ID = "keyed-strict-v1"
PROTOCOL = "keyed-strict-v1"

import json

# Closed refusal kinds, exactly from contract/types.py
REFUSAL_KINDS = {
    "malformed_json","truncated_response","unexpected_shape",
    "count_mismatch","duplicate_id","unknown_id","missing_id",
    "invalid_type","score_out_of_range","score_not_finite",
    "no_recording","timeout","retries_exhausted","cancelled","unsupported_protocol"
}

def parse(articles, response):
    # Defensive: response may be string or dict. Parse as json if needed.
    if isinstance(response, dict) and "results" in response:
        results = response["results"]
    elif isinstance(response, str):
        try:
            obj = json.loads(response)
        except Exception as e:
            return refuse("malformed_json", f"Could not parse JSON: {e}")
        if not isinstance(obj, dict) or "results" not in obj:
            return refuse("unexpected_shape", "JSON did not contain 'results' array.")
        results = obj["results"]
    else:
        return refuse("unexpected_shape", f"Response must be dict with 'results' or JSON str.")

    if not isinstance(results, list):
        return refuse("unexpected_shape", "'results' is not a list.")
    if len(results) != len(articles):
        return refuse("count_mismatch", f"articles {len(articles)} vs results {len(results)}")

    verdicts = []
    for article, result in zip(articles, results):
        relevant = result.get("relevant")
        score_raw = result.get("score")
        reason = result.get("reason", "")
        score = finite_unit_score(score_raw)

        if not isinstance(relevant, bool):
            return refuse("invalid_type", f"'relevant' not bool: {relevant}")
        if score is None:
            if isinstance(score_raw, (int, float)) and not _math.isfinite(float(score_raw)):
                return refuse("score_not_finite", f"Score not finite: {score_raw}")
            else:
                return refuse("score_out_of_range", f"Score out of range: {score_raw}")
        verdicts.append(verdict(article["id"], relevant, score, reason))
    return ok(verdicts)
