"""Opt-in S8 SQL tests in a newly created disposable database, never DATABASE_URL.

No semantic/provider claims. S8_TEST_DATABASE_REQUIRED=1 makes missing setup fail.
Publication-lock probes exercise the documented article/reader protocol; S6's
full schema and end-to-end authorization remain covered by its separate SQL job.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import os
import secrets
from uuid import UUID

import pytest

REQUIRED = os.getenv("S8_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.services import assembly_repository as repo, reader_feedback
from app.services.assembly_contract import RECIPE

BASE_URL = os.getenv("S8_TEST_DATABASE_URL")
if REQUIRED and not BASE_URL:
    raise RuntimeError("S8_TEST_DATABASE_REQUIRED=1 requires S8_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="S8_TEST_DATABASE_URL is not set")
USER, OTHER, ARTICLE, EDITION, EVENT = [str(UUID(int=value)) for value in range(81001, 81006)]


@pytest.fixture(scope="session")
def s8_database_url():
    name = f"daily_s8_test_{os.getpid()}_{secrets.token_hex(8)}"
    admin, created = None, False
    try:
        try:
            admin = psycopg.connect(BASE_URL, autocommit=True, connect_timeout=10)
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
            parameters = conninfo_to_dict(BASE_URL)
            parameters["dbname"] = name
            test_url = make_conninfo(**parameters)
            with psycopg.connect(test_url, autocommit=True, row_factory=dict_row) as conn:
                conn.execute("""CREATE TABLE public.users(id uuid PRIMARY KEY, is_deleted boolean DEFAULT false);
                  CREATE TABLE public.reader_profiles(user_id uuid PRIMARY KEY REFERENCES public.users(id)
                    ON DELETE CASCADE,generation bigint NOT NULL DEFAULT 1);
                  CREATE TABLE public.articles(id uuid PRIMARY KEY);
                  CREATE TABLE public.reading_events(id bigserial PRIMARY KEY,
                    user_id uuid REFERENCES public.users(id) ON DELETE CASCADE,
                    article_id uuid REFERENCES public.articles(id) ON DELETE CASCADE,
                    event_type text,duration_seconds integer,feed_request_id uuid,
                    position_in_feed integer,created_at timestamptz DEFAULT now());
                  CREATE TABLE public.story_clusters(id uuid PRIMARY KEY,recipe_id text,version bigint);
                  CREATE TABLE public.story_memberships(article_id uuid PRIMARY KEY REFERENCES public.articles(id),
                    cluster_id uuid REFERENCES public.story_clusters(id),recipe_id text,version bigint)""")
                reader_feedback.install_schema(conn)
                repo.install_schema(conn)
        except Exception as exc:
            reason = f"S8 PostgreSQL setup unavailable ({type(exc).__name__})"
            if REQUIRED:
                pytest.fail(reason)
            pytest.skip(reason)
        yield test_url
    finally:
        if admin is not None:
            try:
                if created:
                    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            finally:
                admin.close()


@pytest.fixture
def db(s8_database_url):
    with psycopg.connect(s8_database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("TRUNCATE public.users,public.articles,public.story_clusters,public.assembly_control CASCADE")
        conn.execute("INSERT INTO public.users(id) VALUES(%s),(%s)", (USER, OTHER))
        conn.execute("INSERT INTO public.reader_profiles(user_id) VALUES(%s),(%s)", (USER, OTHER))
        conn.execute("INSERT INTO public.articles(id) VALUES(%s)", (ARTICLE,))
        conn.execute("INSERT INTO public.assembly_control(singleton) VALUES(true)")
        yield conn


def receipt(db):
    state = repo.configure(db, deepcopy(RECIPE), approved=True, serving=True)
    reader_feedback.record_delivery(db, USER, EDITION,
        {"generation": 1, "revision": 1, "learning_revision": 1, "profile": {"intents": []}},
        [{"id": ARTICLE, "delivery_position": 3, "_assembly_recipe": state["recipe_hash"],
          "_assembly_coverage_unit": "article:" + ARTICLE, "_assembly_novelty_key": "a" * 64,
          "_assembly_content_hash": "b" * 64}])


def event(**overrides):
    return {"type": "read", "article_id": ARTICLE, "event_id": EVENT,
            "feed_request_id": EDITION, "position": 3, "duration_seconds": 8,
            "read_content_hash": "b" * 64, **overrides}


def revision(db):
    row = db.execute("SELECT revision FROM public.reader_edition_state WHERE user_id=%s AND generation=1",
                     (USER,)).fetchone()
    return row["revision"] if row else 0


def test_install_default_off_idempotent_and_epoch_aba(db):
    assert not repo.control(db)["approved"] and not repo.control(db)["serving"]
    enabled = repo.configure(db, deepcopy(RECIPE), approved=True, serving=True)
    repo.install_schema(db)
    assert repo.control(db)["epoch"] == enabled["epoch"]
    repo.configure(db, deepcopy(RECIPE), approved=True, serving=False)
    restored = repo.configure(db, deepcopy(RECIPE), approved=True, serving=True)
    assert restored["epoch"] == enabled["epoch"] + 2


def test_receipt_read_is_idempotent_by_event_and_content(db):
    receipt(db)
    first = reader_feedback.ingest_events(db, USER, {"events": [event()]})
    duplicate = reader_feedback.ingest_events(db, USER, {"events": [event()]})
    different_event = reader_feedback.ingest_events(db, USER,
        {"events": [event(event_id=str(UUID(int=82001)))]})
    assert first["inserted"] == different_event["inserted"] == 1 and duplicate["inserted"] == 0
    assert revision(db) == 1
    assert db.execute("SELECT count(*) AS n FROM public.reader_edition_reads").fetchone()["n"] == 1


def test_novelty_receipt_and_revision_roll_back_together(db):
    receipt(db)
    with pytest.raises(RuntimeError):
        with db.transaction():
            reader_feedback.ingest_events(db, USER, {"events": [event()]})
            assert revision(db) == 1
            raise RuntimeError("abort final transaction")
    assert revision(db) == 0
    assert db.execute("SELECT count(*) AS n FROM public.reading_events").fetchone()["n"] == 0
    assert db.execute("SELECT count(*) AS n FROM public.reader_edition_reads").fetchone()["n"] == 0


@pytest.mark.parametrize("user,overrides", [(OTHER, {}), (USER, {"position": 0}),
    (USER, {"position": None}), (USER, {"feed_request_id": None}),
    (USER, {"event_id": None}), (USER, {"type": "tap"}), (USER, {"type": "impression"}),
    (USER, {"read_content_hash": None}), (USER, {"read_content_hash": "c" * 64})])
def test_unattributed_and_nonread_events_do_not_create_novelty(db, user, overrides):
    receipt(db)
    reader_feedback.ingest_events(db, user, {"events": [event(**overrides)]})
    assert revision(db) == 0


def test_reset_cleanup_and_old_generation_do_not_repopulate(db):
    receipt(db)
    reader_feedback.ingest_events(db, USER, {"events": [event()]})
    db.execute("UPDATE public.reader_profiles SET generation=2 WHERE user_id=%s", (USER,))
    assert db.execute("SELECT count(*) AS n FROM public.reader_edition_reads").fetchone()["n"] == 0
    assert revision(db) == 0
    reader_feedback.ingest_events(db, USER, {"events": [event(event_id=str(UUID(int=82002)))]})
    assert db.execute("SELECT count(*) AS n FROM public.reader_edition_reads").fetchone()["n"] == 0


def test_deleting_receipt_cascades_its_novelty_proof(db):
    receipt(db)
    reader_feedback.ingest_events(db, USER, {"events": [event()]})
    db.execute("DELETE FROM public.reader_delivery_receipts WHERE user_id=%s", (USER,))
    assert db.execute("SELECT count(*) AS n FROM public.reader_edition_reads").fetchone()["n"] == 0


def test_publication_reader_guard_serializes_history_before_article_writes(db, s8_database_url):
    receipt(db)

    def competing_read():
        with psycopg.connect(s8_database_url, autocommit=True, row_factory=dict_row) as other:
            other.execute("SET lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                reader_feedback.ingest_events(other, USER, {"events": [event()]})

    with db.transaction():
        # Exact user -> reader protocol used by S6 publication_guard.
        db.execute("SELECT id FROM public.users WHERE id=%s FOR SHARE", (USER,))
        db.execute("SELECT user_id FROM public.reader_profiles WHERE user_id=%s FOR UPDATE", (USER,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(competing_read).result(timeout=5)
        assert revision(db) == 0
        assert db.execute("SELECT count(*) AS n FROM public.reading_events").fetchone()["n"] == 0
    reader_feedback.ingest_events(db, USER, {"events": [event()]})
    assert revision(db) == 1


@pytest.mark.parametrize("existing", [False, True])
def test_article_share_fences_membership_insert_as_well_as_update(db, s8_database_url, existing):
    cluster = str(UUID(int=83001))
    db.execute("INSERT INTO public.story_clusters VALUES(%s,'s3',1)", (cluster,))
    if existing:
        db.execute("INSERT INTO public.story_memberships VALUES(%s,%s,'s3',1)", (ARTICLE, cluster))

    def writer():
        with psycopg.connect(s8_database_url, autocommit=True, row_factory=dict_row) as other:
            other.execute("SET lock_timeout='100ms'")
            with pytest.raises(psycopg.errors.LockNotAvailable):
                with other.transaction():
                    # S3 assign/split locks article BEFORE clustering advisory or
                    # membership rows. Absence needs the same parent guard.
                    other.execute("SELECT id FROM public.articles WHERE id=%s FOR UPDATE", (ARTICLE,))
                    other.execute("""INSERT INTO public.story_memberships VALUES(%s,%s,'s3',1)
                      ON CONFLICT(article_id) DO UPDATE SET version=story_memberships.version+1""",
                      (ARTICLE, cluster))

    with db.transaction():
        db.execute("SELECT id FROM public.articles WHERE id=%s FOR SHARE", (ARTICLE,))
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(writer).result(timeout=5)
        row = db.execute("SELECT version FROM public.story_memberships WHERE article_id=%s", (ARTICLE,)).fetchone()
        assert row == ({"version": 1} if existing else None)


def test_config_authority_share_lock_fences_disable(db, s8_database_url):
    receipt(db)

    def disable():
        with psycopg.connect(s8_database_url, autocommit=True, row_factory=dict_row) as other:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                repo.configure(other, deepcopy(RECIPE), approved=True, serving=False)

    with db.transaction():
        assert repo.control(db, lock=True)["serving"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(disable).result(timeout=5)
    assert repo.control(db)["serving"]
