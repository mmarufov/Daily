"""Pin the retention decision recorded in `app/services/retention.py`.

`reading_events`' real retention was an emergent side effect -- an
`ON DELETE CASCADE` to `articles` plus a hardcoded `interval '14 days'` in the
ingestion loop, five files apart, neither mentioning the other. Phase 7.5
decided to keep that coupling and say so. These tests exist so "say so" cannot
quietly stop being true: if someone changes the GC window, drops the cascade,
or adds a behaviour consumer that looks further back than the pool keeps data,
one of them fails.
"""
import importlib
import inspect
import sys

import pytest

import tests._app_stubs  # noqa: F401


def _module(name):
    # See tests/test_account_lifecycle.py for why this is resolved lazily.
    return sys.modules.get(name) or importlib.import_module(name)


@pytest.fixture()
def retention():
    return _module("app.services.retention")


@pytest.fixture()
def main():
    return _module("app.main")


def test_the_gc_uses_the_declared_constant_not_a_literal(main, retention):
    source = " ".join(inspect.getsource(main._ingestion_loop).split())
    assert "make_interval(days => %s)" in source
    assert "ARTICLE_RETENTION_DAYS" in source
    assert "interval '14 days'" not in source, (
        "the article GC window drifted back into a SQL literal; it is the "
        "retention policy for every user-signal table and needs one home"
    )


def test_reading_events_still_cascades_from_articles(main):
    """The coupling being *documented* is only worth anything while it's real."""
    source = " ".join(inspect.getsource(main._ensure_tables).split())
    assert "CREATE TABLE IF NOT EXISTS public.reading_events" in source
    table = source.split("public.reading_events")[1]
    assert "article_id UUID NOT NULL REFERENCES public.articles(id) ON DELETE CASCADE" in table


def test_the_reading_events_ddl_points_at_the_decision_record(main):
    source = inspect.getsource(main._ensure_tables)
    assert "retention.py" in source.split("public.reading_events")[0][-1200:], (
        "the DDL lost the note explaining that this table's retention is the "
        "article GC's; that note is the only place a reader would find out"
    )


def test_behaviour_consumers_never_look_further_back_than_the_pool_keeps(retention):
    """A 30-day behaviour query over a 14-day pool silently returns 14 days of
    data and reports it as 30. Keep the windows honest instead."""
    assert retention.BEHAVIOR_SIGNAL_WINDOW_DAYS <= retention.ARTICLE_RETENTION_DAYS


def test_consumer_windows_match_the_declared_behaviour_window(retention):
    interest_evolution = _module("app.services.interest_evolution")
    source = " ".join(inspect.getsource(interest_evolution).split())
    assert f"interval '{retention.BEHAVIOR_SIGNAL_WINDOW_DAYS} days'" in source


def test_the_receipt_window_is_documented_as_truncated(retention):
    """The 30-day receipt window is longer than the pool lives. That is a known,
    written-down inconsistency, not a promise anything can keep."""
    assert retention.RECEIPT_VALIDATION_DAYS > retention.ARTICLE_RETENTION_DAYS
    assert "declared-vs-enforced" in retention.__doc__


def test_the_decision_itself_is_recorded(retention):
    """A constant without the argument behind it is how this got lost the first
    time. If the docstring goes, so does the reason."""
    doc = retention.__doc__ or ""
    assert "The decision: intentional" in doc
    assert "denormalise" in doc, "the upgrade path has to stay written down"
