"""End-to-end proof that S4's "seen development" suppression can actually fire.

Opt-in, like every other `*_postgres.py` suite::

    S4_TEST_DATABASE_URL=postgresql:///postgres pytest -q \
        backend/tests/test_event_suppression_loop_postgres.py

Why this file exists rather than another case in `test_event_postgres.py`:
every existing S4 suppression test manufactures the `reading_events` row by
hand, with the right `feed_request_id` already in it, and the unit tests hand
the recursive-CTE result straight back from a fake cursor
(`test_event_integration.Connection.seen`). Both start *after* the step that
was broken. The actual defect was upstream of all of them -- the delivered
card never carried `delivery_position`, so the iOS client's
`NewsArticle.deliveryReceipt` (which requires feed_request_id +
delivery_position + reader_generation + reader_revision, all four) stayed nil,
so every event it sent carried `feed_request_id: null`, so the join
`ON r.feed_request_id = d.feed_request_id` compared NULL to a real uuid and
matched nothing, forever.

So this suite walks the whole loop against a real server, using the real
production functions at every hop: publish with `finalize_feed`, rebuild the
client's receipt from the served JSON exactly as `NewsArticle+Reader.swift`
does, ingest through `reader_feedback.ingest_events` (the `/reading-events`
body), then run the verbatim suppression SQL from `event_integration`. And
`test_the_pre_fix_shape_cannot_suppress` reproduces the old bare-card shape to
prove the test would have failed before the fix, rather than passing for free.
"""
from __future__ import annotations

import json
import os
import secrets
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

import tests._app_stubs  # noqa: F401
from app import main as app_main
from app.services import event_integration, reader_feedback, reader_integration

BASE_URL = os.getenv("S4_TEST_DATABASE_URL")
if REQUIRED and not BASE_URL:
    raise RuntimeError("S4_TEST_DATABASE_REQUIRED=1 requires S4_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_URL, reason="set S4_TEST_DATABASE_URL to a disposable PostgreSQL server"
)

# Verbatim from event_integration.compose_feed. Copied rather than imported
# because it is an inline string there; `test_suppression_sql_matches_production`
# below fails if the two ever drift.
SEEN_SQL = """WITH RECURSIVE seen(development_id,development_version) AS (
              SELECT DISTINCT d.development_id,d.development_version
              FROM public.event_delivery_receipts d JOIN public.reading_events r
                ON r.user_id=d.user_id AND r.feed_request_id=d.feed_request_id AND r.article_id=d.article_id
              WHERE d.user_id=%s AND r.event_type IN ('tap','read','already_knew')
              UNION
              SELECT a.target_id,a.target_version FROM seen s JOIN public.event_development_aliases a
                ON a.development_id=s.development_id AND a.version=s.development_version
            ) SELECT development_id,development_version FROM seen"""


@pytest.fixture(scope="module")
def database_url():
    name = f"daily_s4_loop_{os.getpid()}_{secrets.token_hex(4)}"
    admin = psycopg.connect(BASE_URL, autocommit=True, row_factory=dict_row)
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    except Exception as exc:
        admin.close()
        if REQUIRED:
            pytest.fail(f"Required S4 suppression-loop setup failed: {exc}")
        pytest.skip(f"S4 suppression-loop tests require CREATEDB rights: {exc}")

    parameters = conninfo_to_dict(BASE_URL)
    parameters["dbname"] = name
    url = make_conninfo(**parameters)
    try:
        with psycopg.connect(url, autocommit=True, row_factory=dict_row) as conn:
            # The real boot schema, not a synthetic stand-in: the whole point is
            # that the production reading_events/receipt shapes line up.
            app_main._ensure_tables(conn, force=True)
            from app.services.article_content import ensure_article_content_schema
            from app.services.event_repository import ensure_schema as install_events
            from app.services.reader_feedback import install_schema as install_feedback
            from app.services.reader_repository import install_schema as install_reader
            from app.services.understanding_repository import ensure_schema as install_s3

            install_reader(conn)
            install_feedback(conn)
            # S4's schema installer asserts S3's is present first, and S3's
            # depends on the S2 content tables.
            ensure_article_content_schema(conn)
            install_s3(conn)
            install_events(conn)
        yield url
    finally:
        try:
            with admin.cursor() as cur:
                cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        finally:
            admin.close()


