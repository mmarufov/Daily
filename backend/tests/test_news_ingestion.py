import asyncio
import importlib
import inspect
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external deps before importing the module under test
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "feedparser" not in sys.modules:
    sys.modules["feedparser"] = types.SimpleNamespace(parse=lambda x: None)
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object)

# Force-reload to pick up our mocks
sys.modules.pop("app.services.news_ingestion", None)
sys.modules.pop("app.services.image_extraction", None)

news_ingestion = importlib.import_module("app.services.news_ingestion")


# ---------------------------------------------------------------------------
# Mock helpers for _resolve_redirect_urls
# ---------------------------------------------------------------------------

class _MockResponse:
    def __init__(self, url):
        self.url = url


class _FakePolicy:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


# ---------------------------------------------------------------------------
# Tests: _category_for_topic
# ---------------------------------------------------------------------------

class CategoryForTopicTests(unittest.TestCase):
    def test_category_for_topic_maps_known_categories(self):
        # "artificial-intelligence" matches the pattern in FEED_CATEGORIES["ai"]
        self.assertEqual(news_ingestion._category_for_topic("artificial-intelligence"), "ai")
        # "deepmind" matches the ai patterns
        self.assertEqual(news_ingestion._category_for_topic("deepmind research"), "ai")
        # "gaming" substring matches gaming patterns
        self.assertEqual(news_ingestion._category_for_topic("gaming news"), "gaming")
        # "world" substring matches world patterns
        self.assertEqual(news_ingestion._category_for_topic("world politics"), "world")
        # exact match on category name
        self.assertEqual(news_ingestion._category_for_topic("sports"), "sports")

    def test_category_for_topic_returns_general_for_unknown(self):
        self.assertEqual(news_ingestion._category_for_topic("quantum computing"), "general")
        self.assertEqual(news_ingestion._category_for_topic("cooking"), "general")


# ---------------------------------------------------------------------------
# Tests: _resolve_redirect_urls
# ---------------------------------------------------------------------------

class ResolveRedirectUrlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_redirect_urls_resolves_google_news(self):
        google_url = "https://news.google.com/rss/articles/abc123"
        resolved_url = "https://arstechnica.com/real-article"
        articles = [{"url": google_url}]

        safe_fetch = AsyncMock(return_value=_MockResponse(resolved_url))
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            safe_fetch=safe_fetch,
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}):
            await news_ingestion._resolve_redirect_urls(None, articles)

        self.assertEqual(articles[0]["url"], resolved_url)
        safe_fetch.assert_awaited_once()
        self.assertIsNone(safe_fetch.await_args.kwargs["policy"].kwargs["allowed_content_types"])

    async def test_resolve_redirect_urls_keeps_original_on_timeout(self):
        google_url = "https://news.google.com/rss/articles/abc123"
        articles = [{"url": google_url}]

        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            safe_fetch=AsyncMock(side_effect=Exception("timeout")),
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}):
            await news_ingestion._resolve_redirect_urls(None, articles)

        self.assertEqual(articles[0]["url"], google_url)

    async def test_resolve_redirect_urls_skips_non_google_urls(self):
        normal_url = "https://arstechnica.com/some-article"
        articles = [{"url": normal_url}]

        await news_ingestion._resolve_redirect_urls(None, articles)

        self.assertEqual(articles[0]["url"], normal_url)


# ---------------------------------------------------------------------------
# Tests: provenance-safe image upsert
# ---------------------------------------------------------------------------

class UpsertCoalesceTests(unittest.TestCase):
    """Verify trusted images survive refreshes while unknown legacy images heal."""

    def _get_upsert_sql(self):
        """Extract the SQL string from fetch_rss_feeds source code."""
        source = inspect.getsource(news_ingestion._upsert_ingested_article)
        return source

    def test_upsert_preserves_existing_image(self):
        sql = self._get_upsert_sql()
        self.assertIn("THEN EXCLUDED.image_url ELSE public.articles.image_url END", sql)
        self.assertIn("EXCLUDED.image_url IS NOT NULL", sql)

    def test_upsert_fills_missing_image(self):
        sql = self._get_upsert_sql()
        self.assertIn("public.articles.image_url IS NULL", sql)
        # Also verify summary gets the same treatment
        self.assertIn("COALESCE(public.articles.summary, EXCLUDED.summary)", sql)

    def test_upsert_repairs_only_unknown_provenance(self):
        sql = self._get_upsert_sql()
        self.assertIn("ON CONFLICT (url) DO UPDATE SET", sql)
        self.assertIn("public.articles.image_origin IS NULL", sql)
        self.assertIn("public.articles.image_origin = 'legacy_unknown'", sql)

    def test_raw_feed_content_never_enters_article_display_columns(self):
        sql = self._get_upsert_sql()
        self.assertIn("NULL, false", sql)
        self.assertNotIn('article.get("content")', sql.split("cur.execute", 1)[1].split("stored =", 1)[0])

    def test_image_provenance_is_written_as_one_bundle(self):
        sql = self._get_upsert_sql()
        for column in (
            "image_origin",
            "image_source_url",
            "image_attribution",
            "image_is_illustrative",
        ):
            self.assertIn(column, sql)


if __name__ == "__main__":
    unittest.main()
