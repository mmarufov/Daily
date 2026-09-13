"""Hosted disposable PostgreSQL S4 invariants; never mutate the supplied DB.

S4_TEST_DATABASE_URL must name a server with CREATEDB and pgvector. The suite
creates one random database and touches only that database. No provider is
called. Synthetic approvals below are fixture state, not quality evidence.
S4_TEST_DATABASE_REQUIRED=1 makes absent infrastructure a collection failure.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import os
import secrets
import threading
from types import SimpleNamespace
import uuid

import pytest

REQUIRED = os.getenv("S4_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.services.article_content import ensure_article_content_schema
from app.services import event_repository as repo
from app.services import understanding_repository as s3
from app.services.event_contract import DIMENSIONS, digest, snapshot_hash, timestamp
from app.services.understanding_contract import DEFAULT_RECIPE as S3_RECIPE

BASE_URL = os.getenv("S4_TEST_DATABASE_URL")
if REQUIRED and not BASE_URL:
    raise RuntimeError("S4_TEST_DATABASE_REQUIRED=1 requires S4_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="S4_TEST_DATABASE_URL is not set")


@pytest.fixture(scope="session")
def s4_database_url():
    name = f"daily_s4_test_{os.getpid()}_{secrets.token_hex(8)}"
    admin = None
    created = False
    try:
        try:
            admin = psycopg.connect(BASE_URL, autocommit=True, connect_timeout=10)
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            created = True
            parameters = conninfo_to_dict(BASE_URL)
            parameters["dbname"] = name
            url = make_conninfo(**parameters)
            with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
                conn.execute("CREATE TABLE public.users (id uuid PRIMARY KEY)")
                conn.execute("""CREATE TABLE public.articles (
                  id uuid PRIMARY KEY, title text NOT NULL, summary text, author text,
                  source_name text, source_id uuid, url text, image_url text,
                  published_at timestamptz, ingested_at timestamptz NOT NULL DEFAULT now(),
                  language text, source_acquisition_url text, source_acquisition_kind text,
                  category text, content text, content_extracted boolean NOT NULL DEFAULT false,
                  embedding text)""")
                conn.execute("""CREATE TABLE public.reading_events (
                  user_id uuid NOT NULL, feed_request_id uuid, article_id uuid NOT NULL,
                  event_type text NOT NULL)""")
                ensure_article_content_schema(conn)
                s3.ensure_schema(conn)
                repo.ensure_schema(conn)
                repo.ensure_schema(conn)
                repo.check_schema(conn)
        except Exception as exc:
            # Never leak provider credentials through a failed connection string.
            pytest.fail(f"S4 disposable PostgreSQL setup failed ({type(exc).__name__})")
        yield url
    finally:
        if admin is not None:
            try:
                if created:
                    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            finally:
                admin.close()


@pytest.fixture
def db(s4_database_url):
    with psycopg.connect(s4_database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("""TRUNCATE public.users, public.articles, public.article_source_policies,
          public.article_source_policy_events, public.understanding_recipes,
          public.understanding_control, public.understanding_outbox,
          public.understanding_consumer_cursors, public.understanding_event_receipts,
          public.understanding_spend, public.event_recipes, public.event_control,
          public.event_source_registry, public.event_jobs, public.event_spend,
          public.event_upstream_notices, public.event_inbox_receipts,
          public.event_scan_state, public.event_outbox, public.event_delivery_receipts,
          public.event_development_aliases, public.reading_events RESTART IDENTITY CASCADE""")
        conn.execute("INSERT INTO public.understanding_control(singleton) VALUES(true)")
        conn.execute("INSERT INTO public.event_control(singleton) VALUES(true)")
        yield conn


@pytest.fixture
def recipes(db):
    upstream = s3.register_recipe(db, S3_RECIPE, enabled=True)
    s3.configure(db, submissions_enabled=True, daily_budget_usd="1")
    # Isolated fixture prerequisite. Never write a forged evaluation artifact or
    # run an operational approval command; this is not a promoted real recipe.
    db.execute("UPDATE public.understanding_recipes SET approved=true WHERE id=%s", (upstream,))
    db.execute("UPDATE public.understanding_control SET serving_recipe=%s", (upstream,))
    downstream = repo.register_recipe(db, {**deepcopy(repo.DEFAULT_RECIPE),
        "s3_recipe_id": upstream, "supported_languages": ["en"], "coverage_supported": True}, enabled=True)
    repo.configure(db, submissions_enabled=True, daily_budget_usd="1", monthly_budget_usd="2",
                   expected_generation=1)
    # An explicit synthetic upstream coverage attestation is required even in
    # this isolated fixture. Runtime assessment must never mint a watermark.
    db.execute("""UPDATE public.event_control SET coverage_verified=true,
      coverage_observed_through=clock_timestamp()""")
    return upstream, downstream


def _article(db):
    identifier = uuid.uuid4()
    db.execute("""INSERT INTO public.articles(id,title,summary,url,source_name,canonical_source_domain,language)
      VALUES(%s,'Research satellite launches','A satellite launched on Tuesday.',%s,'example.com','example.com','en')""",
      (identifier, f"https://example.com/story/{identifier}"))
    return identifier


def _card(bundle):
    title = bundle["fields"]["title"]
    return {"article_id": bundle["article_id"], "input_hash": bundle["input_hash"],
        "kind": "unknown", "kind_evidence": [], "topics": [], "entities": [], "places": [],
        "commercial": {"value": "unknown", "subtype": None, "evidence": []},
        "about": None, "about_evidence": [],
        "event_hints": [{"actors": [], "action": "launches", "object": "satellite",
                         "date": None, "place_ids": [],
                         "evidence": [{"field": "title", "start": 0, "end": len(title), "quote": title}]}],
        "abstentions": [{"field": field, "reason": "insufficient_evidence"}
                        for field in ("kind", "topics", "entities", "places", "commercial", "about")]}


def _current_article(db, recipes):
    identifier = _article(db)
    _publish_article(db, identifier, recipes[0])
    return identifier


def _publish_article(db, identifier, recipe):
    for job in s3.claim(db, limit=20):
        if job["article_id"] != identifier or job["stage"] not in {"facets", "embedding"}:
            continue
        bundle = s3.prepare(db, job)
        payload = _card(bundle) if job["stage"] == "facets" else {"vector": [1.] + [0.] * 1535}
        assert s3.publish(db, job, bundle, payload)
    assert s3.load_current(db, identifier, recipe)["state"] == "ready"


def _intake(db, recipes):
    article = _current_article(db, recipes)
    repo.reconcile(db, recipes[1], limit=20)
    job = next(j for j in repo.claim(db, limit=16) if j["stage"] == "ingest" and j["subject_id"] == article)
    assert repo.ingest(db, job) == 1
    event = db.execute("SELECT * FROM public.events WHERE seed_key=%s", (str(article) + ":0",)).fetchone()
    return article, event


def _assessment_job(db, recipes):
    article, event = _intake(db, recipes)
    # Test the assessment transaction independently of a paid refinement stage.
    db.execute("UPDATE public.event_jobs SET state='unsupported' WHERE state='pending'")
    repo._schedule(db, recipes[1], "assess", event["id"], event["generation"])
    job = next(j for j in repo.claim(db) if j["stage"] == "assess")
    frozen = repo.prepare(db, job)
    assert frozen is not None
    return article, job, frozen


def _assessment(frozen, *, ready=False):
    return {"event_id": frozen["event_id"], "generation": frozen["generation"], "recipe_id": frozen["recipe_id"],
        "snapshot_hash": snapshot_hash(frozen), "status": "ready" if ready else "insufficient",
        "tier": "routine" if ready else None,
        "dimensions": [{"name": name,
                        "value": "not_met" if ready and name == "consequence" else "unknown",
                        "evidence_ids": [e["id"] for e in frozen["evidence"]] if ready and name == "consequence" else []}
                       for name in DIMENSIONS],
        "scope": {"kind": "unknown", "place_ids": [], "sectors": [], "evidence_ids": []},
        "reason_codes": ["not_significant" if ready else "insufficient_evidence"],
        "evidence_ids": [e["id"] for e in frozen["evidence"]] if ready else [],
        "valid_until": (timestamp(frozen["as_of"]) + timedelta(minutes=5)).isoformat() if ready else None}


def _job_rows(db, recipe, count):
    for index in range(count):
        repo._schedule(db, recipe, "ingest", uuid.uuid4(), index, f"source-{index}")
    return repo.claim(db, limit=count)


def test_migration_is_explicit_idempotent_and_default_closed(db):
    repo.ensure_schema(db)
    repo.check_schema(db)
    control = repo.status(db)["control"]
    assert control["submissions_enabled"] is False
    assert control["delivery_enabled"] is False
    assert control["daily_budget_usd"] == 0
    assert control["coverage_verified"] is False
    assert control["coverage_observed_through"] is None
    assert repo.claim(db) == []
    assert repo.load_candidates(db) == []


def test_migration_preserves_populated_s3_and_s4_rows(db, recipes):
    article, event = _intake(db, recipes)
    before = db.execute("SELECT * FROM public.events WHERE id=%s", (event["id"],)).fetchone()
    repo.ensure_schema(db)
    assert db.execute("SELECT * FROM public.events WHERE id=%s", (event["id"],)).fetchone() == before
    assert s3.load_current(db, article, recipes[0])["state"] == "ready"


def test_controls_require_expected_generation_and_explicit_budget(db):
    with pytest.raises(ValueError, match="budgets"):
        repo.configure(db, submissions_enabled=True, expected_generation=1)
    repo.configure(db, submissions_enabled=True, daily_budget_usd=".1", monthly_budget_usd=".2", expected_generation=1)
    with pytest.raises(repo.StaleInput):
        repo.configure(db, submissions_enabled=False, expected_generation=1)
    with pytest.raises(ValueError, match="approved"):
        repo.configure(db, submissions_enabled=True, delivery_enabled=True,
                       daily_budget_usd=".1", monthly_budget_usd=".2", expected_generation=2)
    assert repo.status(db)["control"]["generation"] == 2


def test_s3_controls_and_recipe_toggles_emit_monotonic_notices(db, recipes):
    before = db.execute("SELECT serving_generation FROM public.understanding_control").fetchone()["serving_generation"]
    s3.configure(db, submissions_enabled=True, daily_budget_usd="1")
    assert db.execute("SELECT serving_generation FROM public.understanding_control").fetchone()["serving_generation"] > before
    s3.set_recipe_enabled(db, recipes[0], False)
    s3.set_recipe_enabled(db, recipes[0], True)
    row = db.execute("SELECT * FROM public.understanding_recipes WHERE id=%s", (recipes[0],)).fetchone()
    assert row["approved"] is False
    assert row["serving_generation"] >= 3
    kinds = {r["kind"] for r in db.execute("SELECT kind FROM public.event_upstream_notices").fetchall()}
    assert {"understanding_control", "understanding_recipes"} <= kinds
    with pytest.raises(repo.StaleInput, match="approved"):
        repo.reconcile(db, recipes[1])


def test_source_metadata_cas_and_policy_versions_are_distinct_fences(db, recipes):
    article = _current_article(db, recipes)
    repo.reconcile(db, recipes[1])
    source, original = repo._source(db, article)
    assert source["metadata"]["origin_status"] == "unknown"
    metadata = {**source["metadata"], "reporting_origin_id": "synthetic-wire-item", "origin_status": "verified"}
    repo.set_source(db, article, metadata, expected_generation=1, reviewed_by="synthetic-fixture")
    with pytest.raises(repo.StaleInput):
        repo.set_source(db, article, metadata, expected_generation=1, reviewed_by="synthetic-fixture")
    _, changed = repo._source(db, article)
    db.execute("INSERT INTO public.article_source_policies(source_domain) VALUES('example.com')")
    _, policy_changed = repo._source(db, article)
    assert len({original, changed, policy_changed}) == 3


def test_receipts_do_not_skip_lower_id_that_commits_later(db, s4_database_url):
    with psycopg.connect(s4_database_url, autocommit=True, row_factory=dict_row) as delayed:
        with delayed.transaction():
            low = delayed.execute("""INSERT INTO public.event_upstream_notices(kind,identity,generation)
              VALUES('test','delayed',1) RETURNING id""").fetchone()["id"]
            high = db.execute("""INSERT INTO public.event_upstream_notices(kind,identity,generation)
              VALUES('test','committed',1) RETURNING id""").fetchone()["id"]
            assert low < high
            assert repo.consume_changes(db) == 1
            assert db.execute("SELECT event_id FROM public.event_inbox_receipts WHERE stream='control'").fetchall() == [{"event_id": high}]
        assert repo.consume_changes(db) == 1
        assert repo.consume_changes(db) == 0
        assert {r["event_id"] for r in db.execute("SELECT event_id FROM public.event_inbox_receipts WHERE stream='control'").fetchall()} == {low, high}


def test_concurrent_claims_are_disjoint_and_bounded(db, recipes, s4_database_url):
    for index in range(8):
        repo._schedule(db, recipes[1], "ingest", uuid.uuid4(), index, f"source-{index}")
    barrier = threading.Barrier(2)
    def worker():
        with psycopg.connect(s4_database_url, autocommit=True, row_factory=dict_row) as conn:
            barrier.wait(timeout=10)
            return {j["id"] for j in repo.claim(conn, limit=4)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker) for _ in range(2)]
        left, right = [f.result(timeout=20) for f in futures]
    assert len(left) == len(right) == 4
    assert left.isdisjoint(right)
    assert repo.claim(db) == []


def test_concurrent_reservations_cannot_exceed_daily_cap(db, recipes, s4_database_url):
    jobs = _job_rows(db, recipes[1], 2)
    barrier = threading.Barrier(2)
    def worker(job):
        with psycopg.connect(s4_database_url, autocommit=True, row_factory=dict_row) as conn:
            barrier.wait(timeout=10)
            return repo.reserve(conn, job, ".6", digest(["request", job["id"]]))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, job) for job in jobs]
        reservations = [f.result(timeout=20) for f in futures]
    assert sum(r is not None for r in reservations) == 1
    assert repo.status(db)["spend"][0]["accounted_usd"] == Decimal(".6")


def test_ambiguous_charge_survives_lease_reaping_and_blocks_redispatch(db, recipes):
    job = _job_rows(db, recipes[1], 1)[0]
    reservation = repo.reserve(db, job, ".8", digest("request"))
    assert reservation is not None
    assert repo.reserve(db, job, ".1", digest("same-attempt")) is None
    db.execute("UPDATE public.event_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job["id"],))
    assert repo.reap(db) == 1
    db.execute("UPDATE public.event_jobs SET retry_at=clock_timestamp()-interval '1 second' WHERE id=%s", (job["id"],))
    replacement = repo.claim(db)[0]
    assert replacement["lease_token"] != job["lease_token"]
    assert repo.reserve(db, replacement, ".3", digest("retry")) is None
    assert repo.status(db)["spend"][0]["unresolved"] == 1
    repo.settle(db, reservation, ".2", "synthetic-request")
    repo.settle(db, reservation, ".2", "synthetic-request")
    with pytest.raises(ValueError, match="conflicting"):
        repo.settle(db, reservation, ".3")
    assert repo.reserve(db, replacement, ".3", digest("retry")) is not None


def test_settlement_overrun_trips_submission_and_delivery_circuit(db, recipes):
    job = _job_rows(db, recipes[1], 1)[0]
    reservation = repo.reserve(db, job, ".1", digest("request"))
    repo.settle(db, reservation, ".2")
    control = repo.status(db)["control"]
    assert control["submissions_enabled"] is False
    assert control["delivery_enabled"] is False
    assert control["circuit_reason"] == "estimate_exceeded"


def test_expired_assessment_lease_cannot_publish(db, recipes):
    _, job, frozen = _assessment_job(db, recipes)
    db.execute("UPDATE public.event_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job["id"],))
    assert repo.publish(db, job, frozen, _assessment(frozen)) is False
    assert db.execute("SELECT count(*) AS n FROM public.event_assessments").fetchone()["n"] == 0


def test_final_real_clock_fence_rolls_back_all_publication_effects(db, recipes, monkeypatch):
    _, job, frozen = _assessment_job(db, recipes)
    before = db.execute("SELECT count(*) AS n FROM public.event_outbox").fetchone()["n"]
    finish = repo._finish
    def expire_before_commit(conn, current, *args, **kwargs):
        conn.execute("UPDATE public.event_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (current["id"],))
        return finish(conn, current, *args, **kwargs)
    monkeypatch.setattr(repo, "_finish", expire_before_commit)
    assert repo.publish(db, job, frozen, _assessment(frozen)) is False
    assert db.execute("SELECT count(*) AS n FROM public.event_assessments").fetchone()["n"] == 0
    assert db.execute("SELECT current_assessment FROM public.events WHERE id=%s", (job["subject_id"],)).fetchone()["current_assessment"] is None
    assert db.execute("SELECT count(*) AS n FROM public.event_outbox").fetchone()["n"] == before
    assert db.execute("SELECT state FROM public.event_jobs WHERE id=%s", (job["id"],)).fetchone()["state"] == "running"


@pytest.mark.parametrize("change", ["article", "delete", "source", "source_policy", "s3_control", "s4_control", "member_removed", "negative_evidence"])
def test_complete_manifest_rejects_changes_before_publication(db, recipes, change):
    article, job, frozen = _assessment_job(db, recipes)
    if change == "article":
        db.execute("UPDATE public.articles SET title='Launch cancelled' WHERE id=%s", (article,))
    elif change == "delete":
        db.execute("DELETE FROM public.articles WHERE id=%s", (article,))
    elif change == "source":
        source, _ = repo._source(db, article)
        repo.set_source(db, article, source["metadata"], expected_generation=source["generation"], reviewed_by="synthetic-fixture")
    elif change == "source_policy":
        db.execute("INSERT INTO public.article_source_policies(source_domain) VALUES('example.com')")
    elif change == "s3_control":
        s3.configure(db, submissions_enabled=True, daily_budget_usd="1")
    elif change == "s4_control":
        repo.configure(db, submissions_enabled=False, expected_generation=2)
    elif change == "member_removed":
        db.execute("DELETE FROM public.event_evidence WHERE event_id=%s", (job["subject_id"],))
    else:
        payload = deepcopy(frozen["evidence"][0])
        payload["role"], payload["claim"]["modality"] = "contradiction", "denied"
        db.execute("UPDATE public.event_evidence SET payload=%s WHERE event_id=%s", (Jsonb(payload), job["subject_id"]))
    with pytest.raises((repo.StaleInput, ValueError)):
        repo.publish(db, job, frozen, _assessment(frozen))
    assert db.execute("SELECT count(*) AS n FROM public.event_assessments").fetchone()["n"] == 0


def test_source_only_reintake_preserves_development_identity_without_unique_conflict(db, recipes):
    article, event = _intake(db, recipes)
    development = db.execute("SELECT development_id FROM public.event_evidence WHERE event_id=%s", (event["id"],)).fetchone()["development_id"]
    source, _ = repo._source(db, article)
    repo.set_source(db, article, source["metadata"], expected_generation=source["generation"], reviewed_by="synthetic-fixture")
    db.execute("UPDATE public.event_jobs SET state='unsupported' WHERE state='pending'")
    repo.reconcile(db, recipes[1])
    job = next(j for j in repo.claim(db) if j["stage"] == "ingest")
    assert repo.ingest(db, job) == 1
    rows = db.execute("SELECT development_id FROM public.event_evidence WHERE event_id=%s AND active", (event["id"],)).fetchall()
    assert rows == [{"development_id": development}]


def test_deletion_preserves_reverse_identity_but_purges_private_evidence(db, recipes):
    article, job, frozen = _assessment_job(db, recipes)
    assert repo.publish(db, job, frozen, _assessment(frozen))
    db.execute("DELETE FROM public.articles WHERE id=%s", (article,))
    while repo.consume_changes(db):
        pass
    evidence = db.execute("SELECT article_id,active,payload FROM public.event_evidence WHERE event_id=%s", (job["subject_id"],)).fetchone()
    assert evidence == {"article_id": article, "active": False, "payload": None}
    assert db.execute("SELECT payload FROM public.event_snapshots WHERE event_id=%s", (job["subject_id"],)).fetchone()["payload"] is None
    assert db.execute("SELECT current_assessment FROM public.events WHERE id=%s", (job["subject_id"],)).fetchone()["current_assessment"] is None


def test_fresh_authorization_hides_committed_correction_without_waiting_for_notices(db, recipes):
    article, job, frozen = _assessment_job(db, recipes)
    assert repo.publish(db, job, frozen, _assessment(frozen, ready=True))
    # Synthetic isolated read-authorization fixture, not operational promotion.
    db.execute("UPDATE public.event_recipes SET approved=true WHERE id=%s", (recipes[1],))
    db.execute("UPDATE public.event_control SET serving_recipe=%s,delivery_enabled=true", (recipes[1],))
    assert len(repo.load_candidates(db)) == 1
    db.execute("UPDATE public.articles SET title='Launch cancelled' WHERE id=%s", (article,))
    assert repo.load_candidates(db) == []


def test_reader_expiry_is_enforced_with_scheduler_stopped(db, recipes):
    _, job, frozen = _assessment_job(db, recipes)
    assert repo.publish(db, job, frozen, _assessment(frozen, ready=True))
    db.execute("UPDATE public.event_recipes SET approved=true WHERE id=%s", (recipes[1],))
    db.execute("UPDATE public.event_control SET serving_recipe=%s,delivery_enabled=true", (recipes[1],))
    assert len(repo.load_candidates(db)) == 1
    db.execute("UPDATE public.event_assessments SET valid_until=clock_timestamp()-interval '1 second'")
    assert repo.load_candidates(db) == []


def _refinement(db, job):
    from app.services.event_refinement import prepare_input, validate_refinement
    frozen = repo.prepare(db, job)
    evidence, bundle = repo.refinement_inputs(db, job, frozen)
    provider_input = prepare_input(evidence, bundle)
    payload = {"evidence_id": evidence["id"], "input_hash": digest(provider_input),
        "role": "core", "modality": "reported", "attribution": None,
        "precision": "unknown", "date_text": None,
        "support": [{"field": "title", "quote": bundle["fields"]["title"]}]}
    return frozen, validate_refinement(payload, provider_input)


def test_fake_refinement_to_grouping_to_assessment_lifecycle(db, recipes):
    article, event = _intake(db, recipes)
    before = s3.load_current(db, article, recipes[0])
    refinement_job = next(j for j in repo.claim(db) if j["stage"] == "refine")
    frozen, checked = _refinement(db, refinement_job)
    assert repo.publish_refinement(db, refinement_job, frozen, checked)
    evidence = db.execute("SELECT refined,payload FROM public.event_evidence WHERE event_id=%s AND active", (event["id"],)).fetchone()
    assert evidence["refined"] is True
    assert evidence["payload"]["claim"]["modality"] == "reported"
    assert evidence["payload"]["claim"]["occurrence"]["precision"] == "unknown"
    grouping_job = next(j for j in repo.claim(db) if j["stage"] == "group")
    assert repo.group(db, grouping_job)
    assessment_job = next(j for j in repo.claim(db) if j["stage"] == "assess")
    current = repo.prepare(db, assessment_job)
    assert repo.publish(db, assessment_job, current, _assessment(current))
    assert db.execute("SELECT count(*) AS n FROM public.events").fetchone()["n"] == 1
    assert s3.load_current(db, article, recipes[0]) == before


def test_expired_refinement_rolls_back_evidence_and_next_stage(db, recipes):
    _, event = _intake(db, recipes)
    job = next(j for j in repo.claim(db) if j["stage"] == "refine")
    frozen, checked = _refinement(db, job)
    db.execute("UPDATE public.event_jobs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s", (job["id"],))
    assert repo.publish_refinement(db, job, frozen, checked) is False
    assert db.execute("SELECT refined FROM public.event_evidence WHERE event_id=%s AND active", (event["id"],)).fetchone()["refined"] is False
    assert db.execute("SELECT count(*) AS n FROM public.event_refinements").fetchone()["n"] == 0
    assert db.execute("SELECT count(*) AS n FROM public.event_jobs WHERE stage='group'").fetchone()["n"] == 0


def test_pending_deadline_and_final_expired_attempt_are_terminal(db, recipes):
    first, second = _job_rows(db, recipes[1], 2)
    db.execute("""UPDATE public.event_jobs SET attempts=5,lease_until=clock_timestamp()-interval '1 second'
      WHERE id=%s""", (first["id"],))
    db.execute("""UPDATE public.event_jobs SET state='pending',lease_token=NULL,lease_until=NULL,
      deadline=clock_timestamp()-interval '1 second' WHERE id=%s""", (second["id"],))
    assert repo.reap(db) == 2
    assert {r["state"] for r in db.execute("SELECT state FROM public.event_jobs").fetchall()} == {"failed_terminal"}
    assert repo.claim(db) == []


def test_assessment_does_not_mint_a_fresh_coverage_watermark(db, recipes):
    article, event = _intake(db, recipes)
    db.execute("UPDATE public.event_jobs SET state='unsupported' WHERE state='pending'")
    watermark = db.execute("""UPDATE public.event_control SET coverage_observed_through=clock_timestamp()-interval '2 hours'
      RETURNING coverage_observed_through""").fetchone()["coverage_observed_through"]
    repo._schedule(db, recipes[1], "assess", event["id"], event["generation"])
    job = next(j for j in repo.claim(db) if j["stage"] == "assess")
    frozen = repo.prepare(db, job)
    assert timestamp(frozen["coverage"]["observed_through"]) == watermark
    assert frozen["coverage"]["complete"] is False
    assert frozen["coverage"]["supported"] is False
    with pytest.raises(ValueError, match="coverage"):
        repo.publish(db, job, frozen, _assessment(frozen, ready=True))


@pytest.mark.parametrize("change", ["s4_recipe", "s3_recipe", "s3_control", "s4_control"])
def test_reservation_rechecks_recipe_and_control_after_snapshot_preparation(db, recipes, change):
    _, job, _ = _assessment_job(db, recipes)
    if change == "s4_recipe":
        repo.set_recipe_enabled(db, recipes[1], False)
    elif change == "s3_recipe":
        s3.set_recipe_enabled(db, recipes[0], False)
    elif change == "s3_control":
        s3.configure(db, submissions_enabled=True, daily_budget_usd="1")
    else:
        repo.configure(db, submissions_enabled=True, daily_budget_usd="1", monthly_budget_usd="2",
                       expected_generation=2)
    assert repo.reserve(db, job, ".1", digest("not-dispatched")) is None
    assert db.execute("SELECT count(*) AS n FROM public.event_spend").fetchone()["n"] == 0


@pytest.mark.parametrize("change", ["s3_control", "s4_control"])
def test_control_reintake_preserves_refinement_and_development_identity(db, recipes, change):
    article, event = _intake(db, recipes)
    job = next(j for j in repo.claim(db) if j["stage"] == "refine")
    frozen, checked = _refinement(db, job)
    assert repo.publish_refinement(db, job, frozen, checked)
    before = db.execute("SELECT development_id,payload FROM public.event_evidence WHERE event_id=%s AND active", (event["id"],)).fetchone()
    db.execute("UPDATE public.event_jobs SET state='unsupported' WHERE state='pending'")
    if change == "s3_control":
        s3.configure(db, submissions_enabled=True, daily_budget_usd="1")
    else:
        repo.configure(db, submissions_enabled=True, daily_budget_usd="1", monthly_budget_usd="2",
                       expected_generation=2)
    assert repo.reconcile(db, recipes[1])["inserted"] == 1
    replacement = next(j for j in repo.claim(db) if j["stage"] == "ingest")
    assert repo.ingest(db, replacement) == 1
    after = db.execute("SELECT development_id,payload,refined FROM public.event_evidence WHERE event_id=%s AND active", (event["id"],)).fetchone()
    assert after["development_id"] == before["development_id"]
    assert after["refined"] is True
    assert after["payload"]["claim"] == before["payload"]["claim"]
    assert after["payload"]["spans"] == before["payload"]["spans"]
    assert db.execute("SELECT count(*) AS n FROM public.event_jobs WHERE state='pending' AND stage='refine'").fetchone()["n"] == 0
    assert db.execute("SELECT count(*) AS n FROM public.event_jobs WHERE state='pending' AND stage='group'").fetchone()["n"] == 1


def _receipt_integration(db, recipes, monkeypatch):
    """Exercise real receipt/ack SQL with a deterministic composer boundary.

    Semantic selection and public projection are independently covered by the
    consumer/feed tests. This fixture isolates exact user/request/article joins.
    """
    from app.services import event_integration as integration
    from app.services import feed_service
    user, article = uuid.uuid4(), uuid.uuid4()
    event, development, assessment = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db.execute("INSERT INTO public.users(id) VALUES(%s)", (user,))
    db.execute("UPDATE public.event_recipes SET approved=true WHERE id=%s", (recipes[1],))
    db.execute("UPDATE public.event_control SET serving_recipe=%s,delivery_enabled=true", (recipes[1],))
    expiry = db.execute("SELECT clock_timestamp()+interval '5 minutes' AS expiry").fetchone()["expiry"].isoformat()
    metadata = {"event_id": str(event), "development_id": str(development), "development_version": 1,
                "assessment_id": str(assessment), "valid_until": expiry}
    seen = []
    def compose(result, candidates, policy, **kwargs):
        seen.append(policy.seen_development_versions)
        return SimpleNamespace(payload={"articles": [{"id": str(article), "event_delivery": metadata}]},
                               decisions=[{"reason": "reserved"}], major_candidates=[])
    monkeypatch.setenv("S4_CONSUMERS_ENABLED", "true")
    # S4 priority is only composed onto an edition something will receipt and
    # the client can echo back; with no publication path enabled the "already
    # knew" control this fixture is about could never suppress anything, so
    # `compose_feed` now declines to promise it. See
    # `event_integration._delivery_is_attributable` and
    # tests/test_event_suppression_loop_postgres.py.
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    monkeypatch.setattr(feed_service, "_load_user_preferences_full", lambda *args: ("", {}, {}, None, None))
    monkeypatch.setattr(feed_service, "_build_preference_profile", lambda *args, **kwargs: {})
    monkeypatch.setattr(repo, "load_candidates", lambda *args, **kwargs: [])
    monkeypatch.setattr(integration, "apply_event_feed", compose)
    return integration, user, article, development, seen


def test_delivery_receipt_is_not_a_read_acknowledgment(db, recipes, monkeypatch):
    integration, user, article, development, seen = _receipt_integration(db, recipes, monkeypatch)
    first = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    second = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    assert first["feed_request_id"] != second["feed_request_id"]
    assert seen == [frozenset(), frozenset()]
    assert db.execute("SELECT count(*) AS n FROM public.event_delivery_receipts WHERE user_id=%s", (user,)).fetchone()["n"] == 2
    assert db.execute("SELECT count(*) AS n FROM public.reading_events").fetchone()["n"] == 0


@pytest.mark.parametrize("case", ["read", "tap", "already_knew", "impression", "other_user", "other_request", "other_article"])
def test_suppression_requires_explicit_ack_bound_to_user_request_and_article(db, recipes, monkeypatch, case):
    integration, user, article, development, seen = _receipt_integration(db, recipes, monkeypatch)
    first = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    event_type = case if case in {"read", "tap", "already_knew", "impression"} else "read"
    db.execute("""INSERT INTO public.reading_events(user_id,feed_request_id,article_id,event_type)
      VALUES(%s,%s,%s,%s)""", (uuid.uuid4() if case == "other_user" else user,
        uuid.uuid4() if case == "other_request" else uuid.UUID(first["feed_request_id"]),
        uuid.uuid4() if case == "other_article" else article, event_type))
    integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    expected = frozenset({(str(development), 1)}) if case in {"read", "tap", "already_knew"} else frozenset()
    assert seen[-1] == expected


def test_account_deletion_cascades_private_delivery_receipts(db, recipes, monkeypatch):
    integration, user, article, development, seen = _receipt_integration(db, recipes, monkeypatch)
    delivered = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    assert "feed_request_id" in delivered
    db.execute("DELETE FROM public.users WHERE id=%s", (user,))
    assert db.execute("SELECT count(*) AS n FROM public.event_delivery_receipts WHERE user_id=%s", (user,)).fetchone()["n"] == 0


def test_old_version_read_does_not_acknowledge_a_later_material_development(db, recipes, monkeypatch):
    integration, user, article, development, seen = _receipt_integration(db, recipes, monkeypatch)
    first = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    # The deterministic composer exposes a newer version on subsequent calls.
    # The already committed receipt remains immutable version-one attribution.
    first["articles"][0]["event_delivery"]["development_version"] = 2
    second = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    assert second["feed_request_id"] != first["feed_request_id"]
    db.execute("INSERT INTO public.reading_events VALUES(%s,%s,%s,'read')",
               (user, uuid.UUID(first["feed_request_id"]), article))
    integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    assert seen[-1] == frozenset({(str(development), 1)})
    assert (str(development), 2) not in seen[-1]


def test_receipt_write_failure_returns_ordinary_feed_without_priority(db, recipes, monkeypatch):
    integration, user, article, development, seen = _receipt_integration(db, recipes, monkeypatch)
    db.execute("DELETE FROM public.users WHERE id=%s", (user,))
    ordinary = {"articles": [], "status": "needs_discovery"}
    assert integration.compose_feed(db, str(user), ordinary, capability="1") == ordinary
    assert db.execute("SELECT count(*) AS n FROM public.event_delivery_receipts").fetchone()["n"] == 0


def _lineage_development(db, recipe, identifier, *, version=1):
    event = uuid.uuid4()
    db.execute("INSERT INTO public.events(id,recipe_id,seed_key) VALUES(%s,%s,%s)",
               (event, recipe, "synthetic-lineage:" + str(identifier)))
    db.execute("INSERT INTO public.event_developments(id,event_id,version,fingerprint) VALUES(%s,%s,%s,%s)",
               (identifier, event, version, digest(str(identifier))))
    for number in range(1, version + 1):
        db.execute("INSERT INTO public.development_versions(development_id,version,claim_hash,change_kind) VALUES(%s,%s,%s,'synthetic-test')",
                   (identifier, number, digest([str(identifier), number])))


@pytest.mark.parametrize("transitive", [False, True])
def test_read_before_merge_follows_exact_version_alias_not_later_material_version(db, recipes, monkeypatch, transitive):
    integration, user, article, old, seen = _receipt_integration(db, recipes, monkeypatch)
    first = integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    db.execute("INSERT INTO public.reading_events VALUES(%s,%s,%s,'read')",
               (user, uuid.UUID(first["feed_request_id"]), article))
    target = uuid.uuid4()
    _lineage_development(db, recipes[1], old)
    _lineage_development(db, recipes[1], target, version=2)
    if transitive:
        middle = uuid.uuid4()
        _lineage_development(db, recipes[1], middle)
        db.execute("INSERT INTO public.event_development_aliases VALUES(%s,1,%s,1)", (old, middle))
        db.execute("INSERT INTO public.event_development_aliases VALUES(%s,1,%s,1)", (middle, target))
    else:
        db.execute("INSERT INTO public.event_development_aliases VALUES(%s,1,%s,1)", (old, target))
    integration.compose_feed(db, str(user), {"articles": []}, capability="1")
    expected = {(str(old), 1), (str(target), 1)}
    if transitive:
        expected.add((str(middle), 1))
    assert seen[-1] == frozenset(expected)
    assert (str(target), 2) not in seen[-1]


def test_merge_chooses_active_development_not_lowest_historical_uuid(db, recipes, monkeypatch):
    from app.services import event_grouping
    definition = deepcopy(repo.DEFAULT_RECIPE)
    definition.update(s3_recipe_id=recipes[0], supported_languages=["en"],
                      coverage_supported=True, grouping_calibrated=True)
    calibrated = repo.register_recipe(db, definition, enabled=True)
    grouping_recipes = (recipes[0], calibrated)
    _, first = _intake(db, grouping_recipes)
    _, second = _intake(db, grouping_recipes)
    winner, loser = sorted([first["id"], second["id"]], key=str)
    active = db.execute("SELECT development_id FROM public.event_evidence WHERE event_id=%s AND active", (winner,)).fetchone()["development_id"]
    inactive = uuid.UUID(int=0)
    db.execute("INSERT INTO public.event_developments(id,event_id,fingerprint) VALUES(%s,%s,'historical-inactive')", (inactive, winner))
    db.execute("INSERT INTO public.development_versions(development_id,version,claim_hash,change_kind) VALUES(%s,1,%s,'synthetic-test')",
               (inactive, digest("inactive")))
    db.execute("UPDATE public.event_jobs SET state='unsupported',lease_token=NULL,lease_until=NULL WHERE state IN ('running','pending')")
    db.execute("UPDATE public.event_evidence SET refined=true WHERE event_id=ANY(%s)", ([winner, loser],))
    # Isolate merge persistence from independently tested/calibrated semantic
    # matching. This fixture is not evidence of event-membership model accuracy.
    monkeypatch.setattr(event_grouping, "relation", lambda *args, **kwargs: {"relation": "same_development"})
    generation = db.execute("SELECT generation FROM public.events WHERE id=%s", (loser,)).fetchone()["generation"]
    repo._schedule(db, calibrated, "group", loser, generation)
    job = next(j for j in repo.claim(db) if j["stage"] == "group")
    assert repo.group(db, job)
    active_ids = {r["development_id"] for r in db.execute("SELECT development_id FROM public.event_evidence WHERE event_id=%s AND active", (winner,)).fetchall()}
    assert active_ids == {active}
    assert inactive not in active_ids
    alias = db.execute("SELECT target_id,target_version FROM public.event_development_aliases").fetchone()
    assert alias["target_id"] == active


def test_old_invalidation_delivered_after_ready_does_not_erase_current_assessment(db, recipes):
    article, job, frozen = _assessment_job(db, recipes)
    assert repo.publish(db, job, frozen, _assessment(frozen, ready=True))
    before = db.execute("SELECT current_assessment,generation FROM public.events WHERE id=%s", (job["subject_id"],)).fetchone()
    # The initial article insertion notice has never been consumed. Its input
    # coordinates equal the snapshot; it does not supersede that snapshot.
    while repo.consume_changes(db):
        pass
    assert db.execute("SELECT current_assessment,generation FROM public.events WHERE id=%s", (job["subject_id"],)).fetchone() == before
    assert db.execute("SELECT active FROM public.event_evidence WHERE event_id=%s", (job["subject_id"],)).fetchone()["active"] is True
    assert db.execute("SELECT payload FROM public.event_snapshots WHERE id=%s", (snapshot_hash(frozen),)).fetchone()["payload"] is not None


def test_correction_and_deletion_purge_inactive_history_without_erasing_newer_snapshot(db, recipes):
    article, job, old = _assessment_job(db, recipes)
    assert repo.publish(db, job, old, _assessment(old))
    old_item = old["evidence"][0]
    db.execute("""INSERT INTO public.event_refinements(event_id,evidence_id,input_hash,recipe_id,payload)
      VALUES(%s,%s,%s,%s,%s)""", (job["subject_id"], old_item["id"], digest("historical-refinement"),
        recipes[1], Jsonb({"evidence": old_item, "synthetic_fixture": True})))
    db.execute("UPDATE public.articles SET title='Corrected research satellite launches' WHERE id=%s", (article,))
    _publish_article(db, article, recipes[0])
    repo.reconcile(db, recipes[1])
    intake = next(j for j in repo.claim(db, limit=16) if j["stage"] == "ingest")
    assert repo.ingest(db, intake) == 1
    db.execute("UPDATE public.event_jobs SET state='unsupported' WHERE state='pending'")
    event = db.execute("SELECT * FROM public.events WHERE id=%s", (job["subject_id"],)).fetchone()
    repo._schedule(db, recipes[1], "assess", event["id"], event["generation"])
    next_job = next(j for j in repo.claim(db) if j["stage"] == "assess")
    current = repo.prepare(db, next_job)
    assert repo.publish(db, next_job, current, _assessment(current))
    assert current["evidence"][0]["dependency"]["semantic_revision"] > old_item["dependency"]["semantic_revision"]
    while repo.consume_changes(db):
        pass
    assert db.execute("SELECT payload FROM public.event_snapshots WHERE id=%s", (snapshot_hash(old),)).fetchone()["payload"] is None
    assert db.execute("SELECT payload FROM public.event_refinements WHERE event_id=%s", (event["id"],)).fetchone()["payload"] is None
    assert db.execute("SELECT payload FROM public.event_snapshots WHERE id=%s", (snapshot_hash(current),)).fetchone()["payload"] is not None
    db.execute("DELETE FROM public.articles WHERE id=%s", (article,))
    while repo.consume_changes(db):
        pass
    assert all(row["payload"] is None for row in db.execute("SELECT payload FROM public.event_snapshots WHERE event_id=%s", (event["id"],)).fetchall())
    assert all(row["payload"] is None and not row["active"] for row in db.execute("SELECT payload,active FROM public.event_evidence WHERE event_id=%s", (event["id"],)).fetchall())
