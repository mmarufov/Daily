"""Independent S4 evaluation artifacts, deliberately separate from runtime cards.

These records are authored from frozen source evidence, never inferred from the
detector under test. Hashes bind a run to the complete dataset and protocol.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Evaluation times must include an explicit UTC offset")
    return parsed.astimezone(timezone.utc)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Review(Strict):
    status: Literal["unreviewed", "model_seed", "adjudicated"]
    provenance: Literal["human", "agent", "model"] | None = None
    reviewer: str | None = None
    rationale: str | None = None
    reviewed_at: str | None = None
    blind_to_predictions: bool = False

    @model_validator(mode="after")
    def independent(self):
        if self.status == "adjudicated":
            if self.provenance not in {"human", "agent"} or not self.reviewer or not self.rationale or not self.reviewed_at:
                raise ValueError("Adjudication requires independent reviewer and evidence rationale")
            instant(self.reviewed_at)
        return self


class Mention(Strict):
    id: str = Field(min_length=1, max_length=200)
    article_revision_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    origin_id: str = Field(min_length=1, max_length=200)
    canonical_id: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    development_id: str = Field(min_length=1, max_length=200)
    available_at: str

    @field_validator("available_at")
    @classmethod
    def timestamp(cls, value):
        instant(value)
        return value


class Development(Strict):
    id: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    family_id: str = Field(min_length=1, max_length=200)
    window_id: str = Field(min_length=1, max_length=200)
    independence_id: str = Field(min_length=1, max_length=200)
    split: Literal["development", "holdout"]
    slices: list[str] = Field(min_length=1, max_length=20)
    event_type: str = Field(min_length=1, max_length=100)
    place_key: str = Field(min_length=1, max_length=200)
    occurred_start: str
    occurred_end: str
    qualifies_at: str
    deadline_at: str
    eligible: bool
    core_mentions: list[str] = Field(min_length=1, max_length=500)
    direct_mentions: list[str] = Field(default_factory=list, max_length=500)
    tier: Literal["world_critical", "major", "routine"] | None
    material: bool | None
    review: Review

    @model_validator(mode="after")
    def valid(self):
        if instant(self.occurred_start) > instant(self.occurred_end):
            raise ValueError("Reversed event interval")
        if instant(self.qualifies_at) > instant(self.deadline_at):
            raise ValueError("Deadline precedes qualifying evidence")
        for values in (self.core_mentions, self.direct_mentions, self.slices):
            if len(values) != len(set(values)) or any(not value for value in values):
                raise ValueError("Duplicate or empty label references")
        if self.review.status == "adjudicated" and (self.tier is None or self.material is None):
            raise ValueError("Adjudicated developments need significance and novelty labels")
        return self


class Dataset(Strict):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=1, max_length=200)
    sampling: Literal["complete_windows", "probability_sample", "adversarial", "balanced"]
    sampling_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_at: str
    mentions: list[Mention] = Field(max_length=100000)
    developments: list[Development] = Field(max_length=20000)

    @model_validator(mode="after")
    def references_and_leakage(self):
        instant(self.frozen_at)
        mentions = {m.id: m for m in self.mentions}
        developments = {d.id: d for d in self.developments}
        if len(mentions) != len(self.mentions) or len(developments) != len(self.developments):
            raise ValueError("Duplicate evaluation identity")
        groups: dict[tuple, set] = {}
        canonical = {}
        for d in self.developments:
            for kind, value in (("family", d.family_id), ("window", d.window_id), ("event", d.event_id)):
                groups.setdefault((kind, value), set()).add(d.split)
            if not set(d.direct_mentions) <= set(d.core_mentions):
                raise ValueError("Direct representatives must support core development evidence")
            for mid in d.core_mentions:
                m = mentions.get(mid)
                if m is None or m.development_id != d.id or m.event_id != d.event_id:
                    raise ValueError("Gold core mention belongs to another event/development")
                if instant(m.available_at) > instant(d.qualifies_at):
                    raise ValueError("Gold core evidence was unavailable when the label claims it qualified")
        for m in self.mentions:
            d = developments.get(m.development_id)
            if d is None or d.event_id != m.event_id:
                raise ValueError("Mention references unknown or different development/event")
            groups.setdefault(("origin", m.origin_id), set()).add(d.split)
            identity = (m.event_id, m.development_id, m.origin_id)
            if m.canonical_id in canonical and canonical[m.canonical_id] != identity:
                raise ValueError("Canonical mention cannot join unrelated evidence/origins")
            canonical[m.canonical_id] = identity
        if any(len(splits) > 1 for splits in groups.values()):
            raise ValueError("Event family, adjacent window, event or syndicated origin leaks across splits")
        return self


class Prediction(Strict):
    id: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    status: Literal["ready", "unknown", "pending", "failed", "unsupported"]
    tier: Literal["world_critical", "major", "routine"] | None
    material: bool | None
    members: list[str] = Field(default_factory=list, max_length=500)
    event_type: str = Field(min_length=1, max_length=100)
    place_key: str = Field(min_length=1, max_length=200)
    occurred_start: str
    occurred_end: str
    completed_at: str
    evidence_cutoff: str
    representative_mention_id: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if instant(self.occurred_start) > instant(self.occurred_end):
            raise ValueError("Reversed prediction interval")
        instant(self.completed_at)
        if instant(self.evidence_cutoff) > instant(self.completed_at):
            raise ValueError("Prediction evidence cutoff follows completion")
        if len(self.members) != len(set(self.members)):
            raise ValueError("Duplicate predicted member")
        if self.status != "ready" and (self.tier is not None or self.material is not None):
            raise ValueError("Non-ready outcome cannot assert a tier/material judgment")
        if self.status == "ready" and (self.tier is None or self.material is None or not self.members):
            raise ValueError("Ready outcome requires evidence, tier and novelty judgment")
        if self.representative_mention_id is not None and self.representative_mention_id not in self.members:
            raise ValueError("Representative is not in the prediction's evidence")
        return self


class OutcomeReview(Strict):
    prediction_id: str = Field(min_length=1, max_length=200)
    prediction_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    unsupported_assertions: int = Field(ge=0)
    direct_support: bool | None
    review: Review


class AdversarialCase(Strict):
    case_id: str = Field(min_length=1, max_length=200)
    false_critical_promotions: int = Field(ge=0)
    unsupported_assertions: int = Field(ge=0)


class AdversarialEvidence(Strict):
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evaluation_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Bind the independently reviewed adversarial run to the same candidate,
    # upstream source cohort and frozen quality protocol as this promotion.
    evaluation_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    review: Review
    cases: list[AdversarialCase] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def unique(self):
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate adversarial cases")
        return self


class Protocol(Strict):
    schema_version: Literal[1] = 1
    status: Literal["draft", "frozen"]
    approved_by: str | None = None
    frozen_at: str
    supported_slices: list[str] = Field(default_factory=list, max_length=100)
    alignment: Literal["core-overlap-type-place-time-maximum-cardinality-v1"] = "core-overlap-type-place-time-maximum-cardinality-v1"
    minimum_core_coverage: float = Field(default=0.5, gt=0, le=1)
    interval_method: Literal["independent-opportunity-clopper-pearson-v1", "blocked-unimplemented"] = "independent-opportunity-clopper-pearson-v1"
    independent_opportunities_attested: bool = False
    minimum_slice_developments: int = Field(default=100, ge=1)
    minimum_metric_denominator: int = Field(default=50, ge=1)
    fixed_adversarial_suite_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    required_adversarial_cases: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("minimum_core_coverage")
    @classmethod
    def finite(cls, value):
        if not math.isfinite(value):
            raise ValueError("Nonfinite threshold")
        return value

    @model_validator(mode="after")
    def valid(self):
        instant(self.frozen_at)
        for values in (self.supported_slices, self.required_adversarial_cases):
            if len(values) != len(set(values)) or any(not s for s in values):
                raise ValueError("Duplicate/empty support slice or adversarial case")
        if self.status == "frozen" and not self.approved_by:
            raise ValueError("Frozen protocol requires policy approval provenance")
        return self


BINDING_KEYS = {"recipe_sha256", "s3_recipe_sha256", "source_registry_sha256",
                "dataset_sha256", "split_sha256", "protocol_sha256"}


def split_digest(dataset: dict) -> str:
    return digest(sorted((d["id"], d["split"], d["family_id"], d["window_id"])
                         for d in dataset["developments"]))


def validate_bindings(bindings: dict) -> None:
    if not isinstance(bindings, dict) or set(bindings) != BINDING_KEYS:
        raise ValueError("Exact S4 evaluation recipe/data/protocol bindings are required")
    for value in bindings.values():
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Evaluation bindings must be SHA-256 digests")
