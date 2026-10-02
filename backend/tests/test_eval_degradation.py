"""Each feed-quality metric can fail, and the gate can no longer miss a silent fallback.

`evals/degrade.py` registers nine faults with the metrics each must move, the
direction, and a 0.05 threshold, committed before any measured run. This file
replays every fault offline from the committed cache and holds each one to its
declaration. It also holds the committed `degradation-matrix.json` to a fresh
replay, so the published numbers cannot drift from the code.

The negative controls at the bottom need no replay. Each one feeds a checker an
input it must reject (an unchanged metric, a reversed direction, a blind fault
that moved, a raised miss, a metric that became None) and asserts it does, so
the checks above are known to have the power to fail.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["EVAL_OFFLINE"] = "1"

from evals import degrade  # noqa: E402
from evals.metrics import offline_violations, regression  # noqa: E402

MATRIX = Path(degrade.MATRIX_PATH)


@pytest.fixture(scope="module")
def matrix() -> dict:
    # Round-trip through JSON so the comparison with the committed file sees
    # exactly what was written.
    return json.loads(json.dumps(degrade.compute_matrix(workers=8)))


def test_declarations_are_the_preregistered_ones():
    assert degrade.registry_digest() == degrade.PREREGISTERED_SHA256


@pytest.mark.parametrize("name", sorted(degrade.REGISTRY))
def test_fault_meets_its_declaration(matrix, name):
    fault = matrix["faults"][name]
    assert fault["failures"] == [], fault["failures"]
    assert fault["passed"]


@pytest.mark.parametrize("name", sorted(degrade.REGISTRY))
def test_fault_run_stayed_offline_on_the_clean_requests(matrix, name):
    fault = matrix["faults"][name]
    for snapshot, run in fault["runs"].items():
        clean = matrix["clean"][fault["runner"]][snapshot]
        assert run["offline_misses_total"] == 0
        assert run["cache_misses_total"] == 0
        assert run["cache_keys_sha256"] == clean["cache_keys_sha256"]
        assert run["calls_total"] == clean["calls_total"]


def test_clean_runs_stayed_offline(matrix):
    for runs in matrix["clean"].values():
        for run in runs.values():
            assert run["offline_misses_total"] == 0 and run["cache_misses_total"] == 0


def test_upstream_fault_now_fails_the_offline_check(matrix):
    gate = matrix["gate_control"]

    assert gate["cache_misses_total"] == 0
    assert gate["old_offline_check_passes"]
    # Count offline misses even when the scorer catches them.
    assert gate["offline_misses_total"] > 0
    assert gate["new_offline_check_fails"]
    assert gate["offline_violations"]


def test_committed_matrix_matches_a_fresh_replay(matrix):
    committed = json.loads(MATRIX.read_text())
    assert committed["registry_sha256"] == degrade.PREREGISTERED_SHA256
    assert degrade.comparable(committed) == degrade.comparable(matrix), (
        "Re-run `cd backend && EVAL_OFFLINE=1 python -m evals.degrade --write` and commit the matrix.")


# ---------------------------------------------------------------------------
# Negative controls: the checkers reject what they must, with no replay.
# ---------------------------------------------------------------------------

def _runs(values_by_snapshot: dict[str, list]) -> dict:
    return {s: {"per_persona": {f"p{i}": {m: v for m in degrade.METRICS} for i, v in enumerate(vals)}}
            for s, vals in values_by_snapshot.items()}


def _stats(clean: list, faulted: list) -> dict:
    c = _runs({s: clean for s in degrade.SNAPSHOTS})
    f = _runs({s: faulted for s in degrade.SNAPSHOTS})
    return {m: degrade.pooled(c, f, m) for m in degrade.METRICS}


def test_control_an_unmoved_metric_fails_every_target():
    stats = _stats([0.5, 0.5], [0.5, 0.5])
    decl = degrade.REGISTRY["rotate_verdicts"]
    assert len(degrade.check(decl, stats)) == len(decl["targets"])


def test_control_a_move_just_under_the_threshold_fails():
    stats = _stats([0.5, 0.5], [0.46, 0.46])
    assert degrade.check({"targets": {"recall_at_k": "down"}}, stats)
    assert not degrade.check({"targets": {"recall_at_k": "down"}}, _stats([0.5, 0.5], [0.44, 0.44]))


def test_control_a_move_in_the_wrong_direction_fails():
    stats = _stats([0.5, 0.5], [0.9, 0.9])
    assert degrade.check({"targets": {"recall_at_k": "down"}}, stats)
    assert not degrade.check({"targets": {"recall_at_k": "up"}}, stats)


def test_control_a_blind_fault_that_moved_fails():
    stats = _stats([0.5, 0.5], [0.3, 0.3])
    assert degrade.check({"blind": True, "targets": {}}, stats)


def test_control_an_unchanged_metric_that_changed_at_all_fails():
    stats = _stats([0.5, 0.5], [0.5, 0.5001])
    assert degrade.check({"targets": {}, "unchanged": ["recall_at_k"]}, stats)


def test_control_rotation_moves_bodies_and_keeps_ids():
    verdicts = [{"article_id": "a", "relevant": True}, {"article_id": "b", "relevant": False}]
    assert degrade._rotate_bodies(verdicts) == [{"article_id": "a", "relevant": False},
                                                {"article_id": "b", "relevant": True}]


def test_control_a_different_request_set_fails_the_offline_check():
    clean = {"snapshot": "s", "offline_misses_total": 0, "cache_misses_total": 0, "cache_keys_sha256": "x"}
    assert degrade.offline_failures({**clean, "cache_keys_sha256": "y"}, clean)
    assert degrade.offline_failures({**clean, "offline_misses_total": 3}, clean)
    assert not degrade.offline_failures(dict(clean), clean)


def test_control_raised_misses_fail_the_gate_even_with_zero_fetches():
    assert offline_violations({"cache_misses_total": 0, "offline_misses_total": 90})
    assert offline_violations({"cache_misses_total": 0})  # predates the counter: unproven
    assert offline_violations({"cache_misses_total": 0, "offline_misses_total": 0}) == []


def test_control_a_metric_that_became_none_is_a_regression():
    assert regression("judge_precision_mean", True, 0.62, None, 0.05)
    assert regression("recall_at_k_mean", True, 0.24, 0.18, 0.05)
    assert regression("never_rate_mean", False, 0.21, 0.30, 0.05)
    assert regression("recall_at_k_mean", True, 0.24, 0.20, 0.05) is None
    assert regression("recall_at_k_mean", True, None, None, 0.05) is None
