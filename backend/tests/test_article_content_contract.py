"""Pure contract tests for S2 serialization and policy boundaries."""
from __future__ import annotations

import uuid

import pytest

from app.services.article_content import (
    classify_failure,
    failure_is_terminal,
    serialize_article,
    valid_original_url,
)


def _row(**overrides):
    row = {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "title": "Publisher story",
        "summary": "A publisher preview.",
        "source_name": "Example News",
        "url": "https://news.example.com/story",
        "presentation_mode": "source_web",
        "presentation_reason": "source_policy_default_deny",
        "body_state": "none",
        "content_access_hint": "unknown",
        "display_content_artifact_id": None,
        "display_body_excerpt": None,
        "content_version": 0,
    }
    row.update(overrides)
    return row


def test_source_handoff_never_leaks_legacy_or_analysis_text():
    serialized = serialize_article(
        _row(
            content="ambiguous legacy publisher-attributed text",
            analysis_text="cross-source ranking context",
            display_body="even a joined body must not bypass presentation mode",
        ),
        include_body=True,
    )

    assert serialized["content"] is None
    assert serialized["body_excerpt"] is None
    assert serialized["presentation"]["body"] is None
    assert serialized["presentation"]["mode"] == "source_web"


def test_feed_and_detail_share_native_version_while_only_detail_has_body():
    row = _row(
        presentation_mode="native_full_text",
        presentation_reason="verified_body_permitted",
        body_state="verified_full",
        display_content_artifact_id=42,
        display_body_excerpt="A safe preview.",
        display_body="Verified full body.",
        display_rights_basis="publisher_permission",
        display_effective_completeness="complete",
        display_policy_version=3,
        content_version=9,
        artifact_kind="origin_extract",
        artifact_method="trafilatura",
        artifact_origin_url="https://news.example.com/story",
        artifact_extractor_version=4,
        artifact_completeness="complete",
        artifact_confidence=0.96,
    )

    feed = serialize_article(row, include_body=False)
    detail = serialize_article(row, include_body=True)

    assert feed["presentation"]["mode"] == detail["presentation"]["mode"]
    assert feed["presentation"]["provenance"]["content_version"] == 9
    assert detail["presentation"]["provenance"]["content_version"] == 9
    assert feed["presentation"]["provenance"]["policy_version"] == 3
    assert feed["content"] is None
    assert feed["presentation"]["body"] is None
    assert detail["content"] == "Verified full body."
    assert detail["presentation"]["body"] == "Verified full body."


@pytest.mark.parametrize(
    "rights_basis",
    ["Unknown", "UNKNOWN", "none", "unverified", "revoked", "not valid rights"],
)
def test_native_serializer_fails_closed_for_non_explicit_rights(rights_basis):
    serialized = serialize_article(
        _row(
            presentation_mode="native_full_text",
            body_state="verified_full",
            display_content_artifact_id=42,
            display_rights_basis=rights_basis,
            display_effective_completeness="complete",
            display_policy_version=2,
            content_version=3,
            display_body="Body that must not render.",
            artifact_kind="origin_extract",
            artifact_origin_url="https://news.example.com/story",
            artifact_extractor_version=4,
            artifact_confidence=0.99,
            artifact_completeness="complete",
        ),
        include_body=True,
    )

    assert serialized["presentation"]["mode"] == "source_web"
    assert serialized["presentation"]["body"] is None
    assert serialized["presentation"]["provenance"] is None


@pytest.mark.parametrize("include_body", [False, True])
def test_missing_selected_artifact_fails_closed(include_body):
    serialized = serialize_article(
        _row(
            presentation_mode="native_full_text",
            body_state="verified_full",
            display_body="orphaned body",
        ),
        include_body=include_body,
    )
    assert serialized["presentation"]["mode"] == "source_web"
    assert serialized["content"] is None


def test_image_contract_quarantines_unknown_and_labels_illustration():
    unknown = serialize_article(
        _row(
            image_url="https://images.example.com/old.jpg",
            image_origin="legacy_unknown",
            image_is_illustrative=True,
        ),
        include_body=False,
    )
    assert unknown["image"] is None
    assert unknown["image_url"] is None

    stock = serialize_article(
        _row(
            image_url="https://images.unsplash.com/photo.jpg",
            image_origin="stock",
            image_source_url="https://unsplash.com/photos/abc",
            image_attribution="Photo by Example on Unsplash",
            image_is_illustrative=True,
        ),
        include_body=False,
    )
    assert stock["image"]["origin"] == "stock"
    assert stock["image"]["illustrative"] is True
    # Old clients cannot label illustrative media, so do not expose it through
    # their ambiguous compatibility field.
    assert stock["image_url"] is None


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:secret@example.com/story",
        "http://localhost/story",
        "http://metadata/story",
        "http://service.internal/story",
        "http://127.0.0.1/story",
        "http://169.254.169.254/story",
        "http://[::1]/story",
        "https://publisher.example/story",
    ],
)
def test_reader_url_validation_rejects_non_public_destinations(url):
    assert not valid_original_url(url)


def test_reader_url_validation_accepts_normal_public_destination():
    assert valid_original_url("https://www.reuters.com/world/story?id=1")


def test_http_451_is_terminal_access_denial():
    extracted = {"error": "http_status", "http_status": 451}
    failure = classify_failure(extracted)
    assert failure == "access_denied"
    assert failure_is_terminal(extracted, failure)
