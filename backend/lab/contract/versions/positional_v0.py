"""Historical behaviour, transcribed from `origin/main`.

Source: backend/app/services/openai_service.py, score_articles_batch, the
`normalized` loop. Verbatim semantics:

    if len(results_list) != len(articles):
        logger.warning("... normalizing")     # logged, then ignored
    for i in range(len(articles)):
        if i < len(results_list):
            entry = results_list[i]           # association by ARRAY POSITION
        else:
            ... {"relevant": False, "score": 0.0, "reason": "scoring incomplete"}

This version is preserved so the experiment can measure the defect rather than
describe it. It is not a control: it is what production does today.
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


VERSION_ID = "positional-v0"
PROTOCOL = "positional-v0"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error"):
        # Production catches this with a blanket `except Exception` and returns
        # an all-zero fallback. Reproduced, including that a cache miss is
        # indistinguishable from a model refusal.
        return ok([verdict(a["id"], False, 0.0, "scoring unavailable") for a in articles])

    content = response.get("content")
    if content is None:
        return ok([verdict(a["id"], False, 0.0, "scoring unavailable") for a in articles])

    try:
        result = json.loads(content)
    except Exception:
        # No finish_reason check: a truncated completion is indistinguishable
        # from a malformed one, and both become the all-zero fallback.
        return ok([verdict(a["id"], False, 0.0, "scoring unavailable") for a in articles])

    results_list = result.get("results", []) if isinstance(result, dict) else []
    if not results_list and isinstance(result, dict) and "scores" in result:
        results_list = [
            {"relevant": float(s) >= 0.5, "score": float(s), "reason": ""}
            for s in result["scores"]
        ]

    out: list[dict[str, Any]] = []
    for i, article in enumerate(articles):
        if i < len(results_list):
            entry = results_list[i] if isinstance(results_list[i], dict) else {}
            try:
                score = max(0.0, min(1.0, float(entry.get("score", 0.5))))
            except Exception:
                score = 0.5
            relevant = bool(entry.get("relevant", score >= 0.5))
            out.append(verdict(article["id"], relevant, score, str(entry.get("reason", ""))))
        else:
            out.append(verdict(article["id"], False, 0.0, "scoring incomplete"))
    return ok(out)
