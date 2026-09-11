"""Real PostgreSQL contract test for `_active_users_with_sources`.

The suite is opt-in because it needs a PostgreSQL server and CREATEDB rights::

    S1_TEST_DATABASE_URL=postgresql:///postgres pytest -q \
        backend/tests/test_main_loops_postgres.py

The configured database is never modified. A uniquely named database is
created on the same server for the test run and dropped afterwards.

This is the first Postgres-integration test for the core app/S1 layer
(unlike S2-S8, it had none before). It exists because
`_active_users_with_sources`'s query has broken twice in ways no
source-inspection test could catch, since both bugs only manifest against a
real Postgres server: a reference to a column that didn't exist yet, and
later `u.id::text = us.user_id` -- a genuine `text = uuid` operator error
that a mocked cursor happily accepts as just another `execute()` call.
"""
from __future__ import annotations

import os
import secrets
import uuid

import pytest

REQUIRED = os.getenv("S1_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

import tests._app_stubs  # noqa: F401  (installs import-time stubs)
from app import main as app_main

BASE_DATABASE_URL = os.getenv("S1_TEST_DATABASE_URL")
if REQUIRED and not BASE_DATABASE_URL:
    raise RuntimeError("S1_TEST_DATABASE_REQUIRED=1 requires S1_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_DATABASE_URL,
    reason="set S1_TEST_DATABASE_URL to a disposable PostgreSQL server",
)


def _database_url(base_url: str, database: str) -> str:
    parameters = conninfo_to_dict(base_url)
    parameters["dbname"] = database
    return make_conninfo(**parameters)


@pytest.fixture(scope="module")
def s1_database_url():
    if not BASE_DATABASE_URL:
        pytest.skip("S1_TEST_DATABASE_URL is not set")

    database_name = f"daily_s1_test_{os.getpid()}_{secrets.token_hex(4)}"
    admin = psycopg.connect(BASE_DATABASE_URL, autocommit=True, row_factory=dict_row)
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except Exception as exc:
        admin.close()
        if REQUIRED:
            pytest.fail(f"Required S1 PostgreSQL setup failed: {exc}")
        pytest.skip(f"S1 PostgreSQL tests require CREATEDB rights: {exc}")

    test_url = _database_url(BASE_DATABASE_URL, database_name)
    try:
        yield test_url
    finally:
        try:
            with admin.cursor() as cur:
                try:
                    cur.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                            sql.Identifier(database_name)
                        )
                    )
                except Exception:
                    cur.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (database_name,),
                    )
                    cur.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {}").format(
                            sql.Identifier(database_name)
                        )
                    )
        finally:
            admin.close()


@pytest.fixture(scope="module")
def _schema_ready(s1_database_url):
    """Create the schema once per disposable database; tests isolate their
    own rows via a per-test transaction rollback instead of a fresh DB each."""
    with psycopg.connect(s1_database_url, autocommit=True, row_factory=dict_row) as connection:
        app_main._ensure_tables(connection, force=True)


@pytest.fixture()
def conn(s1_database_url, _schema_ready):
    # autocommit=False (the default): each test runs in its own transaction,
    # rolled back on teardown, so rows inserted by one test never leak into
    # the next even though they share one disposable database.
    with psycopg.connect(s1_database_url, row_factory=dict_row) as connection:
        yield connection
        connection.rollback()


def _insert_user(conn, *, active_recently: bool) -> str:
    user_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        if active_recently:
            cur.execute(
                "INSERT INTO public.users (id, email, last_login, last_active_at) "
                "VALUES (%s, %s, now(), NULL)",
                (user_id, f"{user_id}@example.com"),
            )
        else:
            cur.execute(
                "INSERT INTO public.users (id, email, last_login, last_active_at) "
                "VALUES (%s, %s, now() - interval '10 days', NULL)",
                (user_id, f"{user_id}@example.com"),
            )
    return user_id


def _insert_source(conn, user_id: str, *, active: bool = True) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.user_sources (user_id, source_url, active) "
            "VALUES (%s, %s, %s)",
            (user_id, f"https://example.com/{secrets.token_hex(4)}/feed.xml", active),
        )


def test_returns_recently_active_users_with_a_source_as_plain_strings(conn):
    """The exact bug this pins down: comparing `u.id` (uuid) against
    `us.user_id` (also uuid, not text) must not raise UndefinedFunction, and
    every downstream caller (`build_feed_for_user`) expects a plain str."""
    user_id = _insert_user(conn, active_recently=True)
    _insert_source(conn, user_id)

    result = app_main._active_users_with_sources(conn)

    assert result == [user_id]
    assert all(isinstance(uid, str) for uid in result)


def test_excludes_users_without_recent_activity(conn):
    user_id = _insert_user(conn, active_recently=False)
    _insert_source(conn, user_id)

    assert app_main._active_users_with_sources(conn) == []


def test_excludes_users_with_only_inactive_sources(conn):
    user_id = _insert_user(conn, active_recently=True)
    _insert_source(conn, user_id, active=False)

    assert app_main._active_users_with_sources(conn) == []


def test_deduplicates_a_user_with_multiple_sources(conn):
    user_id = _insert_user(conn, active_recently=True)
    _insert_source(conn, user_id)
    _insert_source(conn, user_id)

    assert app_main._active_users_with_sources(conn) == [user_id]
