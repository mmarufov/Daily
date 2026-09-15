"""Private S8 contracts: selection consumes authority, it never invents it.

``coverage_key`` is a namespaced, adapter-verified specific coverage identity. None
means an unknown singleton. Titles, proximity, URLs and broad event IDs are not
accepted identity evidence by this module. The adapter owns fresh authorization.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from .reader_contract import StrictModel, canonical_hash


RECIPE = {'version': 's8-assembly-v1', 'ordering': 'grade-intent-variety-v1',
          's3_membership_enabled': False, 'history_retention_days': 30,
          'topic_share': .6, 'publisher_share': .5, 'source_streak': 2}


def validate_recipe(value):
    if not isinstance(value, dict) or set(value) != set(RECIPE):
        raise ValueError('unsupported assembly recipe')
    for key in ('version', 'ordering'):
        if value[key] != RECIPE[key]:
            raise ValueError('unsupported assembly recipe')
    if type(value['s3_membership_enabled']) is not bool:
        raise ValueError('invalid assembly membership capability')
    for key, maximum in [('history_retention_days', 30), ('source_streak', 100)]:
        if type(value[key]) is not int or not 1 <= value[key] <= maximum:
            raise ValueError('invalid assembly bound')
    for key in ('topic_share', 'publisher_share'):
        if type(value[key]) not in (int, float) or not math.isfinite(value[key]) or not .1 <= value[key] <= 1:
            raise ValueError('invalid assembly share')
    return deepcopy(value)


Identifier = Annotated[StrictStr, Field(min_length=1, max_length=512)]
Priority = Annotated[float, Field(strict=True, ge=.1, le=3, allow_inf_nan=False)]
Origin = Literal['ordinary', 'world_critical']


class AssemblyCandidate(StrictModel):
    article_id: Identifier
    ordinal: Annotated[StrictInt, Field(ge=0, le=301)]
    grade: Annotated[StrictInt, Field(ge=0, le=3)]
    intents: dict[Identifier, Priority] = Field(default_factory=dict)
    origin: Origin = 'ordinary'
    # Only an independently authorized S4 adapter can assert this flag. Ordinary
    # authority is its own accepted grade/intents (or accepted generic grade 0).
    authorized: StrictBool = False
    eligible: StrictBool = True
    coverage_key: Identifier | None = None
    novelty_key: Identifier | None = None
    known_read: StrictBool = False
    publisher_id: Identifier | None = None
    topic_ids: Annotated[list[Identifier], Field(max_length=24)] = Field(default_factory=list)
    evidence_stamp: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def coherent(self):
        if self.grade not in (0, 2, 3) or bool(self.intents) != (self.grade >= 2):
            raise ValueError('assembly needs own accepted relevance or neutral generic mode')
        if len(self.intents) > 24 or len(self.topic_ids) != len(set(self.topic_ids)):
            raise ValueError('invalid assembly metadata cardinality')
        if self.known_read and self.novelty_key is None:
            raise ValueError('known read requires a supported content key')
        return self


class AssemblyRequest(StrictModel):
    user_id: Identifier
    request_id: Identifier
    ranking_context_hash: Identifier
    ranking_recipe_hash: Identifier
    generation: Annotated[StrictInt, Field(ge=1)]
    revision: Annotated[StrictInt, Field(ge=1)]
    history_revision: Annotated[StrictInt, Field(ge=0)]
    as_of: datetime
    valid_until: datetime
    limit: Annotated[StrictInt, Field(ge=1, le=100)]
    candidates: Annotated[list[AssemblyCandidate], Field(max_length=302)]
    recipe: dict = Field(default_factory=lambda: deepcopy(RECIPE))
    assembly_epoch: Annotated[StrictInt, Field(ge=1)] = 1
    dependencies: dict = Field(default_factory=dict)

    @field_validator('as_of', 'valid_until')
    @classmethod
    def zoned(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError('assembly time requires timezone')
        return value.astimezone(timezone.utc)

    @model_validator(mode='after')
    def coherent(self):
        self.recipe = validate_recipe(self.recipe)
        if self.valid_until <= self.as_of:
            raise ValueError('assembly validity must be positive')
        ids = [c.article_id for c in self.candidates]
        ordinary = [c for c in self.candidates if c.origin == 'ordinary']
        if len(ids) != len(set(ids)) or len(ordinary) > 300 or len(self.candidates)-len(ordinary) > 2:
            raise ValueError('assembly candidate set must be unique and bounded')
        ordinals = [c.ordinal for c in ordinary]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError('ordinary ranking ordinals must be unique')
        priorities = {}
        for candidate in self.candidates:
            for intent, priority in candidate.intents.items():
                if intent in priorities and priorities[intent] != priority:
                    raise ValueError('inconsistent explicit intent priority')
                priorities[intent] = priority
        return self

    @property
    def recipe_hash(self):
        return canonical_hash(self.recipe)

    @property
    def fingerprint(self):
        data = self.model_dump(mode='json')
        data['candidates'] = sorted(data['candidates'], key=lambda c: (c['origin'], c['ordinal'], c['article_id']))
        for candidate in data['candidates']:
            candidate['topic_ids'] = sorted(candidate['topic_ids'])
        return canonical_hash(data)


class AssemblySelection(StrictModel):
    article_id: Identifier
    origin: Origin
    final_position: Annotated[StrictInt, Field(ge=0, le=99)]
    ordinal: Annotated[StrictInt, Field(ge=0, le=301)]
    grade: Annotated[StrictInt, Field(ge=0, le=3)]
    intents: dict[Identifier, Priority]
    scheduled_intent_id: Identifier | None = None
    coverage_key: Identifier | None = None
    novelty_key: Identifier | None = None


Disposition = Literal['selected', 'equivalent_copy', 'known_read_repeat', 'capacity',
                      'policy_stale', 'critical_unauthorized', 'critical_overflow']


class AssemblyDisposition(StrictModel):
    article_id: Identifier
    reason: Disposition
    identity_status: Literal['verified', 'unknown']
    equivalent_to: Identifier | None = None


class AssemblyResult(StrictModel):
    request_id: Identifier
    context_hash: Identifier
    recipe_hash: Identifier
    assembly_epoch: Annotated[StrictInt, Field(ge=1)]
    history_revision: Annotated[StrictInt, Field(ge=0)]
    valid_until: datetime
    ordered_ids: Annotated[list[Identifier], Field(max_length=100)]
    selections: Annotated[list[AssemblySelection], Field(max_length=100)]
    dispositions: Annotated[list[AssemblyDisposition], Field(max_length=302)]
    dependencies: dict = Field(default_factory=dict)
    diagnostics: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def coherent(self):
        ids = [s.article_id for s in self.selections]
        if ids != self.ordered_ids or len(ids) != len(set(ids)):
            raise ValueError('invalid assembly order')
        if [s.final_position for s in self.selections] != list(range(len(ids))):
            raise ValueError('assembly position gaps')
        dispositions = [d.article_id for d in self.dispositions]
        if len(dispositions) != len(set(dispositions)) or set(ids) != {
                d.article_id for d in self.dispositions if d.reason == 'selected'}:
            raise ValueError('assembly disposition mismatch')
        units = [s.coverage_key for s in self.selections if s.coverage_key is not None]
        if len(units) != len(set(units)) or sum(s.origin == 'world_critical' for s in self.selections) > 2:
            raise ValueError('assembly identity or critical bound violated')
        return self


def validate_result(request: AssemblyRequest, value) -> AssemblyResult:
    """Validate a stored/private result against the exact freshly authorized input."""
    request = AssemblyRequest.model_validate(request.model_dump())
    result = AssemblyResult.model_validate(value.model_dump() if isinstance(value, AssemblyResult) else value)
    expected = (request.request_id, request.fingerprint, request.recipe_hash, request.assembly_epoch,
                request.history_revision, request.valid_until, request.dependencies)
    actual = (result.request_id, result.context_hash, result.recipe_hash, result.assembly_epoch,
              result.history_revision, result.valid_until, result.dependencies)
    candidates = {c.article_id: c for c in request.candidates}
    if actual != expected or len(result.ordered_ids) > request.limit or set(candidates) != {d.article_id for d in result.dispositions}:
        raise ValueError('assembly context or candidate set mismatch')
    selected = {s.article_id: s for s in result.selections}
    ordinary_grades = [s.grade for s in result.selections if s.origin == 'ordinary']
    if ordinary_grades != sorted(ordinary_grades, reverse=True):
        raise ValueError('assembly displaced a stronger relevance grade')
    seen_ordinary = False
    for selection in result.selections:
        candidate = candidates[selection.article_id]
        if selection.origin == 'ordinary':
            seen_ordinary = True
        elif seen_ordinary:
            raise ValueError('critical reservations must precede ordinary selection')
        for field in ('article_id', 'origin', 'ordinal', 'grade', 'intents', 'coverage_key', 'novelty_key'):
            if getattr(selection, field) != getattr(candidate, field):
                raise ValueError('assembly forged candidate attribution')
        if not candidate.eligible or candidate.known_read or (candidate.origin == 'world_critical' and not candidate.authorized):
            raise ValueError('assembly selected an unauthorized opportunity')
        if selection.scheduled_intent_id is not None and (selection.origin != 'ordinary' or selection.scheduled_intent_id not in candidate.intents):
            raise ValueError('invalid assembly intent allocation')
        if candidate.origin == 'ordinary' and candidate.intents and selection.scheduled_intent_id is None:
            raise ValueError('personalized selection requires one scheduling attribution')
    selected_units = {s.coverage_key: s for s in result.selections if s.coverage_key is not None}
    for disposition in result.dispositions:
        candidate = candidates[disposition.article_id]
        expected_reason = ('policy_stale' if not candidate.eligible else
            'critical_unauthorized' if candidate.origin == 'world_critical' and not candidate.authorized else
            'known_read_repeat' if candidate.known_read else
            'selected' if candidate.article_id in selected else
            'equivalent_copy' if candidate.coverage_key is not None and candidate.coverage_key in selected_units else
            'critical_overflow' if candidate.origin == 'world_critical' else 'capacity')
        if disposition.reason != expected_reason:
            raise ValueError('unsupported assembly disposition')
        if disposition.identity_status != ('verified' if candidate.coverage_key is not None else 'unknown'):
            raise ValueError('assembly identity status mismatch')
        if disposition.reason == 'equivalent_copy':
            representative = selected.get(disposition.equivalent_to)
            if not representative or not candidate.coverage_key or candidate.coverage_key != representative.coverage_key:
                raise ValueError('unsupported assembly equivalence')
        elif disposition.equivalent_to is not None:
            raise ValueError('unexpected equivalent representative')
        if disposition.reason == 'known_read_repeat' and not candidate.known_read:
            raise ValueError('unsupported read suppression')
        if disposition.reason == 'capacity' and candidate.origin == 'ordinary' and any(
                s.origin == 'ordinary' and s.grade < candidate.grade for s in result.selections):
            raise ValueError('assembly skipped stronger available relevance')
        if disposition.reason in ('capacity', 'critical_overflow') and len(result.selections) < request.limit:
            raise ValueError('assembly left a fillable capacity gap')
    return result
