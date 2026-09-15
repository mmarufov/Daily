"""Offline S7 metrics over actual candidates and decisions, never injected positives.

Labels must be independently supplied. This module measures a frozen run; it does
not generate truth, select thresholds, or certify semantic quality. Unknown labels
stay unknown and incomplete universes do not receive a deceptively perfect nDCG.
"""
from __future__ import annotations

from collections import Counter
import math
from typing import Annotated

from pydantic import Field, StrictBool, StrictInt

from app.services.reader_contract import StrictModel, canonical_hash
from app.services.ranking_contract import RankingRequest, RankBatch, validate_judgments


Grade = Annotated[StrictInt, Field(ge=0, le=3)]


class RankingLabel(StrictModel):
    grade: Grade | None = None
    prohibited: StrictBool | None = None
    intent_grades: dict[str, Grade | None] = Field(default_factory=dict)


def _rate(numerator, denominator):
    return {'value': numerator / denominator if denominator else None,
            'numerator': numerator, 'denominator': denominator}


def _ndcg(order, universe, labels, k):
    """Unknown relevance makes the ideal ordering unknowable, not zero gain."""
    if not universe or any(labels[key].grade is None for key in universe):
        return None
    dcg = sum((2 ** labels[key].grade - 1) / math.log2(position + 2)
              for position, key in enumerate(order[:k]))
    ideal = sorted((labels[key].grade for key in universe), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(position + 2)
               for position, grade in enumerate(ideal))
    return dcg / idcg if idcg else None


def _quality(order, universe, labels):
    known_shown = [key for key in order if labels[key].grade is not None]
    positives = {key for key in universe if labels[key].grade is not None
                 and labels[key].grade >= 2}
    known_policy = [key for key in order if labels[key].prohibited is not None]
    return {
        'universe_count': len(universe), 'shown_count': len(order),
        'relevance_label_coverage': _rate(sum(labels[key].grade is not None for key in universe), len(universe)),
        'shown_label_coverage': _rate(len(known_shown), len(order)),
        'acceptance_precision': _rate(sum(labels[key].grade >= 2 for key in known_shown), len(known_shown)),
        'known_positive_recall': _rate(len(set(order) & positives), len(positives)),
        'prohibited_rate': _rate(sum(labels[key].prohibited is True for key in known_policy), len(known_policy)),
        'policy_label_coverage': _rate(len(known_policy), len(order)),
        'ndcg_at_10': _ndcg(order, universe, labels, 10),
        'ndcg_at_50': _ndcg(order, universe, labels, 50),
    }


