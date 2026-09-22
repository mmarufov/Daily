"""A candidate parser: keyed association with a positional fallback.

Written for this experiment rather than transcribed from a revision, and
written to be *plausible* rather than to be correct. The instinct it encodes
is a real one and a good one in most contexts -- be liberal in what you
accept, do not discard work you can still make sense of -- applied to a
problem where it is exactly wrong.

The reasoning goes: keyed association is better, so prefer it; but the
recorded responses from production do not carry article ids, because the
prompt that produced them never asked for any. Refusing all of them would
mean refusing every real response we have. So fall back to position when
ids are absent, and refuse only when the response is unusable in both ways.

What that gives up is the property the experiment exists to measure. A
truncated or miscounted response has no ids either, so it takes the same
fallback, and the parser recovers an association from a response no parser
can recover an association from. It refuses less often than the historical
parser it was meant to improve on.

Kept as evidence. `web/lib/lab/runner.ts` routes it to the sandbox because
its bytes match no entry in KNOWN_IMPLEMENTATIONS -- being committed is not
what earns local execution; being on that list is.
"""

from __future__ import annotations

# --- contract prelude -------------------------------------------------------
# Inlined, per the one-self-contained-file rule. Canonical definitions live in
# lab/contract/types.py.

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


VERSION_ID = "keyed-with-positional-fallback"
PROTOCOL = "keyed-v2"


def parse(articles: list[dict[str, Any]], response: dict[str, Any]) -> dict[str, Any]:
    if response.get("error"):
        return refuse("no_recording", str(response.get("error"))[:200])

    content = response.get("content")
    if content is None:
        return refuse("no_recording", "the response carried no content")

    if response.get("finish_reason") not in (None, "stop"):
        return refuse("truncated_response", str(response.get("finish_reason")))

    try:
        result = json.loads(content)
    except Exception as exc:
        return refuse("malformed_json", str(exc))

    if not isinstance(result, dict):
        return refuse("unexpected_shape", f"top level is {type(result).__name__}")

    results_list = result.get("results")
    if not isinstance(results_list, list):
        return refuse("unexpected_shape", "results is not a list")

    keyed = [e for e in results_list if isinstance(e, dict) and "article_id" in e]

    if keyed:
        return _parse_keyed(articles, keyed)

    # The fallback. Every verdict lacks an id, so associate by position --
    # which is the defect this candidate was written to remove, reintroduced
    # under a condition that looked like it excluded the defective cases.
    return _parse_positional(articles, results_list)


def _parse_keyed(articles, entries):
    wanted = {a["id"] for a in articles}
    seen: dict[str, dict] = {}
    for entry in entries:
        aid = entry.get("article_id")
        if not isinstance(aid, str):
            return refuse("invalid_type", "article_id is not a string")
        if aid in seen:
            return refuse("duplicate_id", aid)
        if aid not in wanted:
            return refuse("unknown_id", aid)
        seen[aid] = entry

    missing = wanted - set(seen)
    if missing:
        return refuse("missing_id", ", ".join(sorted(missing))[:200])

    out = []
    for article in articles:
        entry = seen[article["id"]]
        score = finite_unit_score(entry.get("score"))
        if score is None:
            return refuse("score_out_of_range", f"{article['id']}: {entry.get('score')!r}")
        relevant = entry.get("relevant")
        if not isinstance(relevant, bool):
            return refuse("invalid_type", f"{article['id']}: relevant is not a bool")
        out.append(verdict(article["id"], relevant, score, entry.get("reason", "")))
    return ok(out)


def _parse_positional(articles, entries):
    if len(entries) != len(articles):
        return refuse("count_mismatch", f"{len(entries)} verdicts for {len(articles)} articles")

    out = []
    for article, entry in zip(articles, entries):
        if not isinstance(entry, dict):
            return refuse("unexpected_shape", "a verdict is not an object")
        score = finite_unit_score(entry.get("score"))
        if score is None:
            return refuse("score_out_of_range", f"{article['id']}: {entry.get('score')!r}")
        relevant = entry.get("relevant")
        if not isinstance(relevant, bool):
            relevant = score >= 0.5
        out.append(verdict(article["id"], relevant, score, entry.get("reason", "")))
    return ok(out)
