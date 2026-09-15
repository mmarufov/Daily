"""S7 consumer cutover and DB ownership; offline, no listener or provider."""
import asyncio
from contextlib import contextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import ranking_service as ranking
from app.services import reader_integration, feed_service, user_source_pipeline


class Connection:
    def __init__(self):
        self.statements = []

    @contextmanager
    def transaction(self):
        yield

    @contextmanager
    def cursor(self):
        yield self

    def execute(self, sql):
        self.statements.append(sql)

    def fetchall(self):
        return [{"user_id": "reader"}]


class Pool:
    def __init__(self):
        self.conn = Connection()
        self.borrowed = 0
        self.calls = 0

    @contextmanager
    def connection(self, **kwargs):
        self.calls += 1
        self.borrowed += 1
        try:
            yield self.conn
        finally:
            self.borrowed -= 1


@pytest.fixture
def api(monkeypatch):
    from app import main
    monkeypatch.setenv("S7_SERVING_ENABLED", "true")
    monkeypatch.setenv("S5_READER_ENABLED", "false")
    monkeypatch.setenv("S6_SERVING_ENABLED", "true")
    monkeypatch.delenv("S7_BACKGROUND_ENABLED", raising=False)
    monkeypatch.delenv("S7_SHADOW_ENABLED", raising=False)
    monkeypatch.setattr(main, "pool", Pool())
    monkeypatch.setattr(main, "_require_auth", lambda value: "token")

    def authenticate(conn, token):
        assert main.pool.borrowed == 1
        assert conn is main.pool.conn
        return "reader"

    monkeypatch.setattr(main, "_get_user_id_from_token", authenticate)
    monkeypatch.setattr(main, "_ensure_tables", Mock(side_effect=AssertionError("legacy schema path")))
    monkeypatch.setattr(main, "_observe_s6_retrieval", AsyncMock(side_effect=AssertionError("legacy observation path")))
    monkeypatch.setattr(user_source_pipeline, "build_feed_for_user", AsyncMock(side_effect=AssertionError("legacy build")))
    monkeypatch.setattr(user_source_pipeline, "get_feed_state", Mock(side_effect=AssertionError("legacy cache")))
    return main


def test_s7_dependency_does_not_borrow_connection(api):
    assert list(api.get_feed_db()) == [None]
    assert api.pool.calls == 0


def test_legacy_dependency_retains_original_ownership(api, monkeypatch):
    monkeypatch.setenv("S7_SERVING_ENABLED", "false")
    dependency = api.get_feed_db()
    assert next(dependency) is api.pool.conn
    assert api.pool.borrowed == 1
    dependency.close()
    assert api.pool.borrowed == 0


@pytest.mark.parametrize("route", ["build_feed", "refresh_feed"])
@pytest.mark.parametrize("status", ["ready", "building", "unavailable", "needs_build"])
def test_explicit_build_releases_auth_and_never_falls_back(api, monkeypatch, route, status):
    result = {"status": status, "articles": []}

    async def build(pool, user_id, **kwargs):
        assert pool is api.pool and pool.borrowed == 0
        assert user_id == "reader"
        assert kwargs == {"limit": 12, "capability": "1"}
        await asyncio.sleep(0)
        assert pool.borrowed == 0
        return result

    monkeypatch.setattr(ranking, "build_feed", build)
    actual = asyncio.run(getattr(api, route)(Authorization="Bearer token", conn=None, limit=12,
                                           event_expiry="1", edition_version="1"))
    assert actual is result
    assert api.pool.calls == 1 and api.pool.borrowed == 0
    api._ensure_tables.assert_not_called()


def test_get_is_provider_free_and_preserves_exact_edition(api, monkeypatch):
    result = {"status": "ready", "articles": [{"id": "z"}, {"id": "a"}], "feed_request_id": "fixed"}
    builder = AsyncMock(side_effect=AssertionError("GET must not build"))
    monkeypatch.setattr(ranking, "build_feed", builder)

    def cache(conn, user_id, **kwargs):
        assert api.pool.borrowed == 1 and conn is api.pool.conn
        assert kwargs == {"limit": 10, "capability": "1"}
        return result

    monkeypatch.setattr(ranking, "cached_feed", cache)
    assert asyncio.run(api.get_feed(Authorization="Bearer token", conn=None, limit=10, event_expiry="1")) is result
    assert api.pool.borrowed == 0 and api.pool.calls == 2
    builder.assert_not_awaited()


@pytest.mark.parametrize("limit", [0, 101, True, 1.5])
def test_bad_limit_never_enters_ranker(api, monkeypatch, limit):
    builder = AsyncMock()
    monkeypatch.setattr(ranking, "build_feed", builder)
    with pytest.raises(api.HTTPException) as error:
        asyncio.run(api.build_feed(Authorization="Bearer token", conn=None, limit=limit, event_expiry=None))
    assert error.value.status_code == 422
    builder.assert_not_awaited()


