"""S6 independent-label and exact-oracle metrics; no database/provider calls."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from evals.retrieval import conditional_ann_recall, evaluate_candidate_batch, evaluate_retrieval


def candidate(identifier, intents=(), legs=()):
    return {"article_id": identifier, "matched_intent_ids": list(intents),
            "matches": [{"intent_id": "i", "leg": leg, "rank": 1, "score": 0.1} for leg in legs]}


def batch(*rows):
    return {"candidates": list(rows), "diagnostics": {"stop_reason": "budget_limited"}, "status": "degraded"}


def test_recall_does_not_shrink_denominator_to_k_or_available_embeddings():
    report = evaluate_candidate_batch(batch(candidate("a")), corpus_ids=["a", "b", "missing_vector"],
                                      positive_ids=["a", "b", "missing_vector"], k=1)
    assert report["raw_recall_at_k"] == 1 / 3
    assert report["capacity_ceiling"] == 1 / 3
    assert report["missing_ids"] == ["b", "missing_vector"]
    assert report["metric_scope"] == "in_pool_known_positive_recall"
    assert report["retrieval_diagnostics"]["stop_reason"] == "budget_limited"


def test_no_positives_is_undefined_not_perfect():
    report = evaluate_candidate_batch(batch(candidate("a")), corpus_ids=["a"], positive_ids=[])
    assert report["raw_recall_at_k"] is None
    assert report["capacity_ceiling"] is None
    assert report["positive_intent_coverage"] is None
    assert report["retrieved_unjudged_ids"] == ["a"]


def test_zero_k_is_zero_when_there_are_positives():
    report = evaluate_candidate_batch(batch(candidate("a")), corpus_ids=["a"], positive_ids=["a"], k=0)
    assert report["raw_recall_at_k"] == 0
    assert report["capacity_ceiling"] == 0
    assert report["returned_count"] == 0


def test_unjudged_candidates_are_not_negative_and_out_of_pool_is_acquisition_gap():
    report = evaluate_candidate_batch(batch(candidate("a"), candidate("unknown"), candidate("negative")),
                                      corpus_ids=["a", "unknown", "negative", "unseen"],
                                      positive_ids=["a", "outside"], judged_ids=["a", "outside", "negative"])
    assert report["raw_recall_at_k"] == 1
    assert report["positive_ids_outside_pool"] == ["outside"]
    assert report["retrieved_unjudged_ids"] == ["unknown"]
    assert report["retrieved_judged_nonpositive_ids"] == ["negative"]
    assert report["judgment_coverage"] == 0.5
    assert report["labels_complete"] is False


def test_complete_labels_require_full_corpus_judging():
    with pytest.raises(ValueError, match="whole frozen corpus"):
        evaluate_candidate_batch(batch(), corpus_ids=["a", "b"], positive_ids=["a"], labels_complete=True)
    report = evaluate_candidate_batch(batch(), corpus_ids=["a", "b"], positive_ids=["a"],
                                      judged_ids=["a", "b"], labels_complete=True)
    assert report["metric_scope"] == "in_pool_recall"


def test_complete_attestation_cannot_be_truthy_string():
    with pytest.raises(ValueError, match="boolean"):
        evaluate_candidate_batch(batch(), corpus_ids=[], positive_ids=[], labels_complete="false")


def test_per_intent_coverage_distinguishes_recovery_from_attribution():
    report = evaluate_candidate_batch(batch(candidate("shared", ["broad"])), corpus_ids=["shared", "rare"],
                                      positive_ids=["shared", "rare"],
                                      positives_by_intent={"broad": ["shared"], "niche": ["shared", "rare"], "empty": []})
    assert report["positive_intent_coverage"] == 1
    assert report["attributed_positive_intent_coverage"] == 0.5
    assert report["per_intent"]["niche"]["raw_recall_at_k"] == 0.5
    assert report["per_intent"]["niche"]["attributed_recall_at_k"] == 0
    assert report["per_intent"]["empty"]["raw_recall_at_k"] is None


def test_marginal_leg_contribution_preserves_shared_matches():
    report = evaluate_candidate_batch(batch(candidate("a", legs=["lexical", "semantic"]),
                                             candidate("b", legs=["identity"]), candidate("c", legs=["semantic"])),
                                      corpus_ids=["a", "b", "c"], positive_ids=["a", "b", "c"])
    assert report["marginal_legs"]["lexical"]["unique_positive_ids"] == []
    assert report["marginal_legs"]["identity"]["unique_positive_ids"] == ["b"]
    assert report["marginal_legs"]["semantic"]["unique_positive_ids"] == ["c"]


def test_loss_attribution_never_invents_ids_from_aggregate_diagnostics():
    report = evaluate_candidate_batch(batch(candidate("a")), corpus_ids=["a", "b", "c"], positive_ids=["a", "b", "c"],
                                      loss_ids={"missing_vector": ["a", "b"], "budget": ["b"]})
    assert report["loss_ids_by_stage"] == {"budget": ["b"], "missing_vector": ["b"]}
    assert report["unattributed_missing_ids"] == ["c"]


def test_slice_metrics_use_independent_labels_not_candidate_provenance():
    report = evaluate_candidate_batch(batch(candidate("a")), corpus_ids=["a", "b"], positive_ids=["a", "b"],
                                      slices={"language:tg": ["a", "b"], "language:en": []})
    assert report["slices"]["language:tg"]["raw_recall_at_k"] == 0.5
    assert report["slices"]["language:en"]["raw_recall_at_k"] is None


@pytest.mark.parametrize("rows", [(candidate("a"), candidate("a")), (candidate("outside"),)])
def test_broken_candidate_contract_is_rejected(rows):
    with pytest.raises(ValueError):
        evaluate_candidate_batch(batch(*rows), corpus_ids=["a"], positive_ids=[])


@pytest.mark.parametrize("k", [-1, 301, True, 1.5])
def test_invalid_k(k):
    with pytest.raises(ValueError):
        evaluate_candidate_batch(batch(), corpus_ids=[], positive_ids=[], k=k)


def test_invalid_label_contract():
    with pytest.raises(ValueError, match="independent judgment"):
        evaluate_candidate_batch(batch(), corpus_ids=["a"], positive_ids=["a"], judged_ids=[])
    with pytest.raises(ValueError, match="Per-intent positives"):
        evaluate_candidate_batch(batch(), corpus_ids=["a"], positive_ids=[], positives_by_intent={"i": ["a"]})
    with pytest.raises(ValueError, match="not a string"):
        evaluate_candidate_batch(batch(), corpus_ids="abc", positive_ids=[])


def test_ann_exact_oracle_requires_explicit_exhaustive_attestation():
    with pytest.raises(ValueError, match="exhaustive"):
        conditional_ann_recall(["a"], {"a": 0.1}, k=1)


def test_ann_boundary_ties_are_interchangeable_not_id_ordered():
    report = conditional_ann_recall(["a", "c"], {"a": 0.1, "b": 0.2, "c": 0.2, "d": 0.3}, k=2, exhaustive=True)
    assert report["conditional_ann_recall_at_k"] == 1
    assert report["boundary_tie_count"] == 2
    assert report["oracle_count"] == 4


def test_ann_extra_boundary_ties_do_not_replace_strictly_better_neighbor():
    report = conditional_ann_recall(["b", "c"], {"a": 0.1, "b": 0.2, "c": 0.2}, k=2, exhaustive=True)
    assert report["conditional_ann_recall_at_k"] == 0.5
    assert report["missing_strict_ids"] == ["a"]


def test_ann_outside_oracle_has_no_credit():
    report = conditional_ann_recall(["wrong_recipe", "a"], {"a": 0.1, "b": 0.2}, k=2, exhaustive=True)
    assert report["conditional_ann_recall_at_k"] == 0.5
    assert report["outside_oracle_ids"] == ["wrong_recipe"]


@pytest.mark.parametrize("oracle,k", [({}, 3), ({"a": 0.1}, 0)])
def test_ann_empty_denominator_is_undefined(oracle, k):
    assert conditional_ann_recall([], oracle, k=k, exhaustive=True)["conditional_ann_recall_at_k"] is None


@pytest.mark.parametrize("distance", [float("nan"), float("inf"), True, "0.1"])
def test_ann_invalid_geometry_values_rejected(distance):
    with pytest.raises(ValueError, match="finite"):
        conditional_ann_recall(["a"], {"a": distance}, k=1, exhaustive=True)


def test_runtime_evaluator_invokes_actual_builder_once_and_freezes_time():
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    result = {**batch(candidate("a")), "as_of": now.isoformat()}
    build = Mock(return_value=SimpleNamespace(model_dump=Mock(return_value=result)))
    conn = object()
    snapshot = {"profile": {"intents": []}, "generation": 1}
    report = evaluate_retrieval(build, conn, "user", snapshot, as_of=now, corpus_ids=["a", "b"], positive_ids=["a", "b"], k=10)
    build.assert_called_once_with(conn, "user", snapshot, limit=10, as_of=now)
    assert build.call_args.args[2] is not snapshot
    assert report["raw_recall_at_k"] == 0.5


def test_runtime_evaluator_rejects_naive_timestamp_before_builder():
    build = Mock()
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_retrieval(build, None, "user", {}, as_of=datetime(2026, 9, 7), corpus_ids=[], positive_ids=[])
    build.assert_not_called()


def test_runtime_evaluator_rejects_different_batch_time():
    build = Mock(return_value={**batch(), "as_of": "2026-09-06T00:00:00Z"})
    with pytest.raises(ValueError, match="frozen evaluation timestamp"):
        evaluate_retrieval(build, None, "user", {}, as_of=datetime(2026, 9, 7, tzinfo=timezone.utc), corpus_ids=[], positive_ids=[])
