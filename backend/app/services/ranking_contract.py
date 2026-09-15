"""Private S7 contracts. Unknown relevance is not negative training truth."""
from __future__ import annotations

from datetime import datetime
from copy import deepcopy
import math
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, model_validator

from .reader_contract import StrictModel, ReaderProfile, canonical_hash
from .retrieval_contract import CandidateBatch

RECIPE = {'version': 's7-ranking-v1', 'rubric': 'intent-grade-v1',
          'ordering': 'grade-priority-freshness-id-v1', 'central_identity': False,
          'model': 'gpt-4.1-mini-2025-04-14', 'max_attempts': 6,
          'pricing': {'input_usd_per_million': .40, 'output_usd_per_million': 1.60},
          'max_input_tokens': 12000, 'max_output_tokens': 6000,
          'deadline_seconds': 20.0}


def validate_recipe(value):
    """A declared implementation, not arbitrary operator JSON or inferred prices."""
    if not isinstance(value, dict) or set(value) != set(RECIPE):
        raise ValueError('unsupported ranking recipe')
    for key in ('version', 'rubric', 'ordering', 'model'):
        if value[key] != RECIPE[key]:
            raise ValueError('unsupported ranking recipe')
    if type(value['central_identity']) is not bool:
        raise ValueError('invalid central identity capability')
    for key in ('max_attempts', 'max_input_tokens', 'max_output_tokens'):
        if type(value[key]) is not int or not 1 <= value[key] <= RECIPE[key]:
            raise ValueError('invalid ranking ceiling')
    seconds = value['deadline_seconds']
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds <= 20:
        raise ValueError('invalid ranking deadline')
    prices = value['pricing']
    if not isinstance(prices, dict) or set(prices) != set(RECIPE['pricing']) or any(
            type(prices[key]) not in (int, float) or prices[key] != expected
            for key, expected in RECIPE['pricing'].items()):
        raise ValueError('unsupported ranking pricing')
    return deepcopy(value)


class EvidencePack(StrictModel):
    article_id: StrictStr
    input_hash: StrictStr
    title: Annotated[StrictStr, Field(max_length=1000)]
    summary: Annotated[StrictStr, Field(max_length=3000)]
    analysis: Annotated[StrictStr, Field(max_length=6000)] = ''
    analysis_allowed: StrictBool = False
    tier: Literal['publisher_metadata', 'publisher_analysis', 'revoked', 'missing']
    truncated: StrictBool = False
    central_ids: dict[str, list[str] | None] = Field(default_factory=dict)
    retrieval_intent_ids: list[StrictStr] = Field(default_factory=list)
    published_at: datetime | None = None


class RankingRequest(StrictModel):
    batch: CandidateBatch
    profile: ReaderProfile
    recipe: dict = Field(default_factory=lambda: deepcopy(RECIPE))
    evidence: Annotated[list[EvidencePack], Field(max_length=300)]
    learned: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode='after')
    def bound(self):
        self.recipe = validate_recipe(self.recipe)
        if canonical_hash(self.profile.model_dump()) != self.batch.reader_hash:
            raise ValueError('ranking reader hash mismatch')
        ids = [e.article_id for e in self.evidence]
        if len(ids) != len(set(ids)) or set(ids) != {c.article_id for c in self.batch.candidates}:
            raise ValueError('ranking evidence must cover exact candidate set')
        import math
        if any(not math.isfinite(w) or not -1 <= w <= .8 for w in self.learned.values()):
            raise ValueError('invalid learned signal')
        return self

    @property
    def fingerprint(self):
        return canonical_hash({'account': self.batch.user_id, 'request': self.batch.request_id,
            'as_of': self.batch.as_of.isoformat(), 'valid_until': self.batch.valid_until.isoformat(),
            'candidates': [c.model_dump(mode='json', exclude={'article'}) for c in self.batch.candidates],
            's3_recipe_id': self.batch.s3_recipe_id, 'reader': self.batch.reader_hash,
            'stamp': [self.batch.generation, self.batch.revision, self.batch.learning_revision],
            'retrieval': self.batch.retrieval_recipe, 'recipe': self.recipe,
            'evidence': [e.model_dump(mode='json') for e in self.evidence],
            'learned': self.learned})


class IntentGrade(StrictModel):
    intent_id: StrictStr
    grade: Annotated[StrictInt, Field(ge=0, le=3)] | None
    qualifiers: Literal['satisfied', 'contradicted', 'unknown']
    field: Literal['title', 'summary', 'analysis']
    quote: Annotated[StrictStr, Field(max_length=600)]