def evaluate(request: RankingRequest, ranked: RankBatch, labels: dict, *,
             final_ids: list[str] | None = None, full_pool_ids: list[str] | None = None):
    """Report conditional S7 and optional S6/S7/final-selection quality separately.

    ``final_ids`` is the final *S7-personalized* selection, excluding independent
    S4 priority items. ``full_pool_ids`` must explicitly name the frozen eligible
    retrieval universe. A label file is not evidence of a complete universe.
    Metrics on known labels always include their denominator/label coverage.
    """
    request = RankingRequest.model_validate(request.model_dump())
    ranked = RankBatch.model_validate(ranked.model_dump())
    if ranked.request_id != request.batch.request_id or ranked.context_hash != request.fingerprint or ranked.recipe_hash != canonical_hash(request.recipe):
        raise ValueError('evaluation ranking context mismatch')
    validate_judgments(request, request.evidence, ranked.judgments)
    candidate_ids = [item.article_id for item in request.batch.candidates]
    labels = {key: RankingLabel.model_validate(value) for key, value in labels.items()}
    universe = candidate_ids if full_pool_ids is None else list(full_pool_ids)
    if len(universe) != len(set(universe)) or not set(candidate_ids) <= set(universe):
        raise ValueError('full pool must uniquely contain all actual candidates')
    for key in set(universe):
        labels.setdefault(key, RankingLabel())
    selected = list(ranked.ordered_ids if final_ids is None else final_ids)
    if len(selected) != len(set(selected)) or not set(selected) <= set(ranked.ordered_ids):
        raise ValueError('final S7 selection must contain unique accepted IDs')
    by_id = {judgment.article_id: judgment for judgment in ranked.judgments}
    band_errors = {}
    for grade in range(4):
        band = [key for key in candidate_ids if labels[key].grade == grade]
        band_errors[str(grade)] = {
            'sample_size': len(band),
            'false_accept': _rate(sum(by_id[key].decision == 'accept' for key in band), len(band)) if grade < 2 else None,
            'false_reject': _rate(sum(by_id[key].decision == 'reject' for key in band), len(band)) if grade >= 2 else None,
            'abstention': _rate(sum(by_id[key].decision == 'abstain' for key in band), len(band)),
        }
    intent_opportunities = {}
    for intent in request.profile.intents:
        known = {key for key in universe if labels[key].intent_grades.get(intent.id) is not None}
        positive = {key for key in known if labels[key].intent_grades[intent.id] >= 2}
        intent_opportunities[intent.id] = {
            'label_coverage': _rate(len(known), len(universe)),
            'retrieved_known_positive_recall': _rate(len(positive & set(candidate_ids)), len(positive)),
            'final_known_positive_recall': _rate(len(positive & set(selected)), len(positive)),
            'has_known_opportunity': bool(positive),
        }
    packs = {pack.article_id: pack for pack in request.evidence}
    candidates = {item.article_id: item for item in request.batch.candidates}
    slices = {}
    for field in ('source', 'language', 'evidence_tier'):
        values = {}
        for key in candidate_ids:
            article = candidates[key].article
            value = packs[key].tier if field == 'evidence_tier' else article.get('source_id') if field == 'source' else article.get('language')
            values.setdefault(str(value) if value is not None else 'unknown', []).append(key)
        slices[field] = {name: _quality([key for key in selected if key in keys], keys, labels)
                         for name, keys in values.items()}
    ages = [max(0, (request.batch.as_of - packs[key].published_at).total_seconds()) / 3600
            for key in selected if packs[key].published_at and packs[key].published_at.tzinfo]
    # A transparent high-recall comparison, not a learned relevance classifier.
    # Unknown policy labels are excluded rather than called policy-safe.
    baseline = sorted((key for key in candidate_ids if labels[key].prohibited is False),
        key=lambda key: (-(packs[key].published_at.timestamp()) if packs[key].published_at and packs[key].published_at.tzinfo else math.inf, key))
    diagnostics = {}
    for key in ('known_cost_usd', 'elapsed_ms', 'input_tokens', 'output_tokens', 'attempts'):
        value = ranked.diagnostics.get(key)
        diagnostics[key] = value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    return {
        'evaluation_version': 's7-ranking-eval-v1',
        'quality_proven': False,
        'scope': 'frozen S7 personalized selection; independent S4 priority excluded',
        'label_caveat': 'Externally supplied labels; provenance and independence must be established separately.',
        'conditional': _quality(ranked.ordered_ids, candidate_ids, labels),
        'final_conditional': _quality(selected, candidate_ids, labels),
        'end_to_end': _quality(selected, universe, labels) if full_pool_ids is not None else None,
        'decision_counts': dict(Counter(item.decision for item in ranked.judgments)),
        'abstention_coverage': _rate(sum(item.decision == 'abstain' for item in ranked.judgments), len(candidate_ids)),
        'band_errors': band_errors, 'intent_opportunities': intent_opportunities,
        'slices': slices,
        'freshness': {'mean_hours': sum(ages) / len(ages) if ages else None, 'known_count': len(ages), 'shown_count': len(selected)},
        'usage': diagnostics,
        'policy_labeled_high_recall_baseline': {'ordered_ids': baseline,
            'excluded_unknown_policy_count': sum(labels[key].prohibited is None for key in candidate_ids),
            'conditional': _quality(baseline, candidate_ids, labels)},
    }
