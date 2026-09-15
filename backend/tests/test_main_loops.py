"""Phase 0 of S1: leader election, the schema guard, and build identity.

The bugs these pin down were all silent:

* Every background loop ran once per uvicorn worker (`--workers 2`) and once
  per Fly machine, so every feed was fetched two or more times.
* `_per_user_refresh_loop` filtered on `users.last_active_at`, a column that
  was never created. Each tick raised `UndefinedColumn` into a bare `except`,
  so the loop had never run and no reader ever got a rebuilt feed.
* `_ensure_tables` issued ~100 DDL statements on every request handler and
  every 3-minute tick.
* Nothing reported which build was deployed, so a months-old image looked
  identical to a current one.
"""
import os
import sys
import asyncio
import inspect
import logging
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tests._app_stubs as _stubs  # noqa: F401  (installs import-time stubs)
if getattr(_stubs, "SEED_ERROR", None) is not None:
    raise RuntimeError("stub seeding failed") from _stubs.SEED_ERROR

from app import main as app_main


class _Cursor:
    """Cursor over a scripted advisory-lock result. Records every statement."""

    def __init__(self, owner):
        self.owner = owner

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, query, params=None):
        q = " ".join(str(query).split())
        self.owner.executed.append((q, params))
        if "pg_try_advisory_lock" in q:
            key = params[0]
            granted = key not in self.owner.registry
            if granted:
                self.owner.registry.add(key)
            self.owner.result = {"pg_try_advisory_lock": granted}
        elif "pg_advisory_unlock" in q:
            self.owner.registry.discard(params[0])
            self.owner.result = {"pg_advisory_unlock": True}
        else:
            self.owner.result = None

    def fetchone(self):
        return self.owner.result

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, registry, executed):
        self.registry = registry
        self.executed = executed
        self.result = None

    def cursor(self):
        return _Cursor(self)


async def _hang_until_cancelled():
    """Stands in for a background loop in a full-lifespan test: must reach
    `yield` in lifespan() without any loop's real body (which imports heavy
    service modules and touches the DB/network) ever actually running."""
    await asyncio.Event().wait()


class _Pool:
    """Stands in for the psycopg pool, sharing one lock registry across conns."""

    def __init__(self):
        self.registry: set[int] = set()
        self.executed: list[tuple] = []

    def connection(self):
        conn = _Conn(self.registry, self.executed)

        class _Ctx:
            def __enter__(_self):
                return conn

            def __exit__(_self, *a):
                return False

        return _Ctx()


class TestLeaderElection(unittest.TestCase):

    def setUp(self):
        self.pool = _Pool()
        self._p = patch.object(app_main, "pool", self.pool)
        self._p.start()
        app_main._LEADER_OF.clear()

    def tearDown(self):
        self._p.stop()
        app_main._LEADER_OF.clear()

    def test_leader_acquires_and_releases(self):
        with app_main._leader("ingestion") as conn:
            self.assertIsNotNone(conn)
            self.assertIn("ingestion", app_main._LEADER_OF)
            self.assertIn(app_main._LOCK_KEYS["ingestion"], self.pool.registry)
        # released on exit, so the next tick (or another worker) can take it
        self.assertNotIn(app_main._LOCK_KEYS["ingestion"], self.pool.registry)
        statements = [q for q, _ in self.pool.executed]
        self.assertTrue(any("pg_advisory_unlock" in q for q in statements))

    def test_second_holder_is_not_leader(self):
        with app_main._leader("ingestion"):
            with self.assertRaises(app_main._NotLeader):
                with app_main._leader("ingestion"):
                    self.fail("two workers must not both hold the lock")

    def test_lock_released_even_when_the_tick_raises(self):
        with self.assertRaises(ValueError):
            with app_main._leader("ingestion"):
                raise ValueError("tick blew up")
        self.assertNotIn(app_main._LOCK_KEYS["ingestion"], self.pool.registry)
        # a later tick can still become leader
        with app_main._leader("ingestion"):
            pass

    def test_each_loop_elects_independently(self):
        self.assertEqual(len(set(app_main._LOCK_KEYS.values())), len(app_main._LOCK_KEYS))
        with app_main._leader("ingestion"):
            with app_main._leader("per_user_refresh"):
                self.assertEqual(app_main._LEADER_OF, {"ingestion", "per_user_refresh"})

    def test_every_background_loop_is_leader_guarded(self):
        """A new loop that forgets the guard would silently double every fetch."""
        import inspect
        for name in ("_ingestion_loop", "_source_quality_loop",
                     "_interest_evolution_loop", "_per_user_refresh_loop", "_prewarm_loop"):
            source = inspect.getsource(getattr(app_main, name))
            with self.subTest(loop=name):
                self.assertIn("_leader(", source)
                self.assertIn("_NotLeader", source)


