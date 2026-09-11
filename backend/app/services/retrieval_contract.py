"""Private S6 candidate contract. Retrieval rank is never editorial relevance."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
import uuid
import json

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from .reader_contract import StrictModel, ReaderProfile, canonical_hash


RECIPE = {
    'version': 's6-candidates-v1', 'lexical': 'simple-strict-label-v1',
    'fusion': 'family-max-rrf60', 'allocation': 'explicit-weighted-fair-v1',
    'lookback_days': 14, 'max_candidates': 300, 'max_unique': 2400,
    'max_rows': 7200, 'rounds': 3, 'deadline_seconds': 2.0,
}


class RetrievalRequest(StrictModel):
    user_id: StrictStr
    generation: Annotated[StrictInt, Field(ge=1)]
    revision: Annotated[StrictInt, Field(ge=1)]
    learning_revision: Annotated[StrictInt, Field(ge=1)]
    profile: ReaderProfile
    limit: Annotated[StrictInt, Field(ge=0, le=300)] = 300
    as_of: datetime

    @field_validator('user_id')
    @classmethod
    def identity(cls, value):
        return str(uuid.UUID(value))

    @field_validator('as_of')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('as_of requires timezone')
        return value.astimezone(timezone.utc)


class Match(StrictModel):
    intent_id: StrictStr | None
    leg: Literal['lexical', 'identity', 'dense', 'generic']
    variant: StrictStr
    rank: Annotated[StrictInt, Field(ge=1)]
    score: Annotated[float, Field(allow_inf_nan=False)]
    query_hash: StrictStr
    recipe_id: StrictStr | None = None
    input_hash: StrictStr | None = None
    unresolved_qualifiers: bool = False


class Candidate(StrictModel):
    article_id: StrictStr
    allocated_intent_id: StrictStr | None
    matched_intent_ids: list[StrictStr]
    matches: Annotated[list[Match], Field(min_length=1, max_length=120)]
    retrieval_score: Annotated[float, Field(allow_inf_nan=False, ge=0)]
    article_stamp: StrictStr
    evidence_stamp: dict
    policy_evidence: dict
    article: dict


class CandidateBatch(StrictModel):
    request_id: StrictStr
    user_id: StrictStr
    generation: StrictInt
    revision: StrictInt
    learning_revision: StrictInt
    reader_hash: StrictStr
    as_of: datetime
    valid_until: datetime
    retrieval_recipe: StrictStr
    configuration: dict
    s3_recipe_id: StrictStr | None
    space_id: StrictStr | None
    status: Literal['complete', 'degraded', 'empty', 'stale']
    candidates: Annotated[list[Candidate], Field(max_length=300)]
    diagnostics: dict

    @model_validator(mode='after')
    def unique_and_scoped(self):
        ids = [item.article_id for item in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate candidate')
        for item in self.candidates:
            matched = {match.intent_id for match in item.matches if match.intent_id is not None}
            if set(item.matched_intent_ids) != matched or (item.allocated_intent_id is not None
                    and item.allocated_intent_id not in matched):
                raise ValueError('candidate attribution mismatch')
        if self.as_of.tzinfo is None or self.valid_until.tzinfo is None or self.valid_until < self.as_of:
            raise ValueError('invalid validity interval')
        return self


class RankingDecision(StrictModel):
    """An S7 verdict, not a converted retrieval similarity/probability."""
    article_id: StrictStr
    relevant: StrictBool
    score: Annotated[float, Field(strict=True, allow_inf_nan=False)]


def validate_decisions(batch, values):
    decisions = [RankingDecision.model_validate(value) for value in values]
    identifiers = [value.article_id for value in decisions]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != {
            candidate.article_id for candidate in batch.candidates}:
        raise ValueError('ranker must return exactly one verdict per candidate ID')
    return decisions


def validity(request):
    until = request.as_of + timedelta(minutes=15)
    for item in [*request.profile.intents, *request.profile.policies]:
        if item.expires_at:
            expiry = datetime.fromisoformat(item.expires_at.replace('Z', '+00:00'))
            if expiry > request.as_of:
                until = min(until, expiry)
    return until


def article_stamp(article):
    # Whole hydrated metadata includes S2 display artifact provenance. No body or
    # private query text is logged; this digest fences later correction/deletion.
    return canonical_hash(json.loads(json.dumps(
        {k: v for k, v in article.items() if not k.startswith('_')},
        sort_keys=True, default=str, allow_nan=False)))
