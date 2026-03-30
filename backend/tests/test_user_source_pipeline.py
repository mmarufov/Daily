import os
import sys
import types
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)

from app.services import user_source_pipeline


class UserSourcePipelineTests(unittest.TestCase):
    def test_get_feed_state_needs_discovery_without_sources(self):
        user_id = str(uuid.uuid4())

        with patch.object(
            user_source_pipeline,
            "_load_user_preferences",
            return_value=("Profile", {"topics": ["AI"]}, None),
        ), patch.object(
            user_source_pipeline,
            "_load_active_user_sources",
            return_value=[],
        ):
            state = user_source_pipeline.get_feed_state(conn=object(), user_id=user_id, limit=10)

        self.assertEqual(state["status"], "needs_discovery")
        self.assertEqual(state["articles"], [])

    def test_get_feed_state_needs_build_without_cache(self):
        user_id = str(uuid.uuid4())

        with patch.object(
            user_source_pipeline,
            "_load_user_preferences",
            return_value=("Profile", {"topics": ["AI"]}, None),
        ), patch.object(
            user_source_pipeline,
            "_load_active_user_sources",
            return_value=[{"source_url": "https://openai.com/blog/rss/"}],
        ), patch.object(
            user_source_pipeline,
            "_load_cached_feed",
            return_value=None,
        ):
            state = user_source_pipeline.get_feed_state(conn=object(), user_id=user_id, limit=10)

        self.assertEqual(state["status"], "needs_build")

    def test_get_feed_state_ready_with_cached_articles(self):
        user_id = str(uuid.uuid4())
        cached_articles = [
            {"id": str(uuid.uuid4()), "title": "Claude ships a new API", "relevant": True},
            {"id": str(uuid.uuid4()), "title": "Off topic", "relevant": False},
        ]

        with patch.object(
            user_source_pipeline,
            "_load_user_preferences",
            return_value=("Profile", {"topics": ["Claude"]}, None),
        ), patch.object(
            user_source_pipeline,
            "_load_active_user_sources",
            return_value=[{"source_url": "https://news.google.com/rss/search?q=Claude"}],
        ), patch.object(
            user_source_pipeline,
            "_load_cached_feed",
            return_value=cached_articles,
        ):
            state = user_source_pipeline.get_feed_state(conn=object(), user_id=user_id, limit=10)

        self.assertEqual(state["status"], "ready")
        self.assertEqual(len(state["articles"]), 1)
        self.assertEqual(state["articles"][0]["title"], "Claude ships a new API")


if __name__ == "__main__":
    unittest.main()
