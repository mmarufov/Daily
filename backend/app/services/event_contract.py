"""Private S4 contracts. Traceable evidence is not proof of semantic truth.

These pure validators never read a database or certify that a dependency is still
current. The repository must fence the complete manifest, including negative
evidence, against current rows at publication and authorization.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def timestamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be an offset-bearing string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp requires timezone")
    return parsed.astimezone(timezone.utc)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Dependency(StrictModel):
    article_id: str = Field(min_length=1, max_length=200)
    semantic_revision: int = Field(ge=1)
    eligibility_generation: int = Field(ge=1)
    input_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    s3_recipe_id: str = Field(min_length=1, max_length=200)
    facets_result_id: str = Field(min_length=1, max_length=200)
    embedding_result_id: str | None
    cluster_id: str | None
    membership_version: int | None = Field(ge=1)
    cluster_version: int | None = Field(ge=1)
    source_id: str = Field(min_length=1, max_length=200)
    source_generation: int = Field(ge=1)
    artifact_id: str | None
    artifact_hash: str | None = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def complete_references(self):
        if (self.cluster_id is None) != (self.membership_version is None) or \
                (self.cluster_id is None) != (self.cluster_version is None):
            raise ValueError("partial membership reference")
        if (self.artifact_id is None) != (self.artifact_hash is None):
            raise ValueError("partial artifact reference")
        for key in ("article_id", "s3_recipe_id", "facets_result_id", "embedding_result_id", "cluster_id", "source_id", "artifact_id"):
            value = getattr(self, key)
            if value is not None and (not value.strip() or len(value) > 200):
                raise ValueError("invalid dependency identifier")
        return self


class Span(StrictModel):
    field: Literal["title", "summary", "body"]
    field_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def offsets(self):
        if self.end - self.start != len(self.quote):
            raise ValueError("span offsets mismatch")
        return self


class Occurrence(StrictModel):
    start: str | None
    end: str | None
    precision: Literal["unknown", "day", "instant", "interval"]
    evidence_ids: list[str] = Field(max_length=16)

    @model_validator(mode="after")
    def interval(self):
        _unique(self.evidence_ids, "occurrence references")
        if self.precision == "unknown":
            if self.start is not None or self.end is not None or self.evidence_ids:
                raise ValueError("unknown occurrence must not invent bounds")
        else:
            if self.start is None or self.end is None or not self.evidence_ids:
                raise ValueError("known occurrence requires supported bounds")
            if timestamp(self.start) > timestamp(self.end):
                raise ValueError("reversed occurrence interval")
        return self


class Claim(StrictModel):
    actor_ids: list[str] = Field(max_length=12)
    action: str = Field(min_length=1, max_length=300)
    object: str | None = Field(max_length=500)
    place_ids: list[str] = Field(max_length=12)
    modality: Literal["unknown", "reported", "alleged", "denied", "predicted", "disputed", "corrected", "retracted"]
    attribution: str | None = Field(max_length=500)
    occurrence: Occurrence

    @model_validator(mode="after")
    def identifiers(self):
        for values in (self.actor_ids, self.place_ids):
            _unique(values, "claim identities")
            if any(len(value) > 200 for value in values):
                raise ValueError("claim identity too long")
        if not self.action.strip() or self.object is not None and not self.object.strip():
            raise ValueError("blank claim action/object")
        return self


class Source(StrictModel):
    publisher_id: str | None = Field(max_length=200)
    reporting_origin_id: str | None = Field(max_length=200)
    origin_status: Literal["unknown", "verified"]
    primary_verified: bool
    language: str | None = Field(max_length=40)

    @model_validator(mode="after")
    def origin(self):
        if (self.origin_status == "verified") != (self.reporting_origin_id is not None):
            raise ValueError("origin identity requires verified provenance")
        for value in (self.publisher_id, self.reporting_origin_id, self.language):
            if value is not None and not value.strip():
                raise ValueError("blank source metadata")
        return self


class Evidence(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    dependency: Dependency
    hint_index: int = Field(ge=0, le=7)
    hint_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    role: Literal["core", "background", "contradiction", "withdrawn", "unknown"]
    claim: Claim
    source: Source
    spans: list[Span] = Field(min_length=1, max_length=8)
    observed_at: str
    published_at: str | None

    @model_validator(mode="after")
    def original_evidence(self):
        if not self.id.strip():
            raise ValueError("blank evidence identity")
        timestamp(self.observed_at)
        if self.published_at is not None:
            timestamp(self.published_at)
        if any(span.field == "body" for span in self.spans) and self.dependency.artifact_id is None:
            raise ValueError("body span needs original artifact")
        return self


class Coverage(StrictModel):
    complete: bool
    supported: bool
    observed_through: str


class SupportPolicy(StrictModel):
    minimum_independent_origins: int = Field(ge=2, le=20)
    allow_verified_primary: bool


class Snapshot(StrictModel):
    event_id: str = Field(min_length=1, max_length=200)
    generation: int = Field(ge=1)
    recipe_id: str = Field(min_length=1, max_length=200)
    s3_control_generation: int = Field(ge=1)
    s4_control_generation: int = Field(ge=1)
    member_generation: int = Field(ge=1)
    as_of: str
    evidence: list[Evidence] = Field(max_length=128)
    coverage: Coverage
    support_policy: SupportPolicy
    previous_snapshot_hash: str | None = Field(pattern=r"^[a-f0-9]{64}$")
    dependency_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Dimension(StrictModel):
    name: Literal["consequence", "scope", "time_sensitivity", "support", "material_change", "coverage_quality"]
    value: Literal["met", "not_met", "unknown"]
    evidence_ids: list[str] = Field(max_length=32)


class Scope(StrictModel):
    kind: Literal["global", "regional", "local", "sector", "unknown"]
    place_ids: list[str] = Field(max_length=24)
    sectors: list[str] = Field(max_length=12)
    evidence_ids: list[str] = Field(max_length=32)


class Assessment(StrictModel):
    event_id: str = Field(min_length=1, max_length=200)
    generation: int = Field(ge=1)
    recipe_id: str = Field(min_length=1, max_length=200)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["ready", "insufficient", "unsupported", "disputed", "pending", "error", "stale"]
    tier: Literal["world_critical", "major", "routine"] | None
    dimensions: list[Dimension] = Field(min_length=6, max_length=6)
    scope: Scope
    reason_codes: list[Literal["supported_consequence", "scoped_consequence", "not_significant", "no_material_change", "insufficient_evidence", "unknown_origin", "conflicting_evidence", "unsupported_slice", "incomplete_coverage", "awaiting_assessment", "provider_failure", "dependency_changed"]] = Field(min_length=1, max_length=12)
    evidence_ids: list[str] = Field(max_length=64)
    valid_until: str | None


DIMENSIONS = ("consequence", "scope", "time_sensitivity", "support", "material_change", "coverage_quality")


def _unique(values, name):
    if len(values) != len(set(values)):
        raise ValueError("duplicate " + name)
    if any(isinstance(value, str) and not value.strip() for value in values):
        raise ValueError("blank " + name)


def dependency_digest(evidence: list[dict]) -> str:
    """Pin every admitted mention, role and negative claim, not only support.

    Identical article dependencies may occur in multiple mentions. Each mention
    is retained independently; replacing a negative claim changes this digest.
    """
    return digest(sorted(evidence, key=lambda item: item["id"]))


def validate_snapshot(payload: Mapping[str, Any]) -> dict:
    snapshot = Snapshot.model_validate(payload).model_dump()
    as_of = timestamp(snapshot["as_of"])
    if timestamp(snapshot["coverage"]["observed_through"]) > as_of:
        raise ValueError("coverage cutoff exceeds assessment cutoff")
    evidence = snapshot["evidence"]
    if len({item["dependency"]["s3_recipe_id"] for item in evidence}) > 1:
        raise ValueError("mixed S3 recipes cannot share an event snapshot")
    ids = [item["id"] for item in evidence]
    _unique(ids, "evidence IDs")
    if len(canonical_json(snapshot).encode("utf-8")) > 512_000:
        raise ValueError("snapshot exceeds byte limit; no implicit truncation")
    article_dependencies = {}
    source_generations = {}
    for item in evidence:
        dep = item["dependency"]
        _unique([dep["article_id"]], "article ID")
        dependency = canonical_json([dep, item["source"]])
        existing = article_dependencies.setdefault(dep["article_id"], dependency)
        if existing != dependency:
            raise ValueError("mixed article dependency versions")
        generation = source_generations.setdefault(dep["source_id"], dep["source_generation"])
        if generation != dep["source_generation"]:
            raise ValueError("mixed source registry generations")
        if timestamp(item["observed_at"]) > as_of:
            raise ValueError("future evidence cannot enter replay")
        if item["published_at"] is not None:
            timestamp(item["published_at"])
        claim = item["claim"]
        _unique(claim["actor_ids"], "actor IDs")
        _unique(claim["place_ids"], "place IDs")
        occurrence = claim["occurrence"]
        refs = occurrence["evidence_ids"]
        _unique(refs, "occurrence references")
        if set(refs) - set(ids):
            raise ValueError("unknown occurrence reference")
        if occurrence["precision"] == "unknown":
            if occurrence["start"] is not None or occurrence["end"] is not None or refs:
                raise ValueError("unknown occurrence must not invent bounds")
        else:
            if occurrence["start"] is None or occurrence["end"] is None or not refs:
                raise ValueError("known occurrence requires supported bounds")
            if timestamp(occurrence["start"]) > timestamp(occurrence["end"]):
                raise ValueError("reversed occurrence interval")
    if snapshot["dependency_digest"] != dependency_digest(evidence):
        raise ValueError("dependency manifest mismatch")
    return snapshot


def snapshot_hash(snapshot: Mapping[str, Any]) -> str:
    return digest(validate_snapshot(snapshot))


def validate_assessment(payload: Mapping[str, Any], snapshot: Mapping[str, Any], *, now=None) -> dict:
    frozen = validate_snapshot(snapshot)
    result = Assessment.model_validate(payload).model_dump()
    if any(result[key] != frozen[key] for key in ("event_id", "generation", "recipe_id")) or \
            result["snapshot_hash"] != digest(frozen):
        raise ValueError("assessment identity or snapshot mismatch")
    _unique([item["name"] for item in result["dimensions"]], "dimensions")
    if {item["name"] for item in result["dimensions"]} != set(DIMENSIONS):
        raise ValueError("all policy dimensions required")
    _unique(result["reason_codes"], "reason codes")
    all_ids = {item["id"] for item in frozen["evidence"]}
    for refs in [result["evidence_ids"], result["scope"]["evidence_ids"],
                 *(dim["evidence_ids"] for dim in result["dimensions"])]:
        _unique(refs, "assessment references")
        if set(refs) - all_ids:
            raise ValueError("unknown assessment evidence")
    if result["status"] != "ready":
        if result["tier"] is not None or result["valid_until"] is not None:
            raise ValueError("non-ready assessment cannot authorize priority")
        return result
    if result["tier"] is None or result["valid_until"] is None or not result["evidence_ids"]:
        raise ValueError("ready assessment requires tier, evidence and expiry")
    expiry = timestamp(result["valid_until"])
    as_of = timestamp(frozen["as_of"])
    current = timestamp(now) if isinstance(now, str) else now
    if current is not None and (not isinstance(current, datetime) or current.tzinfo is None):
        raise ValueError("now must be offset-bearing")
    if current is not None and as_of > current:
        raise ValueError("future snapshot cannot authorize an assessment")
    if expiry <= as_of or (expiry - as_of).total_seconds() > 86400:
        raise ValueError("expiry outside bounded 24-hour validity")
    if current is not None and expiry <= current:
        raise ValueError("assessment expired")
    if not frozen["coverage"]["complete"] or not frozen["coverage"]["supported"]:
        raise ValueError("incomplete or unsupported coverage cannot be ready")
    for dim in result["dimensions"]:
        if dim["value"] != "unknown" and not dim["evidence_ids"]:
            raise ValueError("asserted dimension requires evidence")
    if result["tier"] == "routine" and next(dim["value"] for dim in result["dimensions"] if dim["name"] == "consequence") != "not_met":
        raise ValueError("routine requires affirmative low-consequence assessment")
    if result["scope"]["kind"] != "unknown" and not result["scope"]["evidence_ids"]:
        raise ValueError("asserted scope requires evidence")
    if result["scope"]["kind"] in ("regional", "local") and not result["scope"]["place_ids"]:
        raise ValueError("localized scope requires explicit places")
    if result["scope"]["kind"] == "sector" and not result["scope"]["sectors"]:
        raise ValueError("sector scope requires explicit sector")
    known_places = {place for item in frozen["evidence"] for place in item["claim"]["place_ids"]}
    if set(result["scope"]["place_ids"]) - known_places:
        raise ValueError("scope contains unsupported places")
    if result["tier"] in ("major", "world_critical"):
        required = {"consequence", "scope", "support", "coverage_quality"}
        if any(dim["value"] != "met" for dim in result["dimensions"] if dim["name"] in required):
            raise ValueError("elevation requires supported scoped consequence")
        if result["scope"]["kind"] == "unknown":
            raise ValueError("elevation needs scoped consequence")
        support_ids = next(dim["evidence_ids"] for dim in result["dimensions"] if dim["name"] == "support")
        core = [item for item in frozen["evidence"] if item["id"] in support_ids and item["role"] == "core"
                and item["claim"]["modality"] in ("reported", "corrected")]
        origins = {item["source"]["reporting_origin_id"] for item in core if item["source"]["origin_status"] == "verified"}
        policy = frozen["support_policy"]
        if len(origins) < policy["minimum_independent_origins"] and not (
            policy["allow_verified_primary"] and any(item["source"]["primary_verified"] for item in core)
        ):
            raise ValueError("insufficient independent core support")
    return result


def priority_eligible(assessment: Mapping[str, Any], snapshot: Mapping[str, Any], *, now) -> bool:
    """Pure priority prerequisite, not reader authorization or live DB fencing.

    Significance may persist while a new copy adds nothing. Only a current,
    material development can occupy a reserved slot; caller still enforces
    reader exclusions, current dependencies, representative eligibility and cap.
    """
    if now is None:
        raise ValueError("priority eligibility requires an authorization time")
    try:
        result = validate_assessment(assessment, snapshot, now=now)
    except ValueError:
        return False
    return result["status"] == "ready" and result["tier"] == "world_critical" and all(
        dim["value"] == "met" for dim in result["dimensions"])


def snapshot_schema() -> dict:
    return Snapshot.model_json_schema()


def assessment_schema() -> dict:
    return Assessment.model_json_schema()
