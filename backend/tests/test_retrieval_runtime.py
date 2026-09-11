"""Offline S6 deadline/admission tests; no DB listener or provider credits."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from psycopg.errors import QueryCanceled

from app.services import retrieval_runtime as runtime


class Connection:
    def __init__(self):
        self.statements = []
        self.transactions = 0

    @contextmanager
    def transaction(self):
        self.transactions += 1
        try:
            yield
        finally:
            self.transactions -= 1

    def execute(self, statement, params):
        self.statements.append((statement, params))


class Pool:
    def __init__(self, *, failure=None, cleanup=None):
        self.conn = Connection()
        self.failure = failure
        self.cleanup = cleanup
        self.calls = []
        self.borrowed = 0
        self.released = threading.Event()

    @contextmanager
    def connection(self, *, timeout):
        self.calls.append(timeout)
        if self.failure:
            raise self.failure
        self.borrowed += 1
        try:
            yield self.conn
        finally:
            if self.cleanup:
                self.cleanup()
            self.borrowed -= 1
            self.released.set()


def batch():
    return SimpleNamespace(status='degraded', candidates=[{'secret': 'raw article'}],
                           diagnostics={'unique_examined': 3, 'rows_returned': 5, 'rounds': 2,
                                        'legs': [{'status': 'missing_vector', 'intent_id': 'secret'},
                                                 {'status': 'exhausted'}, {'status': 'private text'}],
                                        'query': 'private reader intent', 'reader': 'private ID'})


@pytest.fixture
def dependencies(monkeypatch):
    loader = Mock(return_value={'migration_status': 'ready', 'profile': {'private': 'intent'}})
    builder = Mock(return_value=batch())
    monkeypatch.setattr(runtime, 'load_reader', loader)
    monkeypatch.setattr(runtime, 'build_candidate_batch', builder)
    return loader, builder


def test_disabled_shadow_is_noop(monkeypatch):
    monkeypatch.delenv('S6_SHADOW_ENABLED', raising=False)
    runner = Mock()
    monkeypatch.setattr(runtime, '_runner', runner)
    pool = Mock()
    assert asyncio.run(runtime.shadow(pool, 'private ID')) == {'status': 'disabled'}
    runner.run.assert_not_called()
    pool.connection.assert_not_called()


@pytest.mark.parametrize('value', ['1', 'yes', 'false', ' true '])
def test_only_explicit_true_enables(monkeypatch, value):
    monkeypatch.setenv('S6_SHADOW_ENABLED', value)
    assert asyncio.run(runtime.shadow(Mock(), 'reader')) == {'status': 'disabled'}


def test_shadow_uses_dedicated_connection_and_only_returns_aggregates(dependencies):
    loader, builder = dependencies
    pool = Pool()
    runner = runtime.ShadowRunner()

    async def scenario():
        result = await runner.run(pool, 'private ID')
        assert await runner.aclose()
        return result

    before = time.monotonic()
    result = asyncio.run(scenario())
    assert result == {'status': 'degraded', 'candidates': 1,
                      'legs': {'missing_vector': 1, 'exhausted': 1},
                      'unique_examined': 3, 'rows_returned': 5, 'rounds': 2}
    assert len(pool.calls) == 1 and 0 < pool.calls[0] <= 2
    assert pool.borrowed == 0 and pool.released.is_set()
    loader.assert_called_once_with(pool.conn, 'private ID', create=False)
    assert builder.call_args.args[:2] == (pool.conn, 'private ID')
    assert before + 2 <= builder.call_args.kwargs['deadline'] <= time.monotonic() + 2
    assert builder.call_args.kwargs['as_of'].tzinfo is not None
    assert pool.conn.transactions == 0
    assert len(pool.conn.statements) == 1
    statement, params = pool.conn.statements[0]
    assert 'set_config' in statement and 'statement_timeout' in statement and 'lock_timeout' in statement
    assert 0 < int(params[0]) <= 2000 and 0 < int(params[1]) <= 100


def test_worker_trusts_a_batch_completed_after_its_own_deadline_passed(dependencies):
    """Regression: observed live against a real production reader profile.

    build_candidate_batch already enforces this exact deadline internally
    (reader_retrieval._remaining tightens statement_timeout per query and
    build_candidate_batch catches its own RetrievalDeadline/QueryCanceled,
    always returning a valid -- possibly degraded -- CandidateBatch either
    way). A stray remaining() check *after* that call returned was found to
    discard an already-computed, valid batch as 'timed_out' purely because
    wall-clock time had ticked past the deadline while build_candidate_batch
    was correctly finishing up (Postgres actually cancelling/rolling back a
    statement is not free). Calls _worker directly (synchronous, no executor
    or event loop involved) so the deadline can be crossed deterministically
    -- not by racing a real sleep against asyncio.wait_for's own, separate
    timeout, which is a different, legitimate enforcement layer covered by
    test_run_trusts_whatever_wait_for_returns below.
    """
    loader, builder = dependencies
    deadline = time.monotonic() + 0.01

    def finishes_just_past_the_deadline(*args, **kwargs):
        time.sleep(0.02)  # _worker's own deadline has now elapsed mid-call
        return batch()

    builder.side_effect = finishes_just_past_the_deadline
    pool = Pool()

    result = runtime.ShadowRunner._worker(
        pool, 'private ID', deadline, datetime.now(timezone.utc), threading.Event())

    assert result == {'status': 'degraded', 'candidates': 1,
                      'legs': {'missing_vector': 1, 'exhausted': 1},
                      'unique_examined': 3, 'rows_returned': 5, 'rounds': 2}


def test_run_trusts_whatever_wait_for_returns(monkeypatch):
    """Same fix, at the run() layer: asyncio.wait_for already raises
    asyncio.TimeoutError (handled separately) when the worker doesn't finish
    in time, and shield() keeps it running either way. If wait_for instead
    returns a result, the worker genuinely finished within its window -- a
    second wall-clock re-check on the way out used to discard that result
    for a race wait_for had already resolved correctly. Mocks wait_for
    directly so this is deterministic: no real thread, deadline, or sleep.
    """
    sentinel = {'status': 'degraded', 'candidates': 99}

    async def fake_wait_for(awaitable, timeout):
        return sentinel

    monkeypatch.setattr(runtime.asyncio, 'wait_for', fake_wait_for)
    # If a stale post-check like `result if time.monotonic() < deadline else
    # ...` still existed, this makes it take the 'else' branch every time.
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: float('inf'))
    runner = runtime.ShadowRunner()

    async def scenario():
        result = await runner.run(Pool(), 'reader')
        assert await runner.aclose()
        return result

    assert asyncio.run(scenario()) is sentinel


def test_worker_and_run_no_longer_recheck_wall_clock_after_a_result_exists():
    """Source-level guard for both fixes above: neither layer should regain
    a post-hoc `time.monotonic() < deadline`-style re-check between getting
    a result and returning it -- that shape is exactly what discarded valid,
    already-computed work in production."""
    import inspect
    worker_source = inspect.getsource(runtime.ShadowRunner._worker)
    run_source = inspect.getsource(runtime.ShadowRunner.run)
    # The only legitimate deadline check in _worker is remaining(), used to
    # bound *waiting* (for a connection, before issuing SQL) -- never called
    # again after build_candidate_batch has already returned a result.
    after_build = worker_source.split('batch = build_candidate_batch', 1)[1]
    assert 'remaining()' not in after_build
    assert 'time.monotonic() < deadline' not in run_source


@pytest.mark.parametrize('snapshot', [None, {'migration_status': 'needs_review'}])
def test_unready_reader_never_builds_or_migrates(dependencies, snapshot):
    loader, builder = dependencies
    loader.return_value = snapshot
    runner = runtime.ShadowRunner()

    async def scenario():
        assert await runner.run(Pool(), 'reader') == {'status': 'reader_unavailable'}
        assert await runner.aclose()

    asyncio.run(scenario())
    builder.assert_not_called()
    assert loader.call_args.kwargs == {'create': False}


@pytest.mark.parametrize('where', ['pool', 'load', 'build'])
def test_failures_do_not_leak_details_and_release_slots(dependencies, where):
    loader, builder = dependencies
    error = RuntimeError('postgres://password private article private query')
    pool = Pool(failure=error if where == 'pool' else None)
    if where == 'load':
        loader.side_effect = error
    if where == 'build':
        builder.side_effect = error
    runner = runtime.ShadowRunner(max_workers=1)

    async def scenario():
        assert await runner.run(pool, 'reader') == {'status': 'unavailable'}
        # Real completion, rather than the request finally block, restores admission.
        assert await runner.run(pool, 'reader') == {'status': 'unavailable'}
        assert await runner.aclose()

    asyncio.run(scenario())
    assert len(pool.calls) == 2 and pool.borrowed == 0


def test_database_cancellation_has_typed_timeout(dependencies):
    dependencies[1].side_effect = QueryCanceled('query text must not escape')
    runner = runtime.ShadowRunner()

    async def scenario():
        assert await runner.run(Pool(), 'reader') == {'status': 'timed_out'}
        assert await runner.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize('cancel', [False, True])
def test_abandoned_worker_keeps_slot_and_connection_until_actual_cleanup(dependencies, cancel):
    entered, release = threading.Event(), threading.Event()

    def blocking_build(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return batch()

    dependencies[1].side_effect = blocking_build
    pool = Pool()
    runner = runtime.ShadowRunner(max_workers=1, deadline_seconds=0.08)

    async def scenario():
        task = asyncio.create_task(runner.run(pool, 'reader'))
        assert await asyncio.to_thread(entered.wait, 1)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task == {'status': 'timed_out'}
        assert pool.borrowed == 1 and not pool.released.is_set()
        assert await runner.run(pool, 'another reader') == {'status': 'busy'}
        assert len(pool.calls) == 1
        release.set()
        assert await runner.aclose()
        assert pool.borrowed == 0

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_pool_cleanup_itself_retains_admission(dependencies):
    cleanup_started, release_cleanup = threading.Event(), threading.Event()

    def cleanup():
        cleanup_started.set()
        assert release_cleanup.wait(2)

    pool = Pool(cleanup=cleanup)
    runner = runtime.ShadowRunner(max_workers=1, deadline_seconds=0.06)

    async def scenario():
        task = asyncio.create_task(runner.run(pool, 'reader'))
        assert await asyncio.to_thread(cleanup_started.wait, 1)
        assert await task == {'status': 'timed_out'}
        assert await runner.run(pool, 'reader') == {'status': 'busy'}
        assert not await runner.aclose(timeout=0.01)
        assert pool.borrowed == 1
        release_cleanup.set()
        assert await runner.aclose()
        assert await runner.run(pool, 'reader') == {'status': 'closed'}

    try:
        asyncio.run(scenario())
    finally:
        release_cleanup.set()


def test_two_workers_are_global_across_callers_and_third_is_not_queued(dependencies):
    release = threading.Event()
    reached_two = threading.Event()
    count_lock = threading.Lock()
    count = 0

    def build(*args, **kwargs):
        nonlocal count
        with count_lock:
            count += 1
            if count == 2:
                reached_two.set()
        assert release.wait(2)
        return batch()

    dependencies[1].side_effect = build
    runner = runtime.ShadowRunner()
    pools = [Pool(), Pool(), Pool()]

    async def scenario():
        calls = [asyncio.create_task(runner.run(pool, 'reader')) for pool in pools[:2]]
        assert await asyncio.to_thread(reached_two.wait, 1)
        assert await runner.run(pools[2], 'reader') == {'status': 'busy'}
        assert not pools[2].calls
        release.set()
        assert all(result['status'] == 'degraded' for result in await asyncio.gather(*calls))
        assert await runner.aclose()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_pool_wait_consumes_same_deadline_and_abandonment_prevents_query(dependencies):
    acquired, release = threading.Event(), threading.Event()
    conn = Connection()

    class SlowPool:
        @contextmanager
        def connection(self, *, timeout):
            assert 0 < timeout <= 0.04
            acquired.set()
            assert release.wait(2)
            yield conn

    runner = runtime.ShadowRunner(max_workers=1, deadline_seconds=0.04)

    async def scenario():
        task = asyncio.create_task(runner.run(SlowPool(), 'reader'))
        assert await asyncio.to_thread(acquired.wait, 1)
        assert await task == {'status': 'timed_out'}
        release.set()
        assert await runner.aclose()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
    dependencies[0].assert_not_called()
    dependencies[1].assert_not_called()
    assert not conn.statements


@pytest.mark.parametrize('options', [{'max_workers': 3}, {'max_workers': 0},
                                    {'deadline_seconds': 3}, {'deadline_seconds': 0}])
def test_bounds_cannot_be_loosened(options):
    with pytest.raises(ValueError):
        runtime.ShadowRunner(**options)


def test_aggregation_drops_untrusted_diagnostics():
    value = batch()
    value.diagnostics.update(unique_examined='reader text', rows_returned=True, rounds=-1)
    result = runtime._aggregate(value)
    assert result['unique_examined'] == result['rows_returned'] == result['rounds'] == 0


@pytest.fixture
def api(monkeypatch):
    import tests._app_stubs  # noqa: F401
    from app import main
    monkeypatch.setattr(main, '_require_auth', lambda value: 'token')
    monkeypatch.setattr(main, '_get_user_id_from_token', lambda *args: 'private reader ID')
    monkeypatch.setattr(main, '_ensure_tables', Mock())
    monkeypatch.setattr(main, 'pool', Mock())
    monkeypatch.setattr(main, 'logger', Mock())
    monkeypatch.delenv('S6_SERVING_ENABLED', raising=False)
    monkeypatch.delenv('S6_SHADOW_ENABLED', raising=False)
    return main


def test_api_default_off_does_not_log_or_borrow(api, monkeypatch):
    runner = Mock()
    monkeypatch.setattr(runtime, '_runner', runner)
    assert asyncio.run(api._observe_s6_retrieval('private reader ID')) is None
    api.pool.connection.assert_not_called()
    runner.run.assert_not_called()
    api.logger.info.assert_not_called()


def test_api_serving_gate_cannot_enable_unreviewed_ranking(api, monkeypatch):
    monkeypatch.setenv('S6_SERVING_ENABLED', 'true')
    monkeypatch.setenv('S6_SHADOW_ENABLED', 'true')
    observation = AsyncMock(return_value={'status': 'empty'})
    monkeypatch.setattr(runtime, 'shadow', observation)
    with pytest.raises(api.HTTPException) as error:
        asyncio.run(api._observe_s6_retrieval('reader'))
    assert error.value.status_code == 503
    observation.assert_not_awaited()
    api.logger.info.assert_not_called()


def test_api_logs_real_runtime_aggregates_without_profile_or_article_data(api, dependencies, monkeypatch):
    monkeypatch.setenv('S6_SHADOW_ENABLED', 'true')
    pool = Pool()
    runner = runtime.ShadowRunner()
    monkeypatch.setattr(runtime, '_runner', runner)
    monkeypatch.setattr(api, 'pool', pool)

    async def scenario():
        assert await api._observe_s6_retrieval('private reader ID') is None
        assert await runner.aclose()

    asyncio.run(scenario())
    api.logger.info.assert_called_once_with('S6 shadow: %s', {
        'status': 'degraded', 'candidates': 1,
        'legs': {'missing_vector': 1, 'exhausted': 1},
        'unique_examined': 3, 'rows_returned': 5, 'rounds': 2,
    })
    rendered = repr(api.logger.info.call_args)
    for secret in ('private reader ID', 'private reader intent', 'raw article', 'intent_id'):
        assert secret not in rendered


@pytest.mark.parametrize('endpoint', ['build_feed', 'get_feed', 'refresh_feed'])
@pytest.mark.parametrize('enabled', [False, True])
def test_api_observation_precedes_final_fences_and_never_changes_feed(api, monkeypatch, endpoint, enabled):
    from app.services import user_source_pipeline, event_integration, reader_integration
    order = []
    feed = {'status': 'ready', 'articles': [{'id': 'final article'}], 'feed_request_id': 'fixed'}

    async def observe(pool, user_id):
        assert pool is api.pool and user_id == 'private reader ID'
        order.append('shadow')
        return {'status': 'degraded', 'candidates': 300} if enabled else {'status': 'disabled'}

    def pipeline(*args, **kwargs):
        order.append('pipeline')
        return feed

    async def build(*args, **kwargs):
        return pipeline(*args, **kwargs)

    def compose(conn, user_id, value, **kwargs):
        order.append('compose')
        assert value is feed
        return value

    def finalize(conn, user_id, value):
        order.append('finalize')
        assert value is feed
        return value

    monkeypatch.setattr(runtime, 'shadow', observe)
    monkeypatch.setattr(user_source_pipeline, 'build_feed_for_user', build)
    monkeypatch.setattr(user_source_pipeline, 'get_feed_state', pipeline)
    monkeypatch.setattr(event_integration, 'compose_feed', compose)
    monkeypatch.setattr(reader_integration, 'finalize_feed', finalize)
    result = asyncio.run(getattr(api, endpoint)(Authorization='token', limit=50, conn=object(),
                                                event_expiry='1'))
    assert order == ['shadow', 'pipeline', 'compose', 'finalize']
    assert result is feed
    assert result == {'status': 'ready', 'articles': [{'id': 'final article'}], 'feed_request_id': 'fixed'}
    if not enabled:
        api.logger.info.assert_not_called()


@pytest.mark.parametrize('endpoint', ['build_feed', 'get_feed', 'refresh_feed'])
def test_api_serving_gate_stops_before_feed_work(api, monkeypatch, endpoint):
    from app.services import user_source_pipeline, event_integration, reader_integration
    monkeypatch.setenv('S6_SERVING_ENABLED', 'true')
    observation = AsyncMock()
    pipeline = AsyncMock()
    cached = Mock()
    compose, finalize = Mock(), Mock()
    monkeypatch.setattr(runtime, 'shadow', observation)
    monkeypatch.setattr(user_source_pipeline, 'build_feed_for_user', pipeline)
    monkeypatch.setattr(user_source_pipeline, 'get_feed_state', cached)
    monkeypatch.setattr(event_integration, 'compose_feed', compose)
    monkeypatch.setattr(reader_integration, 'finalize_feed', finalize)
    with pytest.raises(api.HTTPException) as error:
        asyncio.run(getattr(api, endpoint)(Authorization='token', limit=50, conn=object(),
                                          event_expiry='1'))
    assert error.value.status_code == 503
    observation.assert_not_awaited()
    pipeline.assert_not_awaited()
    cached.assert_not_called()
    compose.assert_not_called()
    finalize.assert_not_called()
    api.logger.exception.assert_not_called()


def test_startup_reuses_active_runner_and_restarts_only_drained_lifespan(dependencies, monkeypatch):
    first = runtime.ShadowRunner()
    monkeypatch.setattr(runtime, '_runner', first)

    async def scenario():
        assert runtime.startup()
        assert runtime._runner is first
        assert await first.run(Pool(), 'reader') == runtime._aggregate(batch())
        assert await runtime.shutdown()
        assert runtime.startup()
        second = runtime._runner
        assert second is not first
        assert await second.run(Pool(), 'reader') == runtime._aggregate(batch())
        assert await runtime.shutdown()

    asyncio.run(scenario())


def test_startup_cannot_bypass_worker_cap_while_previous_lifespan_drains(dependencies, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def blocking_build(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return batch()

    dependencies[1].side_effect = blocking_build
    first = runtime.ShadowRunner(max_workers=1)
    monkeypatch.setattr(runtime, '_runner', first)
    pool = Pool()

    async def scenario():
        task = asyncio.create_task(first.run(pool, 'reader'))
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not await first.aclose(timeout=0)
        assert not runtime.startup()
        assert runtime._runner is first
        assert pool.borrowed == 1
        release.set()
        assert await first.aclose()
        assert runtime.startup()
        assert runtime._runner is not first
        assert pool.borrowed == 0
        assert await runtime.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        release.set()
