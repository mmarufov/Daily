"""Real PostgreSQL contracts for crash-report storage, rollup and retention.

Opt-in, like every other `*_postgres.py` suite::

    S1_TEST_DATABASE_URL=postgresql:///postgres pytest -q \
        backend/tests/test_client_diagnostics_postgres.py

What needs a real server rather than a fake cursor: the `ON CONFLICT` that
makes a retried upload idempotent, the `jsonb_array_elements_text` rollup (a
fake cursor would happily accept the SQL and return whatever it was told), the
`ON DELETE CASCADE` that takes a deleted account's crash reports with it, and
the retention sweep.
"""
from __future__ import annotations

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest

REQUIRED = os.getenv("S1_TEST_DATABASE_REQUIRED") == "1"
if REQUIRED:
    import psycopg
else:
    psycopg = pytest.importorskip("psycopg")
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

import tests._app_stubs  # noqa: F401
from app import main as app_main
from app.services import account_lifecycle, client_diagnostics

BASE_DATABASE_URL = os.getenv("S1_TEST_DATABASE_URL")
if REQUIRED and not BASE_DATABASE_URL:
    raise RuntimeError("S1_TEST_DATABASE_REQUIRED=1 requires S1_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not BASE_DATABASE_URL,
    reason="set S1_TEST_DATABASE_URL to a disposable PostgreSQL server",
)


@pytest.fixture(scope="module")
def diagnostics_database_url():
    if not BASE_DATABASE_URL:
        pytest.skip("S1_TEST_DATABASE_URL is not set")

    database_name = f"daily_diag_test_{os.getpid()}_{secrets.token_hex(4)}"
    admin = psycopg.connect(BASE_DATABASE_URL, autocommit=True, row_factory=dict_row)
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except Exception as exc:
        admin.close()
        if REQUIRED:
            pytest.fail(f"Required diagnostics PostgreSQL setup failed: {exc}")
        pytest.skip(f"Diagnostics PostgreSQL tests require CREATEDB rights: {exc}")

    parameters = conninfo_to_dict(BASE_DATABASE_URL)
    parameters["dbname"] = database_name
    try:
        yield make_conninfo(**parameters)
    finally:
        try:
            with admin.cursor() as cur:
                cur.execute(
                    sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
                )
        finally:
            admin.close()


@pytest.fixture(scope="module")
def _schema_ready(diagnostics_database_url):
    with psycopg.connect(diagnostics_database_url, autocommit=True, row_factory=dict_row) as conn:
        app_main._ensure_tables(conn, force=True)


@pytest.fixture()
def conn(diagnostics_database_url, _schema_ready):
    with psycopg.connect(diagnostics_database_url, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("TRUNCATE public.client_diagnostics")
        yield conn


@pytest.fixture()
def user_id(conn):
    account = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO public.users (id, email, last_login) VALUES (%s, %s, now())",
        (account, f"{account}@example.com"),
    )
    yield account
    account_lifecycle.delete_account(conn, account)


def _report(**overrides):
    base = {
        "report_id": str(uuid.uuid4()),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "app_version": "1.0",
        "build_number": "42",
        "os_version": "Version 26.0",
        "kinds": ["crash"],
        "payload": '{"crashDiagnostics":[{"callStackTree":{}}]}',
        "truncated": False,
    }
    base.update(overrides)
    return base


