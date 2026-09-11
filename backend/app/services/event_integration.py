"""Default-off final feed hook. Never stores priority in the legacy feed cache.

One fresh DB snapshot authorizes event dependencies, current reader exclusions
and S2 serialization of new representatives together. Existing ordinary S2
public fields remain caller-owned. This is not a redesign of S7 personalized scoring.
No model work, extraction, DDL or source discovery is initiated here.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from . import event_repository as repo
from .event_consumers import ReaderPolicy
from .event_feed import apply_event_feed

logger = logging.getLogger(__name__)


def _reauthorize_ordinary(conn, result, policy, profile, score_candidate):
    """Check existing public rows against current policy without leaking DB rows.

    Ordinary reporting does not require S3 readiness or analysis permission.
    Only an explicit taxonomy exclusion needs a current approved S3 topic card;
    an unknown card cannot prove that such an exclusion does not match.
    """
    articles = result.get('articles')
    if not isinstance(articles, list) or len(articles) > 10000:
        raise ValueError('bounded ordinary feed required')
    if not articles:
        return result
    identifiers = set()
    for article in articles:
        try:
            identifiers.add(uuid.UUID(article['id']))
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    rows = conn.execute('''SELECT a.* FROM public.articles a WHERE a.id=ANY(%s)''',
                        (sorted(identifiers, key=str),)).fetchall() if identifiers else []
    current = {str(row['id']): row for row in rows}
    topic_recipe = None
    if policy.blocked_topic_ids:
        topic_recipe = conn.execute('''SELECT r.id FROM public.understanding_control c
          JOIN public.understanding_recipes r ON r.id=c.serving_recipe
          WHERE r.enabled AND r.approved''').fetchone()
    accepted = []
    for public in articles:
        if not isinstance(public, dict):
            continue
        row = current.get(public.get('id'))
        if row is None or str(row['id']) in policy.blocked_article_ids:
            continue
        source_ids = {str(row[key]) for key in ('source_id', 'canonical_source_domain') if row.get(key)}
        if policy.blocked_source_ids and (not source_ids or source_ids.intersection(policy.blocked_source_ids)):
            continue
        _, _, excluded = score_candidate(row, profile)
        if excluded:
            continue
        if policy.blocked_topic_ids:
            if topic_recipe is None:
                continue
            card = repo.s3.load_current(conn, row['id'], topic_recipe['id'])
            if card.get('state') != 'ready' or not card.get('facets'):
                continue
            topics = card['facets'].get('payload', {}).get('topics')
            if not isinstance(topics, list) or any(
                not isinstance(topic, dict) or not isinstance(topic.get('topic_id'), str) or not topic['topic_id'].strip()
                for topic in topics
            ):
                continue
            if policy.blocked_topic_ids.intersection(topic['topic_id'] for topic in topics):
                continue
        # Public S2 fields and existing S7 scores survive unchanged. The current
        # private DB row is used only for policy checks, never merged into output.
        item = dict(public)
        if item.get('event_delivery') is not None or item.get('feed_role') in ('world_critical', 'event_priority'):
            item.pop('feed_role', None)
            item.pop('why_now', None)
            item.pop('relevance_reason', None)
        item.pop('event_delivery', None)
        accepted.append(item)
    output = dict(result)
    output['articles'] = accepted
    if 'article_count' in output:
        output['article_count'] = len(accepted)
    if not accepted and output.get('status') == 'ready':
        output['status'] = 'needs_build'
    return output


def compose_feed(conn, user_id, result, *, capability=None, limit=50):
    if os.getenv('S4_CONSUMERS_ENABLED', 'false').lower() != 'true' or capability != '1':
        return result
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('S4 edition limit must be 1..100')
    from .feed_service import _load_user_preferences_full, _build_preference_profile, _score_candidate
    fallback = result
    try:
        if not conn.autocommit or conn.info.transaction_status != 0:
            raise RuntimeError('S4 request requires fresh database snapshot')
        with conn.transaction():
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            control = conn.execute('SELECT * FROM public.event_control').fetchone()
            if not control or not control['delivery_enabled']:
                return result
            ai, interests, v2, _, _ = _load_user_preferences_full(conn, uuid.UUID(user_id))
            profile = _build_preference_profile(ai or '', interests, user_profile_v2=v2)
            # Unlike the legacy optional helper, an unavailable hard-hide lookup
            # must reject new priority, not silently return an empty exclusion set.
            hidden = conn.execute('''SELECT DISTINCT article_id FROM public.reading_events WHERE user_id=%s
              AND event_type IN ('not_relevant','less_like_this','already_knew','hide_source')''', (uuid.UUID(user_id),)).fetchall()
            blocked = frozenset(str(row['article_id']) for row in hidden)
            seen = conn.execute('''WITH RECURSIVE seen(development_id,development_version) AS (
              SELECT DISTINCT d.development_id,d.development_version
              FROM public.event_delivery_receipts d JOIN public.reading_events r
                ON r.user_id=d.user_id AND r.feed_request_id=d.feed_request_id AND r.article_id=d.article_id
              WHERE d.user_id=%s AND r.event_type IN ('tap','read','already_knew')
              UNION
              SELECT a.target_id,a.target_version FROM seen s JOIN public.event_development_aliases a
                ON a.development_id=s.development_id AND a.version=s.development_version
            ) SELECT development_id,development_version FROM seen''', (uuid.UUID(user_id),)).fetchall()
            settings = v2 or {}
            def values(key):
                raw = settings.get(key, [])
                if not isinstance(raw, list) or any(type(v) is not str or not v.strip() for v in raw):
                    raise ValueError('invalid explicit reader policy')
                return raw
            policy = ReaderPolicy(delivery_enabled=True, client_supports_event_expiry=True,
                blocked_article_ids=blocked, blocked_source_ids=frozenset(values('blocked_source_ids')),
                blocked_topic_ids=frozenset(values('blocked_topic_ids')),
                seen_development_versions=frozenset((str(r['development_id']), r['development_version']) for r in seen),
                # Only canonical settings are usable; free-form locations do not
                # become canonical place IDs by inference.
                place_ids=frozenset(values('place_ids')), sector_ids=frozenset(values('sector_ids')),
                preferred_languages=tuple(values('preferred_languages')))
            fallback = {**result, 'articles': [], 'status': 'needs_build'}
            if 'article_count' in fallback:
                fallback['article_count'] = 0
            authorized_ordinary = _reauthorize_ordinary(conn, result, policy, profile, _score_candidate)
            # Later S4/receipt errors cannot resurrect rows already rejected by
            # this request's current reader policy.
            fallback = authorized_ordinary
            candidates = repo.load_candidates(conn, in_snapshot=True)
            now = conn.execute('SELECT clock_timestamp() AS time').fetchone()['time']
            def hard_allowed(article):
                _, _, excluded = _score_candidate(article, profile)
                return not excluded and str(article['id']) not in blocked and article.get('analysis_revoked') is not True
            selected = apply_event_feed(authorized_ordinary, candidates, policy, now=now, limit=limit, hard_allowed=hard_allowed)
        priority = [item for item in selected.payload['articles'] if item.get('event_delivery')]
        if priority:
            request_id = uuid.uuid4()
            # This history does not authorize or cache priority. It records the
            # versions authorized above; invalidation after that point cannot
            # recall an in-flight response. No acknowledgment is fabricated.
            with conn.transaction():
                for item in priority:
                    metadata = item['event_delivery']
                    conn.execute('''INSERT INTO public.event_delivery_receipts(user_id,feed_request_id,article_id,event_id,
                      development_id,development_version,assessment_id,valid_until) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
                      (uuid.UUID(user_id), request_id, uuid.UUID(item['id']), uuid.UUID(metadata['event_id']),
                       uuid.UUID(metadata['development_id']), metadata['development_version'],
                       uuid.UUID(metadata['assessment_id']), metadata['valid_until']))
            selected.payload['feed_request_id'] = str(request_id)
        logger.info('S4 composition authorized; candidates=%s reserved=%s major_handoff=%s', len(candidates),
                    sum(d.get('reason') == 'reserved' for d in selected.decisions), len(selected.major_candidates))
        return selected.payload
    except Exception:
        # Fail closed for S4 while preserving ordinary eligible reporting. No
        # private DB/source/error strings or user identity enter this log.
        logger.warning('S4 composition unavailable; preserving ordinary feed')
        return fallback
