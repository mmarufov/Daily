from copy import deepcopy

import pytest

from app.services.event_grouping import choose_match, cosine, rank_candidates, relation
from tests.test_event_contract import evidence


def test_default_uncalibrated_recipe_never_merges_even_identical_signatures():
    assert relation(evidence(1), evidence(2))["relation"] == "insufficient"
    assert choose_match([{"event_id": "a", "score": 1, "relation": "same_development"}])["event_id"] is None


@pytest.mark.parametrize("value", ["false", "true", 1, 0, None])
def test_calibration_flag_cannot_be_enabled_by_truthy_config_coercion(value):
    with pytest.raises(ValueError):
        relation(evidence(), evidence(2), calibrated=value)
    with pytest.raises(ValueError):
        choose_match([], calibrated=value)


def test_candidate_embedding_cohort_cannot_mix_recipes():
    other = evidence(2)
    other["dependency"]["s3_recipe_id"] = "different-space"
    with pytest.raises(ValueError, match="mixes"):
        rank_candidates(evidence(), [other], query_vector=[1], vectors={"evd-2": [1]})


def test_calibrated_exact_signature_groups_supported_core_development_only():
    assert relation(evidence(1), evidence(2), calibrated=True)["relation"] == "same_development"
    assert relation(evidence(1), evidence(2, role="background"), calibrated=True)["relation"] != "same_development"


@pytest.mark.parametrize("key,value", [("actor_ids", []), ("place_ids", []), ("object", None),
                                      ("modality", "denied"), ("modality", "unknown"), ("modality", "corrected")])
def test_unknown_identity_or_modality_does_not_merge(key, value):
    second = evidence(2)
    second["claim"][key] = value
    assert relation(evidence(), second, calibrated=True)["relation"] != "same_development"


def test_same_place_different_day_is_different_development_not_same_event_proof():
    second = evidence(2)
    second["claim"]["occurrence"].update(start="2026-09-07T10:00:00Z", end="2026-09-07T10:00:00Z")
    assert relation(evidence(), second, calibrated=True)["relation"] == "different"


def test_unresolved_entity_still_has_lexical_or_vector_recall():
    query, other = evidence(1), evidence(2)
    query["claim"]["actor_ids"] = []
    other["claim"]["actor_ids"] = []
    assert rank_candidates(query, [other])[0]["evidence_id"] == "evd-2"
    other["claim"].update(action="different", object="unrelated")
    assert rank_candidates(query, [other]) == []
    assert rank_candidates(query, [other], query_vector=[1, 0], vectors={"evd-2": [1, 0]})[0]["cosine"] == 1


def test_candidate_order_deterministic_and_not_a_membership_decision():
    a, b = evidence(2), evidence(3)
    assert rank_candidates(evidence(), [a, b]) == rank_candidates(evidence(), [b, a])
    assert "relation" not in rank_candidates(evidence(), [a])[0]


def test_candidate_intake_and_limit_are_explicitly_bounded():
    with pytest.raises(ValueError):
        rank_candidates(evidence(), [evidence(i) for i in range(129)])
    with pytest.raises(ValueError):
        rank_candidates(evidence(), [], limit=True)
    with pytest.raises(ValueError):
        rank_candidates(evidence(), [evidence(2), evidence(2)])


@pytest.mark.parametrize("left,right", [([], []), ([0], [1]), ([True], [1]), ([float("nan")], [1]),
                                      ([float("inf")], [1]), ([1, 2], [1]), ("[1]", [1])])
def test_invalid_vectors_are_not_similarity_evidence(left, right):
    assert cosine(left, right) is None


def test_candidate_tie_abstains_not_first_match():
    rows = [{"event_id": "a", "score": .95, "relation": "same_development"},
            {"event_id": "b", "score": .94, "relation": "same_event_new_development"}]
    options = dict(calibrated=True, minimum_score=.9, margin=.05)
    assert choose_match(rows, **options) == choose_match(list(reversed(rows)), **options)
    assert choose_match(rows, **options)["event_id"] is None
    rows[1]["score"] = .7
    assert choose_match(rows, **options)["event_id"] == "a"


def test_related_topic_is_never_accepted_event_match():
    assert choose_match([{"event_id": "topic-a", "score": 1, "relation": "related_only"}],
                        calibrated=True, minimum_score=.9, margin=.05)["event_id"] is None


@pytest.mark.parametrize("value", [None, True, 0, -1, float("nan"), float("inf")])
def test_calibrated_thresholds_are_required(value):
    with pytest.raises(ValueError):
        choose_match([], calibrated=True, minimum_score=value, margin=.05)


def test_duplicate_adjudicated_event_and_nonfinite_score_fail():
    row = {"event_id": "a", "score": .9, "relation": "same_development"}
    for rows in ([row, row], [{**row, "score": float("nan")}], [{**row, "sql": "anything"}]):
        with pytest.raises(ValueError):
            choose_match(rows, calibrated=True, minimum_score=.9, margin=.05)
