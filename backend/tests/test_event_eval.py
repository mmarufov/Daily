"""Synthetic arithmetic/contract fixtures, never real event-quality evidence."""
import copy
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.events import digest, evaluate, split_digest, validate_report
from evals.events.contracts import Dataset, Prediction, Protocol
from evals.events.metrics import align, binomial_bound, membership, score

T = "2026-09-06T10:00:00Z"
LATE = "2026-09-06T10:06:00Z"


def fixture(count=2, critical=1):
    mentions, developments, predictions = [], [], []
    for i in range(count):
        mids = [f"m{i}-a", f"m{i}-b"]
        for mid in mids:
            mentions.append({"id": mid, "article_revision_sha256": digest(mid),
                             "evidence_sha256": digest([mid, "synthetic"]), "origin_id": mid,
                             "canonical_id": mid, "event_id": f"e{i}", "development_id": f"d{i}",
                             "available_at": T})
        is_critical = i < critical
        developments.append({"id": f"d{i}", "event_id": f"e{i}", "family_id": f"f{i}",
                             "window_id": f"w{i}", "independence_id": f"i{i}",
                             "split": "holdout", "slices": ["synthetic"], "event_type": "incident",
                             "place_key": f"place{i}", "occurred_start": T, "occurred_end": T,
                             "qualifies_at": T, "deadline_at": "2026-09-06T10:05:00Z", "eligible": True,
                             "core_mentions": mids, "direct_mentions": mids,
                             "tier": "world_critical" if is_critical else "routine", "material": is_critical,
                             "review": {"status": "adjudicated", "provenance": "agent", "reviewer": "test-fixture",
                                        "rationale": "Synthetic arithmetic only; not empirical labels",
                                        "reviewed_at": T, "blind_to_predictions": True}})
        predictions.append({"id": f"p{i}", "event_id": f"pe{i}", "status": "ready",
                            "tier": "world_critical" if is_critical else "routine", "material": is_critical,
                            "members": list(mids), "event_type": "incident", "place_key": f"place{i}",
                            "occurred_start": T, "occurred_end": T, "completed_at": T, "evidence_cutoff": T,
                            "representative_mention_id": mids[0]})
    dataset = {"schema_version": 1, "id": "synthetic-not-quality-evidence", "sampling": "complete_windows",
               "sampling_manifest_sha256": digest("synthetic"), "frozen_at": T,
               "mentions": mentions, "developments": developments}
    protocol = {"schema_version": 1, "status": "frozen", "approved_by": "test-fixture", "frozen_at": T,
                "supported_slices": ["synthetic"], "independent_opportunities_attested": True,
                "minimum_slice_developments": 1, "minimum_metric_denominator": 1,
                "fixed_adversarial_suite_sha256": digest("synthetic-adversarial-fixture"),
                "required_adversarial_cases": ["synthetic-test-only"]}
    execution = {"requests": 0, "cache_hits": 0, "cache_misses": 0, "known_usage_usd": 0.,
                 "unresolved_reserved_usd": 0., "budget_usd": 0., "ledger_sha256": digest("no-calls")}
    return dataset, predictions, protocol, execution


def bindings(data, protocol):
    return {"recipe_sha256": digest("s4-fixture"), "s3_recipe_sha256": digest("s3-fixture"),
            "source_registry_sha256": digest("registry-fixture"), "dataset_sha256": digest(data),
            "protocol_sha256": digest(protocol), "split_sha256": split_digest(data)}


def run(data, predictions, protocol, execution):
    # These explicitly synthetic reviews exercise arithmetic only. No generated
    # review is ever written to a real dataset or accepted as empirical proof.
    reviewer = {"status": "adjudicated", "provenance": "agent", "reviewer": "test-fixture",
                "rationale": "Synthetic arithmetic only", "reviewed_at": T}
    reviews = [{"prediction_id": p["id"], "prediction_sha256": digest(p), "unsupported_assertions": 0,
                "direct_support": True, "review": reviewer} for p in predictions]
    adversarial = {"suite_sha256": digest("synthetic-adversarial-fixture"),
                   "evaluation_sha256": digest("synthetic-fixture-result"), "review": reviewer,
                   "evaluation_binding_sha256": digest(bindings(data, protocol)),
                   "cases": [{"case_id": "synthetic-test-only", "false_critical_promotions": 0,
                              "unsupported_assertions": 0}]}
    return evaluate(data, predictions, protocol, bindings=bindings(data, protocol), execution=execution,
                    outcome_reviews=reviews, adversarial=adversarial)


def test_one_to_one_duplicates_cannot_multiply_true_positives():
    d, p, policy, e = fixture()
    p.append({**p[0], "id": "duplicate", "event_id": "duplicate-event"})
    m = run(d, p, policy, e)["metrics"]
    assert len(m["alignment"]) == 2
    assert m["critical"]["precision"]["value"] == .5
    assert m["critical"]["recall"]["value"] == 1


