"""Fresh S4 feed composition does not weaken S2 privacy or reader policy."""
from copy import deepcopy
from dataclasses import replace

import pytest

from app.services.event_consumers import ReaderPolicy
from app.services.event_feed import apply_event_feed
from test_event_consumers import ENABLED, NOW, candidate, ordinary


def raw_event(index=1, tier="world_critical"):
    event = candidate(index, tier=tier)
    for rep in event["representatives"]:
        rep["publisher_source_id"] = "publisher-source"
        rep["article"].update(source_id="publisher-source", url="https://example.com/report",
            source_name="Source Publisher", content="PRIVATE ANALYSIS BODY", _analysis_text="PRIVATE PROMPT",
            evidence={"ledger": "PRIVATE LEDGER"}, prompt="PRIVATE PROMPT", summary="Source summary")
    return event


def compose(events=None, *, policy=ENABLED, envelope=None, allowed=lambda _: True, limit=5):
    return apply_event_feed(envelope if envelope is not None else {"status": "ready", "articles": [ordinary()]},
                            events if events is not None else [raw_event()], policy,
                            now=NOW, limit=limit, hard_allowed=allowed)


def test_reserved_raw_article_crosses_s2_allowlist_without_private_body_or_prompt():
    output = compose().payload
    assert len(output["articles"]) == 2
    article = output["articles"][0]
    assert article["presentation"]["mode"] == "source_web"
    assert article["source"] == "Source Publisher"
    assert article["publisher"]["canonical_url"] == "https://example.com/report"
    assert article["content"] is None and article["presentation"]["body"] is None
    assert article["event_delivery"]["assessment_id"] == "assessment-1"
    assert all(private not in str(output) for private in ("PRIVATE", "publisher_source_id", "source_generation"))
    assert article["relevant"] is True


def test_independent_event_arrives_even_when_user_has_no_sources():
    envelope = {"status": "needs_discovery", "articles": [], "article_count": 0, "quality_met": False}
    output = compose(envelope=envelope).payload
    assert output["status"] == "ready" and output["article_count"] == 1
    assert output["quality_met"] is False  # One event does not prove source-pool quality.


def test_disabled_and_old_client_do_not_invoke_policy_or_add_fields():
    def must_not_call(_):
        pytest.fail("disabled S4 must not execute representative checks")
    envelope = {"status": "needs_build", "articles": []}
    for policy in (ReaderPolicy(), replace(ENABLED, client_supports_event_expiry=False)):
        result = compose(policy=policy, envelope=envelope, allowed=must_not_call)
        assert result.payload == envelope
        assert result.major_candidates == []


def test_existing_public_native_presentation_is_not_reserialized_or_downgraded():
    row = ordinary(presentation={"mode": "native_full_text", "body": None, "provenance": {"kind": "origin_extract"}},
                   image={"url": "https://example.com/image.jpg", "origin": "publisher_metadata"})
    envelope = {"status": "ready", "articles": [row]}
    result = compose([], envelope=envelope)
    assert result.payload == envelope
    assert result.payload is not envelope and result.payload["articles"][0] is not row


@pytest.mark.parametrize("decision", [False, None, 1, "true"])
def test_hard_policy_must_affirmatively_allow_representative(decision):
    result = compose(allowed=lambda _: decision)
    assert result.payload["articles"] == [ordinary()]
    assert result.decisions[0]["reason"] == "no_permissible_core_representative"


def test_policy_lookup_failure_preserves_ordinary_fallback():
    def failure(_):
        raise RuntimeError("unavailable current policy")
    assert compose(allowed=failure).payload["articles"] == [ordinary()]


def test_unavailable_first_report_falls_back_to_another_source_web_core():
    event = raw_event()
    event["representatives"][0]["article"]["url"] = "http://127.0.0.1/private"
    result = compose([event])
    assert result.payload["articles"][0]["id"] == "1-article-2"
    for rep in event["representatives"]:
        rep["article"]["url"] = None
    assert compose([event]).payload["articles"] == [ordinary()]


def test_publisher_identity_is_distinct_from_provenance_and_source_block_still_applies():
    event = raw_event()
    assert "event_delivery" in compose([event]).payload["articles"][0]
    policy = replace(ENABLED, blocked_source_ids=frozenset({"publisher-source"}))
    assert compose([event], policy=policy).payload["articles"] == [ordinary()]


def test_topic_hard_block_uses_current_explicit_topic_ids():
    policy = replace(ENABLED, blocked_topic_ids=frozenset({"public-safety"}))
    assert compose(policy=policy).payload["articles"] == [ordinary()]


def test_expired_priority_removed_but_saved_article_access_preserved():
    row = ordinary(event_delivery={"tier": "world_critical", "valid_until": "past"}, s4_development_id="private-key")
    result = compose([], envelope={"status": "ready", "articles": [row]})
    assert result.payload["articles"] == [ordinary()]
    assert "event_delivery" in row


def test_major_handoff_is_scoped_and_unforced_and_never_publicly_leaks():
    policy = replace(ENABLED, place_ids=frozenset({"city-a"}))
    result = compose([raw_event(tier="major")], policy=policy)
    assert result.payload["articles"] == [ordinary()]
    assert len(result.major_candidates) == 1
    assert "major_candidates" not in result.payload and "PRIVATE" not in str(result.payload)


def test_more_than_two_events_do_not_overflow_or_mutate_inputs():
    events = [raw_event(i) for i in range(5)]
    original = deepcopy(events)
    result = compose(events, limit=2)
    assert len(result.payload["articles"]) == 2 and len(result.decisions) == 5
    assert events == original


@pytest.mark.parametrize("envelope", [{}, {"articles": None}, {"articles": "bad"}])
def test_public_envelope_required(envelope):
    with pytest.raises(ValueError):
        compose(envelope=envelope)


def test_limits_and_required_policy_validated_before_callback():
    def forbidden(_):
        pytest.fail("must reject bounds first")
    with pytest.raises(ValueError):
        compose([raw_event()] * 257, allowed=forbidden)
    with pytest.raises(ValueError):
        compose(allowed=None)
    with pytest.raises(ValueError):
        compose(limit=True, allowed=forbidden)
