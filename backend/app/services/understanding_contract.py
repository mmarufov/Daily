"""Pure, private S3 evidence and output contracts.

Offsets always address normalized fields in the frozen bundle. A valid span
proves traceability, not semantic truth; accuracy requires independent labels.
No body, prompt, or span in this module belongs in the public article serializer.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field

from .article_content import EXTRACTOR_VERSION, valid_original_url
from .entity_linker import prepare_candidates, validate_resolution

_TOPIC_BYTES = (Path(__file__).parent.parent / "data/understanding/topics-v1.json").read_bytes()
TOPIC_VOCABULARY = json.loads(_TOPIC_BYTES)
TOPIC_IDS = frozenset(topic["id"] for topic in TOPIC_VOCABULARY["topics"])
MAX_FIELD_CHARS = 250_000


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("evidence text must be a string")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _url(value: Any) -> str:
    if not valid_original_url(value):
        return ""
    parsed = urlsplit(str(value).strip())
    # Query parameters and path are identity-bearing; only strip the fragment.
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    if not isinstance(value, str):
        raise ValueError("date must be a timestamp or string")
    try:
        return _date(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        raise ValueError("invalid publication timestamp") from None


def _positive(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def build_evidence(row: Mapping[str, Any], artifact: Mapping[str, Any] | None = None) -> dict:
    """Freeze trusted article metadata plus one original S2 artifact.

    A wrong-owner or cross-source artifact is excluded, never replaced with
    legacy ``content`` or ``analysis_text``. ``analysis_allowed=false`` revokes
    the whole bundle; native display policy is intentionally irrelevant.
    """
    article_id = str(row.get("id") or row.get("article_id") or "")
    revision = _positive(row.get("semantic_revision", 1), "semantic_revision")
    eligibility = _positive(row.get("analysis_eligibility_generation", 1), "analysis_eligibility_generation")
    allowed = row.get("analysis_allowed", True) is True and row.get("analysis_revoked", False) is False
    url = _url(row.get("url"))
    fields = {"title": normalize_text(row.get("title")), "summary": normalize_text(row.get("summary")), "body": ""}
    metadata = {"url": url, "source_id": str(row["source_id"]) if row.get("source_id") else None,
                "source_name": normalize_text(row.get("source_name")), "author": normalize_text(row.get("author")),
                "published_at": _date(row.get("published_at"))}
    language = normalize_text(row.get("language")) or None
    selected = None
    if artifact and allowed:
        kind = artifact.get("kind")
        origin = _url(artifact.get("origin_url"))
        owner = str(artifact.get("article_id") or "") == article_id and bool(article_id)
        source_matches = not artifact.get("origin_source_id") or (
            metadata["source_id"] is not None and str(artifact["origin_source_id"]) == metadata["source_id"])
        identity = bool(url and origin) and origin == url
        if kind in {"publisher_feed", "licensed_api"}:
            # A feed/API endpoint is an acquisition principal, not a publisher
            # domain. The caller must obtain this identity from its trusted
            # source registry, never from the artifact or model output.
            acquisition = _url(row.get("source_acquisition_url"))
            identity = bool(url and origin and acquisition and metadata["source_id"])
            identity = identity and origin == acquisition and row.get("source_acquisition_kind") == kind
        version = artifact.get("version")
        confidence = artifact.get("confidence", 0)
        raw_text = artifact.get("text")
        hash_matches = isinstance(raw_text, str) and artifact.get("content_hash") == hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        selected_id = row.get("analysis_content_artifact_id")
        is_selected = selected_id is not None and str(selected_id) == str(artifact.get("id"))
        extractor = artifact.get("extractor_version")
        extractor_current = isinstance(extractor, int) and not isinstance(extractor, bool) and extractor >= EXTRACTOR_VERSION
        trusted = (owner and source_matches and identity
                   and is_selected and hash_matches
                   and kind in {"publisher_feed", "origin_extract", "licensed_api"}
                   and artifact.get("is_current") is True and artifact.get("analysis_allowed", True) is True
                   and artifact.get("completeness") in {"complete", "partial", "unknown"}
                   and isinstance(version, int) and not isinstance(version, bool) and version > 0
                   and isinstance(confidence, (int, float)) and not isinstance(confidence, bool)
                   and math.isfinite(confidence) and 0.8 <= confidence <= 1.0
                   and (kind != "origin_extract" or extractor_current))
        if trusted:
            fields["body"] = normalize_text(artifact.get("text"))
            selected = {"id": str(artifact.get("id") or ""), "article_id": article_id, "version": version,
                        "kind": kind, "origin_url": origin, "origin_source_id": str(artifact["origin_source_id"]) if artifact.get("origin_source_id") else None,
                        "method": str(artifact.get("method") or ""), "extractor_version": artifact.get("extractor_version"),
                        "completeness": artifact["completeness"], "content_hash": artifact["content_hash"],
                        "text_hash": digest(fields["body"])}
            if not selected["id"]:
                fields["body"], selected = "", None
    if not allowed:
        fields = {key: "" for key in fields}
    if any(len(value) > MAX_FIELD_CHARS for value in fields.values()):
        raise ValueError("evidence exceeds field limit; must not silently truncate")
    sufficient = bool(allowed and article_id and url and any(fields.values()))
    tier = ("insufficient" if not sufficient else "original_body" if fields["body"]
            else "title_summary" if fields["summary"] else "title_only")
    bundle = {"article_id": article_id, "semantic_revision": revision,
              "analysis_eligibility_generation": eligibility, "fields": fields,
              "metadata": metadata, "language": language, "evidence_tier": tier,
              "manifest": {"normalization": "nfc-whitespace-v1", "artifact": selected,
                           "field_hashes": {key: digest(value) for key, value in fields.items()},
                           "truncated": False, "analysis_allowed": allowed},
              "entity_candidates": prepare_candidates(row.get("entity_candidates")),
              "place_candidates": prepare_candidates(row.get("place_candidates")), "sufficient": sufficient}
    bundle["input_hash"] = digest(bundle)
    return bundle


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class EvidenceSpan(StrictModel):
    field: Literal["title", "summary", "body"]
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=4000)


class Topic(StrictModel):
    topic_id: str
    role: Literal["primary", "secondary", "mentioned"]
    evidence: list[EvidenceSpan] = Field(min_length=1, max_length=8)


class Entity(StrictModel):
    mention: str = Field(min_length=1, max_length=300)
    entity_type: Literal["person", "organization", "product", "event", "other"]
    role: Literal["subject", "actor", "affected", "mentioned"]
    resolved_id: str | None
    resolution: Literal["resolved", "unresolved", "ambiguous"]
    evidence: list[EvidenceSpan] = Field(min_length=1, max_length=8)


class Place(StrictModel):
    mention: str = Field(min_length=1, max_length=300)
    place_id: str | None
    role: Literal["event_location", "affected_area", "mentioned"]
    resolution: Literal["resolved", "unresolved", "ambiguous"]
    evidence: list[EvidenceSpan] = Field(min_length=1, max_length=8)


class Commercial(StrictModel):
    value: Literal["yes", "no", "unknown"]
    subtype: Literal["sponsored", "affiliate", "advertisement", "sales", "other"] | None
    evidence: list[EvidenceSpan] = Field(max_length=8)


class EventHint(StrictModel):
    actors: list[str] = Field(max_length=12)
    action: str = Field(min_length=1, max_length=300)
    object: str | None
    date: str | None
    place_ids: list[str] = Field(max_length=12)
    evidence: list[EvidenceSpan] = Field(min_length=1, max_length=8)


class Abstention(StrictModel):
    field: Literal["kind", "topics", "entities", "places", "commercial", "about", "event_hints"]
    reason: Literal["insufficient_evidence", "ambiguous_mention", "unsupported_language", "conflicting_evidence", "no_candidates", "not_applicable"]


class ArticleCard(StrictModel):
    article_id: str
    input_hash: str
    kind: Literal["report", "analysis", "opinion", "explainer", "interview", "review", "roundup", "listicle", "promo", "obituary", "satire", "other", "unknown"]
    kind_evidence: list[EvidenceSpan] = Field(max_length=8)
    topics: list[Topic] = Field(max_length=12)
    entities: list[Entity] = Field(max_length=30)
    places: list[Place] = Field(max_length=20)
    commercial: Commercial
    about: str | None
    about_evidence: list[EvidenceSpan] = Field(max_length=8)
    event_hints: list[EventHint] = Field(max_length=8)
    abstentions: list[Abstention] = Field(max_length=20)


def card_schema() -> dict:
    return ArticleCard.model_json_schema()


def validate_card(payload: Mapping[str, Any], bundle: Mapping[str, Any]) -> dict:
    if not bundle["sufficient"]:
        raise ValueError("insufficient/revoked evidence cannot produce a ready card")
    card = ArticleCard.model_validate(payload)
    if card.article_id != bundle["article_id"] or card.input_hash != bundle["input_hash"]:
        raise ValueError("card response identity does not match the frozen input")
    spans = [*card.kind_evidence, *card.about_evidence, *card.commercial.evidence]
    for collection in (card.topics, card.entities, card.places, card.event_hints):
        for item in collection:
            spans.extend(item.evidence)
    for span in spans:
        field = bundle["fields"][span.field]
        if span.end <= span.start or span.end > len(field) or field[span.start:span.end] != span.quote:
            raise ValueError("evidence span does not match frozen input")
    if card.kind != "unknown" and not card.kind_evidence:
        raise ValueError("asserted kind requires evidence")
    if card.about is not None and (not card.about.strip() or len(card.about) > 1200 or not card.about_evidence):
        raise ValueError("about requires bounded text and evidence")
    if card.commercial.value != "unknown" and not card.commercial.evidence:
        raise ValueError("commercial yes/no requires evidence")
    if card.commercial.value != "yes" and card.commercial.subtype is not None:
        raise ValueError("commercial subtype requires yes")
    unknown_fields = {name for name in ("topics", "entities", "places", "event_hints") if not getattr(card, name)}
    if card.kind == "unknown":
        unknown_fields.add("kind")
    if card.about is None:
        unknown_fields.add("about")
    if card.commercial.value == "unknown":
        unknown_fields.add("commercial")
    abstained = [item.field for item in card.abstentions]
    if len(abstained) != len(set(abstained)):
        raise ValueError("duplicate field abstention")
    if not unknown_fields.issubset(abstained):
        raise ValueError("unknown or empty fields require explicit abstentions")
    seen_topics = set()
    for topic in card.topics:
        if topic.topic_id not in TOPIC_IDS or topic.topic_id in seen_topics:
            raise ValueError("unknown or duplicate topic ID")
        seen_topics.add(topic.topic_id)
    for entity in card.entities:
        if not any(entity.mention in span.quote for span in entity.evidence):
            raise ValueError("entity mention must occur in its evidence")
        validate_resolution(entity.mention, entity.resolved_id, entity.resolution,
                            bundle["entity_candidates"], entity_type=entity.entity_type)
    for place in card.places:
        if not any(place.mention in span.quote for span in place.evidence):
            raise ValueError("place mention must occur in its evidence")
        validate_resolution(place.mention, place.place_id, place.resolution, bundle["place_candidates"], entity_type="place")
    for hint in card.event_hints:
        if any(identifier not in {p.place_id for p in card.places if p.resolution == "resolved"} for identifier in hint.place_ids):
            raise ValueError("event refers to an unresolved place")
        if any(actor not in {e.mention for e in card.entities} for actor in hint.actors):
            raise ValueError("event actor lacks an evidenced entity mention")
        if any(not any(actor in span.quote for span in hint.evidence) for actor in hint.actors):
            raise ValueError("event actor must occur in event evidence")
        if hint.date is not None:
            from datetime import date
            try:
                if date.fromisoformat(hint.date).isoformat() != hint.date:
                    raise ValueError("noncanonical date")
            except ValueError:
                raise ValueError("event date must be a valid ISO calendar date") from None
        if not hint.action.strip() or hint.object is not None and (not hint.object.strip() or len(hint.object) > 500):
            raise ValueError("event action/object must be bounded nonblank text")
    return card.model_dump(mode="json")


def validate_embedding(vector: Any, dimensions: int = 1536) -> list[float]:
    if isinstance(dimensions, bool) or not isinstance(dimensions, int) or dimensions <= 0:
        raise ValueError("invalid dimensions")
    if not isinstance(vector, (list, tuple)) or len(vector) != dimensions:
        raise ValueError("embedding dimensions do not match recipe")
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector):
        raise ValueError("embedding must contain finite numbers")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0:
        raise ValueError("embedding must have finite nonzero norm")
    return [float(value) for value in vector]


def embedding_text(bundle: Mapping[str, Any]) -> str:
    if not bundle["sufficient"]:
        raise ValueError("insufficient evidence")
    return "\n".join(f"{name}: {bundle['fields'][name]}" for name in ("title", "summary", "body") if bundle["fields"][name])


DEFAULT_RECIPE = {
    # The pilot bake-off rejected gpt-4.1-mini-2025-04-14 on 6/20 facet calls
    # (5 missing evidenced event actors, 1 non-exact quote); gpt-4o-mini-2024-07-18
    # passed 20/20 (docs/stages/s3-implementation-status.md). Not live-impacting on
    # its own -- nothing is promoted off this recipe yet -- but this constant
    # is exactly what a future promotion would copy, so it should be the
    # model that actually won, not the one that lost.
    "version": 1, "status": "provisional_unpromoted", "model": "gpt-4o-mini-2024-07-18",
    "embedding_model": "text-embedding-3-small", "dimensions": 1536,
    "maximum_input_tokens": 12000, "maximum_output_tokens": 6000, "maximum_embedding_tokens": 8000,
    "schema_hash": digest(card_schema()), "taxonomy_hash": hashlib.sha256(_TOPIC_BYTES).hexdigest(),
    "input_version": "original-evidence-nfc-v1", "prompt_version": "source-attributed-facets-v3",
    "linker_version": "supplied-candidates-v1", "document_recipe": "labeled-title-summary-body-v1",
    "query_recipe": "raw-nfc-whitespace-v1",
    "cluster_policy": "singleton-until-calibrated-v1", "cluster_cosine_threshold": None,
}


def recipe_id(recipe: Mapping[str, Any] | None = None) -> str:
    return digest(dict(DEFAULT_RECIPE if recipe is None else recipe))