@pytest.mark.parametrize("status", ["unknown", "failed", "pending", "unsupported", "missing", "late"])
def test_absent_or_late_predictions_remain_recall_misses(status):
    d, p, policy, e = fixture()
    if status == "missing":
        p = p[1:]
    elif status == "late":
        p[0]["completed_at"] = LATE
    else:
        p[0].update(status=status, tier=None, material=None)
    m = run(d, p, policy, e)["metrics"]
    assert m["critical"]["recall"] == {"numerator": 0, "denominator": 1, "value": 0}


def test_wrong_place_and_topic_bridge_do_not_get_multiple_alignment_credit():
    d, p, policy, e = fixture(3, 2)
    p[0]["members"] += p[1]["members"]
    p[1]["place_key"] = "wrong-place"
    m = run(d, p, policy, e)["metrics"]
    assert len(m["alignment"]) == 2
    assert m["critical"]["recall"]["value"] == .5
    assert m["event_membership"]["ambiguous_mentions"] > 0


def test_negative_rate_counts_decision_opportunities_not_slots_or_duplicate_predictions():
    d, p, policy, e = fixture(3, 1)
    p[1].update(tier="world_critical", material=True)
    p.append({**p[1], "id": "again"})
    m = run(d, p, policy, e)["metrics"]
    assert m["negative_decisions"]["value"] == .5
    assert m["critical"]["precision"]["value"] == pytest.approx(1 / 3)
    assert m["unchanged_fact_alerts"] >= 1


def test_syndicated_canonical_mentions_do_not_inflate_pair_denominators():
    d, p, policy, e = fixture(1)
    d["mentions"].append({**d["mentions"][0], "id": "syndicated-copy"})
    p[0]["members"].append("syndicated-copy")
    m = run(d, p, policy, e)["metrics"]
    assert m["event_membership"]["canonical_mentions"] == 2
    assert m["event_membership"]["precision"]["denominator"] == 1


@pytest.mark.parametrize("key", ["family_id", "window_id", "event_id"])
def test_family_window_event_split_leakage_rejected(key):
    d, p, policy, e = fixture()
    d["developments"][1][key] = d["developments"][0][key]
    d["developments"][1]["split"] = "development"
    if key == "event_id":
        for m in d["mentions"][2:]:
            m["event_id"] = "e0"
    with pytest.raises(ValueError, match="leaks across splits"):
        run(d, p, policy, e)


def test_syndicated_origin_split_leakage_rejected():
    d, p, policy, e = fixture()
    d["mentions"][2]["origin_id"] = d["mentions"][0]["origin_id"]
    d["developments"][1]["split"] = "development"
    with pytest.raises(ValueError, match="leaks across splits"):
        run(d, p, policy, e)


@pytest.mark.parametrize("sampling", ["balanced", "adversarial", "probability_sample"])
def test_nonrepresentative_or_unimplemented_weighted_estimator_cannot_promote(sampling):
    d, p, policy, e = fixture()
    d["sampling"] = sampling
    report = run(d, p, policy, e)
    assert "population_estimator_not_implemented_for_sampling_design" in report["blockers"]
    assert not report["quality_gates_passed"]


@pytest.mark.parametrize("key", ["family_id", "window_id", "independence_id"])
def test_correlated_opportunities_cannot_borrow_independent_bounds(key):
    d, p, policy, e = fixture()
    d["developments"][1][key] = d["developments"][0][key]
    report = run(d, p, policy, e)
    assert "correlated_or_unattested_opportunities_require_blocked_interval" in report["blockers"]


def test_tiny_perfect_sample_is_not_quality_proof():
    report = run(*fixture())
    assert report["metrics"]["critical"]["precision"]["value"] == 1
    assert report["metrics"]["critical"]["precision_lower_95"] == pytest.approx(.05)
    assert not report["quality_gates_passed"]
    assert not report["release_ready"]


def test_exact_one_sided_binomial_examples_and_nontrivial_bound():
    assert binomial_bound(0, 600, side="upper") == pytest.approx(.004980443, abs=1e-8)
    assert binomial_bound(300, 300, side="lower") == pytest.approx(.9900639, abs=1e-7)
    # Published formula inversion, n=2,k=1: P(X>=1)=.05 -> p=1-sqrt(.95).
    assert binomial_bound(1, 2, side="lower") == pytest.approx(1 - .95 ** .5)
    assert binomial_bound(1, 2, side="upper") == pytest.approx(.95 ** .5)
    assert binomial_bound(0, 0, side="lower") is None
    with pytest.raises(ValueError):
        binomial_bound(True, 2, side="upper")


