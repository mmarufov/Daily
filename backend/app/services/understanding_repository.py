"""S3 durable state. Network work must never run within these transactions.

Article -> job -> projection/cluster is the write lock order. Claims/reapers lock
jobs only, commit, and never acquire an article lock afterwards. All serving reads
fence revision, analysis eligibility, enabled recipe AND the recomputed input hash.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, ROUND_CEILING
from functools import wraps
from pathlib import Path

from psycopg.types.json import Jsonb


class _LeaseLost(Exception):
    """Abort the entire publication transaction, including projection events."""


def lease_fenced(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except _LeaseLost:
            return False
    return guarded


def ensure_schema(conn):
    with conn.transaction():
        conn.execute(Path(__file__).with_name('understanding_schema.sql').read_text())


def check_schema(conn):
    row = conn.execute("""SELECT to_regclass('public.article_understanding_current') IS NOT NULL
      AND to_regprocedure('public.s3_revision_guard()') IS NOT NULL AS ready""").fetchone()
    if not row or not row['ready']:
        raise RuntimeError('S3 migration is required before enabling S3')


def register_recipe(conn, definition, *, enabled=False):
    from app.services.understanding_contract import DEFAULT_RECIPE
    if definition.get('dimensions') != 1536 or definition.get('embedding_model') != 'text-embedding-3-small':
        raise ValueError('this schema supports only the v1 embedding space')
    for field in ('schema_hash','taxonomy_hash','input_version','prompt_version','linker_version',
                  'document_recipe','query_recipe'):
        if definition.get(field) != DEFAULT_RECIPE[field]:
            raise ValueError('recipe is incompatible with this worker: '+field)
    identifier = hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(',', ':'),
                                         ensure_ascii=False).encode()).hexdigest()
    with conn.transaction():
        conn.execute("""INSERT INTO public.understanding_recipes(id,definition,enabled)
          VALUES(%s,%s,%s) ON CONFLICT(id) DO NOTHING""", (identifier, Jsonb(definition), enabled))
        row = conn.execute('SELECT definition FROM public.understanding_recipes WHERE id=%s',
                           (identifier,)).fetchone()
        if row['definition'] != definition:
            raise ValueError('immutable recipe mismatch')
    return identifier


def set_recipe_enabled(conn, recipe_id, enabled):
    with conn.transaction():
        conn.execute('SELECT singleton FROM public.understanding_control FOR UPDATE')
        if not enabled:
            conn.execute("""UPDATE public.understanding_control SET serving_recipe=NULL
              WHERE serving_recipe=%s""", (recipe_id,))
        changed = conn.execute('UPDATE public.understanding_recipes SET enabled=%s WHERE id=%s',
                               (enabled, recipe_id)).rowcount
        if not changed:
            raise ValueError('unknown recipe')


def configure(conn, *, submissions_enabled, daily_budget_usd):
    budget = _money(daily_budget_usd)
    if submissions_enabled and budget <= 0:
        raise ValueError('enabled submissions require an explicit positive daily budget')
    with conn.transaction():
        conn.execute("""UPDATE public.understanding_control SET submissions_enabled=%s,
          daily_budget_usd=%s,updated_at=now()""", (submissions_enabled, budget))


def _money(value):
    d = Decimal(str(value))
    if not d.is_finite() or d < 0:
        raise ValueError('invalid monetary amount')
    return d.quantize(Decimal('0.00000001'), rounding=ROUND_CEILING)


def reconcile(conn, recipe_id, *, limit=100, after=None):
    """Bounded UUID cursor; repeat from the beginning to heal missed schedules.

    Locks articles before inserting jobs, so a correction cannot race scheduling
    for the old revision. Existing terminal jobs stay terminal until explicit replay.
    """
    limit = max(1, min(int(limit), 1000))
    with conn.transaction():
        recipe = conn.execute('SELECT enabled FROM public.understanding_recipes WHERE id=%s',
                              (recipe_id,)).fetchone()
        if not recipe or not recipe['enabled']:
            raise ValueError('recipe is not enabled for computation')
        rows = conn.execute("""SELECT a.id,a.semantic_revision,a.analysis_eligibility_generation,
            COALESCE(a.canonical_source_domain,a.source_name,'unknown') AS source_key,
            COALESCE(a.ingested_at,now()) > now()-interval '1 day' AS fresh
          FROM public.articles a WHERE NOT a.analysis_revoked
            AND (%s::uuid IS NULL OR a.id > %s::uuid)
          ORDER BY a.id LIMIT %s FOR UPDATE OF a""", (after, after, limit)).fetchall()
        inserted = 0
        for row in rows:
            inserted += conn.execute("""INSERT INTO public.article_understanding_jobs
              (article_id,semantic_revision,eligibility_generation,recipe_id,stage,source_key,fresh)
              SELECT %s,%s,%s,%s,s,%s,%s FROM unnest(ARRAY['facets','embedding']) s
              ON CONFLICT DO NOTHING""", (row['id'], row['semantic_revision'],
              row['analysis_eligibility_generation'], recipe_id, row['source_key'], row['fresh'])).rowcount
    return {'scanned': len(rows), 'inserted': inserted,
            'next_cursor': str(rows[-1]['id']) if rows else None}


def reap(conn):
    with conn.transaction():
        return conn.execute("""UPDATE public.article_understanding_jobs
          SET state=CASE WHEN attempts>=5 OR deadline<=now() THEN 'failed_terminal' ELSE 'retry_wait' END,
              failure_reason=CASE WHEN deadline<=now() THEN 'deadline_exceeded' ELSE 'lease_expired' END,
              lease_token=NULL,lease_until=NULL,retry_at=now()+interval '30 seconds',updated_at=now()
          WHERE (state='running' AND lease_until<=now())
             OR (state IN ('pending','retry_wait') AND deadline<=now())""").rowcount


def claim(conn, *, limit=4, fresh=True, lease_seconds=120):
    limit = max(1, min(int(limit), 20))
    lease_seconds = max(60, min(int(lease_seconds), 600))
    with conn.transaction():
        # Window ranking chooses one due job per source before a second from a firehose.
        rows = conn.execute("""WITH eligible AS (
          SELECT j.id,row_number() OVER(PARTITION BY source_key ORDER BY retry_at,j.id) AS source_rank
          FROM public.article_understanding_jobs j JOIN public.understanding_recipes r ON r.id=j.recipe_id
          CROSS JOIN public.understanding_control c
          WHERE r.enabled AND c.submissions_enabled AND (c.circuit_until IS NULL OR c.circuit_until<=now())
            AND j.state IN ('pending','retry_wait') AND j.retry_at<=now() AND j.deadline>now()
            AND j.attempts<5 AND j.fresh=%s
        ) SELECT j.*,r.definition FROM public.article_understanding_jobs j
          JOIN eligible e ON e.id=j.id JOIN public.understanding_recipes r ON r.id=j.recipe_id
          ORDER BY e.source_rank,j.retry_at,j.id LIMIT %s FOR UPDATE OF j SKIP LOCKED""",
          (fresh, limit)).fetchall()
        for row in rows:
            token = uuid.uuid4()
            conn.execute("""UPDATE public.article_understanding_jobs SET state='running',attempts=attempts+1,
              lease_token=%s,lease_until=now()+(%s * interval '1 second'),updated_at=now() WHERE id=%s""",
              (token, lease_seconds, row['id']))
            row.update(lease_token=token, attempts=row['attempts']+1)
    return rows


def evidence_for_article(conn, article_id, *, lock=False):
    from app.services.understanding_contract import build_evidence
    row = conn.execute('SELECT * FROM public.articles WHERE id=%s' + (' FOR UPDATE' if lock else ''),
                       (article_id,)).fetchone()
    if not row or row.get('analysis_revoked'):
        return None
    artifact = None
    if row.get('analysis_content_artifact_id'):
        artifact = conn.execute('SELECT * FROM public.article_content_artifacts WHERE id=%s AND article_id=%s',
                                (row['analysis_content_artifact_id'], article_id)).fetchone()
    return build_evidence(row, artifact)


def prepare(conn, job):
    with conn.transaction():
        bundle = evidence_for_article(conn, job['article_id'], lock=True)
        if not bundle or bundle['semantic_revision'] != job['semantic_revision'] or \
                bundle['analysis_eligibility_generation'] != job['eligibility_generation']:
            _finish_job(conn, job, 'superseded', 'input_changed')
            return None
        current = _locked_job(conn, job)
        if current is None:
            return None
        if not bundle['sufficient']:
            _finish_job(conn, job, 'insufficient', 'no_attributable_evidence')
            return None
        conn.execute('UPDATE public.article_understanding_jobs SET input_hash=%s WHERE id=%s',
                     (bundle['input_hash'], job['id']))
        job['input_hash'] = bundle['input_hash']
        return bundle


def _locked_job(conn, job):
    # Hold a recipe share lock through publication so disabling computation cannot
    # race a stale worker's final CAS. Recipe operations never lock articles/jobs.
    recipe = conn.execute('SELECT enabled FROM public.understanding_recipes WHERE id=%s FOR SHARE',
                          (job['recipe_id'],)).fetchone()
    if not recipe or not recipe['enabled']:
        return None
    return conn.execute("""SELECT j.* FROM public.article_understanding_jobs j
      JOIN public.understanding_recipes r ON r.id=j.recipe_id AND r.enabled
      WHERE j.id=%s AND j.state='running' AND j.lease_token=%s AND j.lease_until>clock_timestamp()
        AND j.deadline>clock_timestamp()
      FOR UPDATE OF j""", (job['id'], job['lease_token'])).fetchone()


def _finish_job(conn, job, state, reason=None):
    return conn.execute("""UPDATE public.article_understanding_jobs SET state=%s,failure_reason=%s,
      lease_token=NULL,lease_until=NULL,updated_at=now() WHERE id=%s AND lease_token=%s
      AND state='running'""", (state, reason, job['id'], job['lease_token'])).rowcount


def finish_publication(conn, job):
    # now() is the transaction start, which can precede a long lock wait. Check
    # real time again at the final write, and roll back all writes on lease loss.
    changed = conn.execute("""UPDATE public.article_understanding_jobs SET state='ready',
      failure_reason=NULL,lease_token=NULL,lease_until=NULL,updated_at=now()
      WHERE id=%s AND lease_token=%s AND state='running'
        AND lease_until>clock_timestamp() AND deadline>clock_timestamp()""",
      (job['id'], job['lease_token'])).rowcount
    if not changed:
        raise _LeaseLost()


def reserve(conn, job, estimate_usd):
    amount = _money(estimate_usd)
    if amount <= 0:
        raise ValueError('paid stages require positive known price')
    with conn.transaction():
        # Budget lock only: never acquire article/job write locks afterwards.
        control = conn.execute('SELECT * FROM public.understanding_control FOR UPDATE').fetchone()
        allowed = conn.execute("""SELECT 1 FROM public.article_understanding_jobs j
          JOIN public.understanding_recipes r ON r.id=j.recipe_id AND r.enabled
          WHERE j.id=%s AND j.lease_token=%s AND j.state='running'
            AND j.lease_until>clock_timestamp() AND j.deadline>clock_timestamp()""",
          (job['id'], job['lease_token'])).fetchone()
        if not control['submissions_enabled'] or not allowed:
            return None
        paused = conn.execute('SELECT %s::timestamptz > now() AS paused',
                              (control['circuit_until'],)).fetchone()['paused']
        if paused:
            return None
        used = conn.execute("""SELECT COALESCE(sum(CASE WHEN settled THEN actual_usd ELSE reserved_usd END),0)
          AS total FROM public.understanding_spend WHERE day=(now() AT TIME ZONE 'UTC')::date""").fetchone()['total']
        if used + amount > control['daily_budget_usd']:
            return None
        reservation = uuid.uuid4()
        conn.execute("""INSERT INTO public.understanding_spend(id,job_id,attempt,reserved_usd)
          VALUES(%s,%s,%s,%s)""", (reservation, job['id'], job['attempts'], amount))
        return reservation


def settle(conn, reservation, actual_usd):
    amount = _money(actual_usd)
    with conn.transaction():
        conn.execute('SELECT singleton FROM public.understanding_control FOR UPDATE')
        row = conn.execute('SELECT * FROM public.understanding_spend WHERE id=%s FOR UPDATE',
                           (reservation,)).fetchone()
        if not row:
            raise ValueError('unknown reservation')
        if row['settled']:
            if row['actual_usd'] != amount:
                raise ValueError('reservation already settled with different usage')
            return
        conn.execute('UPDATE public.understanding_spend SET actual_usd=%s,settled=true WHERE id=%s',
                     (amount, reservation))
        if amount > row['reserved_usd']:
            conn.execute("""UPDATE public.understanding_control SET submissions_enabled=false,
              circuit_reason='usage_exceeded_reservation',updated_at=now()""")


def fail(conn, job, reason, *, retryable=True, retry_after=30, provider_wide=False):
    delay = max(1, min(float(retry_after), 86400))
    with conn.transaction():
        # Job-only transaction, no later article locking.
        conn.execute("""UPDATE public.article_understanding_jobs SET state=CASE
          WHEN NOT %s OR attempts>=5 OR deadline<=now() THEN 'failed_terminal' ELSE 'retry_wait' END,
          failure_reason=%s,retry_at=now()+(%s*interval '1 second'),lease_token=NULL,lease_until=NULL,
          updated_at=now() WHERE id=%s AND state='running' AND lease_token=%s""",
          (retryable, reason[:120], delay, job['id'], job['lease_token']))
    if provider_wide:
        with conn.transaction():
            conn.execute("""UPDATE public.understanding_control SET circuit_until=greatest(
              COALESCE(circuit_until,now()),now()+(%s*interval '1 second')),
              circuit_reason=%s,updated_at=now()""", (max(delay, 300), reason[:120]))


def defer_without_attempt(conn, job, reason, *, delay=300):
    """Budget pauses made no external attempt and must not exhaust five retries."""
    with conn.transaction():
        conn.execute("""UPDATE public.article_understanding_jobs j SET state='retry_wait',
          attempts=greatest(attempts-1,0),failure_reason=%s,retry_at=now()+(%s*interval '1 second'),
          lease_token=NULL,lease_until=NULL,updated_at=now()
          WHERE id=%s AND state='running' AND lease_token=%s
            AND NOT EXISTS (SELECT 1 FROM public.understanding_spend s
              WHERE s.job_id=j.id AND s.attempt=j.attempts)""",
          (reason,delay,job['id'],job['lease_token']))


@lease_fenced
def publish(conn, job, bundle, payload, usage_usd=0, request_id=None):
    from app.services.understanding_contract import validate_card, validate_embedding
    vector = None
    if job['stage'] == 'facets':
        payload = validate_card(payload, bundle)
    elif job['stage'] == 'embedding':
        vector = validate_embedding(payload['vector'])
        payload = {'dimensions': len(vector)}
    else:
        raise ValueError('invalid publication stage')
    with conn.transaction():
        current_input = evidence_for_article(conn, job['article_id'], lock=True)
        current = _locked_job(conn, job)
        if not current:
            return False
        if not current_input or current_input['input_hash'] != bundle['input_hash'] or \
                current_input['semantic_revision'] != job['semantic_revision'] or \
                current_input['analysis_eligibility_generation'] != job['eligibility_generation'] or \
                current['input_hash'] != bundle['input_hash']:
            _finish_job(conn, job, 'superseded', 'input_changed')
            return False
        # Keep only metadata/hashes, not a second persisted source body.
        manifest = {'manifest': bundle['manifest'], 'evidence_tier': bundle['evidence_tier'],
                    'language': bundle.get('language')}
        conn.execute("""INSERT INTO public.article_understanding_results
          (article_id,semantic_revision,eligibility_generation,recipe_id,stage,input_hash,
           evidence_manifest,payload,embedding,provider_request_id,usage_usd)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,%s) ON CONFLICT DO NOTHING""",
          (job['article_id'],job['semantic_revision'],job['eligibility_generation'],job['recipe_id'],
           job['stage'],bundle['input_hash'],Jsonb(manifest),Jsonb(payload),
           str(vector) if vector is not None else None,request_id,_money(usage_usd)))
        conn.execute("""INSERT INTO public.understanding_outbox
          (article_id,semantic_revision,eligibility_generation,recipe_id,kind) VALUES(%s,%s,%s,%s,%s)""",
          (job['article_id'],job['semantic_revision'],job['eligibility_generation'],job['recipe_id'],job['stage']+'_ready'))
        conn.execute("""INSERT INTO public.article_understanding_jobs
          (article_id,semantic_revision,eligibility_generation,recipe_id,stage,source_key,fresh,input_hash)
          SELECT %s,%s,%s,%s,'cluster',%s,%s,%s WHERE (
            SELECT count(*) FROM public.article_understanding_results WHERE article_id=%s
              AND semantic_revision=%s AND eligibility_generation=%s AND recipe_id=%s
              AND input_hash=%s)=2 ON CONFLICT DO NOTHING""",
          (job['article_id'],job['semantic_revision'],job['eligibility_generation'],job['recipe_id'],
           job['source_key'],job['fresh'],bundle['input_hash'],job['article_id'],job['semantic_revision'],
           job['eligibility_generation'],job['recipe_id'],bundle['input_hash']))
        finish_publication(conn, job)
    return True


def load_current(conn, article_id, recipe_id=None):
    # Hold a stable database snapshot for evidence+results+membership. The second
    # input hash check protects callers that use READ COMMITTED while an article
    # correction commits between reads; serving cannot fabricate a ready state.
    if recipe_id is None:
        row = conn.execute('SELECT serving_recipe FROM public.understanding_control').fetchone()
        recipe_id = row['serving_recipe'] if row else None
    if not recipe_id:
        return {'state': 'disabled'}
    bundle = evidence_for_article(conn, article_id)
    if not bundle:
        return {'state': 'revoked_or_missing'}
    results = conn.execute("""SELECT * FROM public.article_understanding_current
      WHERE article_id=%s AND recipe_id=%s AND input_hash=%s""",
      (article_id,recipe_id,bundle['input_hash'])).fetchall()
    by_stage = {r['stage']: r for r in results}
    membership = conn.execute("""SELECT * FROM public.story_memberships WHERE article_id=%s
      AND recipe_id=%s AND semantic_revision=%s AND eligibility_generation=%s AND input_hash=%s""",
      (article_id,recipe_id,bundle['semantic_revision'],bundle['analysis_eligibility_generation'],bundle['input_hash'])).fetchone()
    latest = evidence_for_article(conn, article_id)
    if latest is None or latest['input_hash'] != bundle['input_hash'] or \
            latest['semantic_revision'] != bundle['semantic_revision'] or \
            latest['analysis_eligibility_generation'] != bundle['analysis_eligibility_generation']:
        return {'state': 'stale'}
    recipe = conn.execute('SELECT enabled FROM public.understanding_recipes WHERE id=%s',
                          (recipe_id,)).fetchone()
    if not recipe or not recipe['enabled']:
        return {'state': 'disabled'}
    return {'state': 'ready' if len(by_stage)==2 else ('partial' if by_stage else 'pending'),
            'article_id': str(article_id),'input_hash': bundle['input_hash'],
            'semantic_revision': bundle['semantic_revision'],
            'analysis_eligibility_generation': bundle['analysis_eligibility_generation'],
            'recipe_id': recipe_id, 'facets': by_stage.get('facets'),
            'embedding': by_stage.get('embedding'), 'membership': membership if len(by_stage)==2 else None}


def revoke(conn, article_id, revoked=True):
    with conn.transaction():
        # Revision trigger handles invalidation and scheduling; never touch display policy.
        return conn.execute("""UPDATE public.articles SET analysis_revoked=%s,
          analysis_eligibility_generation=analysis_eligibility_generation+1 WHERE id=%s""",
          (revoked, article_id)).rowcount


def status(conn):
    check_schema(conn)
    return {
      'jobs': conn.execute("""SELECT recipe_id,stage,state,count(*) AS count,
        extract(epoch FROM now()-min(created_at)) AS oldest_age_seconds
        FROM public.article_understanding_jobs GROUP BY recipe_id,stage,state ORDER BY recipe_id,stage,state""").fetchall(),
      'control': conn.execute('SELECT * FROM public.understanding_control').fetchone(),
      'spend': conn.execute("""SELECT day,sum(CASE WHEN settled THEN actual_usd ELSE reserved_usd END)
        AS accounted_usd,count(*) FILTER(WHERE NOT settled) AS unresolved
        FROM public.understanding_spend GROUP BY day ORDER BY day DESC LIMIT 30""").fetchall(),
      'population': conn.execute("""SELECT count(*) AS articles,count(*) FILTER(WHERE analysis_revoked) AS revoked,
        count(*) FILTER(WHERE NOT analysis_revoked AND NOT EXISTS(SELECT 1 FROM public.article_understanding_jobs j
          WHERE j.article_id=articles.id AND j.semantic_revision=articles.semantic_revision
          AND j.eligibility_generation=articles.analysis_eligibility_generation)) AS unscheduled
        FROM public.articles""").fetchone()}


def read_events(conn, consumer, limit=100):
    with conn.transaction():
        conn.execute('INSERT INTO public.understanding_consumer_cursors(consumer) VALUES(%s) ON CONFLICT DO NOTHING',
                     (consumer,))
        return conn.execute("""SELECT o.* FROM public.understanding_outbox o WHERE NOT EXISTS
          (SELECT 1 FROM public.understanding_event_receipts r WHERE r.consumer=%s AND r.event_id=o.id)
          ORDER BY o.id LIMIT %s""", (consumer,max(1,min(limit,1000)))).fetchall()


def acknowledge_events(conn, consumer, event_ids):
    """Consumer acknowledges only after durable idempotent application of the returned batch."""
    with conn.transaction():
        return conn.execute("""INSERT INTO public.understanding_event_receipts(consumer,event_id)
          SELECT %s,id FROM public.understanding_outbox WHERE id=ANY(%s)
          ON CONFLICT DO NOTHING""",(consumer,list(event_ids))).rowcount
