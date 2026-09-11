from copy import deepcopy

import pytest

from app.services.event_contract import digest
from app.services.event_evidence import coverage_counts, from_s3, validate_original_spans
from app.services.understanding_contract import build_evidence
from tests.test_event_contract import AS_OF, evidence
from tests.test_understanding_contract import row, card, span


def s3_input():
    bundle = build_evidence(row())
    payload = card(bundle)
    payload["event_hints"] = [{"actors": [], "action": "acquire", "object": "Orange", "date": "2026-09-06",
                               "place_ids": [], "evidence": [span(bundle, bundle["fields"]["title"])]}]
    current = {"state": "ready", "article_id": bundle["article_id"], "semantic_revision": bundle["semantic_revision"],
               "analysis_eligibility_generation": bundle["analysis_eligibility_generation"],
               "input_hash": bundle["input_hash"], "recipe_id": "s3-recipe",
               "facets": {"id": "result-a", "payload": payload}, "embedding": {"id": "embedding-a"}, "membership": None}
    return bundle, current


def adapt(bundle, current, **changes):
    options = {"source_id": "source-a", "source_generation": 1, "observed_at": AS_OF}
    options.update(changes)
    return from_s3(bundle, current, **options)


def test_s3_hint_never_guesses_affirmation_or_event_date():
    bundle, current = s3_input()
    item = adapt(bundle, current)[0]
    assert item["claim"]["modality"] == "unknown"
    assert item["claim"]["occurrence"] == {"start": None, "end": None, "precision": "unknown", "evidence_ids": []}
    assert item["role"] == "unknown"
    assert item["source"]["origin_status"] == "unknown"
    assert "does not" in item["spans"][0]["quote"]
    assert item["hint_hash"] == digest(current["facets"]["payload"]["event_hints"][0])


def test_adapter_identity_pins_hint_result_and_revision():
    bundle, current = s3_input()
    first = adapt(bundle, current)[0]
    assert first == adapt(bundle, current)[0]
    current["facets"]["id"] = "result-b"
    assert first["id"] != adapt(bundle, current)[0]["id"]


@pytest.mark.parametrize("changes", [{"semantic_revision": 77}, {"input_hash": "0" * 64},
                                    {"analysis_eligibility_generation": 9}, {"article_id": "wrong"},
                                    {"state": "stale"}, {"state": "disabled"}, {"facets": None}])
def test_stale_or_noncurrent_s3_rows_fail(changes):
    bundle, current = s3_input()
    current.update(changes)
    with pytest.raises(ValueError):
        adapt(bundle, current)


def test_unhashed_or_revoked_bundle_is_not_accepted():
    bundle, current = s3_input()
    bundle["fields"]["title"] = "Fabricated update"
    with pytest.raises(ValueError, match="hash"):
        adapt(bundle, current)
    bundle, current = s3_input()
    bundle["manifest"]["analysis_allowed"] = False
    with pytest.raises(ValueError, match="eligible"):
        adapt(bundle, current)


def test_membership_requires_cluster_generation():
    bundle, current = s3_input()
    current["membership"] = {"cluster_id": "cluster-a", "version": 4}
    with pytest.raises(ValueError, match="cluster generation"):
        adapt(bundle, current)
    dep = adapt(bundle, current, cluster_version=8)[0]["dependency"]
    assert dep["membership_version"] == 4 and dep["cluster_version"] == 8


@pytest.mark.parametrize("key,value", [("quote", "Fabricated quote"), ("field_hash", "0" * 64),
                                      ("field", "body"), ("start", 99)])
def test_original_span_revalidation_catches_forgery(key, value):
    bundle, current = s3_input()
    item = adapt(bundle, current)[0]
    item["spans"][0][key] = value
    with pytest.raises(ValueError):
        validate_original_spans(item, bundle)


def test_coverage_distinguishes_reach_origin_and_sideangle():
    first, second, third, fourth = [evidence(i) for i in range(1, 5)]
    second["source"]["reporting_origin_id"] = "origin-1"
    third["source"].update(origin_status="unknown", reporting_origin_id=None)
    fourth["role"] = "background"
    counts = coverage_counts([first, second, third, fourth])
    assert counts["distribution_publishers"] == 4
    assert counts["independent_core_origins"] == 1
    assert counts["unknown_core_origins"] == 1
    assert counts["verified_primary_core"] == 0


def test_unknown_source_metadata_is_not_a_verified_origin():
    item = evidence()
    item["source"]["reporting_origin_id"] = None
    with pytest.raises(ValueError):
        coverage_counts([item])


def test_adapter_does_not_mutate_s3():
    bundle, current = s3_input()
    original = deepcopy((bundle, current))
    adapt(bundle, current)
    assert (bundle, current) == original
