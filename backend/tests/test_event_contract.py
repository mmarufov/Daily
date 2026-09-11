"""S4 structural/authorization invariants; fixtures are not semantic labels."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.services.event_contract import (
    DIMENSIONS, assessment_schema, dependency_digest, digest, priority_eligible,
    snapshot_hash, snapshot_schema, validate_assessment, validate_snapshot,
)
from app.services.event_evidence import build_snapshot


AS_OF = "2026-09-06T12:00:00+00:00"


def evidence(index=1, **changes):
    identifier = f"evd-{index}"
    quote = "The council issued an evacuation order."
    result = {
        "id": identifier,
        "dependency": {
            "article_id": f"article-{index}", "semantic_revision": 2, "eligibility_generation": 3,
            "input_hash": digest(["input", index]), "s3_recipe_id": "s3-recipe",
            "facets_result_id": f"facets-{index}", "embedding_result_id": f"embedding-{index}",
            "cluster_id": None, "membership_version": None, "cluster_version": None,
            "source_id": f"source-{index}", "source_generation": 1,
            "artifact_id": None, "artifact_hash": None,
        },
        "hint_index": 0, "hint_hash": digest(["hint", index]), "role": "core",
        "claim": {"actor_ids": ["council-a"], "action": "issued", "object": "evacuation order",
                  "place_ids": ["city-a"], "modality": "reported", "attribution": "Council",
                  "occurrence": {"start": "2026-09-06T10:00:00+00:00", "end": "2026-09-06T10:00:00+00:00",
                                 "precision": "instant", "evidence_ids": [identifier]}},
        "source": {"publisher_id": f"publisher-{index}", "reporting_origin_id": f"origin-{index}",
                   "origin_status": "verified", "primary_verified": False, "language": "en"},
        "spans": [{"field": "title", "field_hash": digest(quote), "start": 0, "end": len(quote), "quote": quote}],
        "observed_at": "2026-09-06T11:00:00+00:00", "published_at": "2026-09-06T10:30:00+00:00",
    }
    result.update(changes)
    return result


def snapshot(**changes):
    result = dict(event_id="event-a", generation=1, recipe_id="s4-recipe", s3_control_generation=1,
                  s4_control_generation=1, member_generation=1, as_of=AS_OF,
                  evidence=[evidence(1), evidence(2)],
                  coverage={"complete": True, "supported": True, "observed_through": AS_OF})
    result.update(changes)
    return build_snapshot(**result)


def assessment(frozen, **changes):
    ids = [item["id"] for item in frozen["evidence"]]
    result = {"event_id": frozen["event_id"], "generation": frozen["generation"], "recipe_id": frozen["recipe_id"],
              "snapshot_hash": snapshot_hash(frozen), "status": "ready", "tier": "world_critical",
              "dimensions": [{"name": name, "value": "met", "evidence_ids": ids} for name in DIMENSIONS],
              "scope": {"kind": "local", "place_ids": ["city-a"], "sectors": [], "evidence_ids": ids},
              "reason_codes": ["supported_consequence"], "evidence_ids": ids,
              "valid_until": "2026-09-06T15:00:00+00:00"}
    result.update(changes)
    return result


def resign(frozen):
    frozen["dependency_digest"] = dependency_digest(frozen["evidence"])
    return frozen


def test_private_strict_schemas_reject_unknown_fields_and_have_required_nullable_fields():
    for schema in (snapshot_schema(), assessment_schema()):
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        for child in schema.get("$defs", {}).values():
            assert child["additionalProperties"] is False
            assert set(child["required"]) == set(child["properties"])
    frozen = snapshot()
    with pytest.raises(ValueError):
        validate_snapshot({**frozen, "force": True})
    with pytest.raises(ValueError):
        validate_assessment({**assessment(frozen), "sql": "DROP TABLE"}, frozen)


@pytest.mark.parametrize("key", ["generation", "member_generation", "s3_control_generation", "s4_control_generation"])
@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "1"])
def test_generations_reject_bool_coercion_and_nonpositive(key, value):
    with pytest.raises(ValueError):
        validate_snapshot({**snapshot(), key: value})


@pytest.mark.parametrize("value", ["2026-09-06", "2026-09-06T12:00:00", "not-a-date", 123, True])
def test_cutoff_requires_offset_bearing_time(value):
    with pytest.raises(ValueError):
        validate_snapshot({**snapshot(), "as_of": value})


def test_complete_negative_manifest_is_pinned_and_missing_rows_fail():
    negative = evidence(3, role="contradiction")
    negative["claim"]["modality"] = "denied"
    frozen = snapshot(evidence=[evidence(), negative])
    corrupted = deepcopy(frozen)
    corrupted["evidence"].pop()
    with pytest.raises(ValueError, match="manifest"):
        validate_snapshot(corrupted)
    changed = deepcopy(frozen)
    changed["evidence"][1]["claim"]["modality"] = "corrected"
    assert dependency_digest(changed["evidence"]) != frozen["dependency_digest"]
    assert snapshot_hash(resign(changed)) != snapshot_hash(frozen)


def test_empty_evidence_is_representable_but_cannot_authorize():
    frozen = snapshot(evidence=[])
    result = assessment(frozen, status="insufficient", tier=None, valid_until=None)
    assert validate_assessment(result, frozen)["status"] == "insufficient"
    assert not priority_eligible(result, frozen, now=AS_OF)
    with pytest.raises(ValueError):
        validate_assessment(assessment(frozen), frozen)


def test_future_cutoff_cannot_be_authorized_before_it_exists():
    frozen = snapshot()
    with pytest.raises(ValueError, match='future'):
        validate_assessment(assessment(frozen), frozen, now='2026-09-06T11:59:59+00:00')


def test_routine_requires_an_actual_low_consequence_judgment():
    frozen = snapshot()
    result = assessment(frozen, tier='routine')
    with pytest.raises(ValueError, match='affirmative'):
        validate_assessment(result, frozen)
    for dim in result['dimensions']:
        if dim['name'] == 'consequence':
            dim['value'] = 'not_met'
    assert validate_assessment(result, frozen)['tier'] == 'routine'


def test_snapshot_rejects_duplicate_ids_and_mixed_article_revisions():
    with pytest.raises(ValueError, match="duplicate"):
        snapshot(evidence=[evidence(), evidence()])
    second = evidence(2)
    second["dependency"]["article_id"] = "article-1"
    with pytest.raises(ValueError, match="mixed article"):
        snapshot(evidence=[evidence(), second])


def test_mixed_recipe_and_source_versions_fail_closed():
    second = evidence(2)
    second["dependency"]["s3_recipe_id"] = "experimental-s3"
    with pytest.raises(ValueError, match="mixed S3"):
        snapshot(evidence=[evidence(), second])
    second = evidence(2)
    second["dependency"].update(source_id="source-1", source_generation=2)
    with pytest.raises(ValueError, match="mixed source"):
        snapshot(evidence=[evidence(), second])


@pytest.mark.parametrize("changes", [{"cluster_id": "cluster-a"}, {"membership_version": 1},
                                    {"cluster_version": 2}, {"artifact_id": "artifact-a"},
                                    {"artifact_hash": "a" * 64}, {"source_generation": True}])
def test_partial_dependency_references_fail(changes):
    item = evidence()
    item["dependency"].update(changes)
    with pytest.raises(ValueError):
        snapshot(evidence=[item])


def test_future_observation_and_coverage_are_not_replayed_as_known():
    with pytest.raises(ValueError, match="future"):
        snapshot(evidence=[evidence(observed_at="2026-09-07T10:00:00Z")])
    with pytest.raises(ValueError, match="coverage cutoff"):
        snapshot(coverage={"complete": True, "supported": True, "observed_through": "2026-09-07T10:00:00Z"})


@pytest.mark.parametrize("change", [{"start": 2}, {"end": 2}, {"field": "body"}, {"start": True}])
def test_invalid_original_span_structure_fails(change):
    item = evidence()
    item["spans"][0].update(change)
    with pytest.raises(ValueError):
        snapshot(evidence=[item])


@pytest.mark.parametrize("change", [
    {"precision": "unknown"}, {"evidence_ids": []}, {"evidence_ids": ["missing"]},
    {"start": "2026-09-07T12:00:00Z"}, {"end": None}, {"start": "2026-09-06"},
])
def test_occurrence_does_not_invent_or_reverse_supported_bounds(change):
    item = evidence()
    item["claim"]["occurrence"].update(change)
    with pytest.raises(ValueError):
        snapshot(evidence=[item])


def test_evidence_sort_has_same_hash_for_same_input_set():
    assert snapshot(evidence=[evidence(2), evidence(1)]) == snapshot()


@pytest.mark.parametrize("status", ["insufficient", "unsupported", "disputed", "pending", "error", "stale"])
def test_nonready_is_never_routine_and_cannot_have_expiry(status):
    frozen = snapshot()
    valid = assessment(frozen, status=status, tier=None, valid_until=None)
    assert validate_assessment(valid, frozen)["tier"] is None
    for change in ({"tier": "routine"}, {"valid_until": "2026-09-06T15:00:00Z"}):
        with pytest.raises(ValueError):
            validate_assessment({**valid, **change}, frozen)


@pytest.mark.parametrize("key,value", [("event_id", "wrong"), ("generation", 2), ("generation", True),
                                      ("recipe_id", "wrong"), ("snapshot_hash", "0" * 64)])
def test_assessment_exact_identity(key, value):
    frozen = snapshot()
    with pytest.raises(ValueError):
        validate_assessment({**assessment(frozen), key: value}, frozen)


@pytest.mark.parametrize("expiry", [AS_OF, "2026-09-06T10:00:00Z", "2026-09-08T12:00:00Z", "2026-09-06T15:00:00"])
def test_expiry_bounded_relative_to_snapshot(expiry):
    frozen = snapshot()
    with pytest.raises(ValueError):
        validate_assessment(assessment(frozen, valid_until=expiry), frozen)


def test_expiry_enforced_at_exact_authorization_time():
    frozen = snapshot()
    result = assessment(frozen)
    assert priority_eligible(result, frozen, now=AS_OF)
    assert not priority_eligible(result, frozen, now=result["valid_until"])
    with pytest.raises(ValueError):
        priority_eligible(result, frozen, now=None)


@pytest.mark.parametrize("member", ["evidence_ids", "scope", "dimensions"])
def test_every_assessment_reference_must_exist(member):
    frozen = snapshot()
    result = assessment(frozen)
    if member == "evidence_ids": result[member] = ["missing"]
    elif member == "scope": result[member]["evidence_ids"] = ["missing"]
    else: result[member][0]["evidence_ids"] = ["missing"]
    with pytest.raises(ValueError):
        validate_assessment(result, frozen)


def test_unknown_or_duplicate_dimensions_do_not_pass():
    frozen = snapshot()
    result = assessment(frozen)
    result["dimensions"][0] = deepcopy(result["dimensions"][1])
    with pytest.raises(ValueError):
        validate_assessment(result, frozen)
    result = assessment(frozen)
    result["dimensions"][0]["value"] = "unknown"
    with pytest.raises(ValueError):
        validate_assessment(result, frozen)


def test_significance_can_persist_without_realert():
    frozen = snapshot()
    result = assessment(frozen)
    next(item for item in result["dimensions"] if item["name"] == "material_change")["value"] = "not_met"
    assert validate_assessment(result, frozen)["tier"] == "world_critical"
    assert not priority_eligible(result, frozen, now=AS_OF)


@pytest.mark.parametrize("field", ["complete", "supported"])
def test_incomplete_unsupported_coverage_cannot_be_ready(field):
    frozen = snapshot()
    frozen["coverage"][field] = False
    with pytest.raises(ValueError):
        validate_assessment(assessment(frozen), frozen)


def test_wire_reprints_or_unknown_origins_do_not_make_independent_support():
    second = evidence(2)
    second["source"]["reporting_origin_id"] = "origin-1"
    frozen = snapshot(evidence=[evidence(), second])
    with pytest.raises(ValueError, match="independent core"):
        validate_assessment(assessment(frozen), frozen)
    second["source"].update(reporting_origin_id=None, origin_status="unknown")
    frozen = snapshot(evidence=[evidence(), second])
    with pytest.raises(ValueError, match="independent core"):
        validate_assessment(assessment(frozen), frozen)


@pytest.mark.parametrize("role,modality", [("background", "reported"), ("contradiction", "denied"),
                                         ("core", "alleged"), ("core", "unknown"), ("withdrawn", "retracted")])
def test_sideangles_denials_and_unknown_modality_cannot_pad_core_support(role, modality):
    second = evidence(2, role=role)
    second["claim"]["modality"] = modality
    frozen = snapshot(evidence=[evidence(), second])
    with pytest.raises(ValueError, match="independent core"):
        validate_assessment(assessment(frozen), frozen)


def test_primary_lane_requires_explicit_frozen_policy_and_verified_issuer():
    item = evidence()
    item["source"]["primary_verified"] = True
    frozen = snapshot(evidence=[item])
    with pytest.raises(ValueError):
        validate_assessment(assessment(frozen), frozen)
    frozen = snapshot(evidence=[item], support_policy={"minimum_independent_origins": 2, "allow_verified_primary": True})
    assert validate_assessment(assessment(frozen), frozen)["status"] == "ready"


def test_scope_requires_supported_place_or_explicit_sector():
    frozen = snapshot()
    for scope in ({"kind": "local", "place_ids": [], "sectors": [], "evidence_ids": ["evd-1"]},
                  {"kind": "regional", "place_ids": ["guessed-place"], "sectors": [], "evidence_ids": ["evd-1"]},
                  {"kind": "sector", "place_ids": [], "sectors": [], "evidence_ids": ["evd-1"]}):
        with pytest.raises(ValueError):
            validate_assessment(assessment(frozen, scope=scope), frozen)


def test_oversize_snapshot_is_not_silently_truncated():
    with pytest.raises(ValueError):
        snapshot(evidence=[evidence(i) for i in range(129)])


def test_nan_never_serializes_into_a_digest():
    with pytest.raises(ValueError):
        digest({"value": float("nan")})
