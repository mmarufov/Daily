"""S7/S4 -> S8 adapter. No provider or independent cache; caller owns publication.

All S4 candidates passed here must have survived ranking_events' fresh authorization.
The adapter never turns an S4-only representative into a confirmed S7 match.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os

from .reader_contract import canonical_hash
from .reader_repository import ReaderConflict


def enabled():
    return os.getenv('S8_SERVING_ENABLED', 'false').lower() == 'true'


def _native_content_hash(article):
    presentation = article.get('presentation') or {}
    value = (presentation.get('provenance') or {}).get('content_hash')
    if (presentation.get('mode') == 'native_full_text' and isinstance(value, str)
            and len(value) == 64 and all(c in '0123456789abcdef' for c in value)):
        return value
    return None


def prepare(conn, user_id, request, snapshot, events):
    from . import assembly_repository as repo
    from .ranking_events import article_ids
    control = repo.control(conn)
    if not control or not control['approved'] or not control['serving']:
        raise ReaderConflict('assembly_not_approved')
    identifiers = sorted({c.article_id for c in request.batch.candidates} | set(article_ids(events)))
    return repo.hydrate(conn, user_id, snapshot, identifiers, control['recipe'],
                        as_of=datetime.now(timezone.utc))


def criticals(conn, user_id, ordinary, events, profile, limit):
    from .ranking_events import compose
    # Do not pre-truncate ordinary alternatives using the old S4 append loop.
    result = compose(conn, user_id, {**ordinary, 'articles': [], 'article_count': 0},
                     events, profile, limit=limit, details=True)
    return result


def _development_keys(events, critical_articles):
    """Only supported core coverage shares a development key; side angles do not."""
    selected = {a['event_delivery']['development_id'] for a in critical_articles}
    memberships = {}
    for candidate in events:
        development = candidate['development_id']
        if development not in selected:
            continue
        evidence = {item['dependency']['article_id']: item['dependency']['source_id']
                    for item in candidate['snapshot']['evidence']
                    if item['role'] == 'core' and item['claim']['modality'] in ('reported', 'corrected')
                    and item['id'] in candidate['assessment']['evidence_ids']}
        for rep in candidate['representatives']:
            identifier = rep['article']['id']
            if (rep.get('eligible') is True and rep.get('role') == 'core'
                    and rep.get('development_id') == development
                    and rep.get('development_version') == candidate['development_version']
                    and evidence.get(identifier) == rep.get('source_id')):
                memberships.setdefault(identifier, set()).add(development)
    # Ambiguous multi-development coverage must not merge unrelated stories.
    return {key: 's4-development:' + next(iter(values)) for key, values in memberships.items()
            if len(values) == 1}


def _inputs(request, ranked, snapshot, ordinary, manifest, event_result, events, *, limit):
    from .assembly_contract import AssemblyCandidate, AssemblyRequest
    judgments = {j.article_id: j for j in ranked.judgments}
    priorities = {i.id: i.priority for i in request.profile.intents}
    critical = event_result.payload['articles']
    development_keys = _development_keys(events, critical)
    # Critical serialization loses private ranking provenance: restore ONLY the
    # same article's already confirmed evidence, never another representative's.
    articles = {a['id']: dict(a) for a in ordinary['articles']}
    for article in critical:
        identifier = article['id']
        private = {k: v for k, v in articles.get(identifier, {}).items() if k.startswith('_')}
        articles[identifier] = {**article, **private}
    critical_order = {a['id']: index for index, a in enumerate(critical)}
    ordinal = {identifier: index for index, identifier in enumerate(ranked.ordered_ids)}
    candidates = []
    for identifier, article in articles.items():
        features = manifest['candidates'][identifier]
        judgment = judgments.get(identifier)
        accepted = judgment is not None and judgment.decision == 'accept'
        intents = {key: float(priorities[key]) for key in judgment.confirmed_intent_ids} if accepted else {}
        grade = max((g.grade for g in judgment.grades if g.intent_id in intents), default=0) if accepted else 0
        is_critical = identifier in critical_order
        displayed_hash = _native_content_hash(article)
        novelty_key = features.get('novelty_key') if displayed_hash and displayed_hash == features.get('analysis_content_hash') else None
        candidates.append(AssemblyCandidate(article_id=identifier,
            ordinal=critical_order[identifier] if is_critical else ordinal[identifier],
            grade=grade, intents=intents, origin='world_critical' if is_critical else 'ordinary',
            authorized=is_critical, publisher_id=features.get('publisher_id'),
            topic_ids=features.get('topic_ids') or [],
            coverage_key=development_keys.get(identifier, features.get('coverage_key')),
            novelty_key=novelty_key, known_read=features.get('known_read', False) if novelty_key else False,
            evidence_stamp=features.get('membership_stamp') or {}))
    assembly_request = AssemblyRequest(user_id=request.batch.user_id,
        request_id=request.batch.request_id, ranking_context_hash=ranked.context_hash,
        ranking_recipe_hash=ranked.recipe_hash, generation=snapshot['generation'],
        revision=snapshot['revision'], history_revision=manifest['history_revision'],
        as_of=manifest['as_of'], valid_until=ranked.valid_until, limit=limit,
        candidates=candidates, recipe=manifest['control']['recipe'],
        assembly_epoch=manifest['control']['epoch'], dependencies=manifest)
    return assembly_request, articles


def _cards(assembly_request, result, articles):
    candidates = {c.article_id: c for c in assembly_request.candidates}
    final = []
    for position, identifier in enumerate(result.ordered_ids):
        candidate = candidates[identifier]
        final.append({**articles[identifier], 'delivery_position': position,
            '_assembly_recipe': assembly_request.recipe_hash,
            '_assembly_coverage_unit': candidate.coverage_key or 'article:' + identifier,
            '_assembly_novelty_key': candidate.novelty_key,
            '_assembly_content_hash': _native_content_hash(articles[identifier]) if candidate.novelty_key else None})
    return final


def assemble(request, ranked, snapshot, ordinary, manifest, event_result, events, *, limit):
    from .assembly_service import assemble as select
    assembly_request, articles = _inputs(request, ranked, snapshot, ordinary, manifest,
                                         event_result, events, limit=limit)
    result = select(assembly_request)
    final = _cards(assembly_request, result, articles)
    payload = {**ordinary, 'articles': final, 'article_count': len(final),
               'assembly_recipe': assembly_request.recipe_hash}
    envelope = {'request': assembly_request.model_dump(mode='json'),
                'result': result.model_dump(mode='json'),
                'manifest': manifest, 'critical_signature': critical_signature(event_result)}
    return payload, envelope


def critical_signature(result):
    # Freeze all critical dispositions, including overflow and scoped-major loss,
    # without serializing raw major evidence or manufacturing a relevance verdict.
    return canonical_hash({'articles': result.payload['articles'], 'decisions': result.decisions,
                           'major_ids': [a['id'] for a in result.major_candidates]})


def validate_cached(conn, user_id, request, ranked, snapshot, assembly, event_result,
                    ordinary, events, *, limit):
    from . import assembly_repository as repo
    from .assembly_contract import AssemblyRequest, AssemblyResult, validate_result
    if not enabled():
        raise ReaderConflict('assembly_disabled')
    frozen = AssemblyRequest.model_validate(assembly['request'])
    result = AssemblyResult.model_validate(assembly['result'])
    validate_result(frozen, result)
    if (frozen.ranking_context_hash != ranked.context_hash
            or frozen.ranking_recipe_hash != ranked.recipe_hash
            or frozen.user_id != str(user_id)
            or frozen.generation != snapshot['generation'] or frozen.revision != snapshot['revision']
            or frozen.valid_until != ranked.valid_until
            or canonical_hash(frozen.dependencies) != canonical_hash(assembly['manifest'])
            or critical_signature(event_result) != assembly['critical_signature']):
        raise ReaderConflict('assembly_changed')
    repo.validate(conn, user_id, snapshot, assembly['manifest'])
    expected, articles = _inputs(request, ranked, snapshot, ordinary, assembly['manifest'],
                                 event_result, events, limit=limit)
    if expected.fingerprint != frozen.fingerprint:
        raise ReaderConflict('assembly_candidate_attribution_changed')
    return _cards(frozen, result, articles)
