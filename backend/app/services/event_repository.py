"""S4 durable state. Explicit migration; no model work while a connection is held.

All public operations expect an autocommit psycopg dict-row connection. Serving
uses one fresh repeatable-read snapshot. Publication locks controls, source
policy/registry, articles, S3 recipe, events, developments, then job; never S3 jobs.
S4 deliberately does not consume S3's mutable group partition as event identity.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path

from psycopg.types.json import Jsonb

from . import understanding_repository as s3
from .event_contract import Source, canonical_json, digest, snapshot_hash, validate_assessment, validate_snapshot
from .event_evidence import build_snapshot, from_s3, validate_original_spans

SCHEMA_VERSION = 1
DEFAULT_RECIPE = {
    'version': 1, 's3_recipe_id': None, 'provider': None, 'refinement_provider': None,
    'supported_languages': [], 'coverage_supported': False, 'grouping_calibrated': False,
    'support_policy': {'minimum_independent_origins': 2, 'allow_verified_primary': False},
    'maximum_evidence': 128, 'maximum_observation_lag_seconds': 300,
}


class StaleInput(ValueError):
    """Fixed diagnostic; never include private evidence in exception text."""


class LeaseLost(Exception):
    pass


def _money(value):
    if isinstance(value, bool):
        raise ValueError('invalid monetary amount')
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not 0 <= amount <= Decimal('99999999.99999999'):
            raise ValueError('invalid monetary amount')
        return amount.quantize(Decimal('0.00000001'), rounding=ROUND_CEILING)
    except InvalidOperation:
        raise ValueError('invalid monetary amount')


def _limit(value, maximum=1000):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError('invalid bounded limit')
    return value


def _generation(value):
    if type(value) is not int or value < 1:
        raise ValueError('positive integer generation required')
    return value


def _pair(left, right):
    """Injective version pair; no ABA when recipe or control is toggled back."""
    return (left + right) * (left + right + 1) // 2 + right + 1


def ensure_schema(conn):
    s3.check_schema(conn)
    with conn.transaction():
        conn.execute(Path(__file__).with_name('event_schema.sql').read_text())


def check_schema(conn):
    row = conn.execute("SELECT to_regclass('public.event_schema_version') AS present").fetchone()
    if not row or not row['present']:
        raise RuntimeError('S4 explicit migration required')
    if conn.execute('SELECT version FROM public.event_schema_version').fetchone() != {'version': SCHEMA_VERSION}:
        raise RuntimeError('incompatible S4 schema')


def register_recipe(conn, definition, *, enabled=False):
    if not isinstance(definition, dict) or set(definition) != set(DEFAULT_RECIPE) or type(definition['version']) is not int or definition['version'] != 1:
        raise ValueError('unknown recipe definition')
    if type(enabled) is not bool:
        raise ValueError('explicit enable state required')
    if not isinstance(definition['s3_recipe_id'], str) or not definition['s3_recipe_id']:
        raise ValueError('explicit S3 recipe required')
    if any(type(definition[key]) is not bool for key in ('coverage_supported', 'grouping_calibrated')):
        raise ValueError('explicit boolean recipe controls required')
    _limit(definition['maximum_evidence'], 128)
    _limit(definition['maximum_observation_lag_seconds'], 3600)
    languages = definition['supported_languages']
    if not isinstance(languages, list) or any(type(v) is not str or not v.strip() for v in languages) or len(languages) != len(set(languages)):
        raise ValueError('invalid supported languages')
    from .event_contract import SupportPolicy
    SupportPolicy.model_validate(definition['support_policy'])
    identifier = digest(definition)
    with conn.transaction():
        conn.execute('INSERT INTO public.event_recipes(id,definition,enabled) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING',
                     (identifier, Jsonb(definition), enabled))
        if conn.execute('SELECT definition FROM public.event_recipes WHERE id=%s', (identifier,)).fetchone()['definition'] != definition:
            raise ValueError('immutable recipe mismatch')
    return identifier


def configure(conn, *, submissions_enabled, delivery_enabled=False, daily_budget_usd=0, monthly_budget_usd=0,
              expected_generation):
    _generation(expected_generation)
    if type(submissions_enabled) is not bool or type(delivery_enabled) is not bool:
        raise ValueError('explicit boolean controls required')
    day, month = _money(daily_budget_usd), _money(monthly_budget_usd)
    if submissions_enabled and not 0 < day <= month:
        raise ValueError('explicit positive daily and monthly budgets required')
    with conn.transaction():
        control = conn.execute('SELECT * FROM public.event_control FOR UPDATE').fetchone()
        if control['generation'] != expected_generation:
            raise StaleInput('control_generation_changed')
        if delivery_enabled:
            recipe = conn.execute('SELECT approved,enabled FROM public.event_recipes WHERE id=%s', (control['serving_recipe'],)).fetchone()
            if not recipe or not recipe['approved'] or not recipe['enabled']:
                raise ValueError('approved serving recipe required')
        conn.execute('''UPDATE public.event_control SET submissions_enabled=%s,delivery_enabled=%s,
          daily_budget_usd=%s,monthly_budget_usd=%s,generation=generation+1,updated_at=clock_timestamp()''',
          (submissions_enabled, delivery_enabled, day, month))
        conn.execute("INSERT INTO public.event_upstream_notices(kind,identity,generation) VALUES('s4_control','control',%s)",
                     (expected_generation + 1,))


def set_recipe_enabled(conn, recipe_id, enabled, *, expected_generation=None):
    if expected_generation is not None:
        _generation(expected_generation)
    if type(enabled) is not bool:
        raise ValueError('explicit enable state required')
    with conn.transaction():
        control = conn.execute('SELECT * FROM public.event_control FOR UPDATE').fetchone()
        if expected_generation is not None and expected_generation != control['generation']:
            raise StaleInput('control_generation_changed')
        changed = conn.execute('UPDATE public.event_recipes SET enabled=%s,approved=false WHERE id=%s', (enabled, recipe_id)).rowcount
        if not changed:
            raise ValueError('unknown recipe')
        conn.execute('''UPDATE public.event_control SET generation=generation+1,
          delivery_enabled=false,serving_recipe=NULL,updated_at=clock_timestamp()''')
        conn.execute("INSERT INTO public.event_upstream_notices(kind,identity,generation) VALUES('s4_recipe',%s,1)", (recipe_id,))


def _controls(conn, recipe_id, *, lock=False):
    suffix = ' FOR SHARE' if lock else ''
    upstream = conn.execute('SELECT * FROM public.understanding_control' + suffix).fetchone()
    control = conn.execute('SELECT * FROM public.event_control' + suffix).fetchone()
    recipe = conn.execute('SELECT * FROM public.event_recipes WHERE id=%s' + suffix, (recipe_id,)).fetchone()
    if not recipe or not recipe['enabled']:
        raise StaleInput('recipe_disabled')
    expected = recipe['definition']['s3_recipe_id']
    source_recipe = conn.execute('SELECT * FROM public.understanding_recipes WHERE id=%s', (expected,)).fetchone()
    if not source_recipe or not source_recipe['enabled'] or not source_recipe['approved'] or upstream['serving_recipe'] != expected:
        raise StaleInput('S3_cohort_not_approved')
    return upstream, control, recipe, source_recipe


def _source(conn, article_id, *, create=False):
    row = conn.execute('SELECT * FROM public.event_source_registry WHERE article_id=%s', (article_id,)).fetchone()
    if row and create:
        article = conn.execute('SELECT * FROM public.articles WHERE id=%s', (article_id,)).fetchone()
        if not article:
            raise StaleInput('article_missing')
        domain = article.get('canonical_source_domain') or ''
        if row['source_domain'] != domain or row['metadata']['language'] != article.get('language'):
            metadata = {'publisher_id': domain or None, 'reporting_origin_id': None, 'origin_status': 'unknown',
                        'primary_verified': False, 'language': article.get('language')}
            conn.execute('''UPDATE public.event_source_registry SET source_domain=%s,metadata=%s,
              generation=generation+1,reviewed_by=NULL,updated_at=clock_timestamp() WHERE id=%s''',
              (domain, Jsonb(metadata), row['id']))
            row = conn.execute('SELECT * FROM public.event_source_registry WHERE article_id=%s', (article_id,)).fetchone()
    if not row and create:
        article = conn.execute('SELECT * FROM public.articles WHERE id=%s', (article_id,)).fetchone()
        if not article:
            raise StaleInput('article_missing')
        domain = article.get('canonical_source_domain') or ''
        metadata = {'publisher_id': domain or None, 'reporting_origin_id': None, 'origin_status': 'unknown',
                    'primary_verified': False, 'language': article.get('language')}
        conn.execute('''INSERT INTO public.event_source_registry(id,article_id,source_domain,metadata)
          VALUES(%s,%s,%s,%s) ON CONFLICT(article_id) DO NOTHING''',
          ('article:' + str(article_id), article_id, domain, Jsonb(metadata)))
        row = conn.execute('SELECT * FROM public.event_source_registry WHERE article_id=%s', (article_id,)).fetchone()
    if not row:
        raise StaleInput('source_registry_missing')
    policy = conn.execute('SELECT version FROM public.article_source_policies WHERE source_domain=%s', (row['source_domain'],)).fetchone()
    return row, _pair(row['generation'], policy['version'] if policy else 0)


def set_source(conn, article_id, metadata, *, expected_generation, reviewed_by):
    _generation(expected_generation)
    metadata = Source.model_validate(metadata).model_dump()
    if not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError('provenance reviewer required')
    with conn.transaction():
        changed = conn.execute('''UPDATE public.event_source_registry SET metadata=%s,generation=generation+1,
          reviewed_by=%s,updated_at=clock_timestamp() WHERE article_id=%s AND generation=%s RETURNING generation''',
          (Jsonb(metadata), reviewed_by, article_id, expected_generation)).fetchone()
        if not changed:
            raise StaleInput('source_generation_changed')
        conn.execute("INSERT INTO public.event_upstream_notices(kind,identity,generation) VALUES('source',%s,%s)",
                     (str(article_id), changed['generation']))


def _lock_inputs(conn, article_ids, s3_recipe_id):
    ids = sorted({uuid.UUID(str(value)) for value in article_ids}, key=str)
    # Registry keys must exist before this publication transaction; missing keys fail closed.
    sources = conn.execute('SELECT * FROM public.event_source_registry WHERE article_id=ANY(%s) ORDER BY id', (ids,)).fetchall()
    if len(sources) != len(ids):
        raise StaleInput('source_registry_missing')
    domains = sorted({s['source_domain'] for s in sources})
    conn.execute('SELECT source_domain FROM public.article_source_policies WHERE source_domain=ANY(%s) ORDER BY source_domain FOR SHARE', (domains,)).fetchall()
    locked_sources = conn.execute('SELECT * FROM public.event_source_registry WHERE article_id=ANY(%s) ORDER BY id FOR SHARE', (ids,)).fetchall()
    if {row['id']: row['source_domain'] for row in locked_sources} != {row['id']: row['source_domain'] for row in sources}:
        raise StaleInput('source_policy_discovery_changed')
    rows = conn.execute('SELECT id FROM public.articles WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (ids,)).fetchall()
    if len(rows) != len(ids):
        raise StaleInput('article_missing')
    row = conn.execute('SELECT * FROM public.understanding_recipes WHERE id=%s FOR SHARE', (s3_recipe_id,)).fetchone()
    if not row or not row['enabled'] or not row['approved']:
        raise StaleInput('S3_cohort_not_approved')
    return row


def _current(conn, article_id, s3_recipe_id):
    bundle = s3.evidence_for_article(conn, article_id)
    current = s3.load_current(conn, article_id, s3_recipe_id)
    if not bundle or current['state'] != 'ready':
        raise StaleInput('S3_input_not_ready')
    # Explicitly do not consume S3 cluster identity/version. S4 owns its partition.
    current['membership'] = None
    return bundle, current


def _job(conn, job):
    row = conn.execute('''SELECT * FROM public.event_jobs WHERE id=%s AND state='running'
      AND lease_token=%s AND lease_until>clock_timestamp() AND deadline>clock_timestamp() FOR UPDATE''',
      (job['id'], job['lease_token'])).fetchone()
    if not row:
        raise LeaseLost()
    return row


def _finish(conn, job, state='ready', reason=None):
    changed = conn.execute('''UPDATE public.event_jobs SET state=%s,failure_reason=%s,
      lease_token=NULL,lease_until=NULL,updated_at=clock_timestamp() WHERE id=%s AND state='running'
      AND lease_token=%s AND lease_until>clock_timestamp() AND deadline>clock_timestamp()''',
      (state, reason, job['id'], job['lease_token'])).rowcount
    if not changed:
        raise LeaseLost()


def _schedule(conn, recipe_id, stage, subject_id, revision, source_key='unknown'):
    return conn.execute('''INSERT INTO public.event_jobs(recipe_id,stage,subject_id,revision,source_key)
      VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''', (recipe_id, stage, subject_id, str(revision), source_key)).rowcount


def _dirty(conn, event_id, kind):
    row = conn.execute('''UPDATE public.events SET generation=generation+1,member_generation=member_generation+1,
      current_assessment=NULL,lifecycle=CASE WHEN lifecycle='merged' THEN lifecycle ELSE 'candidate' END,
      updated_at=clock_timestamp() WHERE id=%s RETURNING *''', (event_id,)).fetchone()
    conn.execute('INSERT INTO public.event_outbox(event_id,generation,kind) VALUES(%s,%s,%s)', (event_id, row['generation'], kind))
    conn.execute('INSERT INTO public.event_changes(event_id,generation,kind) VALUES(%s,%s,%s)', (event_id, row['generation'], kind))
    return row


def _invalidate_article(conn, article_id, notice):
    # Notices may commit out of sequence or be replayed after newer evidence is
    # ready. Their monotone article coordinates identify what they supersede;
    # an old notice must never erase a newer valid snapshot or spend again.
    cutoff = (notice['semantic_revision'], notice['eligibility_generation'])
    inclusive = notice['kind'] in ('revoked', 'deleted')
    def outdated(expression):
        operator = '<=' if inclusive else '<'
        return f"(({expression}->>'semantic_revision')::bigint,({expression}->>'eligibility_generation')::bigint) {operator} (%s,%s)"
    ids = [r['event_id'] for r in conn.execute('SELECT DISTINCT event_id FROM public.event_evidence WHERE article_id=%s ORDER BY event_id', (article_id,)).fetchall()]
    # Acquire the entire sorted event set before touching any downstream job.
    conn.execute('SELECT id FROM public.events WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (ids,)).fetchall()
    for eid in ids:
        changed = conn.execute('UPDATE public.event_evidence SET active=false,payload=NULL WHERE event_id=%s AND article_id=%s AND active AND '
                               + outdated('dependency'), (eid, article_id, *cutoff)).rowcount
        # Purge only historical private payloads that actually contain the
        # superseded dependency, even if their current membership is inactive.
        conn.execute('''UPDATE public.event_snapshots SET payload=NULL WHERE event_id=%s AND EXISTS
          (SELECT 1 FROM jsonb_array_elements(payload->'evidence') item
           WHERE item->'dependency'->>'article_id'=%s AND ''' + outdated("(item->'dependency')") + ')',
          (eid, str(article_id), *cutoff))
        conn.execute('''UPDATE public.event_refinements SET payload=NULL WHERE event_id=%s
          AND payload->'evidence'->'dependency'->>'article_id'=%s AND ''' + outdated("(payload->'evidence'->'dependency')"),
          (eid, str(article_id), *cutoff))
        if changed:
            event = _dirty(conn, eid, 'evidence_invalidated')
            _schedule(conn, event['recipe_id'], 'assess', eid, event['generation'])


def consume_changes(conn, *, limit=100):
    """Apply and receipt exact IDs atomically; never assume sequence commit order."""
    _limit(limit)
    count = 0
    for table, stream in (('understanding_outbox', 's3'), ('event_upstream_notices', 'control'),
                          ('article_source_policy_events', 's2_policy')):
        # Table names are fixed code constants, never provider/user input.
        rows = conn.execute(f'''SELECT o.* FROM public.{table} o WHERE NOT EXISTS
          (SELECT 1 FROM public.event_inbox_receipts r WHERE r.stream=%s AND r.event_id=o.id)
          ORDER BY o.id LIMIT %s''', (stream, limit)).fetchall()
        for row in rows:
            # One notice per transaction: never accumulate locally-sorted event
            # locks across unrelated articles and reverse the global order.
            with conn.transaction():
                receipt = conn.execute('INSERT INTO public.event_inbox_receipts(stream,event_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (stream, row['id'])).rowcount
                if not receipt:
                    continue
                if stream == 's3':
                    if row['kind'] in ('invalidated', 'revoked', 'deleted'):
                        _invalidate_article(conn, row['article_id'], row)
                    recipes = conn.execute('SELECT id FROM public.event_recipes WHERE enabled').fetchall()
                    for recipe in recipes:
                        _schedule(conn, recipe['id'], 'ingest', row['article_id'], f"notice:{row['id']}")
                else:
                    # Current reads are immediately fenced; bounded scanner heals schedules.
                    conn.execute("UPDATE public.event_scan_state SET after_id=NULL WHERE name LIKE 'articles:%%'")
                count += 1
    return count


def reconcile(conn, recipe_id, *, limit=100, after=None):
    _limit(limit)
    with conn.transaction():
        upstream, control, recipe, sr = _controls(conn, recipe_id)
        rows = conn.execute('''SELECT a.id,a.semantic_revision,a.analysis_eligibility_generation FROM public.articles a
          WHERE NOT a.analysis_revoked AND (%s::uuid IS NULL OR a.id>%s::uuid) ORDER BY a.id LIMIT %s''', (after, after, limit)).fetchall()
        inserted = 0
        for row in rows:
            source, generation = _source(conn, row['id'], create=True)
            key = digest([row['semantic_revision'], row['analysis_eligibility_generation'], generation,
                          sr['serving_generation'], upstream['serving_generation'], control['generation']])
            inserted += _schedule(conn, recipe_id, 'ingest', row['id'], key, source['source_domain'])
    return {'scanned': len(rows), 'inserted': inserted, 'next_cursor': str(rows[-1]['id']) if rows else None}


def scan(conn, *, limit=100):
    """Cyclic bounded anti-entropy; receipts are not a pruning/retention watermark."""
    recipes = conn.execute('SELECT id FROM public.event_recipes WHERE enabled').fetchall()
    for recipe in recipes:
        name = 'articles:' + recipe['id']
        state = conn.execute('SELECT after_id FROM public.event_scan_state WHERE name=%s', (name,)).fetchone()
        try:
            result = reconcile(conn, recipe['id'], limit=limit, after=state['after_id'] if state else None)
        except StaleInput:
            continue
        conn.execute('''INSERT INTO public.event_scan_state(name,after_id) VALUES(%s,%s)
          ON CONFLICT(name) DO UPDATE SET after_id=EXCLUDED.after_id,updated_at=clock_timestamp()''',
          (name, result['next_cursor'] if result['scanned'] == limit else None))


def reap(conn):
    with conn.transaction():
        return conn.execute('''UPDATE public.event_jobs SET state=CASE WHEN attempts>=5 OR deadline<=clock_timestamp()
          THEN 'failed_terminal' ELSE 'retry_wait' END,failure_reason='lease_or_deadline_expired',lease_token=NULL,lease_until=NULL,
          retry_at=clock_timestamp()+interval '30 seconds',updated_at=clock_timestamp()
          WHERE (state='running' AND lease_until<=clock_timestamp())
             OR (state IN ('pending','retry_wait') AND deadline<=clock_timestamp())''').rowcount


def claim(conn, *, limit=4, lease_seconds=180):
    _limit(limit, 16); _limit(lease_seconds, 600)
    claimed = []
    with conn.transaction():
        rows = conn.execute('''WITH due AS (
          SELECT j.id,row_number() OVER(PARTITION BY j.source_key ORDER BY j.retry_at,j.id) AS rank
          FROM public.event_jobs j JOIN public.event_recipes r ON r.id=j.recipe_id CROSS JOIN public.event_control c
          WHERE r.enabled AND c.submissions_enabled AND (c.circuit_until IS NULL OR c.circuit_until<=clock_timestamp())
            AND j.state IN ('pending','retry_wait') AND j.retry_at<=clock_timestamp() AND j.deadline>clock_timestamp() AND attempts<5
        ) SELECT j.*,r.definition FROM public.event_jobs j JOIN due d ON d.id=j.id JOIN public.event_recipes r ON r.id=j.recipe_id
          WHERE j.state IN ('pending','retry_wait') AND j.retry_at<=clock_timestamp()
            AND j.deadline>clock_timestamp() AND j.attempts<5 AND r.enabled
          ORDER BY d.rank,j.retry_at,j.id LIMIT %s FOR UPDATE OF j SKIP LOCKED''', (limit,)).fetchall()
        for row in rows:
            token = uuid.uuid4()
            updated = conn.execute('''UPDATE public.event_jobs SET state='running',attempts=attempts+1,lease_token=%s,
              lease_until=clock_timestamp()+%s*interval '1 second',updated_at=clock_timestamp() WHERE id=%s
              AND state IN ('pending','retry_wait') AND attempts<5 AND deadline>clock_timestamp() RETURNING *''',
              (token, lease_seconds, row['id'])).fetchone()
            if updated:
                updated['definition'] = row['definition']
                claimed.append(updated)
    return claimed


def fail(conn, job, reason, *, retryable=False, retry_after=60):
    if reason not in {'input_changed','contract_invalid','provider_failure','budget_paused','internal_failure','unsupported_refinement','oversized_snapshot'}:
        reason = 'internal_failure'
    with conn.transaction():
        conn.execute('''UPDATE public.event_jobs SET state=CASE WHEN %s AND attempts<5 AND deadline>clock_timestamp()
          THEN 'retry_wait' ELSE 'failed_terminal' END, failure_reason=%s,lease_token=NULL,lease_until=NULL,
          retry_at=clock_timestamp()+%s*interval '1 second',updated_at=clock_timestamp()
          WHERE id=%s AND state='running' AND lease_token=%s''',
          (retryable, reason, min(3600, max(1, retry_after)), job['id'], job['lease_token']))


def defer_without_attempt(conn, job, reason='budget_paused', *, delay=300):
    with conn.transaction():
        # Only an attempt with no reservation can be returned to the queue.
        return conn.execute('''UPDATE public.event_jobs j SET state='retry_wait',attempts=GREATEST(0,attempts-1),
          lease_token=NULL,lease_until=NULL,failure_reason='budget_paused',
          retry_at=clock_timestamp()+%s*interval '1 second',updated_at=clock_timestamp()
          WHERE id=%s AND state='running' AND lease_token=%s AND NOT EXISTS
            (SELECT 1 FROM public.event_spend s WHERE s.job_id=j.id AND s.attempt=j.attempts)''',
          (min(3600, max(1, delay)), job['id'], job['lease_token'])).rowcount


def pause_provider(conn, reason='provider_failure', *, delay=300):
    with conn.transaction():
        conn.execute("""UPDATE public.event_control SET circuit_until=clock_timestamp()+%s*interval '1 second',
          circuit_reason='provider_failure',updated_at=clock_timestamp()""", (min(3600, max(1, delay)),))


def ingest(conn, job):
    # Registry creation commits before any publication locks. Default provenance unknown.
    with conn.transaction():
        _source(conn, job['subject_id'], create=True)
    with conn.transaction():
        upstream, control, recipe, _ = _controls(conn, job['recipe_id'], lock=True)
        sr = _lock_inputs(conn, [job['subject_id']], recipe['definition']['s3_recipe_id'])
        bundle, current = _current(conn, job['subject_id'], sr['id'])
        source, source_generation = _source(conn, job['subject_id'])
        observed = conn.execute('SELECT clock_timestamp() AS time').fetchone()['time'].isoformat()
        mentions = from_s3(bundle, current, source_id=source['id'], source_generation=source_generation,
                           observed_at=observed, source=source['metadata'])
        # Discover every existing event for this article before locking event rows.
        old = conn.execute('''SELECT DISTINCT ee.event_id FROM public.event_evidence ee
          JOIN public.events e ON e.id=ee.event_id WHERE ee.article_id=%s AND e.recipe_id=%s''', (job['subject_id'], job['recipe_id'])).fetchall()
        seeded = []
        for item in mentions:
            # Seed is an intake idempotency key, not the permanent event identity.
            key = str(job['subject_id']) + ':' + str(item['hint_index'])
            existing = conn.execute('SELECT id FROM public.events WHERE recipe_id=%s AND seed_key=%s', (job['recipe_id'], key)).fetchone()
            seeded.append((item, key, existing['id'] if existing else uuid.uuid4()))
        ids = sorted({r['event_id'] for r in old} | {entry[2] for entry in seeded}, key=str)
        conn.execute('SELECT id FROM public.events WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (ids,)).fetchall()
        # Input is serialized by the article lock; no concurrent seed insert can win.
        for _, key, eid in seeded:
            conn.execute('INSERT INTO public.events(id,recipe_id,seed_key) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (eid, job['recipe_id'], key))
        conn.execute('SELECT id FROM public.event_developments WHERE event_id=ANY(%s) ORDER BY id FOR UPDATE', (ids,)).fetchall()
        _job(conn, job)
        for item, key, eid in seeded:
            event = conn.execute('SELECT * FROM public.events WHERE id=%s', (eid,)).fetchone()
            if event['lifecycle'] == 'merged':
                # Split revised source evidence back into its stable candidate.
                # Both former and current targets are in the retained reverse-link
                # discovery above, locked before the job; never follow redirects late.
                conn.execute("UPDATE public.events SET lifecycle='candidate',redirect_id=NULL WHERE id=%s", (eid,))
                event = _dirty(conn, eid, 'reopened_for_correction')
            prior = conn.execute('SELECT * FROM public.event_evidence WHERE event_id=%s AND evidence_id=%s', (eid, item['id'])).fetchone()
            input_generation = digest([item['dependency'], upstream['serving_generation'], sr['serving_generation'], control['generation']])
            # Do not undo a successfully refined immutable mention on repeated intake.
            if prior and prior['active'] and prior['dependency'] == item['dependency'] and event['input_generation'] == input_generation:
                continue
            preserve_refinement = bool(prior and prior['active'] and prior['refined'] and prior['payload'])
            if preserve_refinement:
                # Source/control provenance may change without changing the exact hint.
                refined = dict(prior['payload']); refined['dependency'] = item['dependency']; refined['source'] = item['source']
                item = refined
            development = (conn.execute('SELECT * FROM public.event_developments WHERE id=%s', (prior['development_id'],)).fetchone()
                           if prior else conn.execute('SELECT * FROM public.event_developments WHERE event_id=%s AND fingerprint=%s', (eid, item['id'])).fetchone())
            dev = development['id'] if development else uuid.uuid4()
            if not development:
                conn.execute('INSERT INTO public.event_developments(id,event_id,fingerprint) VALUES(%s,%s,%s)', (dev, eid, item['id']))
                conn.execute("INSERT INTO public.development_versions VALUES(%s,1,%s,'unassessed',clock_timestamp())", (dev, digest(item['claim'])))
            conn.execute('UPDATE public.event_evidence SET active=false,payload=NULL WHERE event_id=%s AND article_id=%s', (eid, job['subject_id']))
            conn.execute('''INSERT INTO public.event_evidence(event_id,evidence_id,development_id,article_id,dependency,payload,refined)
              VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id,evidence_id) DO UPDATE
              SET dependency=EXCLUDED.dependency,payload=EXCLUDED.payload,active=true,refined=EXCLUDED.refined''',
              (eid, item['id'], dev, job['subject_id'], Jsonb(item['dependency']), Jsonb(item), preserve_refinement))
            conn.execute('UPDATE public.events SET input_generation=%s WHERE id=%s', (input_generation, eid))
            event = _dirty(conn, eid, 'evidence_admitted')
            _schedule(conn, job['recipe_id'], 'group' if preserve_refinement else 'refine', eid, event['generation'], source['source_domain'])
        new_ids = {entry[2] for entry in seeded}
        for eid in {r['event_id'] for r in old} - new_ids:
            changed = conn.execute('UPDATE public.event_evidence SET active=false,payload=NULL WHERE event_id=%s AND article_id=%s AND active', (eid, job['subject_id'])).rowcount
            if changed:
                survivor = _dirty(conn, eid, 'mention_removed')
                _schedule(conn, survivor['recipe_id'], 'assess', eid, survivor['generation'])
        _finish(conn, job, 'ready' if mentions else 'insufficient', None if mentions else 'no_event_mentions')
    return len(mentions)


def _snapshot(conn, event, upstream, control, recipe, sr):
    rows = conn.execute('SELECT payload FROM public.event_evidence WHERE event_id=%s AND active ORDER BY evidence_id', (event['id'],)).fetchall()
    if len(rows) > recipe['definition']['maximum_evidence'] or any(row['payload'] is None for row in rows):
        raise StaleInput('oversized_or_missing_evidence')
    now = conn.execute('SELECT clock_timestamp() AS time').fetchone()['time'].isoformat()
    items = [row['payload'] for row in rows]
    watermark = control['coverage_observed_through']
    from .event_contract import timestamp
    healthy = (control['coverage_verified'] and watermark is not None and watermark <= timestamp(now)
               and (timestamp(now) - watermark).total_seconds() <= recipe['definition']['maximum_observation_lag_seconds'])
    supported = bool(healthy and recipe['definition']['coverage_supported'] and all(
        item['source']['language'] in recipe['definition']['supported_languages'] for item in items)
    )
    return build_snapshot(event_id=str(event['id']), generation=event['generation'], recipe_id=recipe['id'],
        s3_control_generation=_pair(upstream['serving_generation'], sr['serving_generation']),
        s4_control_generation=control['generation'], member_generation=event['member_generation'], as_of=now,
        evidence=items, coverage={'complete': bool(healthy), 'supported': supported,
                                 'observed_through': watermark.isoformat() if watermark else '1970-01-01T00:00:00+00:00'},
        support_policy=recipe['definition']['support_policy'])


def _validate_dependencies(conn, frozen, upstream, control, recipe, sr):
    if (frozen['s3_control_generation'] != _pair(upstream['serving_generation'], sr['serving_generation'])
        or frozen['s4_control_generation'] != control['generation']):
        raise StaleInput('control_changed')
    if frozen['coverage']['complete'] and not control['coverage_verified']:
        raise StaleInput('coverage_revoked')
    event = conn.execute('SELECT * FROM public.events WHERE id=%s', (frozen['event_id'],)).fetchone()
    if not event or event['generation'] != frozen['generation'] or event['member_generation'] != frozen['member_generation'] or event['lifecycle'] == 'merged':
        raise StaleInput('event_changed')
    stored = conn.execute('SELECT evidence_id,dependency,payload FROM public.event_evidence WHERE event_id=%s AND active ORDER BY evidence_id', (event['id'],)).fetchall()
    expected = {item['id']: item for item in frozen['evidence']}
    if len(stored) != len(expected) or any(r['evidence_id'] not in expected or r['payload'] != expected[r['evidence_id']] for r in stored):
        raise StaleInput('member_manifest_changed')
    cache = {}
    for item in frozen['evidence']:
        dep = item['dependency']; article = dep['article_id']
        if article not in cache:
            bundle, current = _current(conn, article, sr['id'])
            source, generation = _source(conn, article)
            cache[article] = bundle, current, source, generation
        bundle, current, source, generation = cache[article]
        article_row = conn.execute('SELECT canonical_source_domain FROM public.articles WHERE id=%s', (article,)).fetchone()
        if (article_row['canonical_source_domain'] or '') != source['source_domain']:
            raise StaleInput('source_domain_changed')
        if (dep['source_id'] != source['id'] or dep['source_generation'] != generation
            or item['source'] != source['metadata'] or dep['s3_recipe_id'] != sr['id']
            or dep['facets_result_id'] != str(current['facets']['result_id'])
            or dep['embedding_result_id'] != str(current['embedding']['result_id'])):
            raise StaleInput('dependency_changed')
        hints = current['facets']['payload']['event_hints']
        if item['hint_index'] >= len(hints) or item['hint_hash'] != digest(hints[item['hint_index']]):
            raise StaleInput('mention_changed')
        validate_original_spans(item, bundle)
    return event


def prepare(conn, job):
    with conn.transaction():
        upstream, control, recipe, _ = _controls(conn, job['recipe_id'], lock=True)
        ids = [row['article_id'] for row in conn.execute('SELECT DISTINCT article_id FROM public.event_evidence WHERE event_id=%s AND active', (job['subject_id'],)).fetchall()]
        sr = _lock_inputs(conn, ids, recipe['definition']['s3_recipe_id'])
        event = conn.execute('SELECT * FROM public.events WHERE id=%s FOR UPDATE', (job['subject_id'],)).fetchone()
        _job(conn, job)
        if not event or str(event['generation']) != job['revision']:
            _finish(conn, job, 'superseded', 'input_changed'); return None
        frozen = _snapshot(conn, event, upstream, control, recipe, sr)
        if {e['dependency']['article_id'] for e in frozen['evidence']} - {str(value) for value in ids}:
            raise StaleInput('prepare_discovery_changed')
        _validate_dependencies(conn, frozen, upstream, control, recipe, sr)
        identifier = snapshot_hash(frozen)
        conn.execute('''INSERT INTO public.event_snapshots(id,event_id,generation,payload,dependency_digest,dependency_count)
          VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
          (identifier, event['id'], event['generation'], Jsonb(frozen), frozen['dependency_digest'], len(frozen['evidence'])))
        conn.execute('UPDATE public.event_jobs SET snapshot_id=%s,input_hash=%s WHERE id=%s', (identifier, identifier, job['id']))
    return frozen


def refinement_inputs(conn, job, frozen):
    if len(frozen['evidence']) != 1:
        raise StaleInput('refinement_requires_one_mention')
    item = frozen['evidence'][0]
    bundle, _ = _current(conn, item['dependency']['article_id'], item['dependency']['s3_recipe_id'])
    validate_original_spans(item, bundle)
    return item, bundle


def publish_refinement(conn, job, frozen, payload):
    from .event_refinement import prepare_input, validate_refinement
    frozen = validate_snapshot(frozen)
    try:
        with conn.transaction():
            upstream, control, recipe, _ = _controls(conn, job['recipe_id'], lock=True)
            sr = _lock_inputs(conn, [e['dependency']['article_id'] for e in frozen['evidence']], recipe['definition']['s3_recipe_id'])
            event = conn.execute('SELECT * FROM public.events WHERE id=%s FOR UPDATE', (job['subject_id'],)).fetchone()
            conn.execute('SELECT id FROM public.event_developments WHERE event_id=%s ORDER BY id FOR UPDATE', (event['id'],)).fetchall()
            current = _job(conn, job)
            if current['snapshot_id'] != snapshot_hash(frozen):
                raise StaleInput('snapshot_changed')
            _validate_dependencies(conn, frozen, upstream, control, recipe, sr)
            evidence, bundle = refinement_inputs(conn, job, frozen)
            checked = validate_refinement(payload['refinement'], prepare_input(evidence, bundle))
            if checked != payload:
                raise ValueError('refinement_provenance_mismatch')
            refined = checked['evidence']
            from .event_delta import claim_fingerprint
            fingerprint = claim_fingerprint(refined['claim'])
            existing_development = conn.execute('SELECT id FROM public.event_developments WHERE event_id=%s AND fingerprint=%s',
                                                (event['id'], fingerprint)).fetchone()
            link = conn.execute('SELECT development_id FROM public.event_evidence WHERE event_id=%s AND evidence_id=%s',
                                (event['id'], refined['id'])).fetchone()
            if existing_development:
                conn.execute('UPDATE public.event_evidence SET development_id=%s WHERE event_id=%s AND evidence_id=%s',
                             (existing_development['id'], event['id'], refined['id']))
            else:
                # Refined factual state gets immutable version history. A later
                # source/control refresh preserves this identity and version.
                version = conn.execute('UPDATE public.event_developments SET fingerprint=%s,version=version+1 WHERE id=%s RETURNING version',
                                       (fingerprint, link['development_id'])).fetchone()['version']
                conn.execute('''INSERT INTO public.development_versions(development_id,version,claim_hash,change_kind)
                  VALUES(%s,%s,%s,'refined')''', (link['development_id'], version, digest(refined['claim'])))
            conn.execute('''INSERT INTO public.event_refinements(event_id,evidence_id,input_hash,recipe_id,payload)
              VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
              (event['id'], refined['id'], checked['input_hash'], recipe['id'], Jsonb(checked)))
            conn.execute('UPDATE public.event_evidence SET payload=%s,refined=true WHERE event_id=%s AND evidence_id=%s',
                         (Jsonb(refined), event['id'], refined['id']))
            updated = _dirty(conn, event['id'], 'evidence_refined')
            _schedule(conn, recipe['id'], 'group', event['id'], updated['generation'], job['source_key'])
            _finish(conn, job)
        return True
    except LeaseLost:
        return False


def group(conn, job):
    """Conservative exact-identity grouping, enabled only by a calibrated recipe.

    Bounded candidate discovery is diagnostic until quality approval. A match
    merges stable event IDs by redirect and preserves both development histories.
    Topic adjacency and cosine never authorize this merge.
    """
    from .event_grouping import relation
    discovery = conn.execute('''SELECT e.id,e.generation,ee.payload FROM public.events e
      JOIN public.event_evidence ee ON ee.event_id=e.id AND ee.active AND ee.refined
      WHERE e.id=%s AND e.lifecycle<>'merged' ORDER BY ee.evidence_id''', (job['subject_id'],)).fetchall()
    if not discovery:
        fail(conn, job, 'input_changed'); return False
    query = discovery[0]['payload']
    definition = job['definition']
    candidates = []
    if definition['grouping_calibrated']:
        # Exact action/object recall is deliberately limited v1, not hybrid recall
        # certification. Overfull candidates abstain, never choose a truncated winner.
        candidates = conn.execute('''SELECT e.id,e.generation,ee.payload FROM public.events e
          JOIN public.event_evidence ee ON ee.event_id=e.id AND ee.active AND ee.refined
          WHERE e.recipe_id=%s AND e.id<>%s AND e.lifecycle<>'merged'
            AND lower(ee.payload->'claim'->>'action')=lower(%s)
            AND lower(ee.payload->'claim'->>'object')=lower(%s)
          ORDER BY e.id,ee.evidence_id LIMIT 129''',
          (job['recipe_id'], job['subject_id'], query['claim']['action'], query['claim']['object'])).fetchall()
    matches = [row for row in candidates if relation(query, row['payload'], calibrated=True)['relation'] == 'same_development'] if len(candidates) <= 128 else []
    target_ids = sorted({row['id'] for row in matches}, key=str)
    # Several existing duplicates need explicit reconciliation, not a greedy chain.
    target = target_ids[0] if len(target_ids) == 1 else None
    event_ids = sorted({job['subject_id']} | ({target} if target else set()), key=str)
    dependencies = conn.execute('SELECT DISTINCT article_id FROM public.event_evidence WHERE event_id=ANY(%s) AND active', (event_ids,)).fetchall()
    try:
        with conn.transaction():
            upstream, control, recipe, _ = _controls(conn, job['recipe_id'], lock=True)
            sr = _lock_inputs(conn, [r['article_id'] for r in dependencies], recipe['definition']['s3_recipe_id'])
            events = conn.execute('SELECT * FROM public.events WHERE id=ANY(%s) ORDER BY id FOR UPDATE', (event_ids,)).fetchall()
            conn.execute('SELECT id FROM public.event_developments WHERE event_id=ANY(%s) ORDER BY id FOR UPDATE', (event_ids,)).fetchall()
            _job(conn, job)
            by_id = {r['id']: r for r in events}
            event = by_id.get(job['subject_id'])
            if not event or str(event['generation']) != job['revision'] or event['lifecycle'] == 'merged':
                _finish(conn, job, 'superseded', 'input_changed'); return False
            # Snapshot validation rejects missing/changed evidence on either side.
            locked_articles = {str(r['article_id']) for r in dependencies}
            for row in events:
                snapshot = _snapshot(conn, row, upstream, control, recipe, sr)
                if {e['dependency']['article_id'] for e in snapshot['evidence']} - locked_articles:
                    raise StaleInput('group_discovery_changed')
                _validate_dependencies(conn, snapshot, upstream, control, recipe, sr)
            if target:
                # Canonical minimum stable ID makes opposite workers converge; no cycle.
                winner, loser = min(event_ids, key=str), max(event_ids, key=str)
                actual = conn.execute('SELECT payload FROM public.event_evidence WHERE event_id=ANY(%s) AND active ORDER BY evidence_id', (event_ids,)).fetchall()
                if len(actual) > recipe['definition']['maximum_evidence'] or any(
                    relation(query, r['payload'], calibrated=True)['relation'] != 'same_development' for r in actual):
                    target = None
                else:
                    # Keep old links as content-free tombstones. Stable development IDs
                    # remain available in lineage; one canonical development serves copies.
                    canonical = conn.execute('''SELECT DISTINCT d.id,d.version FROM public.event_developments d
                      JOIN public.event_evidence ee ON ee.development_id=d.id
                      WHERE ee.event_id=%s AND ee.active AND ee.refined ORDER BY d.id LIMIT 1''', (winner,)).fetchone()
                    aliases = conn.execute('''SELECT DISTINCT d.id,d.version FROM public.event_developments d
                      JOIN public.event_evidence ee ON ee.development_id=d.id
                      WHERE ee.event_id=%s AND ee.active''', (loser,)).fetchall()
                    for alias in aliases:
                        conn.execute('''INSERT INTO public.event_development_aliases(development_id,version,target_id,target_version)
                          VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                          (alias['id'], alias['version'], canonical['id'], canonical['version']))
                    conn.execute('''INSERT INTO public.event_evidence(event_id,evidence_id,development_id,article_id,dependency,payload,active,refined)
                      SELECT %s,evidence_id,%s,article_id,dependency,payload,true,refined FROM public.event_evidence
                      WHERE event_id=%s AND active ON CONFLICT(event_id,evidence_id) DO UPDATE
                      SET development_id=EXCLUDED.development_id,dependency=EXCLUDED.dependency,payload=EXCLUDED.payload,
                          active=true,refined=EXCLUDED.refined''', (winner, canonical['id'], loser))
                    conn.execute('UPDATE public.event_evidence SET active=false,payload=NULL WHERE event_id=%s', (loser,))
                    lost = _dirty(conn, loser, 'merged')
                    conn.execute("UPDATE public.events SET lifecycle='merged',redirect_id=%s WHERE id=%s", (winner, loser))
                    conn.execute('UPDATE public.event_changes SET details=%s WHERE event_id=%s AND generation=%s',
                                 (Jsonb({'redirect_id': str(winner)}), loser, lost['generation']))
                    event = _dirty(conn, winner, 'merged_evidence')
            _schedule(conn, job['recipe_id'], 'assess', event['id'], event['generation'], job['source_key'])
            _finish(conn, job)
        return True
    except LeaseLost:
        return False


def reserve(conn, job, amount, request_hash):
    amount = _money(amount)
    if amount <= 0 or not isinstance(request_hash, str) or len(request_hash) != 64 or any(c not in '0123456789abcdef' for c in request_hash):
        raise ValueError('positive priced request required')
    with conn.transaction():
        upstream = conn.execute('SELECT * FROM public.understanding_control FOR SHARE').fetchone()
        control = conn.execute('SELECT * FROM public.event_control FOR UPDATE').fetchone()
        recipe = conn.execute('SELECT * FROM public.event_recipes WHERE id=%s FOR SHARE', (job['recipe_id'],)).fetchone()
        if not recipe or not recipe['enabled']:
            return None
        sr = conn.execute('SELECT * FROM public.understanding_recipes WHERE id=%s FOR SHARE',
                          (recipe['definition']['s3_recipe_id'],)).fetchone()
        if not sr or not sr['enabled'] or not sr['approved'] or upstream['serving_recipe'] != sr['id']:
            return None
        usage = conn.execute('''SELECT COALESCE(sum(CASE WHEN settled THEN actual_usd ELSE reserved_usd END)
          FILTER(WHERE day=(clock_timestamp() AT TIME ZONE 'UTC')::date),0) AS daily,
          COALESCE(sum(CASE WHEN settled THEN actual_usd ELSE reserved_usd END),0) AS monthly
          FROM public.event_spend WHERE day>=date_trunc('month',clock_timestamp() AT TIME ZONE 'UTC')::date''').fetchone()
        if (not control['submissions_enabled'] or control['circuit_until'] and control['circuit_until'] > datetime.now(timezone.utc)
            or usage['daily'] + amount > control['daily_budget_usd'] or usage['monthly'] + amount > control['monthly_budget_usd']):
            return None
        # Read-only job check; do not acquire a job lock after spend controls.
        active = conn.execute('''SELECT j.snapshot_id,s.payload AS snapshot FROM public.event_jobs j
          LEFT JOIN public.event_snapshots s ON s.id=j.snapshot_id WHERE j.id=%s AND j.state='running' AND j.lease_token=%s
          AND j.lease_until>clock_timestamp() AND j.deadline>clock_timestamp()''', (job['id'], job['lease_token'])).fetchone()
        if not active:
            return None
        if active['snapshot_id'] is not None:
            frozen = active['snapshot']
            if (frozen is None or frozen['s4_control_generation'] != control['generation']
                or frozen['s3_control_generation'] != _pair(upstream['serving_generation'], sr['serving_generation'])):
                return None
        identifier = uuid.uuid4()
        inserted = conn.execute('''INSERT INTO public.event_spend(id,job_id,attempt,stage,request_hash,reserved_usd)
          VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(job_id,attempt) DO NOTHING''',
          (identifier, job['id'], job['attempts'], job['stage'], request_hash, amount)).rowcount
        # A duplicate attempt must never dispatch again, even after a crash.
        return identifier if inserted else None


def settle(conn, reservation, actual, request_id=None):
    actual = _money(actual)
    with conn.transaction():
        # Same control→ledger order as reservations; ambiguous attempts stay held.
        conn.execute('SELECT singleton FROM public.event_control FOR UPDATE')
        row = conn.execute('SELECT * FROM public.event_spend WHERE id=%s FOR UPDATE', (reservation,)).fetchone()
        if not row:
            raise ValueError('unknown reservation')
        if row['settled']:
            if row['actual_usd'] != actual:
                raise ValueError('conflicting settlement')
            return
        conn.execute('UPDATE public.event_spend SET actual_usd=%s,settled=true,request_id=%s WHERE id=%s', (actual, request_id, reservation))
        if actual > row['reserved_usd']:
            conn.execute("UPDATE public.event_control SET submissions_enabled=false,delivery_enabled=false,generation=generation+1,circuit_reason='estimate_exceeded'")


def publish(conn, job, frozen, payload):
    frozen = validate_snapshot(frozen)
    result = validate_assessment(payload, frozen)
    try:
        with conn.transaction():
            upstream, control, recipe, _ = _controls(conn, job['recipe_id'], lock=True)
            sr = _lock_inputs(conn, [e['dependency']['article_id'] for e in frozen['evidence']], recipe['definition']['s3_recipe_id'])
            conn.execute('SELECT id FROM public.events WHERE id=%s FOR UPDATE', (job['subject_id'],)).fetchone()
            current = _job(conn, job)
            if current['snapshot_id'] != snapshot_hash(frozen):
                raise StaleInput('snapshot_changed')
            event = _validate_dependencies(conn, frozen, upstream, control, recipe, sr)
            now = conn.execute('SELECT clock_timestamp() AS time').fetchone()['time']
            validate_assessment(result, frozen, now=now)
            identifier = uuid.uuid4()
            conn.execute('''INSERT INTO public.event_assessments(id,event_id,snapshot_id,recipe_id,generation,payload,valid_until)
              VALUES(%s,%s,%s,%s,%s,%s,%s)''',
              (identifier, event['id'], current['snapshot_id'], recipe['id'], event['generation'], Jsonb(result), result['valid_until']))
            conn.execute('UPDATE public.events SET current_assessment=%s,lifecycle=%s WHERE id=%s',
                         (identifier, 'active' if result['status'] == 'ready' else 'inactive', event['id']))
            conn.execute("INSERT INTO public.event_outbox(event_id,generation,kind) VALUES(%s,%s,'assessed')", (event['id'], event['generation']))
            _finish(conn, job)
        return True
    except LeaseLost:
        return False


def load_candidates(conn, *, limit=64, in_snapshot=False):
    """Coherent authorization snapshot; no persistent priority cache to race.

    Requires a fresh autocommit connection. Callers serialize S2 article bodies
    separately and keep this private DTO out of the public API.
    """
    _limit(limit, 128)
    from contextlib import nullcontext
    if in_snapshot:
        state = conn.execute("SELECT current_setting('transaction_isolation') AS isolation,current_setting('transaction_read_only') AS readonly").fetchone()
        if state != {'isolation': 'repeatable read', 'readonly': 'on'}:
            raise RuntimeError('S4 authorization requires a coherent readonly snapshot')
    elif not conn.autocommit or conn.info.transaction_status != 0:
        raise RuntimeError('S4 authorization requires a fresh transaction')
    output = []
    with nullcontext() if in_snapshot else conn.transaction():
        if not in_snapshot:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        c = conn.execute('SELECT * FROM public.event_control').fetchone()
        if not c['delivery_enabled'] or not c['serving_recipe']:
            return []
        try:
            upstream, control, recipe, sr = _controls(conn, c['serving_recipe'])
        except StaleInput:
            return []
        if not recipe['approved']:
            return []
        now = conn.execute('SELECT clock_timestamp() AS time').fetchone()['time']
        rows = conn.execute('''SELECT a.id AS assessment_id,a.payload,s.payload AS snapshot,e.id AS event_id
          FROM public.events e JOIN public.event_assessments a ON a.id=e.current_assessment
          JOIN public.event_snapshots s ON s.id=a.snapshot_id
          WHERE e.recipe_id=%s AND e.lifecycle='active' AND a.valid_until>%s
          ORDER BY CASE a.payload->>'tier' WHEN 'world_critical' THEN 0 WHEN 'major' THEN 1 ELSE 2 END,
                   a.created_at DESC,e.id LIMIT %s''', (recipe['id'], now, limit)).fetchall()
        for row in rows:
            frozen = row['snapshot']
            if frozen is None:
                continue
            try:
                validate_assessment(row['payload'], frozen, now=now)
                _validate_dependencies(conn, frozen, upstream, control, recipe, sr)
                # Explicit observation age: a quiet/stalled pipeline does not renew validity.
                from .event_contract import timestamp
                if (now - timestamp(frozen['coverage']['observed_through'])).total_seconds() > recipe['definition']['maximum_observation_lag_seconds']:
                    continue
            except (StaleInput, ValueError):
                continue
            links = conn.execute('''SELECT ee.*,d.version AS development_version FROM public.event_evidence ee
              JOIN public.event_developments d ON d.id=ee.development_id WHERE ee.event_id=%s AND ee.active''', (row['event_id'],)).fetchall()
            for dev in sorted({r['development_id'] for r in links}, key=str):
                representatives = []
                version = None
                for link in links:
                    if link['development_id'] != dev:
                        continue
                    article = conn.execute('''SELECT a.*,artifact.kind AS artifact_kind,artifact.method AS artifact_method,
                      artifact.origin_url AS artifact_origin_url,artifact.fetched_at AS artifact_fetched_at,
                      artifact.extractor_version AS artifact_extractor_version,artifact.completeness AS artifact_completeness,
                      artifact.confidence AS artifact_confidence,artifact.content_hash AS artifact_content_hash
                      FROM public.articles a LEFT JOIN public.article_content_artifacts artifact
                        ON artifact.id=a.display_content_artifact_id AND artifact.article_id=a.id WHERE a.id=%s''', (link['article_id'],)).fetchone()
                    if article is None:
                        continue
                    article = dict(article); article['id'] = str(article['id'])
                    if article.get('source_id') is not None:
                        article['source_id'] = str(article['source_id'])
                    _, card = _current(conn, link['article_id'], sr['id'])
                    topics = [topic['topic_id'] for topic in card['facets']['payload']['topics']]
                    version = link['development_version']
                    representatives.append({'article': article, 'role': link['payload']['role'], 'development_id': str(dev),
                        'development_version': version, 'eligible': not article['analysis_revoked'],
                        'source_id': link['payload']['dependency']['source_id'], 'topic_ids': topics,
                        'publisher_source_id': article.get('source_id') or article.get('canonical_source_domain'),
                        'language': link['payload']['source']['language']})
                output.append({'snapshot': frozen, 'assessment': row['payload'], 'assessment_id': str(row['assessment_id']),
                    'development_id': str(dev), 'development_version': version, 'representatives': representatives})
                if len(output) >= 128:
                    return output
    return output


def status(conn):
    check_schema(conn)
    return {'control': conn.execute('SELECT * FROM public.event_control').fetchone(),
        'jobs': conn.execute('SELECT stage,state,count(*) AS count FROM public.event_jobs GROUP BY stage,state ORDER BY stage,state').fetchall(),
        'spend': conn.execute('''SELECT day,sum(CASE WHEN settled THEN actual_usd ELSE reserved_usd END) AS accounted_usd,
          count(*) FILTER(WHERE NOT settled) AS unresolved FROM public.event_spend GROUP BY day ORDER BY day DESC LIMIT 32''').fetchall()}


def set_coverage(conn, *, observed_through, verified, expected_generation, reviewed_by):
    """Explicit attestation supplied by upstream operations, never assessment time.

    V1 does not implement an S1 coverage monitor. Until that integration is
    verified, leave this unset. False/old coverage always fails ready publication.
    """
    from .event_contract import timestamp
    _generation(expected_generation)
    if type(verified) is not bool or not isinstance(reviewed_by, str) or not reviewed_by.strip():
        raise ValueError('explicit coverage attestation required')
    when = timestamp(observed_through) if observed_through is not None else None
    if verified and (when is None or when > datetime.now(timezone.utc)):
        raise ValueError('valid upstream observation time required')
    with conn.transaction():
        control = conn.execute('SELECT * FROM public.event_control FOR UPDATE').fetchone()
        if control['generation'] != expected_generation:
            raise StaleInput('control_generation_changed')
        conn.execute('''UPDATE public.event_control SET coverage_verified=%s,coverage_observed_through=%s,
          generation=generation+1,updated_at=clock_timestamp()''', (verified, when))
        conn.execute("INSERT INTO public.event_upstream_notices(kind,identity,generation) VALUES('coverage',%s,%s)",
                     (reviewed_by, expected_generation + 1))


def registry_digest(conn):
    rows = conn.execute('SELECT id,generation,source_domain,metadata FROM public.event_source_registry ORDER BY id').fetchall()
    return digest(rows)


def validate_operations(operations):
    if not isinstance(operations, dict):
        raise ValueError('reviewed operational evidence required')
    import re
    if (not isinstance(operations.get('build_sha'), str) or not re.fullmatch('[0-9a-f]{40}', operations['build_sha'])
        or operations.get('schema_version') != SCHEMA_VERSION or type(operations['schema_version']) is not int):
        raise ValueError('exact build and schema evidence required')
    for key in ('s1_s2_s3_verified','hosted_postgres_passed','no_skipped_database_tests','rollback_verified',
                'reader_policy_verified','budget_verified','source_policy_verified','independent_review_approved'):
        if operations.get(key) is not True:
            raise ValueError('operational gate missing: ' + key)
    for key, minimum in (('load_multiplier', 2), ('observation_hours', 72)):
        value = operations.get(key)
        if type(value) not in (int, float) or not minimum <= value < float('inf'):
            raise ValueError('operational minimum missing: ' + key)
    for key in ('stale_publications','lost_invalidations','hard_policy_bypasses','unaccounted_requests','wrong_representatives'):
        if type(operations.get(key)) is not int or operations[key] != 0:
            raise ValueError('integrity failures: ' + key)
    for key in ('approved_by','verification_run','rollback_run'):
        if not isinstance(operations.get(key), str) or not operations[key].strip():
            raise ValueError('reviewed evidence reference missing: ' + key)


def promote(conn, recipe_id, *, report, expected_bindings, operations, expected_generation):
    # Tooling runs from the reviewed backend checkout/image; no report downloads.
    from evals.events import validate_promotion
    _generation(expected_generation)
    validate_promotion(report, expected_bindings)
    validate_operations(operations)
    with conn.transaction():
        upstream = conn.execute('SELECT * FROM public.understanding_control FOR SHARE').fetchone()
        control = conn.execute('SELECT * FROM public.event_control FOR UPDATE').fetchone()
        if control['generation'] != expected_generation:
            raise StaleInput('control_generation_changed')
        recipe = conn.execute('SELECT * FROM public.event_recipes WHERE id=%s FOR UPDATE', (recipe_id,)).fetchone()
        if not recipe or not recipe['enabled']:
            raise ValueError('enabled recipe required')
        definition = recipe['definition']
        if (expected_bindings['recipe_sha256'] != recipe_id or expected_bindings['s3_recipe_sha256'] != definition['s3_recipe_id']
            or upstream['serving_recipe'] != definition['s3_recipe_id']
            or expected_bindings['source_registry_sha256'] != registry_digest(conn)):
            raise ValueError('live input binding mismatch')
        if not definition['coverage_supported'] or not definition['grouping_calibrated'] or not definition['supported_languages']:
            raise ValueError('uncalibrated or unsupported recipe')
        if not 0 < control['daily_budget_usd'] <= control['monthly_budget_usd']:
            raise ValueError('explicit production budgets required')
        from .event_provider import validate_recipe
        validate_recipe(definition['provider'], stage='assessment')
        validate_recipe(definition['refinement_provider'], stage='refinement')
        conn.execute('UPDATE public.event_recipes SET approved=true,evaluation=%s WHERE id=%s',
                     (Jsonb({'quality': report, 'operations': operations}), recipe_id))
        conn.execute('''UPDATE public.event_control SET serving_recipe=%s,delivery_enabled=false,
          generation=generation+1,updated_at=clock_timestamp()''', (recipe_id,))
        conn.execute("INSERT INTO public.event_upstream_notices(kind,identity,generation) VALUES('promotion',%s,%s)", (recipe_id, expected_generation + 1))


def replay(conn, job_id, *, expected_generation):
    # Administration and subject work are distinct transactions: no exclusive
    # control lock may subsequently acquire article/event/job locks.
    _generation(expected_generation)
    control = conn.execute('SELECT generation FROM public.event_control').fetchone()
    if control['generation'] != expected_generation:
        raise StaleInput('control_generation_changed')
    job = conn.execute('SELECT * FROM public.event_jobs WHERE id=%s', (job_id,)).fetchone()
    if not job or job['state'] not in ('failed_terminal', 'quarantined', 'insufficient', 'unsupported', 'superseded'):
        raise ValueError('terminal job required for explicit replay')
    with conn.transaction():
        # Read/share controls in the ordinary publication order, never upgrade.
        _controls(conn, job['recipe_id'], lock=True)
        if conn.execute('SELECT generation FROM public.event_control').fetchone()['generation'] != expected_generation:
            raise StaleInput('control_generation_changed')
        if job['stage'] == 'ingest':
            return _schedule(conn, job['recipe_id'], 'ingest', job['subject_id'], 'replay:' + str(uuid.uuid4()), job['source_key'])
        event = conn.execute('SELECT * FROM public.events WHERE id=%s FOR UPDATE', (job['subject_id'],)).fetchone()
        if not event or event['lifecycle'] == 'merged':
            raise ValueError('replay the source intake for merged events')
        event = _dirty(conn, event['id'], 'manual_replay')
        return _schedule(conn, job['recipe_id'], job['stage'], event['id'], event['generation'], job['source_key'])
