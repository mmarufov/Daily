"""Promotion must require matching quality and real operational evidence."""
from copy import deepcopy

import pytest

from scripts.manage_s3_understanding import parser, validate_promotion


def promotion_evidence():
    return {"recipe_id": "recipe-test", "quality_gates_passed": True, "blockers": [],
            "supported_slices": ["en:title_summary"], "operations": {
                "build_sha": "a" * 40, "schema_version": 1,
                "s1_s2_verified": True, "rollback_verified": True,
                "quiet_and_burst_verified": True, "observation_hours": 72,
                "reviewed_articles": 600, "holdout_articles": 150,
                "ready_fraction": .99, "filtered_ann_recall_at_50": .98,
                "load_multiplier": 2, "stale_publications": 0,
                "wrong_article_evidence": 0, "private_text_leaks": 0,
                "mixed_spaces": 0, "budget_verified": True}}


def test_valid_evidence_passes_and_mutations_are_not_applied():
    doc = promotion_evidence()
    original = deepcopy(doc)
    validate_promotion(doc, "recipe-test")
    assert doc == original
    assert parser().parse_args(["promote"]).apply is False
    assert parser().parse_args(["configure"]).daily_budget_usd == 0


@pytest.mark.parametrize("field,value", [
    ("recipe_id", "other-recipe"), ("quality_gates_passed", False),
    ("quality_gates_passed", 1), ("blockers", ["unmeasured"]),
    ("supported_slices", []), ("operations", None),
])
def test_promotion_rejects_missing_quality_or_recipe_identity(field, value):
    doc = promotion_evidence()
    doc[field] = value
    with pytest.raises(ValueError):
        validate_promotion(doc, "recipe-test")


@pytest.mark.parametrize("field", ["s1_s2_verified", "rollback_verified", "quiet_and_burst_verified", "budget_verified"])
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_promotion_requires_explicit_verified_operational_flags(field, value):
    doc = promotion_evidence()
    doc["operations"][field] = value
    with pytest.raises(ValueError):
        validate_promotion(doc, "recipe-test")


@pytest.mark.parametrize("field", ["observation_hours", "reviewed_articles", "holdout_articles", "ready_fraction", "filtered_ann_recall_at_50", "load_multiplier"])
@pytest.mark.parametrize("value", [0, None, "999", True, float("nan"), float("inf")])
def test_promotion_rejects_invalid_or_insufficient_measurements(field, value):
    doc = promotion_evidence()
    doc["operations"][field] = value
    with pytest.raises(ValueError):
        validate_promotion(doc, "recipe-test")


@pytest.mark.parametrize("field", ["stale_publications", "wrong_article_evidence", "private_text_leaks", "mixed_spaces"])
@pytest.mark.parametrize("value", [None, -1, 1, "0", False, True, 0.0])
def test_integrity_failures_and_absent_counters_block_promotion(field, value):
    doc = promotion_evidence()
    doc["operations"][field] = value
    with pytest.raises(ValueError):
        validate_promotion(doc, "recipe-test")


@pytest.mark.parametrize("field", ["ready_fraction", "filtered_ann_recall_at_50"])
@pytest.mark.parametrize("value", [1.000001, 2, 99])
def test_operational_fractions_cannot_exceed_one(field, value):
    doc = promotion_evidence()
    doc["operations"][field] = value
    with pytest.raises(ValueError, match="fraction exceeds one"):
        validate_promotion(doc, "recipe-test")


def test_perfect_operational_fractions_are_valid():
    doc = promotion_evidence()
    doc["operations"]["ready_fraction"] = 1
    doc["operations"]["filtered_ann_recall_at_50"] = 1.0
    validate_promotion(doc, "recipe-test")


@pytest.mark.parametrize("field,value", [("reviewed_articles", 600.0), ("holdout_articles", 150.5),
                                         ("holdout_articles", 601), ("schema_version", True),
                                         ("schema_version", 1.0), ("schema_version", -1),
                                         ("build_sha", True), ("build_sha", "   ")])
def test_operational_metadata_and_counts_require_correct_types(field, value):
    doc = promotion_evidence()
    doc["operations"][field] = value
    with pytest.raises(ValueError):
        validate_promotion(doc, "recipe-test")


@pytest.mark.parametrize("value", [None, [], "passing", 1])
def test_report_requires_an_object(value):
    with pytest.raises(ValueError):
        validate_promotion(value, "recipe-test")


@pytest.mark.parametrize("field,value", [("operations", []), ("operations", "verified"),
                                         ("blockers", None), ("blockers", False),
                                         ("supported_slices", "en:title_summary"),
                                         ("supported_slices", True), ("supported_slices", [""]),
                                         ("supported_slices", [1])])
def test_report_shape_is_fail_closed(field, value):
    doc = promotion_evidence()
    doc[field] = value
    with pytest.raises(ValueError):
        validate_promotion(doc, "recipe-test")
