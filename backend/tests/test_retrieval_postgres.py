"""Opt-in S6 SQL contracts against a newly created disposable database only.

S6_TEST_DATABASE_URL must explicitly name a PostgreSQL server with CREATEDB and
pgvector available. No application DATABASE_URL or backend/.env is consulted.
S6_TEST_DATABASE_REQUIRED=1 makes missing infrastructure fail instead of skip.
These correctness tests are not a latency benchmark or an ANN recall gate.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import secrets
import uuid

import pytest

REQUIRED = os.getenv("S6_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.pq import TransactionStatus
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.services.article_content import ensure_article_content_schema
from app.services import reader_retrieval as retrieval
from app.services import understanding_repository as understanding
from app.services.retrieval_contract import RetrievalRequest
from app.services.understanding_contract import DEFAULT_RECIPE, TOPIC_IDS, validate_card

BASE_URL = os.getenv("S6_TEST_DATABASE_URL")
if REQUIRED and not BASE_URL:
    raise RuntimeError("S6_TEST_DATABASE_REQUIRED=1 requires S6_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="S6_TEST_DATABASE_URL is not set")
AS_OF = datetime(2026, 9, 7, 12, tzinfo=timezone.utc)
USER = str(uuid.UUID(int=900_001))


@pytest.fixture(scope="session")
def s6_database_url():
    name = f"daily_s6_test_{os.getpid()}_{secrets.token_hex(8)}"
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
                understanding.ensure_schema(conn)
                understanding.check_schema(conn)
                # Matches manage_s5_reader.py's `index` command: lexical_rows/
                # _s6_page read this generated column directly rather than
                # recomputing to_tsvector(title||summary) inline per query.
                conn.execute("""ALTER TABLE public.articles ADD COLUMN
                  title_summary_tsv tsvector GENERATED ALWAYS AS
                  (to_tsvector('simple',COALESCE(title,'')||' '||COALESCE(summary,''))) STORED""")
        except Exception as exc:
            reason = f"S6 PostgreSQL setup unavailable ({type(exc).__name__})"
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
def db(s6_database_url, monkeypatch):
    for flag in ("S6_DENSE_ENABLED", "S6_ANN_ENABLED"):
        monkeypatch.setenv(flag, "false")
    with psycopg.connect(s6_database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("""TRUNCATE public.articles, public.understanding_recipes,
          public.understanding_control, public.understanding_outbox,
          public.understanding_consumer_cursors, public.understanding_spend
          RESTART IDENTITY CASCADE""")
        conn.execute("INSERT INTO public.understanding_control(singleton) VALUES(true)")
        yield conn


def profile(*queries, policies=None):
    return {"generation": 1, "revision": 1, "learning_revision": 1,
            "migration_status": "ready", "profile": {
                "intents": [{"id": str(uuid.UUID(int=1000 + index)), "kind": "topic",
                             "label": query, "query": query, "priority": 1.0}
                            for index, query in enumerate(queries)],
                "policies": policies or []}}


def article(db, number, *, title="Satellite launch", source="independent.example.com",
            published=None, ingested=None, url=True):
    identifier = uuid.UUID(int=number)
    db.execute("""INSERT INTO public.articles
      (id,title,summary,url,source_name,canonical_source_domain,source_id,published_at,ingested_at)
      VALUES(%s,%s,'',%s,%s,%s,%s,%s,%s)""", (
        identifier, title, f"https://{source}/story/{identifier}" if url else None,
        source, source, uuid.UUID(int=number + 1_000_000),
        published or AS_OF - timedelta(hours=1), ingested or AS_OF - timedelta(hours=1)))
    return str(identifier)


def build(db, reader=None, **kwargs):
    # Freeze the cooperative wall clock for deterministic SQL correctness tests;
    # actual SQL still has the service's statement and lock timeouts.
    return retrieval.build_candidate_batch(db, USER, reader or profile("Satellite"),
        as_of=AS_OF, clock=lambda: 0.0, **kwargs)


@pytest.fixture
def promoted_recipe(db):
    identifier = understanding.register_recipe(db, DEFAULT_RECIPE, enabled=True)
    # This is synthetic fixture promotion inside the disposable database, not
    # a quality approval or a path available to retrieval in production.
    db.execute("UPDATE public.understanding_recipes SET approved=true WHERE id=%s", (identifier,))
    db.execute("UPDATE public.understanding_control SET serving_recipe=%s", (identifier,))
    return db.execute("SELECT * FROM public.understanding_recipes WHERE id=%s", (identifier,)).fetchone()


def understanding_result(db, identifier, recipe, *, vector=None, topic=None, role="primary"):
    bundle = understanding.evidence_for_article(db, identifier)
    if vector is not None:
        stage, payload = "embedding", {"dimensions": 1536}
    else:
        stage = "facets"
        fields = ("kind", "topics", "entities", "places", "commercial", "about", "event_hints")
        payload = {"article_id": bundle["article_id"], "input_hash": bundle["input_hash"],
                   "kind": "unknown", "kind_evidence": [], "topics": [], "entities": [], "places": [],
                   "commercial": {"value": "unknown", "subtype": None, "evidence": []},
                   "about": None, "about_evidence": [], "event_hints": [],
                   "abstentions": [{"field": field, "reason": "insufficient_evidence"}
                                   for field in fields if field != "topics" or topic is None]}
        if topic is not None:
            title = bundle["fields"]["title"]
            payload["topics"] = [{"topic_id": topic, "role": role,
                "evidence": [{"field": "title", "start": 0, "end": len(title), "quote": title}]}]
        payload = validate_card(payload, bundle)
    manifest = {"manifest": bundle["manifest"], "evidence_tier": bundle["evidence_tier"],
                "language": bundle.get("language")}
    db.execute("""INSERT INTO public.article_understanding_results
      (article_id,semantic_revision,eligibility_generation,recipe_id,stage,input_hash,
       evidence_manifest,payload,embedding)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)""", (
        identifier, bundle["semantic_revision"], bundle["analysis_eligibility_generation"],
        recipe["id"], stage, bundle["input_hash"], Jsonb(manifest), Jsonb(payload),
        str(vector) if vector is not None else None))
    return bundle


def request_for(reader=None):
    reader = reader or profile("Satellite")
    return RetrievalRequest(user_id=USER, profile=reader["profile"], as_of=AS_OF,
                            generation=1, revision=1, learning_revision=1)


def test_global_pool_works_without_subscriptions_or_promoted_recipe(db):
    expected = {article(db, 1), article(db, 2, source="another.example.org")}
    article(db, 3, title="Unrelated football match")
    batch = build(db)
    assert {item.article_id for item in batch.candidates} == expected
    assert batch.s3_recipe_id is None
    assert all({match.leg for match in item.matches} == {"lexical"} for item in batch.candidates)
    assert db.execute("SELECT to_regclass('public.user_sources') AS relation").fetchone()["relation"] is None
    assert all("relevant" not in item.article for item in batch.candidates)
    assert db.info.transaction_status == TransactionStatus.IDLE


def test_real_lexical_query_preserves_unicode_and_requires_every_term(db):
    expected = article(db, 1, title="Новости Таджикистана")
    article(db, 2, title="Новости мира")
    article(db, 3, title="Таджикистана спорт")
    assert [item.article_id for item in build(db, profile("Новости Таджикистана")).candidates] == [expected]


def test_keyset_pages_are_tie_stable_and_disjoint(db):
    expected = [article(db, number) for number in range(1, 8)]
    reader = profile("Satellite")
    request = RetrievalRequest(user_id=USER, profile=reader["profile"], as_of=AS_OF,
                               generation=1, revision=1, learning_revision=1)
    state = {"leg": "lexical", "query": "Satellite", "cursor": None}
    ids = []
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for _ in range(4):
            rows = retrieval._s6_page(db, state, request=request, recipe=None, count=2,
                                      config=retrieval.retrieval_configuration())
            ids.extend(str(row["id"]) for row in rows)
            if rows:
                state["cursor"] = (rows[-1]["score"], str(rows[-1]["id"]))
    assert ids == expected
    assert len(ids) == len(set(ids))


def test_repeatable_pages_do_not_mix_concurrent_article_corrections(db, s6_database_url):
    first, second = article(db, 1), article(db, 2)
    reader = profile("Satellite")
    request = RetrievalRequest(user_id=USER, profile=reader["profile"], as_of=AS_OF,
                               generation=1, revision=1, learning_revision=1)
    state = {"leg": "lexical", "query": "Satellite", "cursor": None}
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        page = retrieval._s6_page(db, state, request=request, recipe=None, count=1,
                                  config=retrieval.retrieval_configuration())
        assert str(page[0]["id"]) == first
        state["cursor"] = (page[0]["score"], first)
        with psycopg.connect(s6_database_url, autocommit=True) as other:
            other.execute("UPDATE public.articles SET title='Corrected football story' WHERE id=%s", (second,))
        page = retrieval._s6_page(db, state, request=request, recipe=None, count=1,
                                  config=retrieval.retrieval_configuration())
        assert [str(row["id"]) for row in page] == [second]
    # Fresh retrieval sees the corrected publisher metadata, unlike the earlier
    # snapshot. Runtime publication must separately fence this same situation.
    assert [item.article_id for item in build(db).candidates] == [first]


def test_future_old_and_undisplayable_rows_are_excluded(db):
    expected = article(db, 1)
    article(db, 2, published=AS_OF + timedelta(seconds=1))
    article(db, 3, ingested=AS_OF + timedelta(seconds=1))
    article(db, 4, published=AS_OF - timedelta(days=14))
    article(db, 5, url=False)
    batch = build(db)
    assert [item.article_id for item in batch.candidates] == [expected]
    assert batch.diagnostics["rejected"]["display_unavailable"] == 1


def test_analysis_revocation_does_not_hide_displayable_lexical_metadata(db):
    expected = article(db, 1)
    understanding.revoke(db, expected)
    batch = build(db)
    assert [item.article_id for item in batch.candidates] == [expected]
    assert {match.leg for match in batch.candidates[0].matches} == {"lexical"}


def test_missing_subject_evidence_fails_closed_without_inventing_metadata(db):
    article(db, 1)
    policy = {"id": str(uuid.UUID(int=2000)), "kind": "subject",
              "scope": "sector", "value": "sector:advertising"}
    batch = build(db, profile("Satellite", policies=[policy]))
    assert batch.candidates == []
    assert batch.diagnostics["rejected"]["policy_unknown"] == 1


def test_policy_filtering_refills_beyond_first_300_rows(db):
    with db.transaction():
        for number in range(1, 301):
            article(db, number, source="blocked.example.com")
        expected = {article(db, number) for number in range(301, 351)}
    policy = {"id": str(uuid.UUID(int=2000)), "kind": "publisher",
              "scope": "source", "value": "blocked.example.com"}
    batch = build(db, profile("Satellite", policies=[policy]), limit=50)
    assert {item.article_id for item in batch.candidates} == expected
    assert batch.diagnostics["rounds"] >= 2
    assert batch.diagnostics["rejected"]["policy_denied"] == 300


def test_single_lexical_leg_can_return_the_full_300(db):
    with db.transaction():
        expected = {article(db, number) for number in range(1, 301)}
    batch = build(db, limit=300)
    assert {item.article_id for item in batch.candidates} == expected
    assert batch.diagnostics["returned"] == 300


def test_builder_owns_repeatable_read_only_transaction_and_restores_settings(db, monkeypatch):
    expected = article(db, 1)
    original = retrieval._s6_page
    before = db.execute("SHOW statement_timeout").fetchone()["statement_timeout"]
    observed = []

    def checked(conn, state, **kwargs):
        observed.append((conn.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"],
                         conn.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]))
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            with conn.transaction():
                conn.execute("UPDATE public.articles SET title='must not persist'")
        return original(conn, state, **kwargs)

    monkeypatch.setattr(retrieval, "_s6_page", checked)
    assert [item.article_id for item in build(db).candidates] == [expected]
    assert observed and set(observed) == {("repeatable read", "on")}
    assert db.info.transaction_status == TransactionStatus.IDLE
    assert db.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == before
    assert db.execute("SELECT title FROM public.articles").fetchone()["title"] == "Satellite launch"


def test_existing_transaction_is_rejected_without_rolling_back_caller(db):
    with db.transaction():
        expected = article(db, 1)
        with pytest.raises(ValueError, match="idle"):
            build(db)
        assert db.info.transaction_status == TransactionStatus.INTRANS
    assert str(db.execute("SELECT id FROM public.articles").fetchone()["id"]) == expected


def test_failed_sql_leg_rolls_back_before_another_intent_runs(db, monkeypatch):
    expected = article(db, 1, title="Robotics breakthrough")
    original = retrieval._s6_page

    def failing(conn, state, **kwargs):
        if state.get("query") == "Satellite":
            conn.execute("SELECT * FROM public.deliberately_missing_s6_test_relation")
        return original(conn, state, **kwargs)

    monkeypatch.setattr(retrieval, "_s6_page", failing)
    batch = build(db, profile("Satellite", "Robotics"))
    assert [item.article_id for item in batch.candidates] == [expected]
    assert batch.status == "degraded"
    assert any(leg["status"] == "failed" for leg in batch.diagnostics["legs"])
    assert db.info.transaction_status == TransactionStatus.IDLE


def test_exact_dense_sql_orders_cosine_pages_and_restores_index_setting(db, promoted_recipe):
    vectors = ([1.0, 0.0], [0.8, 0.6], [0.0, 1.0])
    expected = []
    bundles = {}
    for number, prefix in enumerate(vectors, 1):
        identifier = article(db, number)
        expected.append(identifier)
        bundles[identifier] = understanding_result(db, identifier, promoted_recipe,
            vector=[*prefix, *([0.0] * 1534)])
    state = {"leg": "dense", "vector": [1.0, *([0.0] * 1535)], "cursor": None}
    config = {**retrieval.retrieval_configuration(), "ann": False}
    actual = []
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        before = db.execute("SHOW enable_indexscan").fetchone()["enable_indexscan"]
        for _ in range(2):
            with db.transaction():
                rows = retrieval._s6_page(db, state, request=request_for(),
                    recipe=promoted_recipe, count=2, config=config)
            assert db.execute("SHOW enable_indexscan").fetchone()["enable_indexscan"] == before
            actual.extend(rows)
            if rows:
                state["cursor"] = (rows[-1]["score"], str(rows[-1]["id"]))
    assert [str(row["id"]) for row in actual] == expected
    assert [row["score"] for row in actual] == pytest.approx([1.0, 0.8, 0.0], abs=1e-6)
    for row in actual:
        bundle = bundles[str(row["id"])]
        assert row["input_hash"] == bundle["input_hash"]
        assert row["semantic_revision"] == bundle["semantic_revision"]
        assert row["analysis_eligibility_generation"] == bundle["analysis_eligibility_generation"]


def test_identity_sql_and_batch_use_current_facets_without_dense_activation(db, promoted_recipe):
    topic = sorted(TOPIC_IDS)[0]
    central = article(db, 1, title="Publisher reporting on the subject")
    mentioned = article(db, 2, title="Incidental reference in other coverage")
    revoked = article(db, 3, title="Revoked reporting")
    corrected = article(db, 4, title="Original reporting")
    for identifier in (central, revoked, corrected):
        understanding_result(db, identifier, promoted_recipe, topic=topic)
    understanding_result(db, mentioned, promoted_recipe, topic=topic, role="mentioned")
    understanding.revoke(db, revoked)
    db.execute("UPDATE public.articles SET title='Publisher correction' WHERE id=%s", (corrected,))
    state = {"leg": "identity", "needle": {"topics": [{"topic_id": topic}]}, "cursor": None}
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        rows = retrieval._s6_page(db, state, request=request_for(), recipe=promoted_recipe,
                                  count=20, config=retrieval.retrieval_configuration())
    # SQL can overretrieve mentioned identities; current validated policy
    # projection must reject those before candidate quota allocation.
    assert {str(row["id"]) for row in rows} == {central, mentioned}
    reader = profile("NoLexicalMatchHere")
    reader["profile"]["intents"][0]["resolved_id"] = topic
    batch = build(db, reader)
    assert [item.article_id for item in batch.candidates] == [central]
    assert {match.leg for match in batch.candidates[0].matches} == {"identity"}
    assert batch.candidates[0].policy_evidence["topic_ids"] == [topic]
    assert batch.diagnostics["rejected"]["stale_or_unresolved_evidence"] == 1


def test_ann_sql_refuses_missing_managed_cosine_index(db, promoted_recipe):
    identifier = article(db, 1)
    vector = [1.0, *([0.0] * 1535)]
    understanding_result(db, identifier, promoted_recipe, vector=vector)
    state = {"leg": "dense", "vector": vector, "cursor": None, "depth": 0,
             "row_allowance": 100, "unique_allowance": 100}
    with db.transaction():
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        with pytest.raises(ValueError, match="valid S6 cosine index"):
            retrieval._s6_page(db, state, request=request_for(), recipe=promoted_recipe,
                count=10, config={**retrieval.retrieval_configuration(), "ann": True})
