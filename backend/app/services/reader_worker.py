"""Default-off, budgeted S5 per-intent embeddings. No feed request calls a model.

Schema is installed explicitly. Short database transactions never cross network
awaits. A timeout is conservatively charged, and each job has at most three paid
attempts. Embeddings contain only the explicit intent query, never biography.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .understanding_consumers import serving_recipe
from .understanding_contract import normalize_text, validate_embedding
from .understanding_provider import OpenAIUnderstandingProvider, ProviderFailure

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
MAX_QUERY_BYTES = 2048


def enabled():
    return os.getenv('S5_WORKER_ENABLED', 'false').lower() == 'true'


def space_id(definition):
    """Facet/prompt revisions do not change geometry; query/document recipes do."""
    keys = ('embedding_model', 'dimensions', 'input_version', 'query_recipe', 'document_recipe')
    if any(key not in definition for key in keys) or definition['dimensions'] != 1536:
        raise ValueError('unsupported reader embedding space')
    raw = json.dumps({key: definition[key] for key in keys}, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode()).hexdigest()


def intent_query(intent):
    text = normalize_text(" ".join([intent.get('query') or intent.get('label') or '', *intent.get('qualifiers', [])]))
    if not text or len(text) > 280 or len(text.encode('utf-8')) > MAX_QUERY_BYTES:
        raise ValueError('invalid bounded reader query')
    return text


def semantic_hash(intent):
    return hashlib.sha256(intent_query(intent).encode('utf-8')).hexdigest()


def active_intents(snapshot, *, now=None):
    now = now or datetime.now(timezone.utc)
    result = []
    intents = snapshot.get('profile', {}).get('intents', [])
    if not isinstance(intents, list) or len(intents) > 24:
        raise ValueError('invalid reader intent bounds')
    for intent in intents:
        expiry = intent.get('expires_at')
        if expiry:
            expiry = datetime.fromisoformat(expiry.replace('Z', '+00:00')) if isinstance(expiry, str) else expiry
            if expiry.tzinfo is None:
                raise ValueError('reader expiry requires timezone')
            if expiry <= now:
                continue
        intent_query(intent)
        result.append(intent)
    return result


def install_schema(conn):
    with conn.transaction():
        conn.execute(Path(__file__).with_name('reader_embedding_schema.sql').read_text())


def _snapshot(row):
    return {'profile': row['profile'], 'generation': str(row['generation'])}


def _current_reader(conn, user_id):
    # Match the authority's user -> reader lock order, including soft deletion.
    user = conn.execute('''SELECT id FROM public.users WHERE id=%s
      AND NOT COALESCE(is_deleted,false) FOR SHARE''', (user_id,)).fetchone()
    if not user:
        return None
    return conn.execute('''SELECT profile,generation FROM public.reader_profiles
      WHERE user_id=%s AND migration_status='ready' FOR UPDATE''', (user_id,)).fetchone()


def job_matches(job, snapshot, recipe, *, now=None):
    if (str(job['generation']) != str(snapshot['generation'])
            or job['space_id'] != space_id(recipe['definition'])
            or job['recipe_id'] != recipe['id']):
        return False
    return any(str(intent['id']) == str(job['intent_id']) and semantic_hash(intent) == job['semantic_hash']
               for intent in active_intents(snapshot, now=now))


def reconcile(conn, *, after_user=None, limit=100):
    """Bounded keyset sweep catches mutations AND a newly promoted S3 recipe.

    The durable canonical snapshot is the work source. Generic reader jobs are not
    consumed here, so completion of source reconciliation cannot lose embeddings.
    """
    if not enabled():
        return None
    recipe = serving_recipe(conn)
    geometry = space_id(recipe['definition'])
    rows = conn.execute('''SELECT user_id,profile,generation FROM public.reader_profiles r
      WHERE migration_status='ready' AND EXISTS(SELECT 1 FROM public.users u
        WHERE u.id=r.user_id AND NOT COALESCE(u.is_deleted,false))
      AND (%s::uuid IS NULL OR user_id>%s::uuid) ORDER BY user_id LIMIT %s''',
      (after_user, after_user, max(1, min(int(limit), 100)))).fetchall()
    for row in rows:
        with conn.transaction():
            # The authority writer locks this row too. Deleted/reset state cannot
            # reappear between reconciliation and insertion.
            current = _current_reader(conn, row['user_id'])
            if not current:
                continue
            snapshot = _snapshot(current)
            intents = active_intents(snapshot)
            identifiers = [uuid.UUID(str(intent['id'])) for intent in intents]
            desired_jobs = json.dumps([{'intent_id': i['id'], 'semantic_hash': semantic_hash(i)} for i in intents])
            conn.execute('''DELETE FROM public.reader_embedding_jobs j WHERE user_id=%s
              AND state<>'running' AND (generation<>%s OR space_id<>%s OR NOT EXISTS
                (SELECT 1 FROM jsonb_to_recordset(%s::jsonb) AS desired(intent_id uuid,semantic_hash text)
                 WHERE desired.intent_id=j.intent_id AND desired.semantic_hash=j.semantic_hash))''',
              (row['user_id'], snapshot['generation'], geometry, desired_jobs))
            conn.execute('''DELETE FROM public.reader_intent_embeddings WHERE user_id=%s
              AND (generation<>%s OR NOT(intent_id=ANY(%s::uuid[])) OR space_id<>%s)''',
              (row['user_id'], snapshot['generation'], identifiers, geometry))
            for intent in intents:
                digest = semantic_hash(intent)
                conn.execute('''DELETE FROM public.reader_intent_embeddings WHERE user_id=%s
                  AND intent_id=%s AND semantic_hash<>%s''', (row['user_id'], intent['id'], digest))
                conn.execute('''INSERT INTO public.reader_embedding_jobs
                  (user_id,generation,intent_id,semantic_hash,space_id,recipe_id)
                  SELECT %s,%s,%s,%s,%s,%s WHERE NOT EXISTS(
                    SELECT 1 FROM public.reader_intent_embeddings WHERE user_id=%s AND generation=%s
                      AND intent_id=%s AND semantic_hash=%s AND space_id=%s)
                  ON CONFLICT(user_id,generation,intent_id,semantic_hash,space_id) DO UPDATE
                  SET recipe_id=EXCLUDED.recipe_id,state='pending',attempts=0,lease_token=NULL,
                    lease_until=NULL,retry_at=clock_timestamp(),updated_at=clock_timestamp()
                  WHERE reader_embedding_jobs.recipe_id<>EXCLUDED.recipe_id
                    OR reader_embedding_jobs.state='superseded' ''',
                  (row['user_id'], snapshot['generation'], intent['id'], digest, geometry, recipe['id'],
                   row['user_id'], snapshot['generation'], intent['id'], digest, geometry))
    return str(rows[-1]['user_id']) if len(rows) == max(1, min(int(limit), 100)) else None


def claim(conn, *, limit=2):
    if not enabled():
        return []
    with conn.transaction():
        control = conn.execute('SELECT * FROM public.reader_embedding_control').fetchone()
        if not control or not control['enabled'] or min(control['daily_global_tokens'], control['daily_user_tokens']) <= 0:
            return []
        conn.execute('''UPDATE public.reader_embedding_jobs SET
          state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'retry_wait' END,
          lease_token=NULL,lease_until=NULL,failure_code='lease_expired',retry_at=clock_timestamp()
          WHERE state='running' AND lease_until<=clock_timestamp()''')
        return conn.execute('''WITH due AS (
          SELECT id FROM public.reader_embedding_jobs WHERE state IN ('pending','retry_wait')
            AND attempts<3 AND retry_at<=clock_timestamp() ORDER BY retry_at,id
            LIMIT %s FOR UPDATE SKIP LOCKED)
          UPDATE public.reader_embedding_jobs j SET state='running',lease_token=gen_random_uuid(),
            lease_until=clock_timestamp()+interval '120 seconds',updated_at=clock_timestamp()
          FROM due WHERE j.id=due.id RETURNING j.*''', (max(1, min(int(limit), 8)),)).fetchall()


def _finish(conn, job, state, code=None, delay=0):
    return conn.execute('''UPDATE public.reader_embedding_jobs SET state=%s,failure_code=%s,
      lease_token=NULL,lease_until=NULL,retry_at=clock_timestamp()+(%s*interval '1 second'),
      updated_at=clock_timestamp() WHERE id=%s AND state='running' AND lease_token=%s
      AND lease_until>clock_timestamp()''', (state, code, delay, job['id'], job['lease_token'])).rowcount


def prepare(conn, job):
    """Recheck and reserve conservatively before a network request, atomically."""
    if not enabled():
        return None
    with conn.transaction():
        current = _current_reader(conn, job['user_id'])
        recipe = serving_recipe(conn)
        if not current or not job_matches(job, _snapshot(current), recipe):
            _finish(conn, job, 'superseded', 'reader_or_recipe_changed')
            return None
        intent = next(i for i in active_intents(_snapshot(current)) if str(i['id']) == str(job['intent_id']))
        query = intent_query(intent)
        # UTF-8 bytes are a conservative upper bound for the byte-level embedding
        # tokenizer. Do not undercount multilingual inputs by len(chars)/4.
        reservation = len(query.encode('utf-8'))
        control = conn.execute('SELECT * FROM public.reader_embedding_control FOR UPDATE').fetchone()
        if not control or not control['enabled']:
            _finish(conn, job, 'retry_wait', 'disabled', 300)
            return None
        lease = conn.execute('''SELECT attempts FROM public.reader_embedding_jobs WHERE id=%s
          AND state='running' AND lease_token=%s AND lease_until>clock_timestamp() FOR UPDATE''',
          (job['id'], job['lease_token'])).fetchone()
        if not lease or lease['attempts'] >= MAX_ATTEMPTS:
            return None
        day = conn.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date AS day").fetchone()['day']
        conn.execute('''INSERT INTO public.reader_embedding_global_spend(day) VALUES(%s) ON CONFLICT DO NOTHING''', (day,))
        conn.execute('''INSERT INTO public.reader_embedding_user_spend(user_id,day) VALUES(%s,%s)
          ON CONFLICT DO NOTHING''', (job['user_id'], day))
        global_used = conn.execute('SELECT reserved_tokens FROM public.reader_embedding_global_spend WHERE day=%s', (day,)).fetchone()['reserved_tokens']
        user_used = conn.execute('''SELECT reserved_tokens FROM public.reader_embedding_user_spend
          WHERE user_id=%s AND day=%s''', (job['user_id'], day)).fetchone()['reserved_tokens']
        if (global_used + reservation > control['daily_global_tokens']
                or user_used + reservation > control['daily_user_tokens']):
            _finish(conn, job, 'retry_wait', 'budget_exhausted', 300)
            return None
        conn.execute('''UPDATE public.reader_embedding_global_spend SET reserved_tokens=reserved_tokens+%s
          WHERE day=%s''', (reservation, day))
        conn.execute('''UPDATE public.reader_embedding_user_spend SET reserved_tokens=reserved_tokens+%s
          WHERE user_id=%s AND day=%s''', (reservation, job['user_id'], day))
        conn.execute('''UPDATE public.reader_embedding_jobs SET attempts=attempts+1 WHERE id=%s''', (job['id'],))
        return {'query': query, 'definition': recipe['definition'], 'attempt': lease['attempts'] + 1}


class LostLease(Exception):
    pass


def publish(conn, job, vector):
    vector = validate_embedding(vector)
    try:
        with conn.transaction():
            current = _current_reader(conn, job['user_id'])
            # Serialize promotion/disable with this short publication transaction.
            conn.execute('SELECT singleton FROM public.understanding_control FOR SHARE')
            recipe = serving_recipe(conn)
            conn.execute('SELECT id FROM public.understanding_recipes WHERE id=%s FOR SHARE', (recipe['id'],))
            recipe = serving_recipe(conn)
            if not current or not job_matches(job, _snapshot(current), recipe):
                _finish(conn, job, 'superseded', 'reader_or_recipe_changed')
                return False
            control = conn.execute('SELECT enabled FROM public.reader_embedding_control FOR SHARE').fetchone()
            if not enabled() or not control or not control['enabled']:
                _finish(conn, job, 'retry_wait', 'disabled', 300)
                return False
            conn.execute('''INSERT INTO public.reader_intent_embeddings
              (user_id,generation,intent_id,semantic_hash,space_id,embedding) VALUES(%s,%s,%s,%s,%s,%s::vector)
              ON CONFLICT DO NOTHING''', (job['user_id'], job['generation'], job['intent_id'],
                job['semantic_hash'], job['space_id'], str(vector)))
            if not _finish(conn, job, 'ready'):
                raise LostLease()
        return True
    except LostLease:
        return False


def fail(conn, job, *, retryable=False, code='provider_failure', attempt=1):
    # Only fixed categories from this module are persisted, never provider text.
    state = 'retry_wait' if retryable and attempt < MAX_ATTEMPTS else 'failed'
    with conn.transaction():
        _finish(conn, job, state, code, min(3600, 30 * 2 ** max(0, min(attempt, 3))))


class ReaderWorker:
    def __init__(self, pool, provider, *, concurrency=2):
        self.pool, self.provider = pool, provider
        self.concurrency = max(1, min(int(concurrency), 8))
        self.stop = asyncio.Event()
        self.after_user = None

    async def db(self, function, *args, **kwargs):
        def operation():
            with self.pool.connection() as conn:
                return function(conn, *args, **kwargs)
        return await asyncio.to_thread(operation)

    async def process(self, job):
        prepared = None
        try:
            prepared = await self.db(prepare, job)
            if prepared is None:
                return
            outcome = await asyncio.wait_for(self.provider.query_embedding(
                prepared['query'], prepared['definition']), timeout=60)
            await self.db(publish, job, outcome.payload['vector'])
        except asyncio.CancelledError:
            # Lease expires; reservation remains charged even if billing is unknown.
            raise
        except (TimeoutError, ProviderFailure) as exc:
            await self.db(fail, job, retryable=isinstance(exc, TimeoutError) or exc.retryable,
                          code='provider_failure', attempt=prepared['attempt'] if prepared else MAX_ATTEMPTS)
        except (ValueError, TypeError, KeyError):
            await self.db(fail, job, code='invalid_contract', attempt=MAX_ATTEMPTS)
        except Exception:
            logger.warning('S5 embedding work unavailable; no private payload logged')
            await self.db(fail, job, retryable=True, code='internal_failure',
                          attempt=prepared['attempt'] if prepared else MAX_ATTEMPTS)

    async def tick(self):
        if not enabled():
            return 0
        self.after_user = await self.db(reconcile, after_user=self.after_user)
        jobs = await self.db(claim, limit=self.concurrency)
        await asyncio.gather(*(self.process(job) for job in jobs))
        return len(jobs)

    async def run(self):
        while not self.stop.is_set():
            task, stopped = asyncio.create_task(self.tick()), asyncio.create_task(self.stop.wait())
            try:
                done, _ = await asyncio.wait((task, stopped), return_when=asyncio.FIRST_COMPLETED)
                if stopped in done:
                    return
                count = await task
                delay = .5 if count else 5
            except Exception:
                logger.warning('S5 worker unavailable; retrying without provider work')
                delay = 10
            finally:
                for future in (task, stopped):
                    if not future.done():
                        future.cancel()
                await asyncio.gather(task, stopped, return_exceptions=True)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=delay)
            except TimeoutError:
                pass


async def main():
    from dotenv import load_dotenv
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool
    load_dotenv()
    if not enabled():
        return
    pool = ConnectionPool(os.environ['DATABASE_URL'], min_size=1, max_size=4,
        kwargs={'row_factory': dict_row, 'autocommit': True,
                'options': '-c statement_timeout=30000 -c lock_timeout=5000'})
    provider = OpenAIUnderstandingProvider(os.environ['OPENAI_API_KEY'])
    worker = ReaderWorker(pool, provider)
    for signum in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(signum, worker.stop.set)
    try:
        await worker.run()
    finally:
        await provider.aclose()
        pool.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
