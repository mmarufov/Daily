"""Synthetic fault-injection cases, with ground truth known by construction.

Kept in a separate group from `observed.json` and never mixed with it. An
observed case can only ever assert what the recording settles; a synthetic case
is built from a known-correct association, so it can assert the exact verdict
every article must receive.

    python -m lab.build_synthetic
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# A small, fixed batch. Ids deliberately look nothing like positions.
ARTICLES: list[dict[str, str]] = [
    {"id": "a00407", "title": "Giants' 53-man roster to include Odell Beckham", "source": "ESPN"},
    {"id": "n-dil-02", "title": "Mirziyoyev signs decree abolishing exit visa-style registration", "source": "Gazeta.uz"},
    {"id": "a00037", "title": "World mostly shrugs off Bessent's 'D-Day' Iran sanctions threat", "source": "Reuters"},
    {"id": "a00980", "title": "How Sunny Mehta Will Stand Out Among The New Wave Of Young GMs", "source": "Yahoo Sports NHL"},
    {"id": "a00976", "title": "Hurricanes announce more broadcast details", "source": "Yahoo Sports NHL"},
    {"id": "a01204", "title": "NJ Transit to suspend Morris & Essex line service", "source": "NJ.com"},
]

#: The association every correct parser must produce for the base response.
TRUTH: dict[str, tuple[bool, float, str]] = {
    "a00407": (False, 0.10, "discusses NFL team rosters"),
    "n-dil-02": (True, 0.95, "Uzbek policy change, directly on topic"),
    "a00037": (True, 0.80, "sanctions policy"),
    "a00980": (False, 0.20, "NHL management profile"),
    "a00976": (False, 0.05, "NHL broadcast logistics"),
    "a01204": (True, 0.70, "New Jersey transit disruption"),
}


def keyed_entry(article_id: str) -> dict[str, Any]:
    relevant, score, reason = TRUTH[article_id]
    return {"article_id": article_id, "relevant": relevant, "score": score, "reason": reason}


def keyed_body(order: list[str]) -> str:
    return json.dumps({"results": [keyed_entry(i) for i in order]})


def positional_body(order: list[str]) -> str:
    return json.dumps(
        {"results": [{k: v for k, v in keyed_entry(i).items() if k != "article_id"} for i in order]}
    )


def association() -> dict[str, dict[str, Any]]:
    return {
        i: {"relevant": TRUTH[i][0], "score": TRUTH[i][1]} for i in (a["id"] for a in ARTICLES)
    }


def parse_case(case_id: str, protocol: str, content: str, why: str, **extra: Any) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "group": "synthetic",
        "origin": "fault-injection",
        "protocol": protocol,
        "family": "protocol-association",
        "articles": ARTICLES,
        "response": {"content": content, "finish_reason": "stop", "error": None, **extra},
        "expectation": {
            "expect": "parse",
            "association": association(),
            "refusal_kinds": [],
            "why": why,
        },
    }


def refuse_case(
    case_id: str,
    protocol: str,
    content: str | None,
    kinds: list[str],
    why: str,
    family: str = "protocol-association",
    **response: Any,
) -> dict[str, Any]:
    base = {"content": content, "finish_reason": "stop", "error": None}
    base.update(response)
    return {
        "case_id": case_id,
        "group": "synthetic",
        "origin": "fault-injection",
        "protocol": protocol,
        "family": family,
        "articles": ARTICLES,
        "response": base,
        "expectation": {"expect": "refuse", "association": None, "refusal_kinds": kinds, "why": why},
    }


def refuse_case_universal(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """A refusal every parser owes regardless of the protocol it speaks."""
    return refuse_case(*args, family="universal-refusal", **kwargs)


def build() -> list[dict[str, Any]]:
    ids = [a["id"] for a in ARTICLES]
    cases: list[dict[str, Any]] = []

    # --- the association must survive ordering -----------------------------
    cases.append(parse_case("syn-keyed-in-order", "keyed-v2", keyed_body(ids),
                            "a well-formed keyed response in request order"))
    cases.append(parse_case("syn-keyed-reversed", "keyed-v2", keyed_body(list(reversed(ids))),
                            "the same verdicts, reversed; association must not move"))
    cases.append(parse_case("syn-keyed-rotated", "keyed-v2", keyed_body(ids[2:] + ids[:2]),
                            "the same verdicts, rotated; association must not move"))

    # --- id-set violations --------------------------------------------------
    dup = json.dumps({"results": [keyed_entry(i) for i in ids] + [keyed_entry(ids[0])]})
    cases.append(refuse_case("syn-duplicate-id", "keyed-v2", dup, ["duplicate_id"],
                             "the same article is judged twice; no winner may be picked"))

    unknown = json.dumps({"results": [keyed_entry(i) for i in ids[1:]] +
                          [{"article_id": "a99999", "relevant": True, "score": 0.9, "reason": "?"}]})
    cases.append(refuse_case("syn-unknown-id", "keyed-v2", unknown, ["unknown_id"],
                             "a verdict for an article that was never sent"))

    cases.append(refuse_case("syn-missing-id", "keyed-v2", keyed_body(ids[:-1]), ["missing_id", "count_mismatch"],
                             "one article receives no verdict; partial salvage is not allowed"))

    # --- value violations ---------------------------------------------------
    for label, raw, kinds in [
        ("nan", float("nan"), ["score_not_finite", "invalid_type", "malformed_json"]),
        ("out-of-range", 9e9, ["score_out_of_range", "invalid_type"]),
        ("string", "high", ["invalid_type"]),
        ("null", None, ["invalid_type"]),
    ]:
        entries = [keyed_entry(i) for i in ids]
        entries[0] = {**entries[0], "score": raw}
        # NaN is not valid JSON; json.dumps emits it anyway, which is itself the
        # thing a strict reader must reject.
        body = json.dumps({"results": entries})
        cases.append(refuse_case(f"syn-score-{label}", "keyed-v2", body, kinds,
                                 f"score is {label}; production clamps it into a real verdict"))

    bad_relevant = [keyed_entry(i) for i in ids]
    bad_relevant[1] = {**bad_relevant[1], "relevant": "yes"}
    cases.append(refuse_case("syn-relevant-not-bool", "keyed-v2", json.dumps({"results": bad_relevant}),
                             ["invalid_type"], "relevant is a string"))

    # --- response-shape violations -----------------------------------------
    cases.append(refuse_case_universal("syn-malformed-json", "keyed-v2", '{"results": [{"article_id": "a00407",',
                             ["malformed_json"], "the response is cut mid-object"))
    cases.append(refuse_case_universal("syn-truncated-finish-reason", "keyed-v2", keyed_body(ids[:3]),
                             ["truncated_response", "count_mismatch", "missing_id"],
                             "the completion stopped at the output ceiling",
                             finish_reason="length"))
    cases.append(refuse_case_universal("syn-not-an-object", "keyed-v2", json.dumps([keyed_entry(i) for i in ids]),
                             ["unexpected_shape"], "top level is an array, not an object"))
    cases.append(refuse_case("syn-empty-results", "keyed-v2", json.dumps({"results": []}),
                             ["missing_id", "count_mismatch"], "no verdicts at all"))

    # --- execution outcomes: never a verdict, never a zero ------------------
    for label, error, kinds in [
        ("no-recording", "no_recording", ["no_recording"]),
        ("timeout", "timeout", ["timeout"]),
        ("cancelled", "cancelled", ["cancelled"]),
        ("budget", "budget_exceeded", ["retries_exhausted", "no_recording"]),
    ]:
        cases.append(refuse_case_universal(f"syn-exec-{label}", "keyed-v2", None, kinds,
                                 f"execution ended as {error}; an unavailable answer is not an answer",
                                 error=error, finish_reason=None))

    # --- positional protocol, for the two historical versions ---------------
    cases.append(refuse_case_universal("syn-positional-short", "positional-v0", positional_body(ids[:4]),
                             ["count_mismatch", "missing_id"],
                             "4 verdicts for 6 articles: which belongs to which is unrecorded"))
    cases.append(refuse_case_universal("syn-positional-long", "positional-v0", positional_body(ids + ids[:1]),
                             ["count_mismatch", "duplicate_id"],
                             "7 verdicts for 6 articles"))
    # Equal length and internally reordered. This is the case the length guard
    # cannot see, and the reason the experiment exists.
    cases.append(refuse_case("syn-positional-reordered", "positional-v0",
                             positional_body(list(reversed(ids))),
                             ["count_mismatch", "unexpected_shape", "unsupported_protocol",
                              "invalid_type", "missing_id"],
                             "equal length, internally reordered — a length check cannot detect this"))

    return cases


def main() -> int:
    cases = build()
    out = Path(__file__).resolve().parent / "cases" / "synthetic.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_suite_version": 1,
        "group": "synthetic",
        "generated_from": "lab/build_synthetic.py — fault injection, ground truth by construction",
        "n_cases": len(cases),
        "cases": cases,
    }
    out.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    print(f"wrote {out} ({len(cases)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