@pytest.mark.parametrize("where", ["pred_id", "pred_members", "pred_time", "gold_future", "gold_seed", "unknown_representative"])
def test_invalid_artifacts_never_silently_normalize(where):
    d, p, policy, e = fixture()
    if where == "pred_id":
        p[0]["id"] = True
    elif where == "pred_members":
        p[0]["members"].append("invented")
    elif where == "pred_time":
        p[0]["completed_at"] = "2026-09-06T10:00:00"
    elif where == "gold_future":
        d["mentions"][0]["available_at"] = LATE
    elif where == "gold_seed":
        d["developments"][0]["review"]["provenance"] = "model"
    else:
        p[0]["representative_mention_id"] = "invented"
    with pytest.raises(ValueError):
        run(d, p, policy, e)


def test_model_seeds_and_unsupported_slices_return_blocked_report():
    d, p, policy, e = fixture()
    d["developments"][0]["review"].update(status="model_seed", provenance="model")
    policy["supported_slices"] = []
    report = run(d, p, policy, e)
    assert "labels_not_independently_adjudicated" in report["blockers"]
    assert "supported_slices_empty" in report["blockers"]


def test_bindings_and_accounting_are_mandatory():
    d, p, policy, e = fixture()
    b = bindings(d, policy)
    b["dataset_sha256"] = digest("different")
    with pytest.raises(ValueError, match="binding mismatch"):
        evaluate(d, p, policy, bindings=b)
    report = evaluate(d, p, policy, bindings=bindings(d, policy))
    assert "missing_complete_execution_accounting" in report["blockers"]
    e.update(cache_misses=1, unresolved_reserved_usd=.1)
    report = run(d, p, policy, e)
    assert {"offline_replay_cache_misses", "unresolved_provider_accounting", "execution_budget_exceeded"} <= set(report["blockers"])


def test_report_integrity_and_blocked_report_cannot_be_promoted():
    d, p, policy, e = fixture()
    report = run(d, p, policy, e)
    with pytest.raises(ValueError, match="have not passed"):
        validate_report(report, bindings(d, policy))
    report["quality_gates_passed"] = True
    with pytest.raises(ValueError, match="integrity"):
        validate_report(report, bindings(d, policy))


def test_sufficient_synthetic_arithmetic_fixture_can_exercise_positive_gate():
    # This is a test of the gate arithmetic only, not production-quality labels.
    d, p, policy, e = fixture(900, 300)
    report = run(d, p, policy, e)
    assert report["blockers"] == []
    assert report["quality_gates_passed"]
    assert not report["release_ready"]
    assert validate_report(report, bindings(d, policy))


def test_omitted_representative_does_not_shrink_denominator():
    d, p, policy, e = fixture()
    p[0]["representative_mention_id"] = None
    report = run(d, p, policy, e)
    assert report["metrics"]["representative"] == {"numerator": 1, "denominator": 2, "value": .5}


def test_upstream_missing_critical_is_visible_in_end_to_end_not_conditional_recall():
    d, p, policy, e = fixture(3, 2)
    d["developments"][0]["eligible"] = False
    p = p[1:]
    metrics = run(d, p, policy, e)["metrics"]
    assert metrics["critical"]["recall"]["value"] == 1.
    assert metrics["end_to_end_critical_recall"] == {"numerator": 1, "denominator": 2, "value": .5}
    assert metrics["upstream_unavailable_critical"] == 1


def test_shared_reporting_origin_prevents_independent_binomial_promotion():
    d, p, policy, e = fixture()
    d["mentions"][2]["origin_id"] = d["mentions"][0]["origin_id"]
    report = run(d, p, policy, e)
    assert "correlated_or_unattested_opportunities_require_blocked_interval" in report["blockers"]


def test_wrong_representative_is_a_zero_tolerance_gate():
    d, p, policy, e = fixture()
    d["developments"][0]["direct_mentions"] = ["m0-b"]
    report = run(d, p, policy, e)
    assert report["metrics"]["invalid_representatives"] == 1
    assert "invalid_representatives" in report["blockers"]


def test_adversarial_evidence_must_bind_exact_candidate():
    d, p, policy, e = fixture()
    existing = run(d, p, policy, e)
    existing["adversarial"]["evaluation_binding_sha256"] = digest("older-candidate")
    report = evaluate(d, p, policy, bindings=bindings(d, policy), execution=e,
                      outcome_reviews=existing["outcome_reviews"], adversarial=existing["adversarial"])
    assert "different_adversarial_candidate_bindings" in report["blockers"]


@pytest.mark.parametrize("field", ["value", "numerator", "denominator", "confidence"])
def test_rehashed_report_cannot_have_inconsistent_rates_or_confidence(field):
    d, p, policy, e = fixture(900, 300)
    report = run(d, p, policy, e)
    if field == "confidence":
        report["metrics"]["critical"]["precision_lower_95"] = 1.
    else:
        report["metrics"]["critical"]["precision"][field] = {"value": .99, "numerator": 1,
                                                                 "denominator": True}[field]
    report["report_sha256"] = digest({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="Quality|quality"):
        validate_report(report, bindings(d, policy))
