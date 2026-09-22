"""Contract properties for the Daily Lab parsers.

The headline property is permutation invariance: permuting a valid keyed
response must not change which article gets which verdict. The synthetic batch
has six articles, so the permutation space is 6! = 720 — small enough to check
**exhaustively** rather than sample, which is strictly stronger than a
property test and removes the flake surface entirely.

The negative control matters as much as the property: `positional_v0` is
asserted *not* to be invariant. A test suite that only demonstrates the good
case cannot tell you whether the check has any power.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import math
from pathlib import Path

import pytest

LAB = Path(__file__).resolve().parent.parent / "lab"


def load(path: Path):
    spec = importlib.util.spec_from_file_location(f"lab_{path.stem}", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KEYED = load(LAB / "contract" / "versions" / "keyed_v2.py")
POSITIONAL = load(LAB / "contract" / "versions" / "positional_v0.py")
GUARD = load(LAB / "contract" / "versions" / "count_guard_v1.py")
TYPES = load(LAB / "contract" / "types.py")

SYNTHETIC = json.loads((LAB / "cases" / "synthetic.json").read_text())
BASE = next(c for c in SYNTHETIC["cases"] if c["case_id"] == "syn-keyed-in-order")
ARTICLES = BASE["articles"]
TRUTH = BASE["expectation"]["association"]


def keyed_response(order):
    entries = json.loads(BASE["response"]["content"])["results"]
    by_id = {e["article_id"]: e for e in entries}
    return {"content": json.dumps({"results": [by_id[i] for i in order]}),
            "finish_reason": "stop", "error": None}


def association(result):
    assert result["ok"] is True, result
    return {v["article_id"]: (v["relevant"], round(v["score"], 9)) for v in result["verdicts"]}


EXPECTED = {i: (TRUTH[i]["relevant"], round(TRUTH[i]["score"], 9)) for i in TRUTH}
IDS = [a["id"] for a in ARTICLES]


def test_permutation_invariance_is_exhaustive_not_sampled():
    assert math.factorial(len(IDS)) == 720


@pytest.mark.parametrize("order", list(itertools.permutations(IDS)))
def test_keyed_association_survives_every_permutation(order):
    """All 720 orderings of a valid keyed response yield one association."""
    assert association(KEYED.parse(ARTICLES, keyed_response(list(order)))) == EXPECTED


def test_positional_is_not_permutation_invariant():
    """The negative control: without ids, order *is* the association.

    If this ever passes, the permutation test above has lost its power and the
    experiment is measuring nothing.
    """
    entries = [
        {k: v for k, v in e.items() if k != "article_id"}
        for e in json.loads(BASE["response"]["content"])["results"]
    ]
    forward = POSITIONAL.parse(
        ARTICLES, {"content": json.dumps({"results": entries}), "finish_reason": "stop", "error": None}
    )
    reversed_ = POSITIONAL.parse(
        ARTICLES,
        {"content": json.dumps({"results": list(reversed(entries))}), "finish_reason": "stop", "error": None},
    )
    assert association(forward) != association(reversed_)


def test_count_guard_cannot_see_an_equal_length_reorder():
    """The precise limit of PR #59, stated as a test rather than an opinion."""
    entries = [
        {k: v for k, v in e.items() if k != "article_id"}
        for e in json.loads(BASE["response"]["content"])["results"]
    ]
    shuffled = list(reversed(entries))
    result = GUARD.parse(
        ARTICLES, {"content": json.dumps({"results": shuffled}), "finish_reason": "stop", "error": None}
    )
    # It parses happily — the lengths match — and the association is wrong.
    assert result["ok"] is True
    assert association(result) != EXPECTED


@pytest.mark.parametrize(
    "case_id",
    [c["case_id"] for c in SYNTHETIC["cases"] if c["expectation"]["expect"] == "refuse"
     and c["protocol"] == "keyed-v2"],
)
def test_keyed_refuses_every_synthetic_violation(case_id):
    case = next(c for c in SYNTHETIC["cases"] if c["case_id"] == case_id)
    result = KEYED.parse(case["articles"], case["response"])
    assert result["ok"] is False, f"{case_id} should have been refused"
    assert result["refusal"]["kind"] in TYPES.REFUSAL_KINDS
    assert result["refusal"]["kind"] in case["expectation"]["refusal_kinds"], (
        f"{case_id}: refused as {result['refusal']['kind']}, "
        f"expected one of {case['expectation']['refusal_kinds']}"
    )


def test_every_candidate_is_a_single_self_contained_file():
    """No project imports: the patch scope is one path and the sandbox needs
    no install step."""
    for path in sorted((LAB / "contract" / "versions").glob("*.py")) + sorted(
        (LAB / "contract" / "controls").glob("*.py")
    ):
        if path.name == "__init__.py":
            continue
        source = path.read_text()
        assert "from ..types" not in source, path
        assert "import lab" not in source, path
        for line in source.splitlines():
            if line.startswith("import ") or line.startswith("from "):
                module = line.split()[1].split(".")[0]
                assert module in {"__future__", "json", "math", "typing"}, f"{path}: {line}"


def test_prelude_copies_agree_with_the_canonical_definitions():
    """Every inlined prelude must still behave like lab/contract/types.py."""
    for path in sorted((LAB / "contract" / "versions").glob("*.py")):
        if path.name == "__init__.py":
            continue
        module = load(path)
        assert module.refuse("count_mismatch", "x") == TYPES.refuse("count_mismatch", "x")
        assert module.verdict("a", True, 0.5, "r") == TYPES.verdict("a", True, 0.5, "r")
        for probe in (0.0, 1.0, 0.5, -0.1, 1.1, float("nan"), float("inf"), "s", None, True):
            if hasattr(module, "finite_unit_score"):
                assert module.finite_unit_score(probe) == TYPES.finite_unit_score(probe), (path, probe)