class TestPerUserRefreshQuery(unittest.TestCase):

    def test_activity_filter_tolerates_a_null_last_active_at(self):
        """`last_active_at` is only set once a client makes an authenticated
        call; without the COALESCE a brand-new reader is never refreshed."""
        import inspect
        source = inspect.getsource(app_main._active_users_with_sources)
        self.assertIn("COALESCE(u.last_active_at, u.last_login)", source)

    def test_loop_delegates_to_the_standalone_query_function(self):
        """The query lives in _active_users_with_sources specifically so a
        real-Postgres test can exercise it without running the infinite
        loop; guard against it silently being inlined back."""
        import inspect
        source = inspect.getsource(app_main._per_user_refresh_loop)
        self.assertIn("_active_users_with_sources(conn)", source)
        self.assertNotIn("SELECT DISTINCT", source)

    def test_schema_creates_last_active_at(self):
        """The column the loop filters on must actually exist."""
        import inspect
        source = inspect.getsource(app_main._ensure_tables)
        self.assertIn("ADD COLUMN IF NOT EXISTS last_active_at", source)

    def test_auth_path_marks_the_reader_active(self):
        import inspect
        source = inspect.getsource(app_main._get_user_id_from_token)
        self.assertIn("last_active_at = now()", source)
        self.assertIn("interval '5 minutes'", source)   # throttled, not per request


class TestSchemaGuard(unittest.TestCase):

    def setUp(self):
        self._prev = app_main._schema_ready
        app_main._schema_ready = False

    def tearDown(self):
        app_main._schema_ready = self._prev

    def test_runs_once_then_short_circuits(self):
        calls = []

        def fake_chat_tables(conn):
            calls.append(conn)

        pool = _Pool()
        conn = _Conn(pool.registry, pool.executed)
        with patch.object(app_main.chat_repository, "ensure_chat_tables", fake_chat_tables):
            app_main._ensure_tables(conn)
            self.assertEqual(len(calls), 1)
            self.assertTrue(app_main._schema_ready)

            app_main._ensure_tables(conn)          # second call is a no-op
            self.assertEqual(len(calls), 1)

            app_main._ensure_tables(conn, force=True)
            self.assertEqual(len(calls), 2)

    def test_readiness_fails_when_schema_initialization_never_completed(self):
        payload = asyncio.run(app_main.readyz())
        self.assertEqual(payload.status_code, 503)

    def test_readiness_checks_the_s2_schema_signature(self):
        app_main._schema_ready = True
        pool = _Pool()
        with patch.object(app_main, "pool", pool), patch.object(
            app_main, "_s2_schema_is_ready", return_value=False
        ) as verify:
            payload = asyncio.run(app_main.readyz())
        self.assertEqual(payload.status_code, 503)
        verify.assert_called_once()

    def test_startup_fails_closed_when_schema_setup_raises(self):
        class StartupPool(_Pool):
            def __init__(self):
                super().__init__()
                self.closed = False

            def close(self):
                self.closed = True

        startup_pool = StartupPool()

        async def start():
            async with app_main.lifespan(None):
                self.fail("lifespan must not yield after schema failure")

        with patch.object(app_main, "ConnectionPool", return_value=startup_pool), patch.object(
            app_main, "_ensure_tables", side_effect=RuntimeError("broken schema")
        ):
            with self.assertRaisesRegex(RuntimeError, "broken schema"):
                asyncio.run(start())
        self.assertTrue(startup_pool.closed)


class TestDrainShadowObservationTasks(unittest.TestCase):
    """_drain_shadow_observation_tasks runs in lifespan()'s shutdown, right
    before pool.close(): a fire-and-forget shadow-observation task left
    running when the pool closes gets a swallowed PoolClosed error instead of
    a clean result -- see the comment at its call site in lifespan().
    """

    def test_waits_for_a_pending_task_to_finish(self):
        async def scenario():
            finished = asyncio.Event()

            async def slow():
                await asyncio.sleep(0.01)
                finished.set()

            task = asyncio.create_task(slow())
            app_main._shadow_observation_tasks.add(task)
            task.add_done_callback(app_main._shadow_observation_tasks.discard)
            await app_main._drain_shadow_observation_tasks(timeout=5)
            self.assertTrue(finished.is_set())
            self.assertNotIn(task, app_main._shadow_observation_tasks)

        asyncio.run(scenario())

    def test_gives_up_after_its_own_timeout_without_raising(self):
        async def scenario():
            async def stuck():
                await asyncio.sleep(10)

            task = asyncio.create_task(stuck())
            app_main._shadow_observation_tasks.add(task)
            try:
                await app_main._drain_shadow_observation_tasks(timeout=0.01)  # must not raise
                self.assertFalse(task.done())
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                app_main._shadow_observation_tasks.discard(task)

        asyncio.run(scenario())

    def test_no_pending_tasks_returns_immediately(self):
        app_main._shadow_observation_tasks.clear()
        asyncio.run(app_main._drain_shadow_observation_tasks(timeout=5))  # must not hang


