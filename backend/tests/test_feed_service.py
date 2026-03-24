import os
import sys
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "bs4" not in sys.modules:
    sys.modules["bs4"] = types.SimpleNamespace(BeautifulSoup=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)

from app.services import feed_service


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self.query = query
        self.params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)


class _FakeOpenAIService:
    async def score_articles_batch(self, articles, user_profile, interests=None):
        return [
            {"relevant": False, "score": 0.0, "reason": "scoring error"}
            for _ in articles
        ]


class FeedServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_prefilter_uses_preferences_and_exclusions(self):
        profile = feed_service._build_preference_profile(
            "Show me OpenAI and startup funding. Avoid sports.",
            {
                "topics": ["OpenAI"],
                "industries": ["startups"],
                "excluded_topics": ["sports"],
            },
        )

        candidates = [
            {
                "id": str(uuid.uuid4()),
                "title": "OpenAI raises new giant funding round",
                "summary": "Startup funding and model research dominate the week.",
                "content": "",
                "source": "TechCrunch",
                "category": "business",
                "published_at": "2026-03-23T10:00:00+00:00",
            },
            {
                "id": str(uuid.uuid4()),
                "title": "ESPN previews the NBA playoffs",
                "summary": "Sports coverage from around the league.",
                "content": "",
                "source": "ESPN",
                "category": "sports",
                "published_at": "2026-03-23T09:00:00+00:00",
            },
        ]

        shortlisted = feed_service._prefilter_candidates(candidates, profile)

        self.assertEqual(len(shortlisted), 1)
        self.assertIn("OpenAI", shortlisted[0]["title"])

    def test_prompt_only_profile_still_creates_matches(self):
        profile = feed_service._build_preference_profile(
            "Show me AI chips and semiconductor news, avoid politics.",
            None,
        )

        matched, reason, excluded = feed_service._score_candidate(
            {
                "title": "Nvidia unveils new AI chip roadmap",
                "summary": "Semiconductor competition is accelerating.",
                "content": "",
                "source": "The Verge",
                "category": "technology",
            },
            profile,
        )

        self.assertGreater(matched, feed_service.DETERMINISTIC_MATCH_THRESHOLD)
        self.assertFalse(excluded)
        self.assertIn("Matched", reason)

    def test_strict_video_game_profile_rejects_gaming_adjacent_deals(self):
        profile = feed_service._build_preference_profile(
            "Show me only video game news.",
            {"topics": ["video games"]},
        )

        matched, reason, excluded = feed_service._score_candidate(
            {
                "title": "PDP's wireless guitar controller has returned to its best price to date",
                "summary": "A deal on a gaming accessory for Fortnite Festival and Rock Band players.",
                "content": "",
                "source": "The Verge",
                "category": "technology",
            },
            profile,
        )

        self.assertAlmostEqual(matched, 0.2)
        self.assertFalse(excluded)
        self.assertIn("outside primary topics", reason.lower())

    def test_strict_video_game_profile_keeps_actual_game_news(self):
        profile = feed_service._build_preference_profile(
            "Show me only video game news.",
            {"topics": ["video games"]},
        )

        matched, reason, excluded = feed_service._score_candidate(
            {
                "title": "Nintendo announces a new Zelda release date",
                "summary": "Polygon reports on the game's launch timing and trailer reveal.",
                "content": "",
                "source": "Polygon",
                "category": "gaming",
            },
            profile,
        )

        self.assertGreaterEqual(matched, feed_service.STRICT_MATCH_THRESHOLD)
        self.assertFalse(excluded)
        self.assertIn("gaming", reason.lower())

    async def test_get_personalized_feed_falls_back_to_deterministic_matching(self):
        user_id = str(uuid.uuid4())
        matching_article = {
            "id": str(uuid.uuid4()),
            "title": "OpenAI unveils a new reasoning model",
            "summary": "The AI company announced a major model upgrade today.",
            "content": "",
            "source": "OpenAI Blog",
            "image_url": None,
            "url": "https://example.com/openai",
            "published_at": "2026-03-23T10:00:00+00:00",
            "category": "ai",
        }
        off_topic_article = {
            "id": str(uuid.uuid4()),
            "title": "Travel destinations for spring break",
            "summary": "A roundup of beach towns and flights.",
            "content": "",
            "source": "Travel Weekly",
            "image_url": None,
            "url": "https://example.com/travel",
            "published_at": "2026-03-23T09:00:00+00:00",
            "category": "general",
        }

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=("Show me OpenAI and AI news.", {"topics": ["OpenAI", "AI"]}, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            return_value=None,
        ), patch.object(
            feed_service,
            "_load_candidates_for_profile",
            new=AsyncMock(return_value=[matching_article, off_topic_article]),
        ), patch.object(
            feed_service,
            "_save_feed_cache",
        ), patch.object(
            feed_service,
            "get_openai_service",
            return_value=_FakeOpenAIService(),
        ):
            articles = await feed_service.get_personalized_feed(user_id, conn=None, limit=10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], matching_article["title"])
        self.assertTrue(articles[0]["relevant"])

    def test_cached_feed_is_invalidated_when_preferences_are_newer(self):
        now = datetime.now(timezone.utc)
        cached_rows = [
            {
                "created_at": now - timedelta(minutes=20),
                "id": uuid.uuid4(),
                "url": "https://example.com/1",
                "title": "Cached article",
                "summary": "Summary",
                "content": "",
                "author": None,
                "source_name": "Example",
                "image_url": None,
                "published_at": now - timedelta(hours=1),
                "category": "technology",
                "relevance_score": 0.9,
                "relevant": True,
                "relevance_reason": "Matched: AI",
            }
        ]
        conn = _FakeConn(cached_rows)

        cached = feed_service._load_cached_feed(
            conn,
            uuid.uuid4(),
            preferences_updated_at=now - timedelta(minutes=5),
        )

        self.assertIsNone(cached)

    async def test_get_personalized_feed_uses_individual_ai_matches(self):
        user_id = str(uuid.uuid4())
        matching_article = {
            "id": str(uuid.uuid4()),
            "title": "OpenAI launches enterprise agents",
            "summary": "A major AI product launch aimed at software teams.",
            "content": "",
            "source": "OpenAI",
            "image_url": None,
            "url": "https://example.com/openai-agents",
            "published_at": "2026-03-23T10:00:00+00:00",
            "category": "ai",
        }
        off_topic_article = {
            "id": str(uuid.uuid4()),
            "title": "Spring recipes for home cooks",
            "summary": "A food roundup for the weekend.",
            "content": "",
            "source": "Bon Appetit",
            "image_url": None,
            "url": "https://example.com/food",
            "published_at": "2026-03-23T09:00:00+00:00",
            "category": "general",
        }

        fake_service = AsyncMock()
        fake_service.score_articles_batch.return_value = [
            {"relevant": True, "score": 0.92, "reason": "Strong match for AI and OpenAI interests."},
            {"relevant": False, "score": 0.03, "reason": "Not related to the user's interests."},
        ]

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=("Show me OpenAI and AI product news.", {"topics": ["OpenAI", "AI"]}, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            return_value=None,
        ), patch.object(
            feed_service,
            "_load_candidates_for_profile",
            new=AsyncMock(return_value=[matching_article, off_topic_article]),
        ), patch.object(
            feed_service,
            "_save_feed_cache",
        ), patch.object(
            feed_service,
            "get_openai_service",
            return_value=fake_service,
        ):
            articles = await feed_service.get_personalized_feed(user_id, conn=None, limit=10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], matching_article["title"])
        self.assertEqual(articles[0]["relevance_reason"], "Strong match for AI and OpenAI interests.")

    async def test_load_candidates_for_profile_expands_windows_for_strict_topics(self):
        profile = feed_service._build_preference_profile(
            "Show me only video game news.",
            {"topics": ["video games"]},
        )
        first_window = [
            {
                "id": uuid.uuid4(),
                "url": "https://example.com/politics",
                "title": "Election roundup",
                "summary": "A politics story.",
                "content": "",
                "author": None,
                "source_name": "Example News",
                "image_url": None,
                "published_at": datetime.now(timezone.utc),
                "ingested_at": datetime.now(timezone.utc),
                "category": "politics",
            }
        ]
        second_window = [
            {
                "id": uuid.uuid4(),
                "url": "https://example.com/gaming",
                "title": "Nintendo reveals the next Mario Kart trailer",
                "summary": "A new gameplay trailer and launch window were announced.",
                "content": "",
                "author": None,
                "source_name": "Polygon",
                "image_url": None,
                "published_at": datetime.now(timezone.utc),
                "ingested_at": datetime.now(timezone.utc),
                "category": "gaming",
            }
        ]

        with patch.object(
            feed_service,
            "_query_candidate_rows",
            side_effect=[first_window, second_window, []],
        ) as query_rows:
            candidates = await feed_service._load_candidates_for_profile(conn=None, profile=profile, limit=10)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source"], "Polygon")
        self.assertGreaterEqual(query_rows.call_count, 2)


if __name__ == "__main__":
    unittest.main()
