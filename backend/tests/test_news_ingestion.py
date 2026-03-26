import asyncio
import importlib
import inspect
import os
import sys
import types
import unittest

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


class _MockClient:
    def __init__(self, responses=None, should_fail=False):
        self._responses = responses or {}
        self._should_fail = should_fail

    async def head(self, url, **kwargs):
        if self._should_fail:
            raise Exception("timeout")
        return _MockResponse(self._responses.get(url, url))


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
        client = _MockClient(responses={google_url: resolved_url})
        articles = [{"url": google_url}]

        await news_ingestion._resolve_redirect_urls(client, articles)

        self.assertEqual(articles[0]["url"], resolved_url)

    async def test_resolve_redirect_urls_keeps_original_on_timeout(self):
        google_url = "https://news.google.com/rss/articles/abc123"
        client = _MockClient(should_fail=True)
        articles = [{"url": google_url}]

        await news_ingestion._resolve_redirect_urls(client, articles)

        self.assertEqual(articles[0]["url"], google_url)

    async def test_resolve_redirect_urls_skips_non_google_urls(self):
        normal_url = "https://arstechnica.com/some-article"
        client = _MockClient(responses={normal_url: "https://should-not-change.com"})
        articles = [{"url": normal_url}]

        await news_ingestion._resolve_redirect_urls(client, articles)

        self.assertEqual(articles[0]["url"], normal_url)


# ---------------------------------------------------------------------------
# Tests: upsert SQL COALESCE pattern
# ---------------------------------------------------------------------------

class UpsertCoalesceTests(unittest.TestCase):
    """Verify the ON CONFLICT upsert SQL uses COALESCE(existing, new) so that
    an existing non-NULL image_url is never overwritten by a NULL from a later feed."""

    def _get_upsert_sql(self):
        """Extract the SQL string from fetch_rss_feeds source code."""
        source = inspect.getsource(news_ingestion.fetch_rss_feeds)
        return source

    def test_upsert_preserves_existing_image(self):
        sql = self._get_upsert_sql()
        # The pattern COALESCE(public.articles.image_url, EXCLUDED.image_url) means:
        # keep existing value if non-NULL, else use the new value.
        self.assertIn("COALESCE(public.articles.image_url, EXCLUDED.image_url)", sql)

    def test_upsert_fills_missing_image(self):
        sql = self._get_upsert_sql()
        # When existing is NULL (first arg to COALESCE), EXCLUDED.image_url wins.
        # This is implicit in COALESCE semantics — we just verify the pattern exists.
        self.assertIn("COALESCE(public.articles.image_url, EXCLUDED.image_url)", sql)
        # Also verify summary gets the same treatment
        self.assertIn("COALESCE(public.articles.summary, EXCLUDED.summary)", sql)

    def test_upsert_coalesce_both_null(self):
        sql = self._get_upsert_sql()
        # Verify ON CONFLICT is present (so the COALESCE is within an upsert context)
        self.assertIn("ON CONFLICT (url) DO UPDATE SET", sql)
        # Verify that image_url uses COALESCE (both NULL → NULL is standard SQL behavior)
        self.assertIn("COALESCE(public.articles.image_url, EXCLUDED.image_url)", sql)


if __name__ == "__main__":
    unittest.main()