class TestPrewarm(unittest.TestCase):
    """S6's lexical retrieval hot set (articles + its GIN index) is loaded
    into shared_buffers explicitly at startup and re-loaded periodically,
    rather than relying on real request traffic to keep it resident -- see
    _prewarm_relations's docstring for the measured sizes and why this
    should stay resident under normal load without help.
    """

    def test_prewarm_relations_loads_both_known_relations(self):
        pool = _Pool()
        conn = _Conn(pool.registry, pool.executed)
        app_main._prewarm_relations(conn)
        prewarmed = [params[0] for q, params in pool.executed if "pg_prewarm" in q]
        self.assertEqual(prewarmed, list(app_main._PREWARM_RELATIONS))

    def test_a_failing_relation_does_not_stop_the_rest(self):
        class FlakyCursor(_Cursor):
            def execute(self, query, params=None):
                if params and params[0] == "public.articles":
                    raise RuntimeError("relation renamed or extension missing")
                return super().execute(query, params)

        class FlakyConn(_Conn):
            def cursor(self):
                return FlakyCursor(self)

        pool = _Pool()
        conn = FlakyConn(pool.registry, pool.executed)
        app_main._prewarm_relations(conn)  # must not raise
        prewarmed = [params[0] for q, params in pool.executed if "pg_prewarm" in q]
        self.assertIn("public.reader_article_lexical_v2", prewarmed)

    def test_startup_prewarm_failure_does_not_block_app_startup(self):
        """Unlike a schema-setup failure (fatal, see test_startup_fails_closed_
        when_schema_setup_raises), a pg_prewarm failure is a latency
        optimization, not a dependency -- lifespan must still reach its
        background loops and yield.
        """
        class StartupPool(_Pool):
            def close(self):
                pass

        pool = StartupPool()

        async def start():
            async with app_main.lifespan(None):
                return "started"

        with patch.object(app_main, "ConnectionPool", return_value=pool), patch.object(
            app_main, "_prewarm_relations", side_effect=RuntimeError("boom")
        ), patch.object(app_main, "_ingestion_loop", _hang_until_cancelled), patch.object(
            app_main, "_source_quality_loop", _hang_until_cancelled
        ), patch.object(
            app_main, "_interest_evolution_loop", _hang_until_cancelled
        ), patch.object(
            app_main, "_per_user_refresh_loop", _hang_until_cancelled
        ), patch.object(
            app_main, "_prewarm_loop", _hang_until_cancelled
        ):
            result = asyncio.run(asyncio.wait_for(start(), timeout=5))
        self.assertEqual(result, "started")


class TestBuildIdentity(unittest.TestCase):

    def test_healthz_reports_the_build(self):
        import asyncio
        payload = asyncio.run(app_main.healthz())
        self.assertEqual(payload["status"], "ok")
        self.assertIn("git_sha", payload)
        self.assertIn("started_at", payload)
        self.assertIsInstance(payload["leader_of"], list)

    def test_git_sha_falls_back_to_unknown_not_a_crash(self):
        self.assertTrue(app_main.GIT_SHA)
        self.assertLessEqual(len(app_main.GIT_SHA), 40)


class TestArticleDetailAuthentication(unittest.TestCase):

    def test_invalid_bearer_is_rejected_before_article_lookup(self):
        executed = []
        conn = _Conn(set(), executed)
        from contextlib import nullcontext
        conn.transaction = nullcontext
        async def phase(pool, operation, **kwargs):
            return operation(conn)

        with patch('app.services.ranking_service.database_phase', phase), self.assertRaises(app_main.HTTPException) as raised:
            asyncio.run(
                app_main.get_feed_article(
                    "00000000-0000-0000-0000-000000000001",
                    Authorization="Bearer definitely-invalid",
                )
            )

        self.assertEqual(raised.exception.status_code, 401)
        statements = [query for query, _params in executed]
        self.assertTrue(any("public.sessions" in query for query in statements))
        self.assertFalse(any("public.articles" in query for query in statements))

    def test_semantic_search_uses_presentation_serializer_not_raw_content(self):
        import inspect

        source = inspect.getsource(app_main.semantic_search)
        self.assertIn("serialize_article", source)
        self.assertNotIn('"content": row.get("content")', source)
        self.assertIn("embedding_content_version = a.analysis_content_version", source)


