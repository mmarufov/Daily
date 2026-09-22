"""CONTROL — keyed parsing with last-write-wins on duplicate ids.

Seeded defect: accepts a response containing the same article twice, keeping
the later verdict. Plausible-looking and wrong: the model has contradicted
itself and the parser has silently picked a winner.

Expected outcome: REJECTED on the duplicate-id cases. If the evaluator ever
accepts this, the evaluator is broken.
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


VERSION_ID = "control:lenient-keyed"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error"):
        return refuse("retries_exhausted", str(response["error"]))
    content = response.get("content")
    if content is None:
        return refuse("retries_exhausted", "no content")
    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))
    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        return refuse("unexpected_shape", "no results array")

    expected = {a["id"] for a in articles}
    by_id: dict[str, dict[str, Any]] = {}
    for entry in result["results"]:
        if not isinstance(entry, dict):
            continue
        article_id = entry.get("article_id", entry.get("id"))
        if article_id not in expected:
            continue  # DEFECT: silently drops unknown ids instead of refusing
        score = finite_unit_score(entry.get("score"))
        if score is None:
            score = 0.0  # DEFECT: coerces NaN / out-of-range to a real verdict
        by_id[article_id] = verdict(
            article_id, bool(entry.get("relevant", score >= 0.5)), score,
            str(entry.get("reason", "")),
        )  # DEFECT: last write wins on a duplicate id

    if len(by_id) != len(expected):
        return refuse("missing_id", f"{len(by_id)} of {len(expected)}")
    return ok([by_id[a["id"]] for a in articles])
