"""S5 authoritative reader contract. No inference or network work belongs here."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator


def clean_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


Text = Annotated[StrictStr, Field(min_length=1, max_length=280)]


class ReaderIntent(StrictModel):
    id: StrictStr
    kind: Literal["topic", "entity", "place", "utility"]
    label: Text
    query: Text = ""
    priority: Annotated[float, Field(strict=True, ge=0.1, le=3, allow_inf_nan=False)] = 1.0
    qualifiers: Annotated[list[Text], Field(max_length=8)] = Field(default_factory=list)
    resolved_id: Annotated[StrictStr, Field(min_length=1, max_length=200)] | None = None
    expires_at: StrictStr | None = None
    provenance: Literal["explicit", "reviewed_proposal", "legacy_import"] = "explicit"

    @model_validator(mode="before")
    @classmethod
    def default_query(cls, value):
        if isinstance(value, dict) and "query" not in value:
            value = {**value, "query": value.get("label")}
        return value

    @field_validator("id")
    @classmethod
    def uuid_id(cls, value):
        return str(UUID(value))

    @field_validator("label", "query")
    @classmethod
    def normalize_text(cls, value):
        value = clean_text(value)
        if not value:
            raise ValueError("text must not be blank")
        return value

    @field_validator("expires_at")
    @classmethod
    def timestamp(cls, value):
        if value is None:
            return None
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("expires_at requires a timezone")
        return date.astimezone(timezone.utc).isoformat()

    @model_validator(mode="after")
    def bounded_qualified_query(self):
        if len(clean_text(" ".join([self.query, *self.qualifiers]))) > 280:
            raise ValueError("query including qualifiers must be at most 280 characters")
        return self


class ReaderPolicy(StrictModel):
    id: StrictStr
    kind: Literal["publisher", "article", "lexical", "subject"]
    value: Text
    scope: Literal["source", "topic", "entity", "place", "sector"] = "topic"
    expires_at: StrictStr | None = None

    _id = field_validator("id")(ReaderIntent.uuid_id.__func__)
    _value = field_validator("value")(ReaderIntent.normalize_text.__func__)
    _expiry = field_validator("expires_at")(ReaderIntent.timestamp.__func__)


class ReaderProfile(StrictModel):
    schema_version: Literal[3] = 3
    intents: Annotated[list[ReaderIntent], Field(max_length=24)] = Field(default_factory=list)
    policies: Annotated[list[ReaderPolicy], Field(max_length=64)] = Field(default_factory=list)
    languages: Annotated[list[Annotated[StrictStr, Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")]], Field(max_length=8)] = Field(default_factory=list)
    depth: Literal["breaking", "balanced", "deep"] = "balanced"
    context: Annotated[StrictStr, Field(max_length=280)] = ""

    @model_validator(mode="after")
    def unique_ids_and_size(self):
        for name in ("intents", "policies"):
            ids = [item.id for item in getattr(self, name)]
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} IDs")
        if len(set(self.languages)) != len(self.languages):
            raise ValueError("duplicate languages")
        if len(self.model_dump_json().encode()) > 32768:
            raise ValueError("reader profile exceeds 32 KiB")
        return self


class ReaderMutation(StrictModel):
    operation_id: StrictStr
    base_generation: Annotated[StrictInt, Field(ge=1)]
    base_revision: Annotated[StrictInt, Field(ge=1)]
    patch: dict
    confirm_migration: StrictBool = False

    _id = field_validator("operation_id")(ReaderIntent.uuid_id.__func__)

    @field_validator("patch")
    @classmethod
    def supported_patch(cls, value):
        unknown = set(value) - {"intents", "policies", "languages", "depth", "context"}
        if unknown:
            raise ValueError("unsupported reader fields: " + ", ".join(sorted(unknown)))
        # Validate supplied values now; omitted values must remain omitted.
        ReaderProfile.model_validate(value)
        return value


def validate_profile(value: dict | ReaderProfile) -> dict:
    return ReaderProfile.model_validate(value).model_dump(mode="json")


def apply_patch(profile: dict, patch: dict) -> dict:
    unknown = set(patch) - {"intents", "policies", "languages", "depth", "context"}
    if unknown:
        raise ValueError("unsupported reader fields")
    return validate_profile({**profile, **patch})


def canonical_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def active(value: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    expiry = value.get("expires_at")
    return expiry is None or datetime.fromisoformat(expiry.replace("Z", "+00:00")) > now


def intent_semantic_hash(intent: dict) -> str:
    """Priority/order/expiry edits do not require a different embedding."""
    return canonical_hash({key: intent.get(key) for key in ("kind", "query", "qualifiers", "resolved_id")})
