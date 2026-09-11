"""Offline S8 comparison over frozen actual opportunities, never oracle retrieval.

Mechanical invariants are not semantic truth. Independently supplied labels and an
explicit full universe are optional; missing labels remain unknown. This harness
does not certify a recipe, set thresholds or issue provider/database calls.
"""
from __future__ import annotations

from collections import Counter
from typing import Annotated

from pydantic import Field, StrictBool, StrictInt, StrictStr

from app.services.assembly_contract import AssemblyRequest, validate_result
from app.services.reader_contract import StrictModel


Grade = Annotated[StrictInt, Field(ge=0, le=3)]


class AssemblyLabel(StrictModel):
    grade: Grade | None = None
    prohibited: StrictBool | None = None
    identical_read_repeat: StrictBool | None = None
    coverage_unit: Annotated[StrictStr, Field(min_length=1, max_length=512)] | None = None
    intent_grades: dict[str, Grade | None] = Field(default_factory=dict)


def _rate(numerator, denominator):
    return {'value': numerator / denominator if denominator else None,
            'numerator': numerator, 'denominator': denominator}


def _label_quality(order, universe, labels):
    shown_relevance = [key for key in order if labels[key].grade is not None]
    known_policy = [key for key in order if labels[key].prohibited is not None]
    known_read = [key for key in order if labels[key].identical_read_repeat is not None]
    units = [labels[key].coverage_unit for key in order if labels[key].coverage_unit is not None]
    positive = {key for key in universe if labels[key].grade is not None and labels[key].grade >= 2}
    return {
        'universe_count': len(universe), 'shown_count': len(order),
        'relevance_label_coverage': _rate(sum(labels[key].grade is not None for key in universe), len(universe)),
        'shown_relevance_label_coverage': _rate(len(shown_relevance), len(order)),
        'known_relevance_precision': _rate(sum(labels[key].grade >= 2 for key in shown_relevance), len(shown_relevance)),
        'known_positive_recall': _rate(len(positive & set(order)), len(positive)),
        'prohibited_rate': _rate(sum(labels[key].prohibited is True for key in known_policy), len(known_policy)),
        'policy_label_coverage': _rate(len(known_policy), len(order)),
        'read_repeat_rate': _rate(sum(labels[key].identical_read_repeat is True for key in known_read), len(known_read)),
        'read_label_coverage': _rate(len(known_read), len(order)),
        'duplicate_unit_rate': _rate(len(units)-len(set(units)), len(units)),
        'identity_label_coverage': _rate(len(units), len(order)),
    }


def _mechanical(order, candidates, k):
    shown = [candidates[key] for key in order]
    ordinary = [c for c in shown if c.origin == 'ordinary']
    available = [c for c in candidates.values() if c.eligible and not c.known_read and
                 (c.origin == 'ordinary' or c.authorized)]
    opportunity_intents = {intent for c in available if c.origin == 'ordinary' for intent in c.intents}
    shown_intents = {intent for c in ordinary for intent in c.intents}
    units = [c.coverage_key for c in shown if c.coverage_key is not None]
    shown_units = set(units)
    left = [c for c in available if c.origin == 'ordinary' and c.article_id not in order and
            (c.coverage_key is None or c.coverage_key not in shown_units)]
    max_left = max((c.grade for c in left), default=0)
    publishers = [c.publisher_id for c in shown if c.publisher_id is not None]
    topics = [c.topic_ids for c in shown if c.topic_ids]
    publisher_counts = Counter(publishers)
    topic_counts = Counter(topic for values in topics for topic in values)
    last, streak, max_streak = None, 0, 0
    for candidate in shown:
        publisher = candidate.publisher_id
        streak = streak+1 if publisher is not None and publisher == last else (1 if publisher else 0)
        last, max_streak = publisher, max(max_streak, streak)
    available_units = {('verified', c.coverage_key) if c.coverage_key is not None else ('unknown_article', c.article_id)
                       for c in available}
    return {
        'requested': k, 'shown': len(order), 'underfill': max(0, k-len(order)),
        'available_candidates': len(available), 'available_verified_or_singleton_units': len(available_units),
        'opportunity_limited_shortfall_lower_bound': max(0, k-len(available_units)),
        'verified_duplicate_unit_rate': _rate(len(units)-len(set(units)), len(units)),
        'verified_identity_coverage': _rate(len(units), len(order)),
        'shown_known_read_count': sum(c.known_read for c in shown),
        'known_read_opportunities': sum(c.known_read for c in candidates.values()),
        'available_intent_coverage': _rate(len(shown_intents & opportunity_intents), len(opportunity_intents)),
        'available_intents': sorted(opportunity_intents), 'shown_intents': sorted(shown_intents),
        'max_publisher_share_known': _rate(max(publisher_counts.values(), default=0), len(publishers)),
        'publisher_metadata_coverage': _rate(len(publishers), len(order)),
        'max_central_topic_share_known': _rate(max(topic_counts.values(), default=0), len(topics)),
        'topic_metadata_coverage': _rate(len(topics), len(order)),
        'max_observed_source_streak': max_streak,
        'ordinary_grade_displacement': sum(c.grade < max_left for c in ordinary),
        'critical_slots': sum(c.origin == 'world_critical' for c in shown),
    }


