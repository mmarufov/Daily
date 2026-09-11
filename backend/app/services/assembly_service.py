"""Bounded, deterministic S8 edition assembly. No database or provider work."""
from __future__ import annotations

from collections import Counter
import math

from .assembly_contract import (AssemblyRequest, AssemblyResult, AssemblySelection,
                                AssemblyDisposition, validate_result)


def assemble(request: AssemblyRequest) -> AssemblyResult:
    # Revalidate even model_copy(update=...) inputs, which Pydantic intentionally
    # trusts. Selection never mutates the caller's snapshot.
    request = AssemblyRequest.model_validate(request.model_dump())
    candidates = sorted(request.candidates, key=lambda c: (c.ordinal, c.article_id))
    selections, reasons, equivalents, relaxations = [], {}, {}, []
    selected_units, publisher_counts, topic_counts, served = {}, Counter(), Counter(), Counter()
    topic_target = max(1, math.ceil(request.limit * request.recipe['topic_share']))
    publisher_target = max(1, math.ceil(request.limit * request.recipe['publisher_share']))
    last_publisher, streak = None, 0

    def select(candidate, intent=None):
        nonlocal last_publisher, streak
        selections.append(AssemblySelection(article_id=candidate.article_id,
            origin=candidate.origin, final_position=len(selections), ordinal=candidate.ordinal,
            grade=candidate.grade, intents=candidate.intents, scheduled_intent_id=intent,
            coverage_key=candidate.coverage_key, novelty_key=candidate.novelty_key))
        reasons[candidate.article_id] = 'selected'
        if candidate.coverage_key is not None:
            selected_units[candidate.coverage_key] = candidate.article_id
        if candidate.publisher_id is not None:
            publisher_counts[candidate.publisher_id] += 1
        for topic in candidate.topic_ids:
            topic_counts[topic] += 1
        if candidate.publisher_id is not None and candidate.publisher_id == last_publisher:
            streak += 1
        else:
            last_publisher, streak = candidate.publisher_id, 1 if candidate.publisher_id else 0
        if intent is not None:
            served[intent] += 1

    for candidate in candidates:
        if not candidate.eligible:
            reasons[candidate.article_id] = 'policy_stale'
        elif candidate.origin == 'world_critical' and not candidate.authorized:
            reasons[candidate.article_id] = 'critical_unauthorized'
        elif candidate.known_read:
            reasons[candidate.article_id] = 'known_read_repeat'

    for candidate in (c for c in candidates if c.origin == 'world_critical' and c.article_id not in reasons):
        if candidate.coverage_key is not None and candidate.coverage_key in selected_units:
            reasons[candidate.article_id] = 'equivalent_copy'
            equivalents[candidate.article_id] = selected_units[candidate.coverage_key]
        elif len(selections) >= min(2, request.limit):
            reasons[candidate.article_id] = 'critical_overflow'
        else:
            select(candidate)

    ordinary = [c for c in candidates if c.origin == 'ordinary' and c.article_id not in reasons]
    while len(selections) < request.limit:
        available = [c for c in ordinary if c.article_id not in reasons and
                     (c.coverage_key is None or c.coverage_key not in selected_units)]
        if not available:
            break
        best_grade = max(c.grade for c in available)
        available = [c for c in available if c.grade == best_grade]
        intent = None
        if best_grade:
            intent_choices = {}
            for candidate in available:
                for intent_id, priority in candidate.intents.items():
                    choice = (served[intent_id] / priority, candidate.ordinal, intent_id)
                    intent_choices[intent_id] = min(intent_choices.get(intent_id, choice), choice)
            intent = min(intent_choices, key=intent_choices.get)
            available = [c for c in available if intent in c.intents]

        def violations(candidate):
            return (
                bool(candidate.topic_ids) and any(topic_counts[t] >= topic_target for t in candidate.topic_ids),
                candidate.publisher_id is not None and publisher_counts[candidate.publisher_id] >= publisher_target,
                candidate.publisher_id is not None and candidate.publisher_id == last_publisher and streak >= request.recipe['source_streak'],
            )

        # Relax topic, then publisher, then streak, only if the protected grade /
        # scheduled intent has no satisfying alternative. Unknowns neither count
        # as fresh identities nor become hard-excluded.
        for level in range(4):
            pool = [c for c in available if not any(violations(c)[level:])]
            if pool:
                break

        def variety(candidate):
            # Unknown metadata is neutral, not the zero-count reward for a new
            # publisher/topic. Its comparison falls back to the S7 ordinal.
            publisher = publisher_counts[candidate.publisher_id] if candidate.publisher_id is not None else max(publisher_counts.values(), default=0)
            topics = max((topic_counts[t] for t in candidate.topic_ids), default=max(topic_counts.values(), default=0))
            return publisher, topics, candidate.ordinal, candidate.article_id

        chosen = min(pool, key=variety)
        if level:
            relaxations.append({'position': len(selections), 'article_id': chosen.article_id,
                                'constraints': ['central_topic', 'publisher_share', 'source_streak'][:level],
                                'grade': best_grade, 'intent_id': intent})
        select(chosen, intent)

    for candidate in candidates:
        if candidate.article_id in reasons:
            continue
        if candidate.coverage_key is not None and candidate.coverage_key in selected_units:
            reasons[candidate.article_id] = 'equivalent_copy'
            equivalents[candidate.article_id] = selected_units[candidate.coverage_key]
        else:
            reasons[candidate.article_id] = 'capacity'
    result = AssemblyResult(request_id=request.request_id, context_hash=request.fingerprint,
        recipe_hash=request.recipe_hash, assembly_epoch=request.assembly_epoch,
        history_revision=request.history_revision, valid_until=request.valid_until,
        ordered_ids=[s.article_id for s in selections], selections=selections,
        dispositions=[AssemblyDisposition(article_id=c.article_id, reason=reasons[c.article_id],
            identity_status='verified' if c.coverage_key is not None else 'unknown',
            equivalent_to=equivalents.get(c.article_id)) for c in candidates],
        dependencies=request.dependencies,
        diagnostics={'requested': request.limit, 'selected': len(selections),
            'shortfall': request.limit-len(selections), 'relaxations': relaxations,
            'intent_service_counts': dict(sorted(served.items())),
            'unknown_identity_count': sum(c.coverage_key is None for c in candidates),
            'critical_selected': sum(s.origin == 'world_critical' for s in selections),
            'disposition_counts': dict(sorted(Counter(reasons.values()).items())),
            'publisher_target': publisher_target, 'central_topic_target': topic_target})
    return validate_result(request, result)
