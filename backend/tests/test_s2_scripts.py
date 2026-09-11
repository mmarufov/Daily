"""Safety rails for S2 operational CLIs."""
from __future__ import annotations

import pytest

from scripts import backfill_s2_content, manage_s2_source_policy
from app.services.article_content import normalize_source_domain, set_source_policy


def test_backfill_defaults_to_read_only():
    args = backfill_s2_content._parser().parse_args([])
    assert args.apply is False
    assert args.validate_constraints is False


def test_backfill_totals_cover_and_accept_every_committed_batch_counter():
    total = backfill_s2_content._empty_migration_counts()
    batch = {
        "rows": 1,
        "legacy_content": 0,
        "jobs": 1,
        "legacy_images": 0,
        "outdated_origins": 1,
        # Future additive counters must not make the resumable command crash
        # after its database transaction has already committed.
        "new_counter": 2,
    }

    backfill_s2_content._accumulate_counts(total, batch)

    assert total == batch


def test_policy_mutation_defaults_to_read_only():
    args = manage_s2_source_policy._parser().parse_args(
        [
            "grant",
            "example.com",
            "--display-policy",
            "native_full_text",
            "--allow-kind",
            "origin_extract",
            "--rights-basis",
            "publisher_permission",
            "--reviewed-by",
            "reviewer@example.invalid",
        ]
    )
    assert args.apply is False


@pytest.mark.parametrize("domain", ["localhost", "127.0.0.1", "https://user@example.com/a"])
def test_policy_cli_rejects_non_publisher_identifiers(domain):
    with pytest.raises(ValueError):
        manage_s2_source_policy._validated_domain(domain)


@pytest.mark.parametrize(
    "domain",
    [
        "localhost",
        "https://localhost/story",
        "http://127.0.0.1/story",
        "https://publisher.internal/story",
        "publisher.test",
    ],
)
def test_authoritative_policy_normalizer_rejects_non_public_hosts(domain):
    assert normalize_source_domain(domain) == ""


def test_policy_api_rejects_mislabeled_revoke_before_database_access():
    with pytest.raises(ValueError, match="revoke must remove"):
        set_source_policy(
            object(),
            source_domain="example.com",
            display_policy="native_full_text",
            allowed_artifact_kinds=["origin_extract"],
            publisher_feed_full_text=False,
            rights_basis="publisher_permission",
            access_hint="open",
            reviewed_by="reviewer@example.invalid",
            action="revoke",
        )


def test_native_policy_requires_reviewed_rights_and_artifact_kind():
    args = manage_s2_source_policy._parser().parse_args(
        [
            "grant",
            "example.com",
            "--display-policy",
            "native_full_text",
            "--rights-basis",
            "unknown",
            "--reviewed-by",
            "reviewer@example.invalid",
        ]
    )
    with pytest.raises(ValueError):
        manage_s2_source_policy._proposal(args, "example.com")


@pytest.mark.parametrize(
    "rights_basis",
    ["Unknown", "NONE", "unverified", "revoked", "not valid rights"],
)
def test_policy_api_rejects_negative_or_malformed_native_rights_before_database(rights_basis):
    with pytest.raises(ValueError, match="rights_basis"):
        set_source_policy(
            object(),
            source_domain="example.com",
            display_policy="native_full_text",
            allowed_artifact_kinds=["origin_extract"],
            publisher_feed_full_text=False,
            rights_basis=rights_basis,
            access_hint="open",
            reviewed_by="reviewer@example.invalid",
            action="grant",
        )


def test_feed_full_text_assertion_requires_feed_artifact_kind():
    args = manage_s2_source_policy._parser().parse_args(
        [
            "grant",
            "example.com",
            "--display-policy",
            "native_full_text",
            "--allow-kind",
            "origin_extract",
            "--publisher-feed-full-text",
            "--rights-basis",
            "publisher_permission",
            "--reviewed-by",
            "reviewer@example.invalid",
        ]
    )
    with pytest.raises(ValueError):
        manage_s2_source_policy._proposal(args, "example.com")


def test_feed_full_text_policy_requires_exact_https_feed_identity():
    missing = manage_s2_source_policy._parser().parse_args(
        [
            "grant", "example.com", "--display-policy", "native_full_text",
            "--allow-kind", "publisher_feed", "--publisher-feed-full-text",
            "--rights-basis", "publisher_feed_license",
            "--reviewed-by", "reviewer@example.invalid",
        ]
    )
    with pytest.raises(ValueError, match="allow-feed-url"):
        manage_s2_source_policy._proposal(missing, "example.com")

    approved = manage_s2_source_policy._parser().parse_args(
        [
            "grant", "example.com", "--display-policy", "native_full_text",
            "--allow-kind", "publisher_feed", "--publisher-feed-full-text",
            "--allow-feed-url", "https://feeds.example.com/full.xml#fragment",
            "--rights-basis", "Publisher_Feed_License",
            "--reviewed-by", "reviewer@example.invalid",
        ]
    )
    proposal = manage_s2_source_policy._proposal(approved, "example.com")
    assert proposal["allowed_feed_urls"] == ["https://feeds.example.com/full.xml"]
    assert proposal["rights_basis"] == "publisher_feed_license"
