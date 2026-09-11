from copy import deepcopy

import pytest

from app.services.event_contract import digest
from app.services.event_delta import claim_fingerprint, compare_snapshots
from tests.test_event_contract import evidence, snapshot


def next_snapshot(prior, **changes):
    result = {**prior, "generation": prior["generation"] + 1,
              "previous_snapshot_hash": digest(prior)}
    result.pop("dependency_digest")
    result.update(changes)
    return snapshot(**result)


def test_exact_repeat_changes_support_not_fact_and_never_realerts():
    prior = snapshot(evidence=[evidence()])
    current = next_snapshot(prior, evidence=[evidence(), evidence(2)])
    result = compare_snapshots(prior, current)
    assert result["kind"] == "support_only"
    assert result["added_claims"] == []
    assert result["automatic_realert"] is False


def test_identical_dependencies_remain_unchanged():
    prior = snapshot()
    assert compare_snapshots(prior, next_snapshot(prior))["kind"] == "unchanged"


def test_new_claim_is_candidate_not_automatic_fact_or_realert():
    prior = snapshot()
    new = evidence(3)
    new["claim"]["object"] = "expanded evacuation order"
    result = compare_snapshots(prior, next_snapshot(prior, evidence=[*prior["evidence"], new]))
    assert result["kind"] == "material_candidate"
    assert result["requires_adjudication"] and not result["automatic_realert"]


@pytest.mark.parametrize("modality", ["denied", "disputed", "corrected", "retracted"])
def test_negation_and_correction_are_not_paraphrase(modality):
    prior = snapshot()
    new = evidence(3, role="contradiction")
    new["claim"]["modality"] = modality
    current = next_snapshot(prior, evidence=[*prior["evidence"], new])
    assert compare_snapshots(prior, current)["kind"] == "correction_candidate"
    assert claim_fingerprint(new["claim"]) != claim_fingerprint(prior["evidence"][0]["claim"])


@pytest.mark.parametrize("modality", ["unknown", "predicted", "alleged"])
def test_uncertain_new_claim_is_not_confirmed_occurrence(modality):
    prior = snapshot()
    new = evidence(3)
    new["claim"]["modality"] = modality
    current = next_snapshot(prior, evidence=[*prior["evidence"], new])
    assert compare_snapshots(prior, current)["kind"] == "insufficient"


def test_removed_fact_requires_correction_review():
    first, second = evidence(), evidence(2)
    second["claim"]["object"] = "separate consequence"
    prior = snapshot(evidence=[first, second])
    assert compare_snapshots(prior, next_snapshot(prior, evidence=[first]))["kind"] == "correction_candidate"


def test_incomplete_input_is_explicit_insufficient():
    current = snapshot(coverage={"complete": False, "supported": True, "observed_through": "2026-09-06T12:00:00Z"})
    assert compare_snapshots(None, current)["kind"] == "insufficient"


@pytest.mark.parametrize("changes", [{"event_id": "other"}, {"recipe_id": "other"},
                                    {"generation": 1}, {"previous_snapshot_hash": "0" * 64}])
def test_delta_requires_exact_monotonic_history(changes):
    prior = snapshot()
    with pytest.raises(ValueError):
        compare_snapshots(prior, next_snapshot(prior, **changes))


def test_claim_hash_ignores_evidence_reference_and_cosmetic_case_not_attribution():
    a, b = evidence(1)["claim"], evidence(2)["claim"]
    b["action"] = "  ISSUED  "
    assert claim_fingerprint(a) == claim_fingerprint(b)
    b["attribution"] = "Different claimant"
    assert claim_fingerprint(a) != claim_fingerprint(b)


def test_missing_prior_does_not_accept_claimed_history():
    with pytest.raises(ValueError):
        compare_snapshots(None, snapshot(previous_snapshot_hash="0" * 64))


def test_no_facts_or_unrefined_mentions_are_not_silent_no_change():
    assert compare_snapshots(None, snapshot(evidence=[]))["kind"] == "insufficient"
    assert compare_snapshots(None, snapshot(evidence=[evidence(role="unknown")]))["kind"] == "insufficient"


def test_equal_instants_with_different_offsets_are_same_fact():
    a, b = evidence(1)["claim"], evidence(2)["claim"]
    b["occurrence"].update(start="2026-09-06T12:00:00+02:00", end="2026-09-06T12:00:00+02:00")
    assert claim_fingerprint(a) == claim_fingerprint(b)