def evaluate(request: AssemblyRequest, result, labels: dict | None = None, *,
             full_pool_ids: list[str] | None = None, cutoffs=(5, 10, 50)):
    request = AssemblyRequest.model_validate(request.model_dump())
    result = validate_result(request, result)
    if any(type(k) is not int or not 1 <= k <= 100 for k in cutoffs) or len(set(cutoffs)) != len(cutoffs):
        raise ValueError('evaluation cutoffs must be unique integers 1..100')
    candidates = {c.article_id: c for c in request.candidates}
    labels = {key: AssemblyLabel.model_validate(value) for key, value in (labels or {}).items()}
    universe = list(candidates) if full_pool_ids is None else list(full_pool_ids)
    if len(universe) != len(set(universe)) or not set(candidates) <= set(universe):
        raise ValueError('full pool must uniquely contain the actual assembly candidate set')
    for key in universe:
        labels.setdefault(key, AssemblyLabel())

    # Identical S4 reservation inputs for both baselines. Ordinary inputs are the
    # actual eligible accepted S7 order, with no semantic labels consulted.
    critical, critical_units = [], set()
    for candidate in sorted(request.candidates, key=lambda c: (c.ordinal, c.article_id)):
        if candidate.origin != 'world_critical' or not candidate.authorized or not candidate.eligible or candidate.known_read:
            continue
        if candidate.coverage_key is not None and candidate.coverage_key in critical_units:
            continue
        critical.append(candidate.article_id)
        if candidate.coverage_key is not None:
            critical_units.add(candidate.coverage_key)
    ordinary = [c.article_id for c in sorted(request.candidates, key=lambda c: (c.ordinal, c.article_id))
                if c.origin == 'ordinary' and c.eligible]
    top = [*critical, *ordinary]
    deduped, seen = [], set()
    for key in top:
        unit = candidates[key].coverage_key
        if unit is not None and unit in seen:
            continue
        deduped.append(key)
        if unit is not None:
            seen.add(unit)

    comparisons = {}
    for cutoff in cutoffs:
        # Do not claim what an unbuilt, larger edition would have selected. Every
        # policy is compared at the same actually requested maximum capacity.
        k = min(cutoff, request.limit)
        policies = {}
        for name, order in [('accepted_s7_top_k', top), ('verified_dedupe_only', deduped),
                            ('proposed', result.ordered_ids)]:
            order = order[:k]
            ordinary_order = [key for key in order if candidates[key].origin == 'ordinary']
            ordinary_universe = [key for key in candidates if candidates[key].origin == 'ordinary']
            policies[name] = {'ordered_ids': order, 'mechanical': _mechanical(order, candidates, k),
                'final_labeled': _label_quality(order, list(candidates), labels),
                'ordinary_labeled': _label_quality(ordinary_order, ordinary_universe, labels),
                'end_to_end_labeled': _label_quality(order, universe, labels) if full_pool_ids is not None else None}
        comparisons[str(cutoff)] = {'effective_capacity': k, 'policies': policies}

    # Report whether verified identity itself is wrong, not just duplicates that
    # survived selection. Pair labels are independent of the assembly key.
    groups = {}
    for candidate in request.candidates:
        if candidate.coverage_key is not None:
            groups.setdefault(candidate.coverage_key, []).append(candidate.article_id)
    total_pairs = known_pairs = false_merges = 0
    for group in groups.values():
        for index, left in enumerate(group):
            for right in group[index+1:]:
                total_pairs += 1
                truth_left, truth_right = labels[left].coverage_unit, labels[right].coverage_unit
                if truth_left is not None and truth_right is not None:
                    known_pairs += 1
                    false_merges += truth_left != truth_right
    read_suppressions = [d.article_id for d in result.dispositions if d.reason == 'known_read_repeat']
    known_suppressions = [key for key in read_suppressions if labels[key].identical_read_repeat is not None]

    return {'evaluation_version': 's8-assembly-eval-v1', 'quality_proven': False,
        'scope': 'Actual accepted ordinary pool plus independently authorized S4 opportunities; no label-injected candidates.',
        'label_caveat': 'External label provenance, coverage and independence require separate review.',
        'baseline_caveat': 'Same authorized S4 prefix; ordinary top-K and verified-dedupe-only do not suppress read repeats.',
        'recipe_hash': request.recipe_hash, 'actual_candidate_count': len(candidates),
        'ignored_outside_universe_label_count': len(set(labels)-set(universe)),
        'critical_opportunity_count': sum(c.origin == 'world_critical' for c in request.candidates),
        'identity_validation': {'false_merge_pair_rate': _rate(false_merges, known_pairs),
            'assumed_equivalent_pair_label_coverage': _rate(known_pairs, total_pairs)},
        'novelty_validation': {'false_read_suppression_rate': _rate(
            sum(labels[key].identical_read_repeat is False for key in known_suppressions), len(known_suppressions)),
            'suppression_label_coverage': _rate(len(known_suppressions), len(read_suppressions))},
        'comparisons': comparisons}
