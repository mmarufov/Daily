"""S7 ranking and publication. Provider work never owns a database connection."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import math
import os
import threading
import time
import uuid

from .reader_contract import canonical_hash, active
from .ranking_contract import (RECIPE, RankingRequest, EvidencePack, ArticleJudgment,
                               IntentGrade, RankBatch, validate_judgments)
from .retrieval_contract import article_stamp

logger = logging.getLogger(__name__)


def enabled():
    return os.getenv('S7_SERVING_ENABLED', 'false').lower() == 'true'


def shadow_enabled():
    return os.getenv('S7_SHADOW_ENABLED', 'false').lower() == 'true'


def identity(snapshot, recipe):
    return {**{key: snapshot[key] for key in ('generation', 'revision', 'learning_revision')},
            'reader_hash': canonical_hash(snapshot['profile']), 'recipe_hash': canonical_hash(recipe)}


def prepare_request(conn, batch, snapshot, recipe=None):
    """Revalidate source inputs and allowlist evidence; never expose raw a.* to a model."""
    from .reader_retrieval import _s6_recipe, _s6_hydrate, _s6_evidence_stamp
    from .reader_repository import ReaderConflict
    from .understanding_contract import build_evidence
    from .reader_feedback import load_learned_weights
    if any(snapshot[key] != getattr(batch, key) for key in ('generation', 'revision', 'learning_revision')):
        raise ReaderConflict('reader_changed')
    with conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        conn.execute("SET LOCAL statement_timeout='2000ms'")
        cohort = _s6_recipe(conn)
        if (cohort['id'] if cohort else None) != batch.s3_recipe_id:
            raise ReaderConflict('retrieval_recipe_changed')
        rows = _s6_hydrate(conn, [c.article_id for c in batch.candidates], cohort)
        packs = []
        for candidate in batch.candidates:
            row = rows.get(candidate.article_id)
            if not row or article_stamp(row['article']) != candidate.article_stamp or _s6_evidence_stamp(row['current']) != candidate.evidence_stamp:
                raise ReaderConflict('retrieval_evidence_changed')
            article = row['article']
            revoked = article.get('analysis_revoked') is True
            bundle = row['current'].get('evidence')
            if not bundle and not revoked:
                try:
                    bundle = build_evidence(article, None)
                except (ValueError, TypeError):
                    bundle = None
            fields = (bundle or {}).get('fields', {})
            # Publisher-owned S3 body only; build_evidence excludes quarantined or
            # cross-source artifacts. Explicit revocation excludes all provider use.
            title = str(fields.get('title') or article.get('title') or '')
            summary = str(fields.get('summary') or article.get('summary') or '')
            body = str(fields.get('body') or '') if not revoked else ''
            allowed = not revoked and bool(bundle and bundle.get('evidence_tier') != 'insufficient')
            values = {'article_id': candidate.article_id, 'title': title[:1000],
                'summary': summary[:3000], 'analysis': body[:6000], 'analysis_allowed': allowed,
                'tier': 'revoked' if revoked else 'publisher_analysis' if body else 'publisher_metadata',
                'truncated': len(title)>1000 or len(summary)>3000 or len(body)>6000 or bool((bundle or {}).get('manifest', {}).get('truncated')),
                'central_ids': {k: row['policy'].get(k) for k in ('topic_ids', 'entity_ids', 'place_ids')},
                'retrieval_intent_ids': candidate.matched_intent_ids,
                'published_at': article.get('published_at') or article.get('ingested_at')}
            values['input_hash'] = article_stamp({**values, 'article_stamp': candidate.article_stamp,
                                                   'evidence_stamp': candidate.evidence_stamp})
            packs.append(EvidencePack(**values))
        learned = load_learned_weights(conn, batch.user_id, snapshot, as_of=batch.as_of)
    # Bodies and embeddings are not needed by S2's feed-card serializer. Their
    # original whole-row digest remains the fresh publication authority.
    batch = batch.model_copy(deep=True)
    for candidate in batch.candidates:
        for key in ('content', 'display_body', 'analysis_text', 'embedding'):
            candidate.article.pop(key, None)
    return RankingRequest(batch=batch, profile=snapshot['profile'], recipe=recipe or dict(RECIPE),
                          evidence=packs, learned=learned)


def abstain(pack, reason='insufficient_evidence'):
    return ArticleJudgment(article_id=pack.article_id, input_hash=pack.input_hash,
        decision='abstain', reason=reason, explanation='Not enough verified information to recommend this story.',
        confirmed_intent_ids=[], grades=[])


def baseline(request):
    intents = [i for i in request.profile.intents if active(i.model_dump(), request.batch.as_of)]
    judgments = []
    for pack in request.evidence:
        if pack.tier == 'revoked':
            judgments.append(abstain(pack, 'analysis_revoked'))
            continue
        if not intents:
            judgments.append(ArticleJudgment(article_id=pack.article_id, input_hash=pack.input_hash,
                decision='accept', reason='generic', explanation='General news, not a personalized recommendation.',
                confirmed_intent_ids=[], grades=[]))
            continue
        grades = []
        if request.recipe.get('central_identity') is True and not pack.truncated:
            for intent in intents:
                values = pack.central_ids.get(intent.kind + '_ids')
                # A narrowed query is a qualifier even if the qualifiers array is
                # empty; do not broaden "Apple privacy regulation" to all Apple.
                if intent.resolved_id and not intent.qualifiers and intent.query == intent.label and isinstance(values, list) and intent.resolved_id in values:
                    quote = pack.title[:600] or pack.summary[:600]
                    if quote:
                        grades.append(IntentGrade(intent_id=intent.id, grade=2, qualifiers='satisfied',
                            field='title' if pack.title else 'summary', quote=quote))
        judgments.append(ArticleJudgment(article_id=pack.article_id, input_hash=pack.input_hash,
            decision='accept', reason='central_identity', explanation='Current subject evidence matches an explicit interest.',
            confirmed_intent_ids=[g.intent_id for g in grades], grades=grades) if grades else abstain(pack))
    return validate_judgments(request, request.evidence, judgments)


def ordered(request, judgments):
    packs = {e.article_id: e for e in request.evidence}
    intents = {i.id: i for i in request.profile.intents}
    def key(j):
        strengths = [(g.grade or 0, max(.1, intents[g.intent_id].priority *
                      (1+max(-.5, min(.25, request.learned.get(g.intent_id, 0))))))
                     for g in j.grades if g.intent_id in j.confirmed_intent_ids]
        grade, priority = max(strengths, default=(0, 0))
        published = packs[j.article_id].published_at
        age = max(0, (request.batch.as_of-published).total_seconds()) if published and published.tzinfo else math.inf
        return (-grade, -priority, age, j.article_id)
    return [j.article_id for j in sorted((j for j in judgments if j.decision == 'accept'), key=key)]


async def rank(request, *, provider=None, reserve=None, settle=None, deadline=None, now=None):
    """Provider callbacks reserve/settle in separate short connection lifetimes."""
    from .ranking_provider import ProviderFailure
    request = RankingRequest.model_validate(request.model_dump())
    current_time = (now or (lambda: datetime.now(timezone.utc)))()
    if request.batch.status == 'stale' or not request.batch.as_of <= current_time < request.batch.valid_until:
        from .reader_repository import ReaderConflict
        raise ReaderConflict('retrieval_expired')
    started = time.monotonic()
    deadline = min(deadline if deadline is not None else started+20,
                   started+request.recipe['deadline_seconds'],
                   started+(request.batch.valid_until-current_time).total_seconds())
    values = {j.article_id: j for j in baseline(request)}
    unresolved = [e for e in request.evidence if values[e.article_id].decision == 'abstain' and e.analysis_allowed]
    # Fair per-intent opportunities for token-limited semantic work. This is work
    # scheduling only, never a forced acceptance or an S8 edition quota.
    groups = {}
    for e in unresolved:
        groups.setdefault(next(iter(e.retrieval_intent_ids), ''), []).append(e)
    pending = []
    while any(groups.values()):
        for key in sorted(groups):
            if groups[key]:
                pending.append(groups[key].pop(0))
    attempts, input_tokens, output_tokens, cost = 0, 0, 0, 0.0
    calls = []
    while pending and provider is not None and reserve is not None and settle is not None:
        if time.monotonic() >= deadline or attempts >= min(6, request.recipe.get('max_attempts', 6)):
            break
        chunk, prepared = [], None
        # Greedy bounded token packing. Oversized one-item packs abstain without
        # blocking other interests or losing their candidate records.
        while pending and len(chunk) < 50 and time.monotonic() < deadline:
            try:
                trial = provider.prepare(request, chunk + [pending[0]])
            except ProviderFailure:
                if chunk:
                    break
                values[pending.pop(0).article_id].reason = 'provider_invalid'
                continue
            chunk.append(pending.pop(0))
            prepared = trial
        if not chunk:
            continue
        attempts += 1
        reservation = None
        try:
            reservation = await reserve(attempts, prepared.reserved_usd)
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                # Nothing submitted; release this reservation with proven zero usage.
                await settle(reservation, 0.0)
                raise TimeoutError()
            outcome = await asyncio.wait_for(provider.judge(request, chunk, prepared=prepared), remaining)
            await settle(reservation, outcome.usage_usd)
            input_tokens += outcome.input_tokens
            output_tokens += outcome.output_tokens
            cost += outcome.usage_usd
            calls.append({'attempt': attempts, 'request_id': getattr(outcome, 'request_id', None),
                          'input_tokens': outcome.input_tokens, 'output_tokens': outcome.output_tokens,
                          'known_cost_usd': outcome.usage_usd})
            checked = validate_judgments(request, chunk, outcome.judgments, provider=True)
            values.update({j.article_id: j for j in checked})
        except asyncio.CancelledError:
            # Ambiguous external spend stays reserved; caller cancellation cannot
            # release budget or authorize late output.
            raise
        except Exception as exc:
            reason = 'budget_exhausted' if reservation is None else 'deadline' if isinstance(exc, TimeoutError) else 'provider_invalid'
            if isinstance(exc, ProviderFailure) and exc.usage_usd is not None and reservation is not None:
                cost += exc.usage_usd
                calls.append({'attempt': attempts, 'request_id': exc.request_id,
                              'known_cost_usd': exc.usage_usd, 'output_usable': False})
                try:
                    await settle(reservation, exc.usage_usd)
                except Exception:
                    pass
            for pack in chunk:
                values[pack.article_id] = abstain(pack, reason)
            # No automatic retries; malformed/provider/budget failures stop spend.
            break
    for pack in pending:
        values[pack.article_id] = abstain(pack, 'deadline' if time.monotonic() >= deadline else
                                        'budget_exhausted' if attempts else 'provider_unavailable')
    judgments = validate_judgments(request, request.evidence, list(values.values()))
    return RankBatch(request_id=request.batch.request_id, context_hash=request.fingerprint,
        recipe_hash=canonical_hash(request.recipe), valid_until=request.batch.valid_until,
        status='degraded' if request.batch.status == 'degraded' or any(j.decision == 'abstain' for j in judgments) else 'complete',
        judgments=judgments, ordered_ids=ordered(request, judgments),
        diagnostics={'attempts': attempts, 'input_tokens': input_tokens, 'output_tokens': output_tokens,
                     'known_cost_usd': cost, 'calls': calls,
                     'unjudged': sum(j.decision == 'abstain' for j in judgments),
                     'elapsed_ms': round((time.monotonic()-started)*1000, 3)})


_DB_SLOTS = threading.BoundedSemaphore(2)


async def database_phase(pool, operation, *, deadline):
    """No connection crosses thread/await boundaries; orphan cleanup retains slot."""
    if not _DB_SLOTS.acquire(blocking=False):
        raise RuntimeError('ranking_database_busy')
    def work():
        started = time.monotonic()
        acquired = None
        try:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            with pool.connection(timeout=min(2, remaining)) as conn:
                acquired = time.monotonic()
                if time.monotonic() >= deadline:
                    raise TimeoutError()
                return operation(conn)
        finally:
            _DB_SLOTS.release()
            finished = time.monotonic()
            logger.info("S9 database pool_wait_ms=%.1f work_ms=%.1f acquired=%s",
                        ((acquired or finished)-started)*1000,
                        (finished-acquired)*1000 if acquired is not None else 0,
                        acquired is not None)
    task = asyncio.create_task(asyncio.to_thread(work))
    # Retrieve eventual exceptions without canceling/reusing the worker's connection.
    task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
    return await asyncio.wait_for(asyncio.shield(task), max(.001, deadline-time.monotonic()))


def _decisions(batch, ranked):
    from .retrieval_contract import RankingDecision
    if {j.article_id for j in ranked.judgments} != {c.article_id for c in batch.candidates}:
        raise ValueError('ranking result candidate mismatch')
    positions = {key: len(ranked.ordered_ids)-i for i, key in enumerate(ranked.ordered_ids)}
    return [RankingDecision(article_id=j.article_id, relevant=j.decision == 'accept',
                            score=float(positions.get(j.article_id, 0))) for j in ranked.judgments]


def _ordinary(batch, ranked, snapshot, limit=None):
    from .article_content import serialize_article
    candidates = {c.article_id: c for c in batch.candidates}
    judgments = {j.article_id: j for j in ranked.judgments}
    result = []
    for identifier in ranked.ordered_ids[:limit]:
        candidate, judgment = candidates[identifier], judgments[identifier]
        item = serialize_article(candidate.article, include_body=False)
        # Public explanations are safe templates. Model prose stays private until
        # semantic explanation evaluation can establish stronger guarantees.
        item.update(relevant=True, relevance_reason='General news' if judgment.reason == 'generic'
                    else 'Substantive match to your interests',
                    _reader_intent_ids=judgment.confirmed_intent_ids,
                    _reader_policy_evidence=candidate.policy_evidence,
                    _ranking_recipe=ranked.recipe_hash,
                    _ranking_evidence_stamp={'article_stamp': candidate.article_stamp, **candidate.evidence_stamp})
        result.append(item)
    return {'status': 'ready', 'articles': result, 'article_count': len(result), 'quality_met': False,
            'personalization_status': ranked.status, 'reader_generation': snapshot['generation'],
            'reader_revision': snapshot['revision'], 'ranking_recipe': ranked.recipe_hash}


def _public(result, request_id, publication=None):
    from .delivery_contract import metadata
    delivery = ({'delivery': metadata(publication, request_id, result,
                    now=datetime.now(timezone.utc))}
                if isinstance(publication, dict) and publication.get('publication_sequence') is not None else {})
    return {**result, **delivery, 'feed_request_id': request_id,
            'articles': [{**{k: v for k, v in a.items() if not k.startswith('_')},
                          'feed_request_id': request_id,
                          'reader_generation': result.get('reader_generation'),
                          'reader_revision': result.get('reader_revision'),
                          'delivery_position': a.get('delivery_position', position)}
                         for position, a in enumerate(result['articles'])]}


def _stamp_positions(result):
    return {**result, 'articles': [{**article, 'delivery_position': position}
                                  for position, article in enumerate(result['articles'])]}


def _compose(conn, user_id, result, capability, limit, *, events=(), profile=None):
    from .ranking_events import compose
    return compose(conn, user_id, result, events, profile, limit=limit)


def _delivery_expiry(ranked, articles):
    return min([ranked.valid_until] + [datetime.fromisoformat(a['event_delivery']['valid_until'].replace('Z', '+00:00'))
               for a in articles if a.get('event_delivery')])


def _check_expiry(expiry):
    from .reader_repository import ReaderConflict
    if datetime.now(timezone.utc) >= expiry:
        raise ReaderConflict('ranking_delivery_expired')


def _publish(conn, user_id, request, ranked, snapshot, claim, limit, capability, deadline):
    from . import ranking_repository as repo
    from .reader_retrieval import authorize_candidate_batch
    from .reader_repository import ReaderConflict
    from .reader_feedback import record_delivery
    from . import ranking_events
    from . import assembly_integration as assembly
    if time.monotonic() >= deadline:
        raise TimeoutError()
    if ranked.context_hash != request.fingerprint or ranked.recipe_hash != canonical_hash(request.recipe):
        raise ValueError('rank context changed')
    validate_judgments(request, request.evidence, ranked.judgments)
    events = ranking_events.prepare(conn, capability)
    assembly_manifest = assembly.prepare(conn, user_id, request, snapshot, events) if assembly.enabled() else None
    with authorize_candidate_batch(conn, user_id, request.batch, _decisions(request.batch, ranked),
            additional_article_ids=ranking_events.article_ids(events),
            before_article_locks=lambda c: ranking_events.lock_sources(c, events)):
        control = repo.control(conn, lock=True)
        if not control or control['recipe_hash'] != ranked.recipe_hash or not control['serving']:
            raise ReaderConflict('ranking_recipe_changed')
        assembly_envelope = None
        if assembly_manifest is not None:
            from . import assembly_repository
            assembly_repository.validate(conn, user_id, snapshot, assembly_manifest)
            ordinary = _ordinary(request.batch, ranked, snapshot)
            critical = assembly.criticals(conn, user_id, ordinary, events, snapshot['profile'], limit)
            final, assembly_envelope = assembly.assemble(request, ranked, snapshot, ordinary,
                assembly_manifest, critical, events, limit=limit)
        else:
            ordinary = _ordinary(request.batch, ranked, snapshot, limit)
            final = _compose(conn, user_id, ordinary, capability, limit, events=events, profile=snapshot['profile'])
        final = _stamp_positions(final)
        request_id = str(uuid.uuid4())
        final = {**final, 'feed_request_id': request_id}
        expiry = _delivery_expiry(ranked, final['articles'])
        envelope = {'request': request.model_dump(mode='json'), 'ranked': ranked.model_dump(mode='json'),
                    'final': final, 'limit': limit, 'capability': capability, 'request_id': request_id}
        if assembly_envelope is not None:
            envelope['assembly'] = assembly_envelope
        if time.monotonic() >= deadline:
            raise TimeoutError()
        publication = repo.publish(conn, user_id, claim['build_id'], claim['token'],
                identity(snapshot, request.recipe), envelope, expiry)
        if not publication:
            raise ReaderConflict('ranking_claim_changed')
        record_delivery(conn, user_id, request_id, snapshot, final['articles'])
        _event_receipts(conn, user_id, request_id, final['articles'])
        _check_expiry(expiry)
        if time.monotonic() >= deadline:
            raise TimeoutError()
        return _public(final, request_id, publication)


def _event_receipts(conn, user_id, request_id, articles):
    for item in articles:
        meta = item.get('event_delivery')
        if meta:
            conn.execute('''INSERT INTO public.event_delivery_receipts(user_id,feed_request_id,article_id,
              event_id,development_id,development_version,assessment_id,valid_until)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
              (user_id, request_id, item['id'], meta['event_id'], meta['development_id'],
               meta['development_version'], meta['assessment_id'], meta['valid_until']))


def cached_feed(conn, user_id, *, limit=50, capability=None, ordinary_only=False, delivery_version=None):
    """Provider-free read; changed dependencies request a rebuild, never legacy fallback."""
    from . import ranking_repository as repo
    from .reader_repository import load_reader, ReaderConflict
    from .reader_retrieval import authorize_candidate_batch
    from .reader_feedback import record_delivery
    from . import ranking_events
    from . import assembly_integration as assembly
    empty = {'status': 'needs_build', 'articles': [], 'article_count': 0}
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('ranking limit must be 1..100')
    if (not enabled() or os.getenv('S5_READER_ENABLED', 'false').lower() != 'true'
            or os.getenv('S6_SERVING_ENABLED', 'false').lower() != 'true'):
        return empty
    try:
        stored = repo.latest(conn, user_id)
        if not stored:
            return empty
        envelope = stored['envelope']
        if delivery_version == '1' and limit != envelope['limit']:
            # A publication sequence identifies one immutable ordered edition,
            # not differently truncated projections of it.
            return empty
        if assembly.enabled() != ('assembly' in envelope):
            # A switch is a new edition transition, never an in-place downgrade.
            return empty
        request = RankingRequest.model_validate(envelope['request'])
        ranked = RankBatch.model_validate(envelope['ranked'])
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='2000ms'")
            conn.execute("SET LOCAL lock_timeout='100ms'")
            snapshot = load_reader(conn, user_id, create=False)
        if (not snapshot or identity(snapshot, request.recipe) != stored['identity']
                or (not ordinary_only and (limit > envelope['limit'] or capability != envelope['capability']))):
            return empty
        # Internal chat/briefing consumers can reuse ordinary stories from a
        # capable client's edition, but never expose unsupported S4 priority.
        composition_capability = envelope['capability'] if ordinary_only else capability
        events = ranking_events.prepare(conn, composition_capability)
        with authorize_candidate_batch(conn, user_id, request.batch, _decisions(request.batch, ranked),
                additional_article_ids=ranking_events.article_ids(events),
                before_article_locks=lambda c: ranking_events.lock_sources(c, events)):
            control = repo.control(conn, lock=True)
            if (not control or not control['serving'] or control['recipe_hash'] != ranked.recipe_hash
                    or control['epoch'] != stored['epoch']):
                return empty
            if ranked.context_hash != request.fingerprint:
                return empty
            validate_judgments(request, request.evidence, ranked.judgments)
            if 'assembly' in envelope:
                ordinary = _ordinary(request.batch, ranked, snapshot)
                critical = assembly.criticals(conn, user_id, ordinary, events, snapshot['profile'], envelope['limit'])
                cards = assembly.validate_cached(conn, user_id, request, ranked, snapshot,
                    envelope['assembly'], critical, ordinary, events, limit=envelope['limit'])
                current = envelope['final']
                if canonical_hash(cards) != canonical_hash(current['articles']):
                    return empty
            else:
                current = _stamp_positions(_compose(conn, user_id,
                    _ordinary(request.batch, ranked, snapshot, envelope['limit']),
                    composition_capability, envelope['limit'], events=events, profile=snapshot['profile']))
                if canonical_hash(current['articles']) != canonical_hash(envelope['final']['articles']):
                    return empty
            items = current['articles']
            if ordinary_only:
                items = [a for a in items if not a.get('event_delivery')]
            items = items[:limit]
            final = {**envelope['final'], 'articles': items, 'article_count': len(items)}
            if 'assembly' not in envelope:
                record_delivery(conn, user_id, envelope['request_id'], snapshot, final['articles'])
            _check_expiry(_delivery_expiry(ranked, current['articles']))
            return _public(final, envelope['request_id'], stored)
    except (ReaderConflict, ValueError, KeyError, TypeError):
        return empty
    except Exception:
        # Cache outages and malformed private envelopes never reopen the legacy
        # scorer. Only a later explicit build may repair the result.
        return ({'status': 'unavailable', 'reason': 'validation_unavailable',
                 'retry_after_seconds': 5, 'articles': [], 'article_count': 0}
                if delivery_version == '1' else empty)


def _reuse_rank(conn, user_id, snapshot, control):
    """Explicit builds only: authorize semantics independently of edition history."""
    from . import ranking_repository as repo
    from .reader_retrieval import authorize_candidate_batch
    stored = repo.latest_rank(conn, user_id)
    if not stored or stored['identity'] != identity(snapshot, control['recipe']):
        return None
    try:
        request = RankingRequest.model_validate(stored['envelope']['request'])
        ranked = RankBatch.model_validate(stored['envelope']['ranked'])
        if (request.batch.user_id != str(user_id) or ranked.context_hash != request.fingerprint
                or ranked.recipe_hash != control['recipe_hash']
                or stored['epoch'] != control['epoch']
                or ranked.valid_until != request.batch.valid_until):
            return None
        _check_expiry(ranked.valid_until)
        validate_judgments(request, request.evidence, ranked.judgments)
        with authorize_candidate_batch(conn, user_id, request.batch, _decisions(request.batch, ranked)):
            state = repo.control(conn, lock=True)
            if not state or not state['serving'] or state['epoch'] != stored['epoch']:
                return None
        return request, ranked
    except (ValueError, KeyError, TypeError):
        # Invalid/stale cached judgment is not a fallback verdict. A fresh normal
        # build may retrieve/judge again, under the existing explicit spend gates.
        return None


async def build_feed(pool, user_id, *, limit=50, capability=None, shadow=False, background=False):
    from . import ranking_repository as repo
    from .reader_repository import load_reader, ReaderConflict
    from .reader_retrieval import build_candidate_batch
    from .ranking_provider import RankingProvider
    from . import assembly_integration as assembly
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('ranking limit must be 1..100')
    if (not shadow and not enabled()) or (shadow and not shadow_enabled()):
        return {'status': 'disabled', 'articles': []}
    if os.getenv('S5_READER_ENABLED', 'false').lower() != 'true' or (not shadow and os.getenv('S6_SERVING_ENABLED', 'false').lower() != 'true'):
        return {'status': 'unavailable', 'articles': []}
    deadline = time.monotonic()+20
    claim = None
    def prepare(conn):
        nonlocal claim
        with conn.transaction():
            conn.execute("SET LOCAL statement_timeout='2000ms'")
            conn.execute("SET LOCAL lock_timeout='100ms'")
            snapshot = load_reader(conn, user_id, create=False)
            control = repo.control(conn)
            if not snapshot or snapshot['migration_status'] != 'ready':
                raise ReaderConflict('reader_not_ready')
            if not control or not control['approved']:
                raise RuntimeError('ranking_not_approved')
            recipe = control['recipe']
            if not shadow and not control['serving']:
                raise RuntimeError('ranking_serving_disabled')
            claim = repo.claim_build(conn, user_id, identity(snapshot, recipe), control['recipe_hash'])
        if not claim:
            return None
        if not shadow and assembly.enabled():
            # Missing/unapproved S8 controls fail before retrieval or any provider
            # admission. Schema installation is never an application side effect.
            from . import assembly_repository
            state = assembly_repository.control(conn)
            if not state or not state['approved'] or not state['serving']:
                raise ReaderConflict('assembly_not_approved')
            reuse = _reuse_rank(conn, user_id, snapshot, control)
            if reuse is not None:
                request, ranked = reuse
                return snapshot, control, claim, request, ranked
        batch = build_candidate_batch(conn, user_id, snapshot, deadline=min(deadline, time.monotonic()+2))
        if batch.user_id != str(user_id):
            raise ReaderConflict('retrieval_account_mismatch')
        request = prepare_request(conn, batch, snapshot, recipe)
        return snapshot, control, claim, request, None
    try:
        prepared = await database_phase(pool, prepare, deadline=deadline)
        if not prepared:
            return {'status': 'building', 'articles': []}
        snapshot, control, claim, request, reused_rank = prepared
        can_spend = (not shadow and control['provider'] and os.getenv('S7_PROVIDER_ENABLED', 'false').lower() == 'true'
                     and (not background or os.getenv('S7_BACKGROUND_ENABLED', 'false').lower() == 'true'))
        async def reserve(attempt, amount):
            return await database_phase(pool, lambda c: repo.reserve(c, user_id, claim['build_id'], claim['token'], attempt, amount), deadline=deadline)
        async def settle(reservation, amount):
            return await database_phase(pool, lambda c: repo.settle(c, reservation['reservation_id'], amount), deadline=deadline)
        ranked = reused_rank if reused_rank is not None else await rank(
            request, provider=RankingProvider() if can_spend else None,
            reserve=reserve, settle=settle, deadline=deadline)
        if shadow:
            return {'status': ranked.status, 'candidates': len(ranked.judgments),
                    'accepted': len(ranked.ordered_ids), 'provider_calls': 0}
        return await database_phase(pool, lambda c: _publish(c, user_id, request, ranked, snapshot,
                    claim, limit, capability, deadline), deadline=deadline)
    except ReaderConflict:
        return {'status': 'needs_build', 'articles': []}
    except asyncio.CancelledError:
        raise
    except Exception:
        return {'status': 'unavailable', 'articles': []}
    finally:
        # Claim leases recover interrupted preflight; known claims can be released
        # without refunding any spend, and never release a different owner's token.
        if claim:
            try:
                await database_phase(pool, lambda c: repo.release_claim(c, user_id, claim['build_id'], claim['token']),
                                     deadline=time.monotonic()+2)
            except Exception:
                pass
