import asyncio
import importlib
import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

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


if __name__ == "__main__":
    unittest.main()
