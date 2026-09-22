"""The proposed contract: every verdict identifies its own article.

Modelled on the id-keyed validation Daily already ships in
`backend/app/services/ranking_contract.py:131` (`validate_judgments`), which is
the pattern this repository already trusts for the S7 ranking path:

    packs = {e.article_id: e for e in evidence}
    ids = [v.article_id for v in values]
    if len(ids) != len(set(ids)) or set(ids) != set(packs):
        raise ValueError('ranker must return exact article ID set')

One set-equality check covers duplicate, unknown and missing ids at once, and
refuses to salvage a partial answer. The same shape is reproduced here, plus
the truncation check `ranking_provider.py:296` performs and
`score_articles_batch` does not:

    if choice.get('finish_reason') != 'stop':
        raise ProviderFailure('incomplete_response')

What this version does NOT claim: that it ranks better. Association is a
correctness property, and correctness is all that is under test. Relevance
quality under this protocol is unmeasured — it needs recordings that do not
exist, because no budgeted keyed run has been made.
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
    error = response.get("error")
    if error:
        if error == "no_recording":
            return refuse("no_recording", "no recorded response for this request")
        if error in {"timeout", "cancelled"}:
            return refuse(error, error)
        if error == "budget_exceeded":
            return refuse("retries_exhausted", error)
        return refuse("retries_exhausted", str(error))

    # A truncated completion is a failure, not a shorter answer. Production
    # never reads finish_reason, which is why 33 recorded responses that stopped
    # at the output ceiling were indistinguishable from malformed ones.
    finish_reason = response.get("finish_reason")
    if finish_reason is not None and finish_reason != "stop":
        return refuse("truncated_response", f"finish_reason={finish_reason}")

    content = response.get("content")
    if content is None:
        return refuse("retries_exhausted", "no content returned")

    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    if not isinstance(result, dict) or not isinstance(result.get("results"), list):
        return refuse("unexpected_shape", "expected an object with a results array")

    entries = result["results"]
    expected = {a["id"]: a for a in articles}

    seen: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            return refuse("invalid_type", f"entry is {type(entry).__name__}")
        article_id = entry.get("article_id", entry.get("id"))
        if not isinstance(article_id, str):
            return refuse("invalid_type", "article_id missing or not a string")
        seen.append(article_id)

    # Duplicate, unknown and missing are distinguished for the operator even
    # though any one of them is fatal. `validate_judgments` collapses all three
    # into one message; the Lab separates them so a counterexample can name the
    # exact failure, then refuses just as hard.
    if len(seen) != len(set(seen)):
        dupes = sorted({i for i in seen if seen.count(i) > 1})
        return refuse("duplicate_id", f"repeated ids: {', '.join(dupes[:5])}")
    unknown = [i for i in seen if i not in expected]
    if unknown:
        return refuse("unknown_id", f"ids not in the request: {', '.join(sorted(unknown)[:5])}")
    missing = [i for i in expected if i not in set(seen)]
    if missing:
        return refuse("missing_id", f"no verdict for: {', '.join(sorted(missing)[:5])}")

    out: list[dict[str, Any]] = []
    for entry in entries:
        article_id = entry.get("article_id", entry.get("id"))
        score = finite_unit_score(entry.get("score"))
        if score is None:
            raw = entry.get("score")
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                # Distinguishes 9e9 (out of range) from NaN (not finite); both
                # are clamped silently by production.
                return refuse(
                    "score_not_finite" if raw != raw or raw in (float("inf"), float("-inf"))
                    else "score_out_of_range",
                    f"score={raw!r} for {article_id}",
                )
            return refuse("invalid_type", f"score is {type(raw).__name__} for {article_id}")
        relevant = entry.get("relevant", score >= 0.5)
        if not isinstance(relevant, bool):
            return refuse("invalid_type", f"relevant is {type(relevant).__name__}")
        out.append(verdict(article_id, relevant, score, str(entry.get("reason", ""))))

    # Emit in request order so downstream consumers see a stable sequence. The
    # association itself is by id and does not depend on this ordering — the
    # permutation property test asserts exactly that.
    by_id = {v["article_id"]: v for v in out}
    return ok([by_id[a["id"]] for a in articles])
