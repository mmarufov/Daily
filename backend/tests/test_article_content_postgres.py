"""Real PostgreSQL contract tests for the S2 article-content state machine.

The suite is opt-in because it needs a PostgreSQL server and CREATEDB rights::

    S2_TEST_DATABASE_URL=postgresql:///postgres pytest -q \
        backend/tests/test_article_content_postgres.py

The configured database is never modified.  A uniquely named database is
created on the same server for the test run and dropped afterwards.  That gives
the tests real transaction, row-lock, SKIP LOCKED, and constraint semantics
without putting application data at risk.
"""
from __future__ import annotations

import os
import secrets
import threading
import time
import uuid

import pytest

REQUIRED = os.getenv("S2_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.services import article_content
from app.services.article_content import (
    claim_content_jobs,
    complete_content_job,
    ensure_article_content_schema,
    record_content_artifact,
    register_ingested_article,
)
from scripts.backfill_s2_content import _apply_batch

set_source_policy = getattr(article_content, "set_source_policy", None)
revoke_source_policy = getattr(article_content, "revoke_source_policy", None)
requires_policy_api = pytest.mark.skipif(
    not set_source_policy or not revoke_source_policy,
    reason="S2 source-policy mutation API is not implemented",
)


BASE_DATABASE_URL = os.getenv("S2_TEST_DATABASE_URL")
if REQUIRED and not BASE_DATABASE_URL:
    raise RuntimeError("S2_TEST_DATABASE_REQUIRED=1 requires S2_TEST_DATABASE_URL")
if REQUIRED and (not set_source_policy or not revoke_source_policy):
    raise RuntimeError("Required S2 PostgreSQL policy API is unavailable")
pytestmark = pytest.mark.skipif(
    not BASE_DATABASE_URL,
    reason="set S2_TEST_DATABASE_URL to a disposable PostgreSQL server",
)


def _database_url(base_url: str, database: str) -> str:
    """Replace only dbname while retaining URI, socket, SSL, and credentials."""
    parameters = conninfo_to_dict(base_url)
    parameters["dbname"] = database
    return make_conninfo(**parameters)


@pytest.fixture(scope="session")
def s2_database_url():
    if not BASE_DATABASE_URL:
        pytest.skip("S2_TEST_DATABASE_URL is not set")

    database_name = f"daily_s2_test_{os.getpid()}_{secrets.token_hex(4)}"
    admin = psycopg.connect(BASE_DATABASE_URL, autocommit=True, row_factory=dict_row)
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except Exception as exc:
        admin.close()
        if REQUIRED:
            pytest.fail(f"Required S2 PostgreSQL setup failed: {exc}")
        pytest.skip(f"S2 PostgreSQL tests require CREATEDB rights: {exc}")

    test_url = _database_url(BASE_DATABASE_URL, database_name)
    try:
        yield test_url
    finally:
        # PostgreSQL 13+ FORCE handles a failed test that left a connection
        # behind.  Fall back to terminating only this uniquely named DB.
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


@pytest.fixture(scope="session")
def initialized_database(s2_database_url):
    with psycopg.connect(s2_database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            # Keep this intentionally minimal: article_content must work with
            # rolling-deployment era articles, not only the newest full schema.
            cur.execute(
                """
                CREATE TABLE public.articles (
                    id uuid PRIMARY KEY,
                    title text NOT NULL,
                    summary text,
                    author text,
                    source_name text,
                    url text,
                    image_url text,
                    published_at timestamptz,
                    category text,
                    content text,
                    content_extracted boolean NOT NULL DEFAULT false,
                    embedding text
                )
                """
            )
        ensure_article_content_schema(conn)
        ensure_article_content_schema(conn)
    return s2_database_url


@pytest.fixture()
def db(initialized_database):
    conn = psycopg.connect(initialized_database, autocommit=True, row_factory=dict_row)
    with conn.cursor() as cur:
        cur.execute(
            """
            TRUNCATE public.article_content_outcomes,
                     public.article_source_policy_events,
                     public.article_content_jobs,
                     public.article_content_artifacts,
                     public.article_source_policies,
                     public.articles
            RESTART IDENTITY CASCADE
            """
        )
    try:
        yield conn
    finally:
        conn.close()


def _article(conn, *, url="https://example.com/story", content=None):
    article_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.articles (id, title, source_name, url, content)
            VALUES (%s, %s, 'Example', %s, %s)
            """,
            (article_id, f"Story {article_id}", url, content),
        )
    return article_id


def _row(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchone()


def _complete_payload(text="Verified publisher prose. " * 80):
    return {
        "content": text,
        "content_state": "complete",
        "completeness": "complete",
        "identity_valid": True,
        "confidence": 0.97,
        "canonical_url": "https://example.com/story",
        "final_url": "https://example.com/story",
        "extraction_method": "trafilatura",
        "extractor_version": 4,
    }


def test_schema_install_waits_for_cluster_wide_advisory_lock(initialized_database):
    holder = psycopg.connect(
        initialized_database, autocommit=False, row_factory=dict_row
    )
    outcome: dict[str, object] = {}
    worker_started = threading.Event()

    def install_from_second_worker():
        try:
            with psycopg.connect(
                initialized_database, autocommit=True, row_factory=dict_row
            ) as worker_conn:
                with worker_conn.cursor() as cur:
                    cur.execute("SET lock_timeout = '5s'")
                    cur.execute("SELECT pg_backend_pid() AS pid")
                    outcome["pid"] = cur.fetchone()["pid"]
                worker_started.set()
                ensure_article_content_schema(worker_conn)
                outcome["completed"] = True
        except Exception as exc:
            outcome["error"] = exc
            worker_started.set()

    worker = threading.Thread(target=install_from_second_worker, daemon=True)
    try:
        with holder.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s)",
                (article_content.S2_SCHEMA_ADVISORY_LOCK_KEY,),
            )
        worker.start()
        assert worker_started.wait(timeout=2)

        deadline = time.monotonic() + 2
        wait_event = None
        while time.monotonic() < deadline:
            with holder.cursor() as cur:
                cur.execute(
                    "SELECT wait_event_type, wait_event FROM pg_stat_activity "
                    "WHERE pid = %s",
                    (outcome.get("pid"),),
                )
                wait_event = cur.fetchone()
            if wait_event and wait_event.get("wait_event_type") == "Lock":
                break
            time.sleep(0.02)
        assert wait_event and wait_event["wait_event_type"] == "Lock"
        assert wait_event["wait_event"] == "advisory"

        holder.commit()
        worker.join(timeout=6)
        assert not worker.is_alive()
        assert "error" not in outcome
        assert outcome.get("completed") is True
    finally:
        if not holder.closed:
            holder.rollback()
            holder.close()


def test_unreviewed_feed_is_analysis_only_and_origin_job_remains_pending(db):
    article_id = _article(db)
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content="Publisher feed text. " * 100,
        feed_url="https://example.com/feed.xml",
    )

    article = _row(
        db,
        "SELECT presentation_mode, display_content_artifact_id, content, "
        "analysis_text FROM public.articles WHERE id = %s",
        (article_id,),
    )
    job = _row(
        db,
        "SELECT state, final_outcome FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    )
    assert article["presentation_mode"] == "source_web"
    assert article["display_content_artifact_id"] is None
    assert article["content"] is None
    assert article["analysis_text"].startswith("Publisher feed text")
    assert job == {"state": "pending", "final_outcome": None}


@requires_policy_api
def test_reviewed_feed_grant_and_revoke_rematerialize_existing_article(db):
    article_id = _article(db)
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content="Syndicated full article. " * 100,
        feed_url="https://example.com/feed.xml",
    )

    granted = set_source_policy(
        db,
        source_domain="EXAMPLE.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["publisher_feed"],
        allowed_feed_urls=["https://example.com/feed.xml"],
        publisher_feed_full_text=True,
        rights_basis="publisher_feed_license",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    article = _row(
        db,
        "SELECT presentation_mode, body_state, content, display_policy_version "
        "FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert granted["source_domain"] == "example.com"
    assert article["presentation_mode"] == "native_full_text"
    assert article["body_state"] == "verified_full"
    assert article["content"].startswith("Syndicated full article")
    assert article["display_policy_version"] == granted["version"]

    revoked = revoke_source_policy(
        db,
        source_domain="example.com",
        reviewed_by="pytest@example.invalid",
        access_hint="publisher_sign_in_required",
    )
    article = _row(
        db,
        "SELECT presentation_mode, display_content_artifact_id, content, "
        "content_access_hint FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert revoked["version"] == granted["version"] + 1
    assert article == {
        "presentation_mode": "source_web",
        "display_content_artifact_id": None,
        "content": None,
        "content_access_hint": "publisher_sign_in_required",
    }
    events = _row(
        db,
        "SELECT array_agg(action ORDER BY policy_version) AS actions, count(*) AS count "
        "FROM public.article_source_policy_events WHERE source_domain = 'example.com'",
    )
    assert events["actions"] == ["grant", "revoke"]
    assert events["count"] == 2


@requires_policy_api
def test_feed_text_cannot_borrow_publishers_policy_from_an_aggregator(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["publisher_feed"],
        allowed_feed_urls=["https://feeds.example.com/full.xml"],
        publisher_feed_full_text=True,
        rights_basis="publisher_feed_license",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )

    injected = "Aggregator-supplied text that must not render. " * 100
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content=injected,
        feed_url="https://news.google.com/rss/search?q=example",
    )
    article = _row(
        db,
        "SELECT presentation_mode, content FROM public.articles WHERE id = %s",
        (article_id,),
    )
    artifact = _row(
        db,
        "SELECT origin_url, completeness, displayable "
        "FROM public.article_content_artifacts "
        "WHERE article_id = %s AND kind = 'publisher_feed' AND is_current = true",
        (article_id,),
    )
    assert article == {"presentation_mode": "source_web", "content": None}
    assert artifact == {
        "origin_url": "https://news.google.com/rss/search?q=example",
        "completeness": "unknown",
        "displayable": False,
    }

    official = "Publisher-authorized full feed body. " * 100
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content=official,
        feed_url="https://feeds.example.com/full.xml#ignored",
    )
    article = _row(
        db,
        "SELECT presentation_mode, content FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert article == {
        "presentation_mode": "native_full_text",
        "content": official.strip(),
    }


def test_feed_text_without_acquisition_url_is_quarantined(db):
    article_id = _article(db)
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content="Unscoped feed body. " * 100,
    )
    article = _row(
        db,
        "SELECT presentation_mode, content, analysis_text "
        "FROM public.articles WHERE id = %s",
        (article_id,),
    )
    artifact = _row(
        db,
        "SELECT kind, method FROM public.article_content_artifacts "
        "WHERE article_id = %s AND is_current = true",
        (article_id,),
    )
    assert article["presentation_mode"] == "source_web"
    assert article["content"] is None
    assert article["analysis_text"].startswith("Unscoped feed body")
    assert artifact == {
        "kind": "legacy_unverified",
        "method": "publisher_feed_missing_origin",
    }


@requires_policy_api
def test_policy_change_from_ready_feed_to_origin_requeues_acquisition(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["publisher_feed"],
        allowed_feed_urls=["https://example.com/feed.xml"],
        publisher_feed_full_text=True,
        rights_basis="publisher_feed_license",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content="Full publisher feed body. " * 100,
        feed_url="https://example.com/feed.xml",
    )
    assert _row(
        db,
        "SELECT state FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    )["state"] == "ready"

    revoke_source_policy(
        db,
        source_domain="example.com",
        reviewed_by="pytest@example.invalid",
    )
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["origin_extract"],
        publisher_feed_full_text=False,
        rights_basis="publisher_permission",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )

    job = _row(
        db,
        "SELECT state, attempt_count, final_outcome "
        "FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    )
    assert job == {"state": "pending", "attempt_count": 0, "final_outcome": None}
    claims = claim_content_jobs(db, "origin-worker", limit=10)
    assert [claim["article_id"] for claim in claims] == [article_id]


@requires_policy_api
def test_reviewed_feed_fences_inflight_origin_worker_and_keeps_precedence(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["publisher_feed", "origin_extract"],
        allowed_feed_urls=["https://example.com/feed.xml"],
        publisher_feed_full_text=True,
        rights_basis="publisher_permission",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    stale_claim = claim_content_jobs(db, "origin-worker", limit=1)[0]

    feed_body = "Authoritative publisher feed body. " * 100
    register_ingested_article(
        db,
        article_id,
        canonical_url="https://example.com/story",
        feed_content=feed_body,
        feed_url="https://example.com/feed.xml",
    )
    assert not complete_content_job(
        db,
        article_id=article_id,
        worker_id="origin-worker",
        job_version=stale_claim["job_version"],
        extracted=_complete_payload("Lower precedence origin result. " * 100),
    )

    article = _row(
        db,
        "SELECT content, presentation_mode FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert article["content"] == feed_body.strip()
    assert article["presentation_mode"] == "native_full_text"
    current = _row(
        db,
        "SELECT kind FROM public.article_content_artifacts "
        "WHERE article_id = %s AND displayable = true",
        (article_id,),
    )
    assert current["kind"] == "publisher_feed"


@requires_policy_api
def test_artifact_versions_are_monotonic_and_allow_a_b_a_history(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["origin_extract"],
        publisher_feed_full_text=False,
        rights_basis="publisher_permission",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    a = "First body. " * 100
    b = "Second body. " * 100
    for text in (a, b, a):
        assert record_content_artifact(
            db,
            article_id,
            kind="origin_extract",
            text=text,
            origin_url="https://example.com/story",
            method="contract-test",
            completeness="complete",
            confidence=0.99,
        )

    with db.cursor() as cur:
        cur.execute(
            "SELECT version, is_current, text FROM public.article_content_artifacts "
            "WHERE article_id = %s ORDER BY version",
            (article_id,),
        )
        artifacts = cur.fetchall()
    assert [row["version"] for row in artifacts] == [1, 2, 3]
    assert [row["is_current"] for row in artifacts] == [False, False, True]
    assert artifacts[-1]["text"] == a.strip()
    article = _row(
        db,
        "SELECT content_version, presentation_mode, content FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert article["content_version"] == 3
    assert article["presentation_mode"] == "native_full_text"
    assert article["content"] == a.strip()


def test_cross_origin_body_is_rejected_without_state_change(db):
    article_id = _article(db)
    artifact_id = record_content_artifact(
        db,
        article_id,
        kind="origin_extract",
        text="Wrong publisher body. " * 100,
        origin_url="https://attacker.example/story",
        method="contract-test",
        completeness="complete",
        confidence=1.0,
    )
    assert artifact_id is None
    assert _row(
        db,
        "SELECT count(*) AS count FROM public.article_content_artifacts WHERE article_id = %s",
        (article_id,),
    )["count"] == 0
    assert _row(
        db,
        "SELECT content_version FROM public.articles WHERE id = %s",
        (article_id,),
    )["content_version"] == 0


def test_materialized_pointer_cannot_reference_another_articles_artifact(db):
    owner_id = _article(db, url="https://example.com/owner")
    victim_id = _article(db, url="https://example.com/victim")
    artifact_id = record_content_artifact(
        db,
        owner_id,
        kind="origin_extract",
        text="Owner article body. " * 100,
        origin_url="https://example.com/owner",
        method="contract-test",
        completeness="complete",
        confidence=0.99,
    )
    assert artifact_id is not None

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with db.cursor() as cur:
            cur.execute(
                "UPDATE public.articles SET display_content_artifact_id = %s, "
                "presentation_mode = 'native_full_text', body_state = 'verified_full' "
                "WHERE id = %s",
                (artifact_id, victim_id),
            )


def test_claims_are_disjoint_and_stale_worker_cannot_commit(initialized_database, db):
    article_ids = [_article(db, url=f"https://example.com/story-{n}") for n in range(4)]
    for article_id in article_ids:
        register_ingested_article(
            db,
            article_id,
            canonical_url=f"https://example.com/story-{article_ids.index(article_id)}",
            feed_content=None,
        )

    worker_one = claim_content_jobs(db, "worker-one", limit=2)
    with psycopg.connect(
        initialized_database, autocommit=True, row_factory=dict_row
    ) as second:
        worker_two = claim_content_jobs(second, "worker-two", limit=2)
    first_ids = {row["article_id"] for row in worker_one}
    second_ids = {row["article_id"] for row in worker_two}
    assert len(first_ids) == len(second_ids) == 2
    assert first_ids.isdisjoint(second_ids)

    stale_job = worker_one[0]
    with db.cursor() as cur:
        cur.execute(
            "UPDATE public.article_content_jobs SET lease_expires_at = now() - interval '1 second' "
            "WHERE article_id = %s",
            (stale_job["article_id"],),
        )
    # Version/owner still match here. Expiry itself must fence completion,
    # otherwise a slow worker can publish after its lease deadline but before
    # another worker happens to reclaim the row.
    assert not complete_content_job(
        db,
        article_id=stale_job["article_id"],
        worker_id="worker-one",
        job_version=stale_job["job_version"],
        extracted={"error": "timeout"},
    )
    reclaimed = claim_content_jobs(db, "worker-three", limit=1)
    assert reclaimed[0]["article_id"] == stale_job["article_id"]


def test_ingestion_and_completion_share_article_then_job_lock_order(
    initialized_database, db
):
    article_id = _article(db)
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    claim = claim_content_jobs(db, "concurrent-worker", limit=1)[0]
    outcome: dict[str, object] = {}
    worker_started = threading.Event()

    def finish_worker():
        try:
            with psycopg.connect(
                initialized_database, autocommit=True, row_factory=dict_row
            ) as worker_conn:
                with worker_conn.cursor() as cur:
                    cur.execute("SET lock_timeout = '5s'")
                    cur.execute("SELECT pg_backend_pid() AS pid")
                    outcome["pid"] = cur.fetchone()["pid"]
                worker_started.set()
                outcome["completed"] = complete_content_job(
                    worker_conn,
                    article_id=article_id,
                    worker_id="concurrent-worker",
                    job_version=claim["job_version"],
                    extracted=_complete_payload(),
                )
        except Exception as exc:  # surfaced on the main pytest thread below
            outcome["error"] = exc
            worker_started.set()

    ingestion_conn = psycopg.connect(
        initialized_database, autocommit=False, row_factory=dict_row
    )
    worker = threading.Thread(target=finish_worker, daemon=True)
    try:
        with ingestion_conn.cursor() as cur:
            cur.execute("SET lock_timeout = '5s'")
            cur.execute(
                "SELECT id FROM public.articles WHERE id = %s FOR UPDATE",
                (article_id,),
            )
        worker.start()
        assert worker_started.wait(timeout=2)

        # Wait until completion is blocked on the article row. With the old
        # job->article order it held the job here and this registration formed
        # a deadlock. The fixed order leaves the job available to ingestion.
        deadline = time.monotonic() + 2
        wait_event = None
        while time.monotonic() < deadline:
            wait_event = _row(
                db,
                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                (outcome.get("pid"),),
            )
            if wait_event and wait_event.get("wait_event_type") == "Lock":
                break
            time.sleep(0.02)
        assert wait_event and wait_event["wait_event_type"] == "Lock"

        register_ingested_article(
            ingestion_conn,
            article_id,
            canonical_url="https://example.com/story",
            feed_content=None,
        )
        ingestion_conn.commit()
        worker.join(timeout=6)
        assert not worker.is_alive()
        assert "error" not in outcome
        assert outcome.get("completed") is True
    finally:
        if not ingestion_conn.closed:
            ingestion_conn.rollback()
            ingestion_conn.close()


def test_expired_final_attempt_is_reaped_to_terminal_source_handoff(db):
    article_id = _article(db)
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    with db.cursor() as cur:
        cur.execute(
            """
            UPDATE public.article_content_jobs
            SET state = 'leased', attempt_count = 3, version = 7,
                lease_owner = 'crashed-worker',
                lease_expires_at = now() - interval '1 minute'
            WHERE article_id = %s
            """,
            (article_id,),
        )
    assert claim_content_jobs(db, "next-worker", limit=10) == []
    job = _row(
        db,
        "SELECT state, failure_class, final_outcome, lease_owner, version "
        "FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    )
    assert job["state"] == "terminal_failure"
    assert job["failure_class"] == "attempts_exhausted"
    assert job["final_outcome"] == "source_web"
    assert job["lease_owner"] is None
    assert job["version"] == 8


@requires_policy_api
def test_outdated_extractor_completion_is_retryable_and_never_materialized(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["origin_extract"],
        publisher_feed_full_text=False,
        rights_basis="publisher_permission",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    claim = claim_content_jobs(db, "old-worker", limit=1)[0]
    payload = _complete_payload()
    payload["extractor_version"] = 3

    assert complete_content_job(
        db,
        article_id=article_id,
        worker_id="old-worker",
        job_version=claim["job_version"],
        extracted=payload,
    )

    job = _row(
        db,
        "SELECT state, failure_class FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    )
    article = _row(
        db,
        "SELECT presentation_mode, display_content_artifact_id, content "
        "FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert job["state"] == "retryable_failure"
    assert job["failure_class"] == "extractor_outdated"
    assert article == {
        "presentation_mode": "source_web",
        "display_content_artifact_id": None,
        "content": None,
    }
    assert _row(
        db,
        "SELECT count(*) AS count FROM public.article_content_artifacts WHERE article_id = %s",
        (article_id,),
    )["count"] == 0


def test_analysis_change_invalidates_embedding_version(db):
    article_id = _article(db)
    first = record_content_artifact(
        db,
        article_id,
        kind="origin_extract",
        text="Version one. " * 100,
        origin_url="https://example.com/story",
        method="contract-test",
        completeness="complete",
        confidence=0.99,
    )
    with db.cursor() as cur:
        cur.execute(
            "UPDATE public.articles SET embedding = 'cached-vector', "
            "embedding_content_version = analysis_content_version, "
            "content_quality = 0.91, "
            "content_quality_content_version = analysis_content_version, "
            "enrichment_completed = true, enrichment_attempts = 3 "
            "WHERE id = %s",
            (article_id,),
        )
    second = record_content_artifact(
        db,
        article_id,
        kind="origin_extract",
        text="Version two. " * 100,
        origin_url="https://example.com/story",
        method="contract-test",
        completeness="complete",
        confidence=0.99,
    )
    assert first != second
    article = _row(
        db,
        "SELECT embedding, embedding_content_version, analysis_content_version, "
        "content_quality, content_quality_content_version, "
        "enrichment_completed, enrichment_attempts "
        "FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert article["embedding"] is None
    assert article["embedding_content_version"] is None
    assert article["analysis_content_version"] == 2
    assert article["content_quality"] is None
    assert article["content_quality_content_version"] is None
    assert article["enrichment_completed"] is False
    assert article["enrichment_attempts"] == 0


def test_outcome_telemetry_failure_does_not_roll_back_ready_state(db):
    article_id = _article(db)
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    claim = claim_content_jobs(db, "worker", limit=1)[0]
    with db.cursor() as cur:
        cur.execute(
            "ALTER TABLE public.article_content_outcomes RENAME TO article_content_outcomes_offline"
        )
    try:
        assert complete_content_job(
            db,
            article_id=article_id,
            worker_id="worker",
            job_version=claim["job_version"],
            extracted=_complete_payload(),
        )
        job = _row(
            db,
            "SELECT state, final_outcome FROM public.article_content_jobs WHERE article_id = %s",
            (article_id,),
        )
        assert job == {"state": "ready", "final_outcome": "verified_full"}
    finally:
        with db.cursor() as cur:
            cur.execute(
                "ALTER TABLE public.article_content_outcomes_offline "
                "RENAME TO article_content_outcomes"
            )


@requires_policy_api
def test_identity_failure_never_becomes_native_body(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["origin_extract"],
        publisher_feed_full_text=False,
        rights_basis="publisher_permission",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    claim = claim_content_jobs(db, "worker", limit=1)[0]
    payload = _complete_payload()
    payload.update(identity_valid=False, error="title_mismatch")
    assert complete_content_job(
        db,
        article_id=article_id,
        worker_id="worker",
        job_version=claim["job_version"],
        extracted=payload,
    )
    article = _row(
        db,
        "SELECT presentation_mode, display_content_artifact_id, content "
        "FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert article == {
        "presentation_mode": "source_web",
        "display_content_artifact_id": None,
        "content": None,
    }


def test_legacy_backfill_is_idempotent_and_quarantines_ambiguous_data(db):
    article_id = _article(db, content="Ambiguous legacy prose. " * 100)
    with db.cursor() as cur:
        cur.execute(
            "UPDATE public.articles "
            "SET image_url = %s, enrichment_completed = true, enrichment_attempts = 3 "
            "WHERE id = %s",
            ("https://images.example/legacy.jpg", article_id),
        )

    first = _apply_batch(db, 10, image_provenance=True)
    second = _apply_batch(db, 10, image_provenance=True)
    assert first == {
        "rows": 1,
        "legacy_content": 1,
        "jobs": 1,
        "legacy_images": 1,
        "outdated_origins": 0,
    }
    assert second == {
        "rows": 0,
        "legacy_content": 0,
        "jobs": 0,
        "legacy_images": 0,
        "outdated_origins": 0,
    }

    article = _row(
        db,
        "SELECT presentation_mode, content, analysis_text, image_origin, "
        "image_is_illustrative, enrichment_completed, enrichment_attempts "
        "FROM public.articles WHERE id = %s",
        (article_id,),
    )
    assert article["presentation_mode"] == "source_web"
    assert article["content"] is None
    assert article["analysis_text"].startswith("Ambiguous legacy prose")
    assert article["image_origin"] == "legacy_unknown"
    assert article["image_is_illustrative"] is True
    assert article["enrichment_completed"] is False
    assert article["enrichment_attempts"] == 0
    assert _row(
        db,
        "SELECT state FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    )["state"] == "pending"


@requires_policy_api
def test_backfill_invalidates_old_extractor_artifact_once_and_requeues(db):
    article_id = _article(db)
    set_source_policy(
        db,
        source_domain="example.com",
        display_policy="native_full_text",
        allowed_artifact_kinds=["origin_extract"],
        publisher_feed_full_text=False,
        rights_basis="publisher_permission",
        access_hint="open",
        reviewed_by="pytest@example.invalid",
        action="grant",
    )
    register_ingested_article(
        db, article_id, canonical_url="https://example.com/story", feed_content=None
    )
    old_artifact = record_content_artifact(
        db,
        article_id,
        kind="origin_extract",
        text="Old heuristic body. " * 100,
        origin_url="https://example.com/story",
        method="old-extractor",
        completeness="complete",
        confidence=0.99,
        extractor_version=3,
    )
    assert old_artifact is not None
    with db.cursor() as cur:
        cur.execute(
            "UPDATE public.article_content_jobs SET state = 'ready', "
            "final_outcome = 'verified_full' WHERE article_id = %s",
            (article_id,),
        )

    first = _apply_batch(db, 10, image_provenance=True)
    second = _apply_batch(db, 10, image_provenance=True)

    assert first["outdated_origins"] == 1
    assert second["rows"] == 0
    assert _row(
        db,
        "SELECT is_current, displayable FROM public.article_content_artifacts WHERE id = %s",
        (old_artifact,),
    ) == {"is_current": False, "displayable": False}
    assert _row(
        db,
        "SELECT state, attempt_count, final_outcome "
        "FROM public.article_content_jobs WHERE article_id = %s",
        (article_id,),
    ) == {"state": "pending", "attempt_count": 0, "final_outcome": None}
