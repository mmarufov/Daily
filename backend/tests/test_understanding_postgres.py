"""Real PostgreSQL/pgvector S3 lifecycle tests; never touch the configured DB.

S3_TEST_DATABASE_URL supplies a server with CREATEDB and pgvector installed.
Only a random database created by this fixture is migrated, truncated or dropped.
CI sets S3_TEST_DATABASE_REQUIRED=1 to turn missing infrastructure into failure.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import os
import secrets
import threading
import uuid

import pytest

REQUIRED = os.getenv("S3_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from app.services.article_content import EXTRACTOR_VERSION, ensure_article_content_schema
from app.services.understanding_contract import DEFAULT_RECIPE
from app.services import understanding_repository as repo

BASE_URL = os.getenv("S3_TEST_DATABASE_URL")
if REQUIRED and not BASE_URL:
    raise RuntimeError("S3_TEST_DATABASE_REQUIRED=1 requires S3_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="S3_TEST_DATABASE_URL is not set")


@pytest.fixture(scope="session")
def s3_database_url():
    name = f"daily_s3_test_{os.getpid()}_{secrets.token_hex(8)}"
    admin = None
    created = False
    try:
        try:
            admin = psycopg.connect(BASE_URL, autocommit=True, connect_timeout=10)
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
            parameters = conninfo_to_dict(BASE_URL)
            parameters["dbname"] = name
            test_url = make_conninfo(**parameters)
            with psycopg.connect(test_url, autocommit=True, row_factory=dict_row) as conn:
                conn.execute("""CREATE TABLE public.articles (
                  id uuid PRIMARY KEY, title text NOT NULL, summary text, author text,
                  source_name text, source_id uuid, url text, image_url text,
                  published_at timestamptz, ingested_at timestamptz NOT NULL DEFAULT now(),
                  language text, source_acquisition_url text, source_acquisition_kind text,
                  category text, content text, content_extracted boolean NOT NULL DEFAULT false,
                  embedding text)""")
                ensure_article_content_schema(conn)
                repo.ensure_schema(conn)
                repo.ensure_schema(conn)
                repo.check_schema(conn)
        except Exception as exc:
            # Do not print a connection string or provider credentials on failure.
            reason = f"S3 PostgreSQL setup unavailable ({type(exc).__name__})"
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
def db(s3_database_url):
    with psycopg.connect(s3_database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("""TRUNCATE public.articles, public.understanding_recipes,
          public.understanding_control, public.understanding_outbox,
          public.understanding_consumer_cursors, public.understanding_spend
          RESTART IDENTITY CASCADE""")
        conn.execute("INSERT INTO public.understanding_control(singleton) VALUES(true)")
        yield conn


@pytest.fixture
def recipe(db):
    identifier = repo.register_recipe(db, DEFAULT_RECIPE, enabled=True)
    repo.configure(db, submissions_enabled=True, daily_budget_usd="1")
    return identifier


def article(db, *, source="example.com"):
    identifier = uuid.uuid4()
    db.execute("""INSERT INTO public.articles(id,title,summary,url,source_name,canonical_source_domain)
      VALUES(%s,'Research satellite launches','A satellite launched on Tuesday.',%s,%s,%s)""",
      (identifier, f"https://{source}/story/{identifier}", source, source))
    return identifier


def row(db, article_id):
    return db.execute("SELECT * FROM public.articles WHERE id=%s", (article_id,)).fetchone()


def card(bundle):
    return {"article_id": bundle["article_id"], "input_hash": bundle["input_hash"],
            "kind": "unknown", "kind_evidence": [], "topics": [], "entities": [], "places": [],
            "commercial": {"value": "unknown", "subtype": None, "evidence": []},
            "about": None, "about_evidence": [], "event_hints": [],
            "abstentions": [{"field": field, "reason": "insufficient_evidence"}
                            for field in ("kind", "topics", "entities", "places", "commercial", "about", "event_hints")]}


def prepared(db):
    jobs = repo.claim(db, limit=20)
    assert jobs
    for job in jobs:
        bundle = repo.prepare(db, job)
        assert bundle is not None
        yield job, bundle


def publish(db, job, bundle):
    payload = card(bundle) if job["stage"] == "facets" else {"vector": [1.0] + [0.0] * 1535}
    return repo.publish(db, job, bundle, payload)


def test_migration_idempotence_and_default_closed(db):
    repo.check_schema(db)
    control = db.execute("SELECT * FROM public.understanding_control").fetchone()
    assert control["submissions_enabled"] is False
    assert control["serving_recipe"] is None
    assert repo.claim(db) == []


def test_revision_tracks_title_and_original_body_but_not_reader_presentation(db, recipe):
    identifier = article(db)
    original = row(db, identifier)
    first_hash = repo.evidence_for_article(db, identifier)["input_hash"]
    db.execute("UPDATE public.articles SET title='Corrected satellite launch' WHERE id=%s", (identifier,))
    corrected = row(db, identifier)
    assert corrected["semantic_revision"] == original["semantic_revision"] + 1
    assert repo.evidence_for_article(db, identifier)["input_hash"] != first_hash
    db.execute("UPDATE public.articles SET image_url='https://example.com/new.jpg',content_version=99 WHERE id=%s", (identifier,))
    assert row(db, identifier)["semantic_revision"] == corrected["semantic_revision"]
    text = "Verified original publisher reporting about the satellite launch."
    artifact = db.execute("""INSERT INTO public.article_content_artifacts
      (article_id,kind,text,origin_url,origin_domain,method,completeness,confidence,content_hash,extractor_version,version)
      VALUES(%s,'origin_extract',%s,%s,'example.com','trafilatura','complete',0.99,%s,%s,1) RETURNING id""",
      (identifier, text, original["url"], hashlib.sha256(text.encode()).hexdigest(), EXTRACTOR_VERSION)).fetchone()["id"]
    db.execute("""UPDATE public.articles SET analysis_content_artifact_id=%s,
      analysis_content_version=1,analysis_text=%s WHERE id=%s""", (artifact,text,identifier))
    body = repo.evidence_for_article(db, identifier)
    assert body["fields"]["body"] == text
    assert body["semantic_revision"] == corrected["semantic_revision"] + 1
    assert row(db, identifier)["content_version"] == 99


def test_concurrent_claims_are_disjoint_and_claim_each_job_once(db, recipe, s3_database_url):
    for index in range(8):
        article(db, source=f"source{index}.example.com")
    barrier = threading.Barrier(2)

    def worker():
        with psycopg.connect(s3_database_url, autocommit=True, row_factory=dict_row) as conn:
            barrier.wait(timeout=10)
            return {job["id"] for job in repo.claim(conn, limit=8)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(worker)
        right = pool.submit(worker)
        left, right = left.result(timeout=20), right.result(timeout=20)
    assert left and right and left.isdisjoint(right)
    assert len(left | right) == 16
    assert repo.claim(db, limit=20) == []


def test_reaper_final_attempt_and_pending_deadline_are_terminal(db, recipe):
    article(db)
    jobs = repo.claim(db, limit=2)
    final = jobs[0]
    db.execute("""UPDATE public.article_understanding_jobs SET attempts=5,
      lease_until=now()-interval '1 second' WHERE id=%s""", (final["id"],))
    db.execute("""UPDATE public.article_understanding_jobs SET state='pending',lease_token=NULL,
      lease_until=NULL,deadline=now()-interval '1 second' WHERE id=%s""", (jobs[1]["id"],))
    assert repo.reap(db) == 2
    states = db.execute("SELECT state,failure_reason FROM public.article_understanding_jobs ORDER BY id").fetchall()
    assert all(item["state"] == "failed_terminal" for item in states)
    assert {item["failure_reason"] for item in states} == {"lease_expired", "deadline_exceeded"}
    assert repo.claim(db) == []


def test_expired_lease_cannot_publish_or_replace_new_owner(db, recipe):
    article(db)
    job, bundle = next(prepared(db))
    db.execute("UPDATE public.article_understanding_jobs SET lease_until=now()-interval '1 second' WHERE id=%s", (job["id"],))
    assert publish(db, job, bundle) is False
    repo.reap(db)
    db.execute("UPDATE public.article_understanding_jobs SET retry_at=now()-interval '1 second' WHERE id=%s", (job["id"],))
    replacement = next(item for item in repo.claim(db, limit=20) if item["id"] == job["id"])
    assert replacement["lease_token"] != job["lease_token"]
    repo.fail(db, job, "late_old_worker")
    assert publish(db, job, bundle) is False
    current = repo.prepare(db, replacement)
    assert publish(db, replacement, current) is True


@pytest.mark.parametrize("change", ["title", "disabled", "delete", "revoke"])
def test_publication_cas_rejects_invalidated_results(db, recipe, change):
    identifier = article(db)
    job, bundle = next(prepared(db))
    if change == "title":
        db.execute("UPDATE public.articles SET title='Publisher correction' WHERE id=%s", (identifier,))
    elif change == "disabled":
        repo.set_recipe_enabled(db, recipe, False)
    elif change == "delete":
        db.execute("DELETE FROM public.articles WHERE id=%s", (identifier,))
    else:
        repo.revoke(db, identifier)
    assert publish(db, job, bundle) is False
    assert db.execute("SELECT count(*) AS n FROM public.article_understanding_results").fetchone()["n"] == 0


def test_ready_results_are_hidden_after_correction_and_revocation(db, recipe):
    identifier = article(db)
    for job, bundle in prepared(db):
        assert publish(db, job, bundle)
    assert repo.load_current(db, identifier, recipe)["state"] == "ready"
    assert db.execute("SELECT count(*) AS n FROM public.article_understanding_jobs WHERE stage='cluster'").fetchone()["n"] == 1
    db.execute("UPDATE public.articles SET summary='The launch has been delayed.' WHERE id=%s", (identifier,))
    assert repo.load_current(db, identifier, recipe)["state"] == "pending"
    repo.revoke(db, identifier)
    assert repo.load_current(db, identifier, recipe)["state"] == "revoked_or_missing"
    before = row(db, identifier)["analysis_eligibility_generation"]
    repo.revoke(db, identifier, False)
    assert row(db, identifier)["analysis_eligibility_generation"] == before + 1
    assert repo.load_current(db, identifier, recipe)["state"] == "pending"


def test_reconcile_is_idempotent_and_inserts_for_preexisting_articles(db, recipe):
    identifier = article(db)
    assert repo.reconcile(db, recipe)["inserted"] == 0
    repo.set_recipe_enabled(db, recipe, False)
    second = article(db)
    repo.set_recipe_enabled(db, recipe, True)
    assert repo.reconcile(db, recipe)["inserted"] == 2
    assert repo.reconcile(db, recipe)["inserted"] == 0
    assert db.execute("SELECT count(*) AS n FROM public.article_understanding_jobs WHERE article_id=ANY(%s)", ([identifier,second],)).fetchone()["n"] == 4


def test_budget_serializes_competing_reservations(db, recipe, s3_database_url):
    article(db)
    jobs = repo.claim(db, limit=2)
    repo.configure(db, submissions_enabled=True, daily_budget_usd="0.10")
    barrier = threading.Barrier(2)

    def reserve(job):
        with psycopg.connect(s3_database_url, autocommit=True, row_factory=dict_row) as conn:
            barrier.wait(timeout=10)
            return repo.reserve(conn, job, "0.06")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(reserve, job) for job in jobs]
        receipts = [future.result(timeout=20) for future in futures]
    assert sum(receipt is not None for receipt in receipts) == 1
    assert db.execute("SELECT sum(reserved_usd) AS total FROM public.understanding_spend").fetchone()["total"] == Decimal("0.06")


def test_receipt_survives_deletion_settles_once_and_overage_stops_submissions(db, recipe):
    identifier = article(db)
    job = repo.claim(db, limit=1)[0]
    receipt = repo.reserve(db, job, "0.01")
    assert receipt is not None
    db.execute("DELETE FROM public.articles WHERE id=%s", (identifier,))
    repo.settle(db, receipt, "0.02")
    repo.settle(db, receipt, "0.02")
    with pytest.raises(ValueError, match="already settled"):
        repo.settle(db, receipt, "0.03")
    control = db.execute("SELECT * FROM public.understanding_control").fetchone()
    assert control["submissions_enabled"] is False
    assert control["circuit_reason"] == "usage_exceeded_reservation"
    assert db.execute("SELECT actual_usd FROM public.understanding_spend WHERE id=%s", (receipt,)).fetchone()["actual_usd"] == Decimal("0.02")


def test_budget_deferral_does_not_exhaust_attempts(db, recipe):
    article(db)
    job = repo.claim(db, limit=1)[0]
    repo.defer_without_attempt(db, job, "budget_exhausted")
    updated = db.execute("SELECT * FROM public.article_understanding_jobs WHERE id=%s", (job["id"],)).fetchone()
    assert updated["state"] == "retry_wait"
    assert updated["attempts"] == 0
    assert updated["lease_token"] is None


def test_outbox_receipts_do_not_lose_a_late_lower_sequence_commit(db, recipe, s3_database_url):
    identifier = article(db)
    consumer = "late-commit-consumer"
    repo.acknowledge_events(db, consumer, [event["id"] for event in repo.read_events(db, consumer)])
    insert = """INSERT INTO public.understanding_outbox
      (article_id,semantic_revision,eligibility_generation,recipe_id,kind)
      VALUES(%s,1,1,%s,'test') RETURNING id"""
    with psycopg.connect(s3_database_url, autocommit=False, row_factory=dict_row) as delayed:
        low = delayed.execute(insert, (identifier, recipe)).fetchone()["id"]
        high = db.execute(insert, (identifier, recipe)).fetchone()["id"]
        assert low < high
        visible = repo.read_events(db, consumer)
        assert [event["id"] for event in visible] == [high]
        assert repo.acknowledge_events(db, consumer, [high]) == 1
        assert repo.acknowledge_events(db, consumer, [high]) == 0
        delayed.commit()
    assert [event["id"] for event in repo.read_events(db, consumer)] == [low]
    assert repo.acknowledge_events(db, consumer, [low]) == 1
    assert repo.read_events(db, consumer) == []


@pytest.mark.parametrize("stage", ["facets", "embedding", "cluster"])
@pytest.mark.parametrize("expired_field", ["lease_until", "deadline"])
def test_expiry_at_final_publication_rolls_back_every_projection(db, recipe, monkeypatch, stage, expired_field):
    """Real wall time must fence the final write, including cluster side effects.

    Inject time expiry only after the implementation has written its projections.
    PostgreSQL now() remains before expiry, so using it for the final CAS would
    incorrectly commit; clock_timestamp() must reject and roll back everything.
    """
    from app.services import story_clustering

    identifier = article(db)
    jobs = list(prepared(db))
    if stage == "cluster":
        for other_job, other_bundle in jobs:
            assert publish(db, other_job, other_bundle)
        job = next(item for item in repo.claim(db, limit=20) if item["stage"] == "cluster")
        bundle = repo.prepare(db, job)
    else:
        job, bundle = next(item for item in jobs if item[0]["stage"] == stage)
        # The second paid stage would also create a cluster job. Verify that
        # this scheduling side effect is rolled back with the failed result.
        for other_job, other_bundle in jobs:
            if other_job["id"] != job["id"]:
                assert publish(db, other_job, other_bundle)

    tables = ("article_understanding_results", "understanding_outbox", "story_memberships",
              "story_membership_events", "story_clusters", "article_understanding_jobs")

    def counts(conn):
        return {table: conn.execute(sql.SQL("SELECT count(*) AS n FROM public.{}").format(
            sql.Identifier(table))).fetchone()["n"] for table in tables}

    before = counts(db)
    finish = repo.finish_publication
    reached_final_write = []

    def expire_then_finish(conn, finishing_job):
        staged = counts(conn)
        assert staged["understanding_outbox"] > before["understanding_outbox"]
        if stage == "cluster":
            assert staged["story_memberships"] == before["story_memberships"] + 1
            assert staged["story_membership_events"] == before["story_membership_events"] + 1
        else:
            assert staged["article_understanding_results"] == before["article_understanding_results"] + 1
            assert staged["article_understanding_jobs"] == before["article_understanding_jobs"] + 1
        conn.execute(sql.SQL("UPDATE public.article_understanding_jobs SET {}=clock_timestamp() "
                             "+ interval '20 milliseconds' WHERE id=%s").format(sql.Identifier(expired_field)),
                     (finishing_job["id"],))
        conn.execute("SELECT pg_sleep(0.03)")
        clock = conn.execute(sql.SQL("SELECT {} > now() AS transaction_clock_valid, "
                                    "{} < clock_timestamp() AS wall_clock_expired "
                                    "FROM public.article_understanding_jobs WHERE id=%s").format(
                                        sql.Identifier(expired_field),sql.Identifier(expired_field)),
                             (finishing_job["id"],)).fetchone()
        assert clock["transaction_clock_valid"] and clock["wall_clock_expired"]
        reached_final_write.append(True)
        return finish(conn, finishing_job)

    monkeypatch.setattr(repo, "finish_publication", expire_then_finish)
    result = story_clustering.assign_story(db, job, bundle) if stage == "cluster" else publish(db, job, bundle)
    assert reached_final_write == [True]
    assert result is False
    assert counts(db) == before
    persisted = db.execute("SELECT state,lease_token FROM public.article_understanding_jobs WHERE id=%s", (job["id"],)).fetchone()
    assert persisted["state"] == "running"
    assert persisted["lease_token"] == job["lease_token"]
    assert db.execute("SELECT id FROM public.articles WHERE id=%s", (identifier,)).fetchone() is not None


@pytest.mark.parametrize("change", ["generation", "recipe"])
def test_current_read_rechecks_generation_and_recipe_after_fetch(db, recipe, monkeypatch, change):
    identifier = article(db)
    for job, bundle in prepared(db):
        assert publish(db, job, bundle)
    assert repo.load_current(db, identifier, recipe)["state"] == "ready"
    evidence = repo.evidence_for_article
    reads = []

    def changed_during_read(conn, article_id, **kwargs):
        reads.append(article_id)
        if len(reads) == 2:
            if change == "generation":
                # A revoke/restore cycle preserves content but must invalidate
                # results fetched before that eligibility generation changed.
                repo.revoke(conn, article_id, True)
                repo.revoke(conn, article_id, False)
            else:
                repo.set_recipe_enabled(conn, recipe, False)
        return evidence(conn, article_id, **kwargs)

    monkeypatch.setattr(repo, "evidence_for_article", changed_during_read)
    current = repo.load_current(db, identifier, recipe)
    assert len(reads) == 2
    assert current["state"] == ("stale" if change == "generation" else "disabled")
    assert "facets" not in current and "membership" not in current
