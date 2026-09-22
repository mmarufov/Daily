"""The frozen interface between a candidate parser and the trusted evaluator.

Everything crossing this boundary is plain JSON. A candidate never returns an
object, a score, a verdict on itself, or an exit code that means anything: it
returns *prediction records* describing what association it produced, and the
evaluator — which lives in another language, in another process, outside the
sandbox — decides whether that was right.

`REFUSAL_KINDS` is a closed vocabulary. A candidate that invents a new kind is
treated as having failed the case rather than as having discovered a new way to
pass, because the expectation set is keyed on these strings.
"""

from __future__ import annotations

import math
from typing import Any

PROTOCOL_POSITIONAL = "positional-v0"
PROTOCOL_KEYED = "keyed-v2"

#: Closed set. The evaluator's expectation fixtures reference these by name.
REFUSAL_KINDS: frozenset[str] = frozenset(
    {
        # Response-shape failures
        "malformed_json",
        "truncated_response",
        "unexpected_shape",
        # Association failures
        "count_mismatch",
        "duplicate_id",
        "unknown_id",
        "missing_id",
        # Value failures
        "invalid_type",
        "score_out_of_range",
        "score_not_finite",
        # Execution failures — never a pass, never a silent zero
        "no_recording",
        "timeout",
        "retries_exhausted",
        "cancelled",
        "unsupported_protocol",
    }
)


def ok(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """A complete, unambiguous association of every article to a verdict."""
    return {"ok": True, "verdicts": verdicts}


def refuse(kind: str, detail: str = "") -> dict[str, Any]:
    """An explicit refusal.

    Refusing is a first-class outcome, not an error path. The defect this
    experiment exists to study is precisely a parser that declined to refuse.
    """
    return {"ok": False, "refusal": {"kind": kind, "detail": detail[:400]}}


def verdict(article_id: str, relevant: bool, score: float, reason: str) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "relevant": bool(relevant),
        "score": float(score),
        "reason": str(reason)[:500],
    }


def finite_unit_score(raw: Any) -> float | None:
    """Return a score in [0, 1], or None when the value is not usable.

    Production clamps with `max(0.0, min(1.0, float(...)))`, which turns 9e9
    into 1.0 and raises on NaN only by accident — `float('nan')` clamps to nan
    and propagates. Returning None forces the caller to decide explicitly.
    """
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    if not math.isfinite(value):
        return None
    if value < 0.0 or value > 1.0:
        return None
    return value
