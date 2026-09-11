"""Pure, default-disabled S4 selection after repository authorization.

This module cannot certify live database validity. Callers must authorize the
complete candidate manifest in one coherent snapshot and fence cache publication
and reuse. Article dictionaries remain INTERNAL and must cross the S2 serializer;
only ``public_event_metadata`` is an event-data public allowlist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.services.event_contract import digest, priority_eligible, timestamp, validate_assessment


@dataclass(frozen=True)
class ReaderPolicy:
    delivery_enabled: bool = False
    client_supports_event_expiry: bool = False
    blocked_article_ids: frozenset[str] = frozenset()
    blocked_source_ids: frozenset[str] = frozenset()
    blocked_topic_ids: frozenset[str] = frozenset()
    place_ids: frozenset[str] = frozenset()
    sector_ids: frozenset[str] = frozenset()
    preferred_languages: tuple[str, ...] = ()
    preferred_source_ids: tuple[str, ...] = ()
    # Explicit durable acknowledgments only; never inferred from loading a feed.
    seen_development_versions: frozenset[tuple[str, int]] = frozenset()


@dataclass
class Selection:
    items: list[dict] = field(default_factory=list)
    major_candidates: list[dict] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 200


def _positive_version(value: Any) -> bool:
    return type(value) is int and value > 0


def _allowed(article: Mapping[str, Any], policy: ReaderPolicy, *, source_id=None, topic_ids=None) -> bool:
    identifier = article.get("id")
    if not _identifier(identifier) or identifier in policy.blocked_article_ids:
        return False
    source = article.get("source_id") if source_id is None else source_id
    topics = article.get("topic_ids", []) if topic_ids is None else topic_ids
    if source is not None and not _identifier(source):
        return False
    if source in policy.blocked_source_ids:
        return False
    if not isinstance(topics, (list, tuple, set, frozenset)) or any(not _identifier(x) for x in topics):
        return False
    return not policy.blocked_topic_ids.intersection(topics)


def scoped_relevance(scope: Mapping[str, Any], policy: ReaderPolicy) -> bool:
    """Major-event recall uses explicit settings, never guessed geography."""
    kind = scope.get("kind")
    if kind == "global":
        return True
    if kind in ("local", "regional"):
        return bool(policy.place_ids.intersection(scope.get("place_ids", [])))
    if kind == "sector":
        return bool(policy.sector_ids.intersection(scope.get("sectors", [])))
    return False


def public_event_metadata(candidate: Mapping[str, Any], *, now: datetime | str) -> dict:
    """Return only validated priority metadata, not evidence or model prose.

    This checks structure/expiry, not repository authorization or reader policy.
    The assessment hash is the immutable decision version, not a mutable label.
    """
    frozen, assessment = candidate["snapshot"], candidate["assessment"]
    if not priority_eligible(assessment, frozen, now=now):
        raise ValueError("candidate cannot authorize priority metadata")
    current = timestamp(now) if isinstance(now, str) else now
    if timestamp(frozen["as_of"]) > current:
        raise ValueError("future assessment cannot authorize priority metadata")
    development_id, version = candidate.get("development_id"), candidate.get("development_version")
    if not _identifier(development_id) or not _positive_version(version):
        raise ValueError("development identity/version required")
    if not _identifier(candidate.get("assessment_id")):
        raise ValueError("immutable assessment identity required")
    return {
        "event_id": assessment["event_id"], "event_version": assessment["generation"],
        "assessment_id": candidate["assessment_id"],
        "assessment_version": digest(assessment), "development_id": development_id,
        "development_version": version, "tier": assessment["tier"],
        "as_of": frozen["as_of"], "valid_until": assessment["valid_until"],
    }


def _representative(candidate: Mapping[str, Any], policy: ReaderPolicy) -> dict | None:
    """A nice image or preferred language cannot turn a side-angle into core evidence."""
    representatives = candidate.get("representatives")
    if not isinstance(representatives, (list, tuple)) or len(representatives) > 128:
        return None
    eligible = []
    # Server evidence membership must corroborate the caller's representative tag.
    core_articles = {
        item["dependency"]["article_id"]: item["dependency"]["source_id"]
        for item in candidate["snapshot"]["evidence"]
        if item["role"] == "core" and item["claim"]["modality"] in ("reported", "corrected")
        and item["id"] in candidate["assessment"]["evidence_ids"]
    }
    for representative in representatives:
        if not isinstance(representative, Mapping):
            continue
        article = representative.get("article")
        if not isinstance(article, Mapping) or representative.get("eligible") is not True:
            continue
        if representative.get("role") != "core" or representative.get("development_id") != candidate["development_id"] \
                or type(representative.get("development_version")) is not int \
                or representative["development_version"] != candidate["development_version"]:
            continue
        source_id = representative.get("source_id")
        if not _identifier(source_id) or core_articles.get(article.get("id")) != source_id:
            continue
        # Provenance registry identity and reader-facing publisher identity are
        # separate namespaces. A per-article provenance key must never stand in
        # for a blocked publisher/source setting.
        publisher_id = representative.get("publisher_source_id", article.get("source_id"))
        if publisher_id is not None and not _identifier(publisher_id):
            continue
        if article.get("source_id") not in (None, publisher_id):
            continue
        if policy.blocked_source_ids and publisher_id is None:
            continue
        if publisher_id in policy.blocked_source_ids:
            continue
        # Explicit topic metadata is required even when empty. Its completeness is
        # the repository's contract, not a source/model-controlled bypass switch.
        topics = representative.get("topic_ids")
        if topics is None or not _allowed(article, policy, source_id=source_id, topic_ids=topics):
            continue
        if not _allowed(article, policy):
            continue
        language = representative.get("language")
        language_rank = policy.preferred_languages.index(language) if language in policy.preferred_languages else len(policy.preferred_languages)
        source_rank = policy.preferred_source_ids.index(source_id) if source_id in policy.preferred_source_ids else len(policy.preferred_source_ids)
        eligible.append(((language_rank, source_rank, article["id"]), dict(article)))
    return min(eligible, key=lambda row: row[0])[1] if eligible else None


def select_event_candidates(
    ordinary: Sequence[Mapping[str, Any]], candidates: Sequence[Mapping[str, Any]], policy: ReaderPolicy,
    *, now: datetime | str, limit: int,
) -> Selection:
    """Select at most two criticals, then fill from existing ordinary ranking.

    Candidates must already be repository-authorized. Each contains snapshot,
    assessment, development_id/version and representatives with article, role,
    development_id/version, eligible, source_id, topic_ids and optional language.
    Input candidate order is the caller's stable editorial order, not a detector
    cutoff. All bounded candidates receive a disposition, including overflow.
    Major candidates are returned separately for S7 scoring, never forced here.
    """
    current = timestamp(now) if isinstance(now, str) else now
    if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("selection requires offset-bearing authorization time")
    if type(limit) is not int or not 0 <= limit <= 100:
        raise ValueError("edition limit must be an integer from 0 to 100")
    if len(candidates) > 256 or len(ordinary) > 10000:
        raise ValueError("selection input exceeds bounded retrieval contract")
    result = Selection()
    selected_articles, selected_developments = set(), set()
    known_developments: dict[str, set[str]] = {}
    active = policy.delivery_enabled is True and policy.client_supports_event_expiry is True
    for candidate in candidates:
        raw_snapshot = candidate.get("snapshot") if isinstance(candidate, Mapping) else None
        identifier = raw_snapshot.get("event_id") if isinstance(raw_snapshot, Mapping) else None
        disposition = {"event_id": identifier, "reason": "disabled_or_incompatible_client"}
        result.decisions.append(disposition)
        if not active:
            continue
        try:
            assessment = validate_assessment(candidate["assessment"], candidate["snapshot"], now=current)
            development, version = candidate.get("development_id"), candidate.get("development_version")
            if not _identifier(development) or not _positive_version(version):
                raise ValueError("invalid development")
            if timestamp(candidate["snapshot"]["as_of"]) > current:
                raise ValueError("future assessment")
            if assessment["status"] != "ready":
                disposition["reason"] = "not_ready"
                continue
            article = _representative(candidate, policy)
            if article is None:
                disposition["reason"] = "no_permissible_core_representative"
                continue
            for representative in candidate["representatives"]:
                if isinstance(representative, Mapping) and isinstance(representative.get("article"), Mapping) \
                        and representative.get("development_id") == development:
                    key = representative["article"].get("id")
                    if _identifier(key):
                        known_developments.setdefault(key, set()).add(development)
            if assessment["tier"] == "major":
                if scoped_relevance(assessment["scope"], policy):
                    article.pop("event_delivery", None)
                    result.major_candidates.append(article)
                    disposition["reason"] = "major_for_normal_ranking"
                else:
                    disposition["reason"] = "major_outside_explicit_scope"
                continue
            if not priority_eligible(assessment, candidate["snapshot"], now=current):
                disposition["reason"] = "not_priority_eligible"
                continue
            if (development, version) in policy.seen_development_versions:
                disposition["reason"] = "explicitly_seen_development"
                continue
            if article["id"] in selected_articles or development in selected_developments:
                disposition["reason"] = "duplicate_development_or_article"
                continue
            if len(result.items) >= min(2, limit):
                disposition["reason"] = "reserved_slot_cap"
                continue
            article["event_delivery"] = public_event_metadata(candidate, now=current)
            result.items.append(article)
            selected_articles.add(article["id"])
            selected_developments.add(development)
            disposition["reason"] = "reserved"
        except (KeyError, TypeError, ValueError, AttributeError):
            disposition["reason"] = "invalid_or_expired_candidate"
    for original in ordinary:
        if len(result.items) >= limit:
            break
        if not isinstance(original, Mapping) or not _allowed(original, policy):
            continue
        identifier = original["id"]
        developments = set(known_developments.get(identifier, ()))
        if _identifier(original.get("s4_development_id")):
            developments.add(original["s4_development_id"])
        if identifier in selected_articles or developments.intersection(selected_developments):
            continue
        article = dict(original)
        # Cached priority is never carried forward as ordinary news. The source
        # article can remain readable; only current authorized candidates elevate.
        if article.get('event_delivery') is not None or article.get('feed_role') in ('world_critical', 'event_priority'):
            article.pop('feed_role', None)
            article.pop('why_now', None)
            article.pop('relevance_reason', None)
        article.pop("event_delivery", None)
        result.items.append(article)
        selected_articles.add(identifier)
        selected_developments.update(developments)
    return result