@pytest.fixture()
def conn(database_url):
    with psycopg.connect(database_url, autocommit=True, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture()
def reader(conn):
    """An account with an S5 reader profile and one article, ready to publish."""
    user_id = str(uuid.uuid4())
    article_id = str(uuid.uuid4())
    profile = {"schema_version": 3, "intents": [], "policies": [], "languages": ["en"]}
    with conn.cursor() as cur:
        cur.execute("INSERT INTO public.users (id, email, last_login) VALUES (%s, %s, now())",
                    (user_id, f"{user_id}@example.com"))
        cur.execute(
            "INSERT INTO public.articles (id, title, url, source_name, summary) VALUES (%s,%s,%s,%s,%s)",
            (article_id, "A critical development", f"https://example.com/{secrets.token_hex(6)}",
             "example.com", "Something material happened and it affects you."),
        )
        cur.execute(
            """INSERT INTO public.reader_profiles (user_id, profile, projections, migration_status)
               VALUES (%s, %s::jsonb, '{}'::jsonb, 'ready')""",
            (user_id, json.dumps(profile)),
        )
    return {"user_id": user_id, "article_id": article_id}


def _write_event_receipt(conn, reader, request_id):
    """What `compose_feed` writes for each priority article it delivers."""
    development_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO public.event_delivery_receipts
             (user_id,feed_request_id,article_id,event_id,development_id,development_version,
              assessment_id,valid_until)
           VALUES (%s,%s,%s,%s,%s,%s,%s, now() + interval '6 hours')""",
        (reader["user_id"], request_id, reader["article_id"], str(uuid.uuid4()),
         development_id, 1, str(uuid.uuid4())),
    )
    return development_id


def _client_receipt(card):
    """Rebuild `NewsArticle.deliveryReceipt` from the served JSON.

    Mirrors Daily/Features/News/Models/NewsArticle+Reader.swift exactly: all
    four fields, a parseable uuid, position >= 0, generation and revision > 0.
    Anything less and the client sends no receipt at all.
    """
    request_id = card.get("feed_request_id")
    position = card.get("delivery_position")
    generation = card.get("reader_generation")
    revision = card.get("reader_revision")
    try:
        uuid.UUID(str(request_id))
    except (TypeError, ValueError):
        return None
    if not isinstance(position, int) or position < 0:
        return None
    if not isinstance(generation, int) or generation <= 0:
        return None
    if not isinstance(revision, int) or revision <= 0:
        return None
    return {"feed_request_id": request_id, "position": position}


def _publish(conn, reader, request_id):
    """Serve one edition through the real S5 publication path."""
    result = {
        "status": "ready",
        # `language` is load-bearing: filter_articles -> policy_allows drops any
        # card whose language isn't in the profile's declared set, silently.
        "articles": [{"id": reader["article_id"], "title": "A critical development",
                      "language": "en"}],
        "article_count": 1,
        "feed_request_id": request_id,
        "reader_generation": 1,
        "reader_revision": 1,
    }
    return reader_integration.finalize_feed(conn, reader["user_id"], result)


def _tap(conn, reader, card, event_type="tap"):
    """Send what ReadingEventTracker would send for this card."""
    receipt = _client_receipt(card)
    event = {"event_id": str(uuid.uuid4()), "article_id": reader["article_id"], "type": event_type}
    if receipt:
        event["feed_request_id"] = receipt["feed_request_id"]
        event["position"] = receipt["position"]
    return reader_feedback.ingest_events(conn, reader["user_id"], {"events": [event]})


def _seen(conn, reader):
    return {(str(row["development_id"]), row["development_version"])
            for row in conn.execute(SEEN_SQL, (uuid.UUID(reader["user_id"]),)).fetchall()}


# ---------------------------------------------------------------------------


def test_a_published_card_carries_everything_the_client_needs(conn, reader, monkeypatch):
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    published = _publish(conn, reader, str(uuid.uuid4()))
    card = published["articles"][0]

    assert _client_receipt(card) is not None, (
        "The served card is missing at least one of feed_request_id / "
        "delivery_position / reader_generation / reader_revision, so the client "
        f"will attribute nothing: {card}"
    )
    assert card["delivery_position"] == 0


def test_delivery_position_matches_the_receipt_it_will_be_validated_against(conn, reader, monkeypatch):
    """A position that disagrees with `final_position` is rejected by
    `ingest_events`, which is the same dead end by a different route."""
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    request_id = str(uuid.uuid4())
    card = _publish(conn, reader, request_id)["articles"][0]

    stored = conn.execute(
        """SELECT final_position FROM public.reader_delivery_receipts
           WHERE user_id=%s AND feed_request_id=%s AND article_id=%s""",
        (reader["user_id"], request_id, reader["article_id"]),
    ).fetchone()

    assert stored["final_position"] == card["delivery_position"]


def test_the_whole_suppression_loop_closes(conn, reader, monkeypatch):
    """Publish -> client receipt -> /reading-events -> the real join matches."""
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    request_id = str(uuid.uuid4())
    development_id = _write_event_receipt(conn, reader, request_id)
    card = _publish(conn, reader, request_id)["articles"][0]

    outcome = _tap(conn, reader, card)

    assert outcome["rejected_indices"] == [], "the client's own receipt was refused by ingest"
    assert outcome["inserted"] == 1
    assert (development_id, 1) in _seen(conn, reader)


@pytest.mark.parametrize("event_type", ["tap", "read"])
def test_every_acknowledging_event_type_suppresses(conn, reader, monkeypatch, event_type):
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    request_id = str(uuid.uuid4())
    development_id = _write_event_receipt(conn, reader, request_id)
    card = _publish(conn, reader, request_id)["articles"][0]

    _tap(conn, reader, card, event_type=event_type)

    assert (development_id, 1) in _seen(conn, reader)


def test_an_impression_alone_never_suppresses(conn, reader, monkeypatch):
    """Seeing a card go by is not "I already knew this"."""
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    request_id = str(uuid.uuid4())
    development_id = _write_event_receipt(conn, reader, request_id)
    card = _publish(conn, reader, request_id)["articles"][0]

    _tap(conn, reader, card, event_type="impression")

    assert (development_id, 1) not in _seen(conn, reader)


def test_another_readers_tap_does_not_suppress_mine(conn, reader, monkeypatch):
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    request_id = str(uuid.uuid4())
    development_id = _write_event_receipt(conn, reader, request_id)
    card = _publish(conn, reader, request_id)["articles"][0]
    _tap(conn, reader, card)

    stranger = {"user_id": str(uuid.uuid4()), "article_id": reader["article_id"]}
    conn.execute("INSERT INTO public.users (id, last_login) VALUES (%s, now())",
                 (stranger["user_id"],))

    assert (development_id, 1) in _seen(conn, reader)
    assert _seen(conn, stranger) == set()


def test_the_pre_fix_shape_cannot_suppress(conn, reader, monkeypatch):
    """Reproduce the bare card the legacy path used to serve.

    This is the control: without it, every assertion above could be passing for
    some unrelated reason. A card missing `delivery_position` yields no client
    receipt, the event goes out with feed_request_id NULL, and NULL never
    equals a uuid -- which is precisely how this shipped unnoticed.
    """
    monkeypatch.setenv("S5_READER_ENABLED", "true")
    request_id = str(uuid.uuid4())
    development_id = _write_event_receipt(conn, reader, request_id)
    card = _publish(conn, reader, request_id)["articles"][0]
    bare = {k: v for k, v in card.items() if k != "delivery_position"}

    assert _client_receipt(bare) is None
    _tap(conn, reader, bare)

    stored = conn.execute(
        "SELECT feed_request_id FROM public.reading_events WHERE user_id=%s",
        (reader["user_id"],),
    ).fetchone()
    assert stored["feed_request_id"] is None
    assert (development_id, 1) not in _seen(conn, reader)


def test_suppression_sql_matches_production(monkeypatch):
    """If `compose_feed`'s query is edited, this file's copy has to follow."""
    import inspect

    source = inspect.getsource(event_integration.compose_feed)
    normalised = " ".join(SEEN_SQL.split())
    assert normalised in " ".join(source.split())


def test_priority_is_withheld_when_nothing_will_receipt_the_edition(conn, reader, monkeypatch):
    """The flag-independent half of the fix: S4 must not promise a suppression
    control on an edition whose cards nothing stamps."""
    monkeypatch.setenv("S4_CONSUMERS_ENABLED", "true")
    monkeypatch.setenv("S5_READER_ENABLED", "false")
    monkeypatch.setenv("S7_SERVING_ENABLED", "false")
    ordinary = {"status": "ready", "articles": [{"id": reader["article_id"]}], "article_count": 1}

    composed = event_integration.compose_feed(conn, reader["user_id"], ordinary, capability="1")

    assert composed is ordinary
    remaining = conn.execute(
        "SELECT count(*) AS n FROM public.event_delivery_receipts WHERE user_id=%s",
        (reader["user_id"],),
    ).fetchone()
    assert remaining["n"] == 0, "an unjoinable receipt was written anyway"
