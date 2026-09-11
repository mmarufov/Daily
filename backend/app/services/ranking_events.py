"""Minimal S8/S4 adapter: independent significance, one S7 publication fence.

Discover in a coherent readonly snapshot, lock the bounded dependency union with
S6, then revalidate before composing. Never issue receipts or make model calls.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

from .reader_repository import ReaderConflict


def prepare(conn, capability):
    if capability != '1' or os.getenv('S4_CONSUMERS_ENABLED', 'false').lower() != 'true':
        return []
    from .event_repository import load_candidates
    candidates = load_candidates(conn)
    if len(article_ids(candidates)) > 300:
        # Bound the lock set, not the semantic verdicts of the S6 batch.
        return []
    return candidates


def article_ids(candidates):
    if len(candidates) > 128:
        raise ReaderConflict('event_candidates_unbounded')
    for candidate in candidates:
        if len(candidate['snapshot']['evidence']) > 128 or len(candidate['representatives']) > 128:
            raise ReaderConflict('event_dependencies_unbounded')
        dependencies = {str(item['dependency']['article_id']) for item in candidate['snapshot']['evidence']}
        if any(str(rep['article']['id']) not in dependencies for rep in candidate['representatives']):
            raise ReaderConflict('event_representative_not_in_snapshot')
    return sorted({item['dependency']['article_id'] for candidate in candidates
                   for item in candidate['snapshot']['evidence']})


def _display_stamp(article):
    """Equivalent database and JSON timestamp representations share a fence."""
    from .retrieval_contract import article_stamp
    values = dict(article)
    for key, value in values.items():
        if isinstance(value, datetime):
            values[key] = value.isoformat()
        elif isinstance(value, str) and (key.endswith('_at') or key.endswith('_until')):
            try:
                values[key] = datetime.fromisoformat(value.replace('Z', '+00:00')).isoformat()
            except ValueError:
                pass
    return article_stamp(values)


def lock_sources(conn, candidates):
    if not candidates:
        return
    from . import event_repository as repo
    recipe_ids = {c['snapshot']['recipe_id'] for c in candidates}
    if len(recipe_ids) != 1:
        raise ReaderConflict('event_recipe_changed')
    _, control, recipe, _ = repo._controls(conn, next(iter(recipe_ids)), lock=True)
    if not control['delivery_enabled'] or control['serving_recipe'] != recipe['id'] or not recipe['approved']:
        raise ReaderConflict('event_recipe_changed')
    identifiers = [uuid.UUID(value) for value in article_ids(candidates)]
    sources = conn.execute('''SELECT * FROM public.event_source_registry
      WHERE article_id=ANY(%s) ORDER BY id''', (identifiers,)).fetchall()
    if len(sources) != len(identifiers):
        raise ReaderConflict('event_source_changed')
    domains = sorted({s['source_domain'] for s in sources})
    conn.execute('''SELECT source_domain FROM public.article_source_policies
      WHERE source_domain=ANY(%s) ORDER BY source_domain FOR SHARE''', (domains,)).fetchall()
    locked = conn.execute('''SELECT * FROM public.event_source_registry
      WHERE article_id=ANY(%s) ORDER BY id FOR SHARE''', (identifiers,)).fetchall()
    if {s['id']: s['source_domain'] for s in sources} != {s['id']: s['source_domain'] for s in locked}:
        raise ReaderConflict('event_source_changed')


def compose(conn, user_id, result, candidates, profile, *, limit, details=False):
    if not candidates:
        if details:
            from .event_feed import FeedResult
            return FeedResult(payload=result, major_candidates=[], decisions=[])
        return result
    from . import event_repository as repo
    from .event_contract import timestamp, validate_assessment
    from .event_consumers import ReaderPolicy
    from .event_feed import apply_event_feed
    from .reader_compiler import policy_allows, projections
    from .reader_retrieval import _s6_hydrate, _s6_recipe
    event_ids = sorted({uuid.UUID(c['snapshot']['event_id']) for c in candidates}, key=str)
    conn.execute('SELECT id FROM public.events WHERE id=ANY(%s) ORDER BY id FOR SHARE', (event_ids,)).fetchall()
    developments = {str(row['id']): row for row in conn.execute('''SELECT id,event_id,version
      FROM public.event_developments WHERE event_id=ANY(%s)
      ORDER BY id FOR SHARE''', (event_ids,)).fetchall()}
    upstream, control, recipe, sr = repo._controls(conn, candidates[0]['snapshot']['recipe_id'])
    if not control['delivery_enabled'] or control['serving_recipe'] != recipe['id'] or not recipe['approved']:
        raise ReaderConflict('event_recipe_changed')
    now = conn.execute('SELECT clock_timestamp() AS time').fetchone()['time']
    fresh = _s6_hydrate(conn, article_ids(candidates), _s6_recipe(conn))
    for candidate in candidates:
        frozen = candidate['snapshot']
        validate_assessment(candidate['assessment'], frozen, now=now)
        event = repo._validate_dependencies(conn, frozen, upstream, control, recipe, sr)
        if event['lifecycle'] != 'active' or str(event['current_assessment']) != candidate['assessment_id']:
            raise ReaderConflict('event_assessment_changed')
        development = developments.get(candidate['development_id'])
        if (not development or str(development['event_id']) != frozen['event_id']
                or type(candidate['development_version']) is not int
                or development['version'] != candidate['development_version']):
            raise ReaderConflict('event_development_changed')
        links = conn.execute('''SELECT article_id,payload FROM public.event_evidence
          WHERE event_id=%s AND development_id=%s AND active ORDER BY evidence_id''',
          (frozen['event_id'], candidate['development_id'])).fetchall()
        if (now-timestamp(frozen['coverage']['observed_through'])).total_seconds() > recipe['definition']['maximum_observation_lag_seconds']:
            raise ReaderConflict('event_coverage_expired')
        for rep in candidate['representatives']:
            if (rep['development_id'] != candidate['development_id']
                    or rep['development_version'] != candidate['development_version']
                    or not any(str(link['article_id']) == str(rep['article']['id'])
                               and link['payload']['role'] == rep['role']
                               and link['payload']['dependency']['source_id'] == rep['source_id']
                               for link in links)):
                raise ReaderConflict('event_representative_membership_changed')
            # The S4 snapshot also froze display fields. Compare them after the
            # union article/artifact locks, not merely the model evidence hash.
            row = conn.execute('''SELECT a.*,artifact.kind AS artifact_kind,artifact.method AS artifact_method,
              artifact.origin_url AS artifact_origin_url,artifact.fetched_at AS artifact_fetched_at,
              artifact.extractor_version AS artifact_extractor_version,artifact.completeness AS artifact_completeness,
              artifact.confidence AS artifact_confidence,artifact.content_hash AS artifact_content_hash
              FROM public.articles a LEFT JOIN public.article_content_artifacts artifact
                ON artifact.id=a.display_content_artifact_id AND artifact.article_id=a.id WHERE a.id=%s''',
              (rep['article']['id'],)).fetchone()
            if not row or _display_stamp(row) != _display_stamp(rep['article']):
                raise ReaderConflict('event_representative_changed')
    hidden = conn.execute('''SELECT DISTINCT article_id FROM public.reading_events WHERE user_id=%s
      AND event_type IN ('not_relevant','less_like_this','already_knew','hide_source')''', (user_id,)).fetchall()
    seen = conn.execute('''WITH RECURSIVE seen(development_id,development_version) AS (
      SELECT DISTINCT d.development_id,d.development_version
      FROM public.event_delivery_receipts d JOIN public.reading_events r
        ON r.user_id=d.user_id AND r.feed_request_id=d.feed_request_id AND r.article_id=d.article_id
      WHERE d.user_id=%s AND r.event_type IN ('tap','read','already_knew')
      UNION SELECT a.target_id,a.target_version FROM seen s JOIN public.event_development_aliases a
        ON a.development_id=s.development_id AND a.version=s.development_version
      ) SELECT development_id,development_version FROM seen''', (user_id,)).fetchall()
    settings = projections(profile, now=now)['user_profile_v2']
    blocked = frozenset(str(r['article_id']) for r in hidden)
    policy = ReaderPolicy(delivery_enabled=True, client_supports_event_expiry=True,
        blocked_article_ids=blocked,
        seen_development_versions=frozenset((str(r['development_id']), r['development_version']) for r in seen),
        place_ids=frozenset(settings['place_ids']), sector_ids=frozenset(settings['sector_ids']),
        preferred_languages=tuple(profile['languages']))
    def hard_allowed(article):
        row = fresh.get(str(article['id']))
        return bool(row and str(article['id']) not in blocked and article.get('analysis_revoked') is not True
                    and policy_allows(profile, {**article, **row['policy']}, now=now))
    selected = apply_event_feed(result, candidates, policy, now=now, limit=limit,
                                hard_allowed=hard_allowed)
    return selected if details else selected.payload
