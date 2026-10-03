"""The 2026-09-30 quota switch, replayed against real PostgreSQL.

Opt-in locally, required in CI's postgres-contracts job::

    S1_TEST_DATABASE_URL=postgresql:///postgres pytest -q \\
        backend/tests/test_llm_observability_postgres.py

Each scenario creates and drops its own database on that server. The
expectations are the ones pre-registered in
`evals/llm_observability/PREREGISTRATION.md`; the committed results file must
match a fresh replay.
"""
from __future__ import annotations

import json
import os

import pytest

REQUIRED = os.getenv("S1_TEST_DATABASE_REQUIRED") == "1"
if not REQUIRED:
    pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

import tests._app_stubs  # noqa: E402,F401  (installs import-time stubs)

BASE_DATABASE_URL = os.getenv("S1_TEST_DATABASE_URL")
if REQUIRED and not BASE_DATABASE_URL:
    raise RuntimeError("S1_TEST_DATABASE_REQUIRED=1 requires S1_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_DATABASE_URL,
                                reason="set S1_TEST_DATABASE_URL to a disposable PostgreSQL server")


@pytest.fixture(scope="module")
def replay():
    from evals.llm_observability import replay as module
    return module


@pytest.fixture(scope="module")
def result(replay):
    return replay.run_all(BASE_DATABASE_URL)


def test_every_preregistered_expectation_holds(result):
    failed = [name for name, held in result["expectations"].items() if not held]
    assert not failed, f"{failed}\n{json.dumps(result['summaries'], indent=2)}"


def test_the_incident_trips_on_fallback_before_coverage(result):
    incident = result["summaries"]["incident"]
    assert incident["first_503"] < incident["coverage_first_trip"]


def test_control_without_the_tag_only_coverage_catches_it(result):
    """The main assertion (503 at 20:10) fails with the tag removed; the
    failure is caught later, by the signal that reads articles instead of traces."""
    control = result["summaries"]["tagging_removed"]
    assert control["status_20_10"] == 200
    assert control["first_503"] == control["coverage_first_trip"]


def test_every_attempt_is_traced_once_even_when_a_flush_is_retried(result):
    for name, summary in result["summaries"].items():
        assert summary["traced"] == summary["attempted"] > 0, name
        assert summary["traced_after_reflush"] == summary["traced"], name


def test_the_committed_results_match_a_fresh_replay(replay, result):
    committed = json.loads(replay.RESULTS.read_text())["replay"]
    assert committed["summaries"] == result["summaries"]
    assert committed["expectations"] == result["expectations"]
    assert committed["unevaluable"] == result["unevaluable"]
    assert committed["timelines"] == result["timelines"]
