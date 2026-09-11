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
                     "_interest_evolution_loop", "_per_user_refresh_loop"):
            source = inspect.getsource(getattr(app_main, name))
            with self.subTest(loop=name):
                self.assertIn("_leader(", source)
                self.assertIn("_NotLeader", source)


class TestPerUserRefreshQuery(unittest.TestCase):

    def test_activity_filter_tolerates_a_null_last_active_at(self):
        """`last_active_at` is only set once a client makes an authenticated
        call; without the COALESCE a brand-new reader is never refreshed."""
        import inspect
        source = inspect.getsource(app_main._per_user_refresh_loop)
        self.assertIn("COALESCE(u.last_active_at, u.last_login)", source)

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


if __name__ == "__main__":
    unittest.main()
