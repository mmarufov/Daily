"""Default-off, bounded S6 shadow execution on exclusively owned connections.

This module never publishes candidates or calls an embedding/ranking provider.
The event loop's deadline bounds caller latency, not Python thread lifetime: an
abandoned worker retains its admission slot and connection until real cleanup.
There is deliberately no cross-thread connection cancellation, which could race
pool return and cancel a subsequent borrower's query. PostgreSQL statement/lock
timeouts bound database work; unavailable workers shed load instead of queuing.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import threading
import time

from psycopg.errors import QueryCanceled

from .reader_repository import load_reader
from .reader_retrieval import build_candidate_batch


_BATCH_STATUSES = frozenset(('complete', 'degraded', 'empty', 'stale'))
_LEG_STATUSES = frozenset(('available', 'exhausted', 'budget_limited', 'failed',
                         'timed_out', 'missing_vector', 'missing_facets', 'disabled'))


def _aggregate(batch):
    """Allowlist counts only; never return raw rows, queries, IDs or exception text."""
    diagnostics = batch.diagnostics
    counts = Counter(leg.get('status') for leg in diagnostics.get('legs', [])
                     if leg.get('status') in _LEG_STATUSES)
    result = {'status': batch.status if batch.status in _BATCH_STATUSES else 'unavailable',
              'candidates': len(batch.candidates), 'legs': dict(counts)}
    for key in ('unique_examined', 'rows_returned', 'rounds'):
        value = diagnostics.get(key, 0)
        result[key] = value if type(value) is int and value >= 0 else 0
    return result


class ShadowRunner:
    """Process-wide admission, independent of event-loop or request lifetime."""

    def __init__(self, *, max_workers=2, deadline_seconds=2.0):
        if not 1 <= max_workers <= 2 or not 0 < deadline_seconds <= 2:
            raise ValueError('S6 shadow bounds may only be tightened')
        self._deadline_seconds = deadline_seconds
        self._slots = threading.BoundedSemaphore(max_workers)
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='s6-shadow')
        self._lock = threading.Lock()
        self._futures = set()
        self._closed = False

    def _finished(self, future):
        # Only executor completion can release a slot, never request cancellation.
        with self._lock:
            self._futures.discard(future)
        self._slots.release()

    @staticmethod
    def _worker(pool, user_id, deadline, as_of, abandoned):
        def remaining():
            left = deadline - time.monotonic()
            if left <= 0 or abandoned.is_set():
                raise TimeoutError('S6 shadow deadline')
            return left

        try:
            with pool.connection(timeout=remaining()) as conn:
                remaining()
                # This connection is never exposed outside this worker. Establish
                # reader lock/query bounds before load_reader's nested transaction.
                # create=False never migrates or changes profile state.
                with conn.transaction():
                    milliseconds = max(1, int(remaining() * 1000))
                    conn.execute("SELECT set_config('statement_timeout',%s,true),"
                                 "set_config('lock_timeout',%s,true)",
                                 (str(milliseconds), str(min(100, milliseconds))))
                    snapshot = load_reader(conn, user_id, create=False)
                remaining()
                if not snapshot or snapshot.get('migration_status') != 'ready':
                    return {'status': 'reader_unavailable'}
                # load_reader has committed; retrieval owns the next idle,
                # read-only repeatable-read transaction on the same connection.
                #
                # No remaining() check here: build_candidate_batch already
                # enforces this exact deadline internally (tightening
                # statement_timeout per query via reader_retrieval._remaining,
                # catching its own RetrievalDeadline/QueryCanceled) and always
                # returns a valid CandidateBatch either way -- 'complete' if it
                # finished, 'degraded' with a partial result and
                # stop_reason='deadline' if it ran out of time. A live
                # production profile with several intents was observed
                # completing its own work correctly but landing microseconds
                # past this external deadline (the cost of Postgres actually
                # cancelling a statement is not free); re-checking here after
                # the batch is already computed can only discard an
                # already-valid result for a race that already resolved.
                batch = build_candidate_batch(conn, user_id, snapshot,
                                               deadline=deadline, as_of=as_of)
                return _aggregate(batch)
        except (TimeoutError, QueryCanceled):
            return {'status': 'timed_out'}
        except Exception:
            # Do not log errors containing SQL, profile text, credentials or rows.
            return {'status': 'unavailable'}

    async def run(self, pool, user_id):
        started = time.monotonic()
        deadline = started + self._deadline_seconds
        if not self._slots.acquire(blocking=False):
            return {'status': 'busy'}
        abandoned = threading.Event()
        with self._lock:
            if self._closed:
                self._slots.release()
                return {'status': 'closed'}
            try:
                future = self._executor.submit(self._worker, pool, user_id, deadline,
                                               datetime.now(timezone.utc), abandoned)
            except Exception:
                self._slots.release()
                return {'status': 'unavailable'}
            self._futures.add(future)
        # Register outside the lock: already-finished futures invoke synchronously.
        future.add_done_callback(self._finished)
        wrapped = asyncio.wrap_future(future)
        try:
            # asyncio.wait_for already is the deadline enforcement: it raises
            # asyncio.TimeoutError (caught below) if the worker doesn't finish
            # within `timeout`, and shield() keeps that worker running rather
            # than cancelling it either way. If wait_for returns instead of
            # raising, the worker genuinely finished in time -- a second
            # wall-clock re-check here only ever fires on the same race
            # _worker used to lose (see the comment above _worker's return),
            # discarding an already-valid result for a timing question
            # wait_for already answered correctly.
            return await asyncio.wait_for(asyncio.shield(wrapped),
                                          timeout=max(0, deadline - time.monotonic()))
        except asyncio.TimeoutError:
            abandoned.set()
            return {'status': 'timed_out'}
        except asyncio.CancelledError:
            abandoned.set()
            raise

    async def aclose(self, *, timeout=2.0):
        """Stop admission and give existing workers a bounded chance to drain.

        Returns False if cleanup is still running; ownership and slots remain
        intact. Threads are not force-killed and connections are not reused early.
        """
        with self._lock:
            self._closed = True
            pending = tuple(self._futures)
        self._executor.shutdown(wait=False, cancel_futures=False)
        if not pending:
            return True
        _, unfinished = await asyncio.wait([asyncio.wrap_future(f) for f in pending],
                                            timeout=max(0, min(timeout, 2.0)))
        return not unfinished


_runner = ShadowRunner()
_lifecycle_lock = threading.Lock()


def startup():
    """Allow a new app lifespan only after the previous workers fully drained."""
    global _runner
    with _lifecycle_lock:
        with _runner._lock:
            if not _runner._closed:
                return True
            if _runner._futures:
                return False
        _runner = ShadowRunner()
        return True


async def shadow(pool, user_id):
    """Optional internal observation; disabled means no connection/thread work."""
    if os.getenv('S6_SHADOW_ENABLED', 'false').lower() != 'true':
        return {'status': 'disabled'}
    return await _runner.run(pool, user_id)


async def shutdown():
    """Call before closing the application pool during graceful shutdown."""
    return await _runner.aclose()
