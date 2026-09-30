"""The site's "worst response" figure is the largest parseable recorded reply.

`/` and `/lab` quote one recorded batch: 40 articles sent, 254 verdicts back.
Two different figures (201 and 254) circulated because they are two different
recorded responses. This pins which one is the worst in the committed case set
and that the page's offending case is that one, so the copy cannot drift from
the records again.

The negative control removes the 254 case and shows the same check then
reports 201, so the assertion depends on the record, not on a constant.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OBSERVED = ROOT / "backend" / "lab" / "cases" / "observed.json"
OFFENDING = ROOT / "web" / "public" / "lab-artifacts" / "offending-case.json"


def worst_parseable(cases: list[dict]) -> tuple[str, int, int]:
    """(case_id, articles sent, verdicts returned) for the largest parseable reply."""
    best: tuple[str, int, int] | None = None
    for case in cases:
        try:
            verdicts = json.loads(case["response"]["content"])["results"]
        except (ValueError, KeyError, TypeError):
            continue  # truncated at the token cap, or not the positional shape
        row = (case["case_id"], len(case["articles"]), len(verdicts))
        if best is None or row[2] > best[2]:
            best = row
    assert best is not None, "no parseable recorded response"
    return best


def _cases() -> list[dict]:
    return json.loads(OBSERVED.read_text())["cases"]


def test_worst_parseable_response_is_254_verdicts_for_40_articles():
    assert worst_parseable(_cases()) == ("observed-2026-09-02-040", 40, 254)


def test_the_page_quotes_the_worst_case():
    offending = json.loads(OFFENDING.read_text())
    case_id, sent, returned = worst_parseable(_cases())
    assert (offending["case_id"], offending["articles_sent"], offending["verdicts_returned"]) == (
        case_id, sent, returned)


def test_negative_control_without_that_case_the_worst_is_201():
    rest = [c for c in _cases() if c["case_id"] != "observed-2026-09-02-040"]
    assert worst_parseable(rest) == ("observed-2026-09-02-006", 40, 201)