class TestStableAdvisoryLockKey(unittest.TestCase):
    """S1 2.2: /sources/discover's duplicate-request guard used
    `abs(hash(user_id)) % (2**31)` as its pg_advisory_lock key. Python's
    hash() for str is randomized per-process (PYTHONHASHSEED) unless
    pinned, and the app runs `--workers 2` -- two concurrent requests for
    the same user landing on different workers computed different keys for
    "the same" lock, so the 409 could silently fail to serialize.
    """

    def test_key_is_identical_across_simulated_processes(self):
        # A subprocess with a different (or unset/random) PYTHONHASHSEED is
        # the real-world case this bug depended on; hash() itself is not
        # patchable in-process (it's a builtin), so this drives the actual
        # concern directly: does the key computation ever consult the `hash`
        # builtin at all? It must not, for any input, for the guarantee to
        # hold. Checked at the bytecode level (co_names), not by grepping
        # source text, so a mention of "hash(" in a comment/docstring can't
        # produce a false failure here.
        self.assertNotIn("hash", app_main._stable_advisory_lock_key.__code__.co_names)
        self.assertIn("sha256", app_main._stable_advisory_lock_key.__code__.co_names)

        user_id = "11111111-2222-3333-4444-555555555555"
        key_a = app_main._stable_advisory_lock_key(user_id)
        key_b = app_main._stable_advisory_lock_key(user_id)
        self.assertEqual(key_a, key_b)

    def test_key_is_a_valid_bigint_and_differs_across_users(self):
        key = app_main._stable_advisory_lock_key("user-a")
        self.assertIsInstance(key, int)
        self.assertGreaterEqual(key, 0)
        self.assertLess(key, 2**63)  # pg_advisory_lock takes a signed bigint
        self.assertNotEqual(key, app_main._stable_advisory_lock_key("user-b"))

    def test_discover_sources_uses_the_stable_key_not_hash(self):
        import inspect

        source = inspect.getsource(app_main.discover_sources)
        self.assertIn("_stable_advisory_lock_key(user_id)", source)
        self.assertNotIn("hash(user_id)", source)


if __name__ == "__main__":
    unittest.main()


class SchemaSetupConcurrencyTests(unittest.TestCase):
    """`_ensure_tables` runs in both uvicorn workers at once.

    `CREATE INDEX IF NOT EXISTS` is not atomic against a concurrent identical
    CREATE -- both sessions see it missing, both proceed, the loser raises
    UniqueViolation on pg_class, and lifespan re-raises, so that worker exits
    with "Application startup failed". Observed live on the 2026-09-13
    production deploy (idx_sessions_user). Self-healing via respawn, but it
    means every deploy adding an index is a coin flip on a startup crash.
    """

    def test_schema_setup_is_serialized_by_an_advisory_lock(self):
        source = " ".join(inspect.getsource(app_main._ensure_tables).split())
        self.assertIn("pg_advisory_lock", source)
        self.assertIn("pg_advisory_unlock", source)

    def test_the_lock_is_released_even_when_the_ddl_raises(self):
        """A worker that fails mid-DDL must not wedge every other worker."""
        source = " ".join(inspect.getsource(app_main._ensure_tables).split())
        self.assertIn("finally:", source)

    def test_the_schema_key_collides_with_no_loop_key(self):
        self.assertNotIn(app_main._SCHEMA_LOCK_KEY, set(app_main._LOCK_KEYS.values()))


class LoggingConfigurationTests(unittest.TestCase):
    """Nothing configured logging, so root sat at WARNING with no handlers and
    every `logger.info` was a silent no-op in production -- including both
    shadow observations, which is the entire output shadow mode exists to
    produce. Confirmed live: `logging.getLogger('app.main').getEffectiveLevel()`
    was WARNING on the deployed machine."""

    # Asserted against the module source rather than the live logger: pytest's
    # own logging plugin installs a root handler, which makes `basicConfig` a
    # no-op and the runtime level an artefact of the test harness rather than
    # of production. The source is what ships.
    def test_logging_is_configured_at_import(self):
        source = open(app_main.__file__).read()
        self.assertIn("logging.basicConfig(", source)

    def test_it_defaults_to_info_so_shadow_observations_are_visible(self):
        source = open(app_main.__file__).read()
        self.assertIn('os.getenv("LOG_LEVEL", "INFO")', source)

    def test_shadow_observations_are_logged_at_that_level(self):
        """If these ever move above INFO the default stops being useful."""
        source = " ".join(inspect.getsource(app_main._run_shadow_observation).split())
        self.assertIn('logger.info("S7 shadow', source)
        self.assertIn('logger.info("S6 shadow', source)
