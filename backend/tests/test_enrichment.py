import asyncio
import importlib
import inspect
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock external deps before importing
if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)

# Force-reload to pick up our mocks
sys.modules.pop("app.services.article_enrichment", None)
sys.modules.pop("app.services.image_extraction", None)
sys.modules.pop("app.services.openai_service", None)

article_enrichment = importlib.import_module("app.services.article_enrichment")
openai_service_mod = importlib.import_module("app.services.openai_service")
article_content_mod = importlib.import_module("app.services.article_content")
web_search_service_mod = importlib.import_module("app.services.web_search_service")


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []
        self.executed = []

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeConn:
    def __init__(self, rows=None):
        self._cursor = _FakeCursor(rows)

    def cursor(self):
        return self._cursor


class _FakeOpenAIService:
    async def generate_expanded_summary(self, title, summary, content):
        return "Expanded content from AI."


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class EnrichmentTests(unittest.IsolatedAsyncioTestCase):
    def test_enrichment_scans_all_pending_rows_and_uses_analysis_text(self):
        source = inspect.getsource(article_enrichment.enrich_articles)
        self.assertIn("analysis_text", source)
        self.assertIn("enrichment_completed = false", source)
        self.assertIn("content_quality_content_version", source)
        self.assertNotIn("WHERE content_extracted = true", source)

    def test_illustrative_image_sources_are_default_off(self):
        self.assertFalse(article_enrichment.ENRICH_STOCK_IMAGES)
        self.assertFalse(article_enrichment.ENRICH_GENERATED_IMAGES)

    async def test_enrichment_retries_on_image_failure(self):
        """Article without image, image fetch fails -> attempts incremented, NOT marked completed."""
        row = {
            "id": "article-1",
            "url": "https://example.com/story",
            "title": "Test Article",
            "summary": "A short summary.",
            "content": "Content that is long enough to skip expansion. " * 20,
            "image_url": None,
            "enrichment_attempts": 0,
        }
        conn = _FakeConn(rows=[row])

        with patch.object(
            article_enrichment,
            "fetch_best_source_image",
            new=AsyncMock(return_value=None),
        ), patch.object(
            openai_service_mod,
            "get_openai_service",
            return_value=_FakeOpenAIService(),
        ):
            result = await article_enrichment.enrich_articles(conn)

        # Check the UPDATE SQL was called with attempts=1 and NOT enrichment_completed = true
        update_calls = [
            (q, p)
            for q, p in conn._cursor.executed
            if "UPDATE" in q
        ]
        self.assertTrue(len(update_calls) >= 1, "Expected at least one UPDATE call")
        update_sql, update_params = update_calls[0]
        self.assertIn("enrichment_attempts", update_sql)
        # attempts = 1 (0 + 1), no image, attempts < MAX => NOT completed
        self.assertNotIn("enrichment_completed = true", update_sql)

    async def test_enrichment_stops_after_max_attempts(self):
        """Article with attempts=2, image fetch fails -> attempts=3, marked completed."""
        row = {
            "id": "article-2",
            "url": "https://example.com/story2",
            "title": "Test Article 2",
            "summary": "A short summary.",
            "content": "Content that is long enough to skip expansion. " * 20,
            "image_url": None,
            "enrichment_attempts": 2,
        }
        conn = _FakeConn(rows=[row])

        with patch.object(
            article_enrichment,
            "fetch_best_source_image",
            new=AsyncMock(return_value=None),
        ), patch.object(
            openai_service_mod,
            "get_openai_service",
            return_value=_FakeOpenAIService(),
        ):
            result = await article_enrichment.enrich_articles(conn)

        update_calls = [
            (q, p)
            for q, p in conn._cursor.executed
            if "UPDATE" in q
        ]
        self.assertTrue(len(update_calls) >= 1, "Expected at least one UPDATE call")
        update_sql, update_params = update_calls[0]
        # attempts=3 (2+1) >= MAX_ENRICHMENT_ATTEMPTS(3), so completed=true
        self.assertIn("enrichment_completed = true", update_sql)

    async def test_enrichment_skips_content_expansion_when_content_adequate(self):
        """Article with good content (>200 chars) but no image -> content NOT re-expanded, image attempted."""
        long_content = "A" * 250  # > MIN_CONTENT_LENGTH (200)
        row = {
            "id": "article-3",
            "url": "https://example.com/story3",
            "title": "Test Article 3",
            "summary": "A short summary.",
            "content": long_content,
            "image_url": None,
            "enrichment_attempts": 0,
        }
        conn = _FakeConn(rows=[row])

        expand_mock = AsyncMock(return_value="Should not be called.")
        fake_openai = _FakeOpenAIService()
        fake_openai.generate_expanded_summary = expand_mock

        with patch.object(
            article_enrichment,
            "fetch_best_source_image",
            new=AsyncMock(return_value=None),
        ), patch.object(
            openai_service_mod,
            "get_openai_service",
            return_value=fake_openai,
        ):
            result = await article_enrichment.enrich_articles(conn)

        expand_mock.assert_not_awaited()
        self.assertEqual(result["content_enriched"], 0)

    async def test_enrichment_marks_completed_when_image_found(self):
        """Article without image, fetch succeeds -> marked completed."""
        row = {
            "id": "article-4",
            "url": "https://example.com/story4",
            "title": "Test Article 4",
            "summary": "A short summary.",
            "content": "Content that is long enough to skip expansion. " * 20,
            "image_url": None,
            "enrichment_attempts": 0,
        }
        conn = _FakeConn(rows=[row])

        with patch.object(
            article_enrichment,
            "fetch_best_source_image",
            new=AsyncMock(return_value="https://cdn.example.com/image.jpg"),
        ), patch.object(
            openai_service_mod,
            "get_openai_service",
            return_value=_FakeOpenAIService(),
        ):
            result = await article_enrichment.enrich_articles(conn)

        update_calls = [
            (q, p)
            for q, p in conn._cursor.executed
            if "UPDATE" in q
        ]
        self.assertTrue(len(update_calls) >= 1, "Expected at least one UPDATE call")
        update_sql, update_params = update_calls[0]
        # Image found -> completed
        self.assertIn("enrichment_completed = true", update_sql)
        self.assertIn("image_url", update_sql)
        self.assertEqual(result["images_found"], 1)

    async def test_stock_search_is_not_called_when_default_disabled(self):
        row = {
            "id": "article-stock-off",
            "url": "https://example.com/story",
            "title": "Publisher story",
            "summary": "A useful summary.",
            "analysis_text": "A" * 300,
            "image_url": None,
            "enrichment_attempts": 0,
        }
        conn = _FakeConn(rows=[row])
        openai_factory = Mock(return_value=_FakeOpenAIService())

        with patch.object(
            article_enrichment,
            "fetch_best_source_image",
            new=AsyncMock(return_value=None),
        ), patch.object(
            openai_service_mod,
            "get_openai_service",
            new=openai_factory,
        ), patch.object(article_enrichment, "ENRICH_STOCK_IMAGES", False):
            await article_enrichment.enrich_articles(conn)

        openai_factory.assert_not_called()

    async def test_tavily_cross_source_text_reaches_analysis_context_never_content(self):
        """S2 P0 guarantee, behaviorally: Tavily cross-source text can never
        become a publisher's own reporting.

        Previously the only coverage of this was a source-string tripwire
        (``test_enrichment_scans_all_pending_rows_and_uses_analysis_text``,
        which just greps the function source for the word "analysis_text").
        This exercises the real path: a short-content article, Tavily
        enabled and returning a match, and asserts the Tavily text (a) is
        the exact payload handed to ``record_analysis_context`` (the
        non-display, provenance-tagged artifact store) and (b) never
        appears anywhere in the dict of column updates that get written to
        the article's own ``content``/displayable columns.
        """
        tavily_text = "Cross-source coverage of the same event, found via Tavily. " * 5
        self.assertGreaterEqual(len(tavily_text), article_enrichment.MIN_CONTENT_LENGTH)
        row = {
            "id": "article-tavily",
            "url": "https://example.com/story",
            "title": "Publisher story with thin native content",
            "summary": "A short summary.",
            "content": "Too short.",  # below MIN_CONTENT_LENGTH -> triggers search
            "analysis_text": None,
            "image_url": "https://cdn.example.com/existing.jpg",
            "image_origin": "publisher_feed",
            "enrichment_attempts": 0,
        }
        conn = _FakeConn(rows=[row])

        fake_search_service = AsyncMock()
        fake_search_service.available = True
        fake_search_service.search_article_content = AsyncMock(
            return_value={
                "content": tavily_text,
                "source_url": "https://other-outlet.example.com/same-story",
                "source_name": "Other Outlet",
            }
        )
        record_analysis_context_mock = Mock(return_value=1)

        with patch.object(
            article_enrichment, "ENRICH_CROSS_SOURCE_ANALYSIS", True
        ), patch.object(
            web_search_service_mod, "get_web_search_service", return_value=fake_search_service
        ), patch.object(
            article_content_mod, "record_analysis_context", new=record_analysis_context_mock
        ), patch.object(
            article_enrichment, "fetch_best_source_image", new=AsyncMock(return_value=None)
        ):
            result = await article_enrichment.enrich_articles(conn)

        # (a) The Tavily text reached the non-display artifact store, tagged
        # with its real source -- not silently dropped, not laundered.
        record_analysis_context_mock.assert_called_once()
        _, call_kwargs = record_analysis_context_mock.call_args
        self.assertEqual(call_kwargs["text"], tavily_text)
        self.assertEqual(call_kwargs["source_url"], "https://other-outlet.example.com/same-story")
        self.assertEqual(result["content_enriched"], 1)

        # (b) The same text never appears in any UPDATE issued against the
        # article's own row -- specifically, no SQL clause sets a `content`
        # column, under any name, from this enrichment pass.
        update_calls = [(q, p) for q, p in conn._cursor.executed if "UPDATE" in q]
        self.assertTrue(update_calls, "expected the enrichment pass to update the article row")
        for sql, params in update_calls:
            self.assertNotRegex(
                sql, r"\bcontent\s*=",
                "Tavily cross-source text must never be written to a displayable content column",
            )
            self.assertNotIn(tavily_text, params or [])


if __name__ == "__main__":
    unittest.main()