class ArticleJudgment(StrictModel):
    article_id: StrictStr
    input_hash: StrictStr
    decision: Literal['accept', 'reject', 'abstain']
    reason: Literal['substantive_match', 'not_relevant', 'insufficient_evidence',
                    'provider_unavailable', 'provider_invalid', 'budget_exhausted',
                    'deadline', 'analysis_revoked', 'generic', 'central_identity']
    explanation: Annotated[StrictStr, Field(max_length=500)]
    confirmed_intent_ids: Annotated[list[StrictStr], Field(max_length=24)]
    grades: Annotated[list[IntentGrade], Field(max_length=24)]

    @model_validator(mode='after')
    def attribution(self):
        reasons = {'accept': {'substantive_match', 'generic', 'central_identity'},
                   'reject': {'not_relevant'},
                   'abstain': {'insufficient_evidence', 'provider_unavailable', 'provider_invalid',
                               'budget_exhausted', 'deadline', 'analysis_revoked'}}
        if self.reason not in reasons[self.decision]:
            raise ValueError('ranking decision/reason mismatch')
        ids = [g.intent_id for g in self.grades]
        if len(ids) != len(set(ids)) or len(self.confirmed_intent_ids) != len(set(self.confirmed_intent_ids)):
            raise ValueError('duplicate ranking intent')
        expected = {g.intent_id for g in self.grades if g.grade is not None and g.grade >= 2 and g.qualifiers == 'satisfied'}
        if set(self.confirmed_intent_ids) != (expected if self.decision == 'accept' else set()):
            raise ValueError('ranking attribution mismatch')
        if self.decision == 'accept' and not expected and self.reason != 'generic':
            raise ValueError('acceptance requires confirmed intent')
        if self.decision != 'accept' and expected:
            raise ValueError('contradictory ranking decision')
        return self


def validate_judgments(request, evidence, values, *, provider=False):
    """Exact sub-batch, strict types, frozen input and grounded quote validation."""
    values = [ArticleJudgment.model_validate(v) for v in values]
    packs = {e.article_id: e for e in evidence}
    ids = [v.article_id for v in values]
    if len(ids) != len(set(ids)) or set(ids) != set(packs):
        raise ValueError('ranker must return exact article ID set')
    active = {i.id: i for i in request.profile.intents if not i.expires_at or
              datetime.fromisoformat(i.expires_at) > request.batch.as_of}
    for value in values:
        pack = packs[value.article_id]
        if value.input_hash != pack.input_hash:
            raise ValueError('ranking evidence hash mismatch')
        if provider and (not pack.analysis_allowed or value.reason in {'generic', 'central_identity'}):
            raise ValueError('provider cannot assert deterministic authority')
        if value.reason == 'generic' and active:
            raise ValueError('generic decision for personalized reader')
        for grade in value.grades:
            if grade.intent_id not in active:
                raise ValueError('unknown ranking intent')
            text = getattr(pack, grade.field)
            if grade.quote and grade.quote not in text:
                raise ValueError('ranking quote not in frozen evidence')
            if grade.grade is not None and grade.grade >= 2 and not grade.quote:
                raise ValueError('positive grade needs evidence')
        # A rejection claims no active intent applies; partial assessment is unknown.
        if value.decision == 'reject' and ({g.intent_id for g in value.grades} != set(active)
                or any(g.grade is None or g.qualifiers == 'unknown' for g in value.grades)):
            raise ValueError('incomplete intent assessment cannot reject')
    return values


class RankBatch(StrictModel):
    request_id: StrictStr
    context_hash: StrictStr
    recipe_hash: StrictStr
    status: Literal['complete', 'degraded', 'stale']
    valid_until: datetime
    judgments: Annotated[list[ArticleJudgment], Field(max_length=300)]
    ordered_ids: Annotated[list[StrictStr], Field(max_length=300)]
    diagnostics: dict = Field(default_factory=dict)

    @model_validator(mode='after')
    def ordered(self):
        ids = [j.article_id for j in self.judgments]
        accepted = {j.article_id for j in self.judgments if j.decision == 'accept'}
        if len(ids) != len(set(ids)) or len(self.ordered_ids) != len(set(self.ordered_ids)) or set(self.ordered_ids) != accepted:
            raise ValueError('invalid ranking order/decision set')
        return self