def test_briefing_uses_cached_headlines_even_when_s5_disabled(api, monkeypatch):
    cache = Mock(return_value={"status": "ready", "articles": [{"title": "First"}, {"title": "Second"}],
                               "feed_request_id": "edition", "reader_revision": 4})
    monkeypatch.setattr(ranking, "cached_feed", cache)
    monkeypatch.setattr(reader_integration, "snapshot_for", Mock(side_effect=AssertionError("legacy snapshot")))
    result = asyncio.run(api.get_briefing(Authorization="Bearer token", conn=None))
    assert result == {"content": "First\n\nSecond", "mode": "headlines", "status": "ready",
                      "feed_request_id": "edition", "reader_revision": 4}
    assert api.pool.borrowed == 0


@pytest.mark.parametrize("entry", ["personalized", "reader", "state", "legacy_build"])
@pytest.mark.parametrize("s5", ["true", "false"])
def test_internal_consumers_are_cache_only(monkeypatch, entry, s5):
    monkeypatch.setenv("S7_SERVING_ENABLED", "true")
    monkeypatch.setenv("S5_READER_ENABLED", s5)
    result = {"status": "needs_build", "articles": []}
    cache = Mock(return_value=result)
    monkeypatch.setattr(ranking, "cached_feed", cache)
    conn = object()
    if entry == "personalized":
        assert asyncio.run(feed_service.get_personalized_feed("reader", conn, limit=7, force_refresh=True)) is result["articles"]
    elif entry == "reader":
        assert reader_integration.serve_feed(conn, "reader", limit=7) is result
    elif entry == "state":
        assert user_source_pipeline.get_feed_state(conn, "reader", limit=7) is result
    else:
        assert asyncio.run(user_source_pipeline.build_feed_for_user(conn, "reader", limit=7)) is result
    cache.assert_called_once_with(conn, "reader", limit=7,
                                  **({"ordinary_only": True} if entry in {"personalized", "reader"} else {}))


def test_finalizer_does_not_reattribute_s7_receipts(monkeypatch):
    monkeypatch.setenv("S7_SERVING_ENABLED", "true")
    result = {"status": "ready", "ranking_recipe": "recipe", "articles": [{"id": "a"}]}
    assert reader_integration.finalize_feed(object(), "reader", result) is result
    assert reader_integration.finalize_feed(object(), "reader", {"status": "ready", "articles": [{"id": "bad"}]}) == {
        "status": "needs_build", "articles": [], "article_count": 0}


def test_background_default_off_has_no_db_or_provider_work(api, monkeypatch):
    builder = AsyncMock()
    monkeypatch.setattr(ranking, "build_feed", builder)
    asyncio.run(api._refresh_s7_background())
    assert api.pool.calls == 0
    builder.assert_not_awaited()


def test_opted_in_background_releases_all_connections_before_ranking(api, monkeypatch):
    monkeypatch.setenv("S7_BACKGROUND_ENABLED", "true")

    async def build(pool, user_id, **kwargs):
        assert pool.borrowed == 0
        assert user_id == "reader" and kwargs == {"limit": 50, "background": True}
        return {"status": "ready", "articles": []}

    builder = AsyncMock(side_effect=build)
    monkeypatch.setattr(ranking, "build_feed", builder)
    asyncio.run(api._refresh_s7_background())
    builder.assert_awaited_once()
    assert api.pool.borrowed == 0 and api.pool.calls == 1


@pytest.mark.parametrize('route', ['get_feed', 'build_feed', 'refresh_feed'])
def test_s8_requires_receipt_capable_client_before_any_work(api, monkeypatch, route):
    monkeypatch.setenv('S8_SERVING_ENABLED', 'true')
    ranker = AsyncMock(side_effect=AssertionError('old client must not build'))
    monkeypatch.setattr(api, '_s7_feed', ranker)
    with pytest.raises(api.HTTPException) as error:
        asyncio.run(getattr(api, route)(Authorization='Bearer token', conn=None,
                                        edition_version=None, event_expiry=None))
    assert error.value.status_code == 409
    ranker.assert_not_awaited()


@pytest.mark.parametrize('status', ['building', 'unavailable'])
def test_older_s7_client_gets_http_error_not_unknown_enum_or_empty_success(api, monkeypatch, status):
    monkeypatch.setenv('S8_SERVING_ENABLED', 'false')
    monkeypatch.setattr(api, '_s7_feed', AsyncMock(return_value={'status': status, 'articles': []}))
    with pytest.raises(api.HTTPException) as error:
        asyncio.run(api.get_feed(Authorization='Bearer token', conn=None,
                                edition_version=None, event_expiry=None))
    assert error.value.status_code == 503


def test_s8_client_keeps_typed_status_without_rewriting(api, monkeypatch):
    monkeypatch.setenv('S8_SERVING_ENABLED', 'true')
    result = {'status': 'building', 'articles': []}
    monkeypatch.setattr(api, '_s7_feed', AsyncMock(return_value=result))
    assert asyncio.run(api.get_feed(Authorization='Bearer token', conn=None,
                                   edition_version='1', event_expiry=None)) is result