def _count(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM public.client_diagnostics").fetchone()["n"]


def test_a_batch_is_stored_verbatim(conn, user_id):
    report = _report(kinds=["crash", "hang"])

    assert client_diagnostics.ingest(conn, user_id, {"reports": [report]}) == {
        "accepted": 1, "stored": 1
    }

    row = conn.execute("SELECT * FROM public.client_diagnostics").fetchone()
    assert str(row["report_id"]) == report["report_id"]
    assert str(row["user_id"]) == user_id
    assert row["payload"] == report["payload"]
    assert sorted(row["kinds"]) == ["crash", "hang"]
    assert row["truncated"] is False


def test_a_retried_upload_does_not_double_count_a_crash(conn, user_id):
    """The client re-sends a batch whose response it never saw. Counting one
    crash twice would misreport how stable a build is."""
    report = _report()

    first = client_diagnostics.ingest(conn, user_id, {"reports": [report]})
    second = client_diagnostics.ingest(conn, user_id, {"reports": [report]})

    assert (first["stored"], second["stored"]) == (1, 0)
    assert _count(conn) == 1


def test_a_maximum_sized_payload_round_trips(conn, user_id):
    payload = "x" * client_diagnostics.MAX_PAYLOAD_CHARS

    client_diagnostics.ingest(conn, user_id, {"reports": [_report(payload=payload)]})

    stored = conn.execute("SELECT payload FROM public.client_diagnostics").fetchone()
    assert len(stored["payload"]) == client_diagnostics.MAX_PAYLOAD_CHARS


def test_the_summary_rolls_up_by_build_and_kind(conn, user_id):
    for _ in range(3):
        client_diagnostics.ingest(conn, user_id, {"reports": [_report(build_number="42")]})
    client_diagnostics.ingest(conn, user_id, {"reports": [_report(build_number="43", kinds=["hang"])]})

    groups = client_diagnostics.summary(conn)["groups"]

    assert {(g["build_number"], g["kind"], g["reports"]) for g in groups} == {
        ("42", "crash", 3),
        ("43", "hang", 1),
    }
    # Worst first: the point of the view is "what is breaking most".
    assert groups[0]["reports"] == 3
    assert all(group["last_seen"] for group in groups)


def test_one_report_with_two_kinds_counts_once_under_each(conn, user_id):
    client_diagnostics.ingest(conn, user_id, {"reports": [_report(kinds=["crash", "hang"])]})

    groups = client_diagnostics.summary(conn)["groups"]

    assert sorted((g["kind"], g["reports"]) for g in groups) == [("crash", 1), ("hang", 1)]


def test_the_summary_never_returns_payload_bodies(conn, user_id):
    client_diagnostics.ingest(conn, user_id, {"reports": [_report()]})

    groups = client_diagnostics.summary(conn)["groups"]

    assert groups and all("payload" not in group for group in groups)


def test_the_summary_window_is_bounded_by_retention(conn, user_id):
    assert client_diagnostics.summary(conn, days=9999)["window_days"] == client_diagnostics.RETENTION_DAYS
    assert client_diagnostics.summary(conn, days=0)["window_days"] == 1


def test_reports_outside_the_window_are_swept(conn, user_id):
    client_diagnostics.ingest(conn, user_id, {"reports": [_report()]})
    stale = _report()
    client_diagnostics.ingest(conn, user_id, {"reports": [stale]})
    conn.execute(
        "UPDATE public.client_diagnostics SET received_at = now() - make_interval(days => %s) "
        "WHERE report_id = %s",
        (client_diagnostics.RETENTION_DAYS + 1, stale["report_id"]),
    )

    assert client_diagnostics.purge_expired(conn) == 1

    assert _count(conn) == 1


def test_deleting_an_account_takes_its_crash_reports_with_it(conn):
    """Crash payloads are personal data by any reasonable reading -- device,
    OS build, timestamps, and whatever the app was doing. They must not outlive
    the account."""
    account = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO public.users (id, email, last_login) VALUES (%s, %s, now())",
        (account, f"{account}@example.com"),
    )
    client_diagnostics.ingest(conn, account, {"reports": [_report()]})
    assert _count(conn) == 1

    account_lifecycle.delete_account(conn, account)

    assert _count(conn) == 0


def test_client_diagnostics_is_covered_by_the_deletion_audit(conn):
    """Belt-and-braces against the table being added and forgotten: the schema
    introspection has to actually classify it, not just find the cascade above."""
    buckets = account_lifecycle.user_scoped_tables(conn)

    assert "client_diagnostics" in buckets["cascaded"]
    assert buckets["uncovered"] == []


def test_a_clock_skewed_report_is_clamped_rather_than_stored_in_the_future(conn, user_id):
    ahead = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

    client_diagnostics.ingest(conn, user_id, {"reports": [_report(captured_at=ahead)]})

    row = conn.execute("SELECT captured_at FROM public.client_diagnostics").fetchone()
    assert row["captured_at"] <= datetime.now(timezone.utc)
