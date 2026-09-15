"""Pure S4 reader contracts. Synthetic decisions do not prove editorial accuracy."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.services.event_consumers import ReaderPolicy, public_event_metadata, select_event_candidates
from app.services.event_contract import dependency_digest
from test_event_contract import assessment, snapshot


NOW = "2026-09-06T12:01:00+00:00"
ENABLED = ReaderPolicy(delivery_enabled=True, client_supports_event_expiry=True)


def candidate(index=1, tier="world_critical"):
    frozen = snapshot(event_id=f"event-{index}")
    for evidence in frozen["evidence"]:
        evidence["dependency"]["article_id"] = f"{index}-{evidence['dependency']['article_id']}"
    frozen["dependency_digest"] = dependency_digest(frozen["evidence"])
    representatives = [
        {"article": {"id": evidence["dependency"]["article_id"], "source_id": evidence["dependency"]["source_id"],
                     "title": "Source report", "presentation_mode": "source_web", "topic_ids": ["public-safety"]},
         "source_id": evidence["dependency"]["source_id"], "topic_ids": ["public-safety"],
         "role": "core", "development_id": f"dev-{index}", "development_version": 1,
         "eligible": True, "language": "en"}
        for evidence in frozen["evidence"]
    ]
    return {"snapshot": frozen, "assessment": assessment(frozen, tier=tier), "assessment_id": f"assessment-{index}",
            "development_id": f"dev-{index}", "development_version": 1, "representatives": representatives}


def ordinary(index=1, **changes):
    return {"id": f"ordinary-{index}", "source_id": "ordinary-source", "topic_ids": [], **changes}


def select(events=None, policy=ENABLED, rows=None, limit=5, now=NOW):
    return select_event_candidates(rows if rows is not None else [ordinary()],
                                   events if events is not None else [candidate()], policy, now=now, limit=limit)


def test_defaults_and_old_client_never_receive_priority():
    for policy in (ReaderPolicy(), replace(ENABLED, delivery_enabled=False),
                   replace(ENABLED, client_supports_event_expiry=False)):
        result = select(policy=policy)
        assert result.items == [ordinary()]
        assert result.decisions[0]["reason"] == "disabled_or_incompatible_client"


@pytest.mark.parametrize("limit", [0, 1, 2, 3, 7])
def test_reserved_and_total_caps_without_changing_detector_results(limit):
    result = select(events=[candidate(i) for i in range(6)], rows=[ordinary(i) for i in range(10)], limit=limit)
    assert len(result.items) == limit
    assert sum("event_delivery" in row for row in result.items) == min(2, limit)
    assert len(result.decisions) == 6
    assert sum(item["reason"] == "reserved_slot_cap" for item in result.decisions) == 6 - min(2, limit)


def test_no_user_linked_sources_still_allows_independent_event_leg():
    result = select(rows=[])
    assert len(result.items) == 1 and "event_delivery" in result.items[0]
    assert result.items[0]["presentation_mode"] == "source_web"


def test_public_event_allowlist_does_not_leak_private_evidence():
    event = candidate()
    event["private_prompt"] = "never public"
    metadata = public_event_metadata(event, now=NOW)
    assert set(metadata) == {"event_id", "event_version", "assessment_id", "assessment_version", "development_id",
                            "development_version", "tier", "as_of", "valid_until"}
    assert metadata["assessment_id"] == "assessment-1"
    assert "evidence" not in str(metadata) and "never public" not in str(metadata)


@pytest.mark.parametrize("mutation", [
    lambda e: e["assessment"].update(valid_until=NOW),
    lambda e: e["assessment"].update(generation=2),
    lambda e: e["assessment"].update(snapshot_hash="a" * 64),
    lambda e: e.update(development_version=True),
    lambda e: e.update(assessment_id=True),
    lambda e: e["assessment"].update(status="error", tier=None, valid_until=None),
    lambda e: e["assessment"]["dimensions"][4].update(value="not_met"),
])
def test_bad_stale_and_unchanged_decisions_fall_back_to_ordinary(mutation):
    event = candidate()
    mutation(event)
    assert select([event]).items == [ordinary()]


@pytest.mark.parametrize("bad", [None, False, {}, {"snapshot": None}, {"snapshot": True}, {"snapshot": []}])
def test_malformed_candidates_do_not_break_ordinary_fallback(bad):
    assert select([bad]).items == [ordinary()]


def test_hard_article_source_and_topic_blocks_apply_before_reservation():
    event = candidate()
    ids = frozenset(rep["article"]["id"] for rep in event["representatives"])
    sources = frozenset(rep["source_id"] for rep in event["representatives"])
    for policy in (replace(ENABLED, blocked_article_ids=ids), replace(ENABLED, blocked_source_ids=sources),
                   replace(ENABLED, blocked_topic_ids=frozenset({"public-safety"}))):
        result = select([event], policy=policy)
        assert result.items == [ordinary()]
        assert result.decisions[0]["reason"] == "no_permissible_core_representative"


def test_blocked_first_representative_selects_another_permissible_core():
    event = candidate()
    blocked_id = event["representatives"][0]["article"]["id"]
    result = select([event], policy=replace(ENABLED, blocked_article_ids=frozenset({blocked_id})))
    assert result.items[0]["id"] == event["representatives"][1]["article"]["id"]


def test_side_angle_cannot_win_by_image_or_preferred_language():
    event = candidate()
    side = deepcopy(event["representatives"][0])
    side.update(role="background", language="fr")
    side["article"].update(id="side-angle", image_url="pretty.jpg")
    event["representatives"].insert(0, side)
    result = select([event], policy=replace(ENABLED, preferred_languages=("fr",)))
    assert result.items[0]["id"] != "side-angle"
    assert result.items[0]["presentation_mode"] == "source_web"


@pytest.mark.parametrize("key,value", [("eligible", False), ("eligible", 1), ("role", "background"),
                                      ("development_id", "different"), ("development_version", 2),
                                      ("development_version", True), ("source_id", "unverified-source"),
                                      ("topic_ids", None)])
def test_representatives_must_support_exact_permitted_development(key, value):
    event = candidate()
    for rep in event["representatives"]:
        rep[key] = value
    assert select([event]).items == [ordinary()]


def test_major_local_scope_requires_explicit_reader_location_and_never_forces():
    event = candidate(tier="major")
    for rep in event["representatives"]:
        rep["article"]["event_delivery"] = {"tier": "world_critical"}
    result = select([event])
    assert result.items == [ordinary()] and result.major_candidates == []
    result = select([event], policy=replace(ENABLED, place_ids=frozenset({"city-a"})))
    assert result.items == [ordinary()] and len(result.major_candidates) == 1
    assert "event_delivery" not in result.major_candidates[0]


def test_future_assessments_never_authorize_selection_or_public_metadata():
    event = candidate()
    before = "2026-09-06T11:59:00+00:00"
    assert select([event], now=before).items == [ordinary()]
    with pytest.raises(ValueError):
        public_event_metadata(event, now=before)


def test_malformed_ordinary_source_and_topic_metadata_fails_closed():
    rows = [ordinary(1, source_id=[]), ordinary(2, topic_ids="not-a-list"),
            ordinary(3, topic_ids=[True]), ordinary(4)]
    assert select(events=[], rows=rows).items == [ordinary(4)]


def test_deduplicate_articles_and_developments_across_both_legs():
    event = candidate()
    result = select([event, deepcopy(event)], rows=[rep["article"] for rep in event["representatives"]] +
                    [ordinary(1, s4_development_id="dev-1"), ordinary(2), ordinary(2)])
    assert [row["id"] for row in result.items] == ["1-article-1", "ordinary-2"]
    assert result.decisions[1]["reason"] == "duplicate_development_or_article"


def test_explicit_seen_version_suppresses_only_same_version_without_fabricating_state():
    policy = replace(ENABLED, seen_development_versions=frozenset({("dev-1", 1)}))
    assert select(policy=policy).items == [ordinary()]
    event = candidate()
    event["development_version"] = 2
    for rep in event["representatives"]:
        rep["development_version"] = 2
    assert "event_delivery" in select([event], policy=policy).items[0]


def test_ordinary_saved_article_survives_without_cached_priority_and_inputs_not_mutated():
    row = ordinary(event_delivery={"tier": "world_critical", "valid_until": "expired"},
                   feed_role='world_critical', why_now='stale priority', relevance_reason='stale critical decision')
    event = candidate()
    original = deepcopy(event)
    assert select(events=[], rows=[row]).items == [ordinary()]
    assert "event_delivery" in row
    select([event])
    assert event == original


@pytest.mark.parametrize("limit", [True, -1, 101, 1.1, "2"])
def test_invalid_limits_rejected(limit):
    with pytest.raises(ValueError):
        select(limit=limit)


def test_naive_time_and_overlarge_input_rejected():
    with pytest.raises(ValueError):
        select(now="2026-09-06T12:01:00")
    with pytest.raises(ValueError):
        select(events=[{}] * 257)
