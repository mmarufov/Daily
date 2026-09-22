"""CONTROL — turns every failure into a confident all-zero answer.

Seeded defect: reproduces the blanket `except Exception` on the production
path, where `CacheMiss` (a RuntimeError) becomes a full set of 0.0 verdicts and
the run reports zero cache misses. An offline replay looks clean while having
scored nothing.

Expected outcome: REJECTED on the no-recording and truncation cases, because
an unavailable answer must surface as incomplete and never as a verdict.
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


VERSION_ID = "control:zero-filling"
PROTOCOL = "positional-v0"


def _zeros(articles: list[dict[str, Any]]) -> dict[str, Any]:
    return ok([verdict(a["id"], False, 0.0, "scoring unavailable") for a in articles])


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    try:
        if response.get("error"):
            return _zeros(articles)
        result = json.loads(response.get("content") or "")
        entries = result["results"]
        return ok([
            verdict(a["id"], bool(e.get("relevant")), float(e.get("score", 0.0)), str(e.get("reason", "")))
            for a, e in zip(articles, entries)
        ])
    except Exception:
        return _zeros(articles)
