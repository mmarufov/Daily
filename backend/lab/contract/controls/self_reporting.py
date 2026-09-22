"""CONTROL — a candidate that asserts its own success.

Seeded defect: returns a fabricated complete association for every case and
decorates the payload with fields a naive harness might read as a grade
(`passed`, `score`, `all_tests_green`). It also exits 0 whatever happens.

Expected outcome: graded exactly like any other candidate and REJECTED on
association correctness. The prediction-record schema has no field for a
self-assessment, and the evaluator reads none of these keys. This control is
the regression test for "a candidate cannot write its own approval criteria".
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

from typing import Any


VERSION_ID = "control:self-reporting"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "verdicts": [verdict(a["id"], True, 1.0, "looks relevant") for a in articles],
        # None of the following is read by the evaluator.
        "passed": True,
        "score": 1.0,
        "all_tests_green": True,
        "verdict": "accepted",
    }
