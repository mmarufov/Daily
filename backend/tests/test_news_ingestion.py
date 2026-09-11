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


class _FakeSafeFetchError(Exception):
    def __init__(self, code="http_status", status_code=503, **kw):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class _FakeFetchResult:
    def __init__(self, text, url):
        self.text = text
        self.url = url


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

class FetchSingleFeedSsrfTests(unittest.IsolatedAsyncioTestCase):
    """S1 2.1: the recurring per-feed fetch used by every ingestion path
    (fetch_rss_feeds, topic search, per-user refresh) previously called
    ``client.get()`` on a plain httpx.AsyncClient with no DNS pinning or
    redirect re-validation -- the one outbound fetch in this file that
    wasn't SSRF-safe, unlike ``_resolve_redirect_urls`` right above it.
    """

    class _FakeEntry(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    async def test_fetch_single_feed_never_touches_the_passed_client(self):
        class _ExplodingClient:
            async def get(self, *a, **kw):
                raise AssertionError("must not use the unvalidated client for network I/O")

        entries = [self._FakeEntry(link="https://example.com/a", title="Story")]
        fake_feed = types.SimpleNamespace(entries=entries, feed={"title": "Feed"})
        safe_fetch = AsyncMock(
            return_value=_FakeFetchResult("<rss/>", "https://example.com/feed.xml")
        )
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            SafeFetchError=_FakeSafeFetchError,
            safe_fetch=safe_fetch,
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}), \
                patch.object(news_ingestion.feedparser, "parse", return_value=fake_feed):
            articles = await news_ingestion._fetch_single_feed(
                _ExplodingClient(), "https://example.com/feed.xml"
            )

        safe_fetch.assert_awaited_once()
        self.assertEqual(safe_fetch.await_args.args[0], "https://example.com/feed.xml")
        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["url"], "https://example.com/a")
        self.assertEqual(articles[0]["feed_url"], "https://example.com/feed.xml")

    async def test_fetch_single_feed_returns_empty_on_unsafe_fetch(self):
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            SafeFetchError=_FakeSafeFetchError,
            safe_fetch=AsyncMock(side_effect=_FakeSafeFetchError("private_address")),
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}):
            articles = await news_ingestion._fetch_single_feed(None, "http://169.254.169.254/feed")

        self.assertEqual(articles, [])

    async def test_fetch_single_feed_accepts_the_full_2xx_range(self):
        """A prior bare `status_code != 200` check treated e.g. 202 Accepted
        as a failure before even trying to parse the body -- observed live
        in production logs for a real publisher feed. safe_fetch's 2xx-range
        success is a real correctness improvement, not just the SSRF fix."""
        entries = [self._FakeEntry(link="https://example.com/a", title="Story")]
        fake_feed = types.SimpleNamespace(entries=entries, feed={"title": "Feed"})
        safe_fetch = AsyncMock(
            return_value=_FakeFetchResult("<rss/>", "https://example.com/feed.xml")
        )
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            SafeFetchError=_FakeSafeFetchError,
            safe_fetch=safe_fetch,
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}), \
                patch.object(news_ingestion.feedparser, "parse", return_value=fake_feed):
            articles = await news_ingestion._fetch_single_feed(None, "https://example.com/feed.xml")

        self.assertEqual(len(articles), 1)


class ParseDateTests(unittest.TestCase):
    """S1 2.5: feedparser's *_parsed struct_time is already UTC-normalized;
    mktime() instead interprets it as *local* time, so on any host not
    running in UTC the parsed date silently shifted by the host's offset.
    calendar.timegm() is the UTC-correct inverse. Pins the host TZ to a
    non-UTC zone for the duration of the test so this can't pass by
    accident just because the runner happens to be UTC.
    """

    def setUp(self):
        self._original_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"  # UTC-4/-5, unambiguous vs UTC
        import time as _time
        if hasattr(_time, "tzset"):
            _time.tzset()

    def tearDown(self):
        import time as _time
        if self._original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self._original_tz
        if hasattr(_time, "tzset"):
            _time.tzset()

    def test_parse_date_is_correct_regardless_of_host_timezone(self):
        import calendar
        from datetime import datetime, timezone as tz

        expected = datetime(2024, 1, 15, 12, 0, 0, tzinfo=tz.utc)
        struct = expected.timetuple()  # feedparser hands back a UTC struct_time
        self.assertEqual(calendar.timegm(struct), int(expected.timestamp()))

        # feedparser always provides the raw string alongside the parsed
        # struct; _parse_date gates on the string being present first.
        entry = {"published": "Mon, 15 Jan 2024 12:00:00 GMT", "published_parsed": struct}
        result = news_ingestion._parse_date(entry)

        self.assertEqual(result, expected)

    def test_parse_date_prefers_published_then_updated(self):
        from datetime import datetime, timezone as tz

        expected = datetime(2024, 6, 1, 0, 0, 0, tzinfo=tz.utc)
        entry = {"updated": "Sat, 01 Jun 2024 00:00:00 GMT", "updated_parsed": expected.timetuple()}
        self.assertEqual(news_ingestion._parse_date(entry), expected)

    def test_parse_date_returns_none_without_parsed_struct(self):
        self.assertIsNone(news_ingestion._parse_date({}))
        self.assertIsNone(news_ingestion._parse_date({"published": "not parseable"}))


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
