"""Real PostgreSQL contract tests for account deletion and session revocation.

Opt-in, same shape as the other `*_postgres.py` suites::

    S1_TEST_DATABASE_URL=postgresql:///postgres pytest -q \
        backend/tests/test_account_lifecycle_postgres.py

A mocked cursor cannot prove any of this. The whole point of the feature is
that `DELETE FROM public.users` fans out across ~25 `ON DELETE CASCADE`
foreign keys -- a fake connection would happily accept the statement and prove
nothing about whether a single row actually went away. The load-bearing test
here is `test_no_user_scoped_table_survives_deletion`, which reads the live
schema rather than a hand-maintained list, so adding a new user-scoped table
without wiring it into deletion fails the build instead of quietly orphaning
that user's rows forever.
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
from app.services import account_lifecycle

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
def account_database_url():
    if not BASE_DATABASE_URL:
        pytest.skip("S1_TEST_DATABASE_URL is not set")

    database_name = f"daily_account_test_{os.getpid()}_{secrets.token_hex(4)}"
    admin = psycopg.connect(BASE_DATABASE_URL, autocommit=True, row_factory=dict_row)
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except Exception as exc:
        admin.close()
        if REQUIRED:
            pytest.fail(f"Required account-lifecycle PostgreSQL setup failed: {exc}")
        pytest.skip(f"Account-lifecycle PostgreSQL tests require CREATEDB rights: {exc}")

    try:
        yield _database_url(BASE_DATABASE_URL, database_name)
    finally:
        try:
            with admin.cursor() as cur:
                try:
                    cur.execute(
                        sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
                    )
                except Exception:
                    cur.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (database_name,),
                    )
                    cur.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name))
                    )
        finally:
            admin.close()


@pytest.fixture(scope="module")
def _schema_ready(account_database_url):
    """Install the boot schema plus every optional S5/S7/S8 schema.

    Deletion has to be correct on a database where the optional additive
    schemas *are* installed -- that is the configuration with the most
    user-scoped tables and therefore the most ways to orphan a row. The
    `to_regclass` guards cover the other direction (schema absent).
    """
    with psycopg.connect(account_database_url, autocommit=True, row_factory=dict_row) as connection:
        app_main._ensure_tables(connection, force=True)
        from app.services.chat_repository import ensure_chat_tables
        from app.services.reader_feedback import install_schema as install_feedback
        from app.services.reader_repository import install_schema as install_reader

        ensure_chat_tables(connection)
        install_reader(connection)
        install_feedback(connection)
        for installer in _optional_installers():
            try:
                installer(connection)
            except Exception:  # pragma: no cover - optional schema, best effort
                pass


def _optional_installers():
    from app.services.assembly_repository import install_schema as install_assembly
    from app.services.ranking_repository import install_schema as install_ranking
    from app.services.reader_worker import install_schema as install_embeddings

    return (install_ranking, install_assembly, install_embeddings)


@pytest.fixture()
def conn(account_database_url, _schema_ready):
    # Deletion opens its own transactions, so these tests commit and clean up
    # after themselves by construction: every row they create belongs to a
    # throwaway account that the test then deletes.
    with psycopg.connect(account_database_url, autocommit=True, row_factory=dict_row) as connection:
        yield connection


def _make_user(conn) -> str:
    user_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.users (id, email, display_name, photo_url, last_login, last_active_at) "
            "VALUES (%s, %s, %s, %s, now(), now())",
            (user_id, f"{user_id}@example.com", "Test Reader", "https://example.com/p.png"),
        )
    return user_id


def _make_session(conn, user_id: str, *, expired: bool = False) -> str:
    token = secrets.token_urlsafe(24)
    expiry = "now() - interval '1 day'" if expired else "now() + interval '30 days'"
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.sessions (user_id, token_hash, expires_at) VALUES (%s, %s, "
            + expiry
            + ")",
            (user_id, account_lifecycle.hash_token(token)),
        )
    return token


def _seed_user_rows(conn, user_id: str) -> None:
    """Put a row in every table this account could plausibly own."""
    article_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO public.articles (id, title, url, source_name) VALUES (%s, %s, %s, %s)",
            (article_id, "Seed", f"https://example.com/{secrets.token_hex(6)}", "example.com"),
        )
        cur.execute(
            "INSERT INTO public.user_identities (user_id, provider, provider_user_id, email) "
            "VALUES (%s, 'google', %s, %s)",
            (user_id, secrets.token_hex(8), f"{user_id}@example.com"),
        )
        cur.execute(
            "INSERT INTO public.user_preferences (user_id, interests) VALUES (%s, %s)",
            (user_id, "[]"),
        )
        cur.execute(
            "INSERT INTO public.user_sources (user_id, source_url, active) VALUES (%s, %s, true)",
            (user_id, f"https://example.com/{secrets.token_hex(4)}/feed.xml"),
        )
        cur.execute(
            "INSERT INTO public.user_feed_cache (user_id, article_id, relevance_score) VALUES (%s, %s, 1.0)",
            (user_id, article_id),
        )
        cur.execute(
            "INSERT INTO public.reading_events (user_id, article_id, event_type) VALUES (%s, %s, 'tap')",
            (user_id, article_id),
        )
        cur.execute(
            "INSERT INTO public.feed_build_log (user_id, git_sha, kept) VALUES (%s, 'test', 1)",
            (user_id,),
        )
        cur.execute(
            "SELECT to_regclass('public.ranking_budget') AS relation",
        )
        if cur.fetchone()["relation"]:
            cur.execute(
                "INSERT INTO public.ranking_budget (day, account, committed_usd) "
                "VALUES (current_date, %s, 0) ON CONFLICT DO NOTHING",
                (user_id,),
            )


def _row_counts(conn, user_id: str) -> dict[str, int]:
    counts = {}
    with conn.cursor() as cur:
        for table, column in (
            ("users", "id"),
            ("user_identities", "user_id"),
            ("user_preferences", "user_id"),
            ("user_sources", "user_id"),
            ("user_feed_cache", "user_id"),
            ("reading_events", "user_id"),
            ("sessions", "user_id"),
            ("feed_build_log", "user_id"),
        ):
            cur.execute(
                "SELECT count(*) AS n FROM public." + table + " WHERE " + column + "::text = %s",
                (user_id,),
            )
            counts[table] = cur.fetchone()["n"]
    return counts


# ---------------------------------------------------------------------------
# Session revocation
# ---------------------------------------------------------------------------


def test_revoking_one_session_leaves_the_others_alone(conn):
    user_id = _make_user(conn)
    phone = _make_session(conn, user_id)
    laptop = _make_session(conn, user_id)

    assert account_lifecycle.revoke_session(conn, phone) is True

    assert app_main._get_user_id_from_token(conn, laptop) == user_id
    with pytest.raises(Exception):
        app_main._get_user_id_from_token(conn, phone)


def test_revoking_the_same_session_twice_is_idempotent(conn):
    user_id = _make_user(conn)
    token = _make_session(conn, user_id)

    assert account_lifecycle.revoke_session(conn, token) is True
    assert account_lifecycle.revoke_session(conn, token) is False


def test_revoke_all_sessions_signs_out_every_device(conn):
    user_id = _make_user(conn)
    tokens = [_make_session(conn, user_id) for _ in range(3)]
    other_user = _make_user(conn)
    other_token = _make_session(conn, other_user)

    assert account_lifecycle.revoke_all_sessions(conn, user_id) == 3

    for token in tokens:
        with pytest.raises(Exception):
            app_main._get_user_id_from_token(conn, token)
    # A bulk revoke is scoped to one account, not the table.
    assert app_main._get_user_id_from_token(conn, other_token) == other_user


def test_expired_sessions_are_swept_and_live_ones_are_not(conn):
    user_id = _make_user(conn)
    live = _make_session(conn, user_id)
    _make_session(conn, user_id, expired=True)

    swept = account_lifecycle.purge_expired_sessions(conn)

    assert swept >= 1
    assert app_main._get_user_id_from_token(conn, live) == user_id


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


def test_soft_delete_kills_the_account_before_any_cascade_runs(conn):
    user_id = _make_user(conn)
    token = _make_session(conn, user_id)
    _seed_user_rows(conn, user_id)

    assert account_lifecycle.soft_delete_account(conn, user_id) is True

    with conn.cursor() as cur:
        cur.execute(
            "SELECT is_deleted, deleted_at, email, display_name, photo_url "
            "FROM public.users WHERE id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    # Still present -- the purge hasn't run -- but dead and scrubbed.
    assert row["is_deleted"] is True
    assert row["deleted_at"] is not None
    assert (row["email"], row["display_name"], row["photo_url"]) == (None, None, None)
    with pytest.raises(Exception):
        app_main._get_user_id_from_token(conn, token)
    assert _row_counts(conn, user_id)["sessions"] == 0
    assert _row_counts(conn, user_id)["user_identities"] == 0

    account_lifecycle.purge_account(conn, user_id)


def test_soft_delete_is_idempotent(conn):
    user_id = _make_user(conn)
    assert account_lifecycle.soft_delete_account(conn, user_id) is True
    assert account_lifecycle.soft_delete_account(conn, user_id) is False
    account_lifecycle.purge_account(conn, user_id)


def test_purge_refuses_to_touch_a_live_account(conn):
    user_id = _make_user(conn)
    _seed_user_rows(conn, user_id)

    assert account_lifecycle.purge_account(conn, user_id) is False

    assert _row_counts(conn, user_id)["users"] == 1


def test_delete_account_removes_every_row_including_the_unlinked_ones(conn):
    user_id = _make_user(conn)
    _make_session(conn, user_id)
    _seed_user_rows(conn, user_id)
    before = _row_counts(conn, user_id)
    assert all(count > 0 for count in before.values()), before

    outcome = account_lifecycle.delete_account(conn, user_id)

    assert outcome == {"deleted": True, "purged": True}
    after = _row_counts(conn, user_id)
    assert after == {table: 0 for table in after}, after


def test_deleting_one_account_does_not_touch_another(conn):
    doomed = _make_user(conn)
    keeper = _make_user(conn)
    _make_session(conn, doomed)
    _make_session(conn, keeper)
    _seed_user_rows(conn, doomed)
    _seed_user_rows(conn, keeper)

    account_lifecycle.delete_account(conn, doomed)

    keeper_counts = _row_counts(conn, keeper)
    assert all(count > 0 for count in keeper_counts.values()), keeper_counts
    account_lifecycle.delete_account(conn, keeper)


def test_sweeper_finishes_a_purge_that_never_ran_inline(conn):
    """The failure this guards: step 2 lost a race and nothing else retried it."""
    user_id = _make_user(conn)
    _seed_user_rows(conn, user_id)
    assert account_lifecycle.soft_delete_account(conn, user_id) is True
    assert _row_counts(conn, user_id)["users"] == 1

    assert account_lifecycle.purge_pending_accounts(conn) >= 1

    assert _row_counts(conn, user_id)["users"] == 0


def test_sweeper_never_purges_a_live_account(conn):
    user_id = _make_user(conn)
    _seed_user_rows(conn, user_id)

    account_lifecycle.purge_pending_accounts(conn)

    assert _row_counts(conn, user_id)["users"] == 1
    account_lifecycle.delete_account(conn, user_id)


def test_no_user_scoped_table_survives_deletion(conn):
    """Read the live schema and prove the purge is exhaustive.

    A hand-written list of tables would be correct exactly once. This walks
    `pg_constraint` for the transitive `ON DELETE CASCADE` closure of
    `public.users` and checks it against every base table that stores a
    `user_id`/`account` column, so the day someone adds a user-scoped table
    without a cascading FK, this fails instead of orphaning rows in production.
    """
    buckets = account_lifecycle.user_scoped_tables(conn)

    assert buckets["uncovered"] == [], (
        "These tables store a per-user column but nothing deletes their rows when "
        "the account goes away. Add a cascading FK to public.users, or list them in "
        f"account_lifecycle._ORPHAN_USER_TABLES: {buckets['uncovered']}"
    )
    # Sanity: the introspection is actually finding things, not silently empty.
    assert "sessions" in buckets["cascaded"]
    assert "reading_events" in buckets["cascaded"]
    assert "feed_build_log" in buckets["explicit"]


def test_a_deleted_reader_signing_in_again_gets_a_fresh_account(conn):
    """Deletion means deletion: the old rows must not re-attach to a new login."""
    email = f"repeat-{secrets.token_hex(4)}@example.com"
    first = app_main._upsert_user_from_oauth(
        conn, {"provider": "google", "provider_user_id": secrets.token_hex(8), "email": email}
    )
    account_lifecycle.delete_account(conn, first["id"])

    second = app_main._upsert_user_from_oauth(
        conn, {"provider": "google", "provider_user_id": secrets.token_hex(8), "email": email}
    )

    assert second["id"] != first["id"]
    account_lifecycle.delete_account(conn, second["id"])


# ---------------------------------------------------------------------------
# Retention (Phase 7.5) -- the article GC is also the behavioural-signal policy
# ---------------------------------------------------------------------------


def test_gcing_an_article_takes_its_reading_events_with_it(conn):
    """The coupling `app/services/retention.py` documents, executed for real.

    A source-level test can assert the FK text; only a server can prove the
    cascade fires, and that the surviving event is the one whose article is
    still in the pool -- the distinction the decision record turns on.
    """
    from app.services.retention import ARTICLE_RETENTION_DAYS

    user_id = _make_user(conn)
    old_article, fresh_article = str(uuid.uuid4()), str(uuid.uuid4())
    with conn.cursor() as cur:
        for article_id, age_days in ((old_article, ARTICLE_RETENTION_DAYS + 1), (fresh_article, 1)):
            cur.execute(
                "INSERT INTO public.articles (id, title, url, ingested_at) "
                "VALUES (%s, %s, %s, now() - make_interval(days => %s))",
                (article_id, "Seed", f"https://example.com/{secrets.token_hex(6)}", age_days),
            )
            cur.execute(
                "INSERT INTO public.reading_events (user_id, article_id, event_type, created_at) "
                "VALUES (%s, %s, 'tap', now())",
                (user_id, article_id),
            )
        # Exactly the ingestion loop's statement.
        cur.execute(
            "DELETE FROM public.articles WHERE ingested_at < now() - make_interval(days => %s)",
            (ARTICLE_RETENTION_DAYS,),
        )
        cur.execute(
            "SELECT article_id::text AS article_id FROM public.reading_events WHERE user_id = %s",
            (user_id,),
        )
        surviving = [row["article_id"] for row in cur.fetchall()]

    # The tap on the aged-out article is gone even though it was logged seconds
    # ago: retention is keyed on the article's age, never the event's.
    assert surviving == [fresh_article]
    account_lifecycle.delete_account(conn, user_id)
