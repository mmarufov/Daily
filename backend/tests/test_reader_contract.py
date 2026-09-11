from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.services.reader_contract import ReaderMutation, apply_patch, intent_semantic_hash, validate_profile
from app.services.reader_compiler import compile_reader, import_legacy, legacy_patch, policy_allows, projections, tokenize


def intent(label="AI", **kw):
    return {"id": str(uuid4()), "kind": "topic", "label": label, **kw}


@pytest.mark.parametrize("patch", [{"typo": []}, {"context": 3}, {"intents": None}, {"languages": ["English"]}, {"intents": [intent(priority=True)]}, {"intents": [intent(label="  ")]}, {"intents": [intent(expires_at="2026-01-01")]}])
def test_strict_input(patch):
    with pytest.raises((ValueError, ValidationError)):
        validate_profile(patch)


def test_missing_is_unchanged_empty_is_clear():
    original = validate_profile({"intents": [intent()], "context": "Do not publish my biography"})
    assert apply_patch(original, {"depth": "deep"})["intents"] == original["intents"]
    assert apply_patch(original, {"intents": []})["intents"] == []


def test_duplicate_ids_and_bounds_rejected():
    item = intent()
    with pytest.raises(ValueError):
        validate_profile({"intents": [item, item]})
    with pytest.raises(ValueError):
        validate_profile({"intents": [intent(str(i)) for i in range(25)]})


def test_unicode_qualified_intent_and_no_private_query():
    profile = validate_profile({"intents": [intent("Новости Таджикистана", qualifiers=["Экономика"])], "context": "private personal details"})
    compiled = compile_reader(profile)
    assert tokenize("Новости Таджикистана") == ["новости", "таджикистана"]
    assert len(compiled["intents"]) == 1
    assert "private" not in str(compiled)
    assert projections(profile)["interests"]["topics"] == ["Новости Таджикистана"]


def test_expiry_read_time_and_weight_does_not_change_embedding_identity():
    profile = validate_profile({"intents": [intent(expires_at="2026-09-07T12:00:00Z")]})
    assert not compile_reader(profile, now=datetime(2026, 9, 7, 12, tzinfo=timezone.utc))["intents"]
    item = profile["intents"][0]
    assert intent_semantic_hash(item) == intent_semantic_hash({**item, "priority": 2, "expires_at": None})
    assert intent_semantic_hash(item) != intent_semantic_hash({**item, "query": "AI regulation"})


def test_exact_literal_exclusion_is_not_substring_or_body_aboutness():
    profile = validate_profile({"policies": [{"id": str(uuid4()), "kind": "lexical", "value": "AI"}]})
    assert policy_allows(profile, {"title": "Retail expands", "content": "AI is mentioned incidentally"})
    assert not policy_allows(profile, {"title": "AI expands"})


def test_publisher_exact_alias_not_unrelated_subdomain():
    profile = validate_profile({"policies": [{"id": str(uuid4()), "kind": "publisher", "value": "example.com"}]})
    assert not policy_allows(profile, {"url": "https://www.example.com/news"})
    assert policy_allows(profile, {"url": "https://otherexample.com/news"})
    assert policy_allows(profile, {"url": "https://sub.example.com/news"})
    assert not policy_allows(profile, {})


def test_hard_constraints_fail_closed_without_evidence():
    profile = validate_profile({"languages": ["en"], "policies": [{"id": str(uuid4()), "kind": "subject", "value": "politics"}]})
    assert not policy_allows(profile, {"language": "en"})
    assert not policy_allows(profile, {"topic_ids": []})
    assert policy_allows(profile, {"language": "en", "topic_ids": []})
    assert not policy_allows(profile, {"language": "en", "topic_ids": ["politics"]})


def test_migration_preserves_conflicting_interests_and_canonical_scopes():
    profile, status, evidence = import_legacy("u", {"interests": {"topics": ["AI"]}, "user_profile_v2": {"stable_interests": ["Space"], "blocked_source_ids": ["bad.example"], "place_ids": ["geo:1"], "sector_ids": ["sector:2"]}})
    assert status == "needs_review"
    assert {"AI", "Space"} <= {i["label"] for i in profile["intents"]}
    v2 = projections(profile)["user_profile_v2"]
    assert v2["blocked_source_ids"] == ["bad.example"]
    assert v2["place_ids"] == ["geo:1"] and v2["sector_ids"] == ["sector:2"]
    assert evidence["interests"]["topics"] == ["AI"]
    assert profile == import_legacy("u", {"interests": {"topics": ["AI"]}, "user_profile_v2": {"stable_interests": ["Space"], "blocked_source_ids": ["bad.example"], "place_ids": ["geo:1"], "sector_ids": ["sector:2"]}})[0]


def test_malformed_legacy_is_not_stringified_and_generated_exclusions_ignored():
    profile, status, _ = import_legacy("u", {"interests": {"topics": [None]}, "user_profile_v2": {"expanded_exclusions": ["retail"]}})
    assert profile["intents"] == [] and profile["policies"] == []
    assert status == "needs_review"


def test_legacy_patch_preserves_unmentioned_entity_and_policy():
    profile = validate_profile({"intents": [intent("AI"), intent("Ada", kind="entity")], "policies": [{"id": str(uuid4()), "kind": "publisher", "value": "bad.example"}]})
    result = apply_patch(profile, legacy_patch(profile, {"topics": ["Space"], "excluded_topics": []}))
    assert {i["label"] for i in result["intents"]} == {"Space", "Ada"}
    assert result["policies"] == profile["policies"]


def test_mutation_rejects_boolean_revision_and_unknown_fields():
    with pytest.raises(ValueError):
        ReaderMutation.model_validate({"operation_id": str(uuid4()), "base_generation": True, "base_revision": 1, "patch": {}})
    with pytest.raises(ValueError):
        ReaderMutation.model_validate({"operation_id": str(uuid4()), "base_generation": 1, "base_revision": 1, "patch": {"schema_version": 3}})
