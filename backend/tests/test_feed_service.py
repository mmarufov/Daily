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
    async def score_articles_batch(self, articles, user_profile, interests=None, user_profile_v2=None):
        return [
            {"relevant": False, "score": 0.0, "reason": "scoring error"}
            for _ in articles
        ]


class FeedServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_canonicalize_url_drops_tracking_params(self):
        canonical = feed_service._canonicalize_url(
            "https://Example.com/story?utm_source=rss&gclid=123&keep=1#section"
        )
        self.assertEqual(canonical, "https://example.com/story?keep=1")

    def test_collapse_duplicate_coverage_merges_canonical_url_matches(self):
        articles = [
            {
                "id": str(uuid.uuid4()),
                "title": "OpenAI launches new developer tools",
                "summary": "Short summary.",
                "content": "Tiny content.",
                "image_url": None,
                "url": "https://example.com/story?utm_source=rss",
                "published_at": "2026-03-24T10:00:00+00:00",
                "relevance_score": 0.7,
            },
            {
                "id": str(uuid.uuid4()),
                "title": "OpenAI launches new developer tools",
                "summary": "Longer summary for the same article.",
                "content": "This version has more content and an image.",
                "image_url": "https://images.example.com/story.jpg",
                "url": "https://example.com/story",
                "published_at": "2026-03-24T10:30:00+00:00",
                "relevance_score": 0.8,
            },
        ]

        deduped = feed_service._collapse_duplicate_coverage(articles)

        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["image_url"], "https://images.example.com/story.jpg")

    def test_articles_are_near_duplicates_for_same_event_titles(self):
        article_a = {
            "title": "Judge says government's Anthropic ban looks like punishment - Reuters",
            "url": "https://reuters.com/a",
            "published_at": "2026-03-24T10:00:00+00:00",
        }
        article_b = {
            "title": "Judge says government Anthropic ban looks like punishment | CNN",
            "url": "https://cnn.com/b",
            "published_at": "2026-03-24T14:00:00+00:00",
        }

        self.assertTrue(feed_service._articles_are_near_duplicates(article_a, article_b))

    def test_select_best_duplicate_representative_prefers_image(self):
        cluster = [
            {
                "id": str(uuid.uuid4()),
                "title": "Duplicate A",
                "summary": "Longer summary",
                "content": "Much longer content body",
                "image_url": None,
                "published_at": "2026-03-24T10:00:00+00:00",
                "relevance_score": 0.95,
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Duplicate B",
                "summary": "Short",
                "content": "Short",
                "image_url": "https://images.example.com/a.jpg",
                "published_at": "2026-03-24T09:00:00+00:00",
                "relevance_score": 0.60,
            },
        ]

        selected = feed_service._select_best_duplicate_representative(cluster)

        self.assertEqual(selected["image_url"], "https://images.example.com/a.jpg")

    def test_select_best_duplicate_representative_prefers_richer_content_when_both_have_images(self):
        cluster = [
            {
                "id": str(uuid.uuid4()),
                "title": "Duplicate A",
                "summary": "Short summary",
                "content": "Short content",
                "image_url": "https://images.example.com/a.jpg",
                "published_at": "2026-03-24T10:00:00+00:00",
                "relevance_score": 0.80,
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Duplicate B",
                "summary": "Longer summary than the first candidate",
                "content": "This version has substantially more content than the first candidate.",
                "image_url": "https://images.example.com/b.jpg",
                "published_at": "2026-03-24T09:00:00+00:00",
                "relevance_score": 0.70,
            },
        ]

        selected = feed_service._select_best_duplicate_representative(cluster)

        self.assertEqual(selected["id"], cluster[1]["id"])

    def test_distinct_same_topic_articles_are_not_collapsed(self):
        article_a = {
            "id": str(uuid.uuid4()),
            "title": "Anthropic releases a new coding model for enterprise teams",
            "summary": "Model launch coverage.",
            "content": "",
            "image_url": None,
            "url": "https://example.com/model",
            "published_at": "2026-03-24T10:00:00+00:00",
            "relevance_score": 0.9,
        }
        article_b = {
            "id": str(uuid.uuid4()),
            "title": "Anthropic faces a government lawsuit over procurement rules",
            "summary": "Policy and legal coverage.",
            "content": "",
            "image_url": None,
            "url": "https://example.com/lawsuit",
            "published_at": "2026-03-24T11:00:00+00:00",
            "relevance_score": 0.8,
        }

        deduped = feed_service._collapse_duplicate_coverage([article_a, article_b])

        self.assertEqual(len(deduped), 2)

    def test_strict_mode_not_triggered_by_casual_just(self):
        self.assertFalse(feed_service._is_strict_profile("I just want good tech news"))

    def test_strict_mode_not_triggered_by_casual_only(self):
        self.assertFalse(feed_service._is_strict_profile("I only read the news in the morning"))

    def test_strict_mode_triggered_by_only_topic_news(self):
        self.assertTrue(feed_service._is_strict_profile("Show me only video game news."))

    def test_strict_mode_triggered_by_only_show(self):
        self.assertTrue(feed_service._is_strict_profile("Only show me AI articles"))

    def test_strict_mode_triggered_by_exclusively(self):
        self.assertTrue(feed_service._is_strict_profile("I exclusively want tech news"))

    def test_strict_mode_triggered_by_nothing_but(self):
        self.assertTrue(feed_service._is_strict_profile("Nothing but gaming news"))

    def test_positive_pattern_matches_i_like(self):
        profile = feed_service._build_preference_profile("I like AI and gaming", None)
        self.assertTrue(profile.has_positive_signals)
        keywords_lower = {k.lower() for k in profile.keyword_terms}
        self.assertTrue({"ai", "gaming"} & keywords_lower)

    def test_positive_pattern_matches_i_want(self):
        profile = feed_service._build_preference_profile("I want tech startup news", None)
        self.assertTrue(profile.has_positive_signals)

    def test_prefilter_drops_zero_score_articles(self):
        profile = feed_service._build_preference_profile(
            "Show me AI news.", {"topics": ["AI"]},
        )
        candidates = [
            {"id": str(uuid.uuid4()), "title": "OpenAI launches new model",
             "summary": "AI research update", "content": "", "source": "TechCrunch",
             "category": "ai", "published_at": "2026-03-23T10:00:00+00:00"},
            {"id": str(uuid.uuid4()), "title": "Best pasta recipes for spring",
             "summary": "Cooking tips for the season.", "content": "", "source": "Food Network",
             "category": "food", "published_at": "2026-03-23T09:00:00+00:00"},
        ]
        shortlisted = feed_service._prefilter_candidates(candidates, profile)
        titles = [a["title"] for a in shortlisted]
        self.assertIn("OpenAI launches new model", titles)

    def test_specific_profile_detected_for_narrow_topics(self):
        profile = feed_service._build_preference_profile(
            "Show me Claude AI news", {"topics": ["Claude AI"]},
        )
        self.assertTrue(profile.is_specific)

    def test_specific_profile_detected_for_proper_noun(self):
        profile = feed_service._build_preference_profile(
            "Goldman Sachs news", {"topics": ["Goldman Sachs"], "people": ["Jamie Dimon"]},
        )
        self.assertTrue(profile.is_specific)

    def test_broad_profile_not_specific(self):
        profile = feed_service._build_preference_profile(
            "AI, gaming, tech, and sports news",
            {"topics": ["AI", "gaming", "tech", "sports"]},
        )
        self.assertFalse(profile.is_specific)

    def test_no_interests_not_specific(self):
        profile = feed_service._build_preference_profile("Show me news", None)
        self.assertFalse(profile.is_specific)

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

        self.assertGreaterEqual(len(articles), 1)
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

        self.assertGreaterEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], matching_article["title"])
        self.assertEqual(articles[0]["relevance_reason"], "Strong match for AI and OpenAI interests.")

    async def test_get_personalized_feed_dedupes_cached_results(self):
        user_id = str(uuid.uuid4())
        cached_articles = [
            {
                "id": str(uuid.uuid4()),
                "title": "Judge says government Anthropic ban looks like punishment - Reuters",
                "summary": "Version without image.",
                "content": "Short content.",
                "author": None,
                "source": "Reuters",
                "image_url": None,
                "url": "https://example.com/anthropic?utm_source=rss",
                "published_at": "2026-03-24T10:00:00+00:00",
                "category": "technology",
                "relevance_score": 0.8,
                "relevant": True,
                "relevance_reason": "Matched: Anthropic",
            },
            {
                "id": str(uuid.uuid4()),
                "title": "Judge says government Anthropic ban looks like punishment | CNN",
                "summary": "Version with image.",
                "content": "This version has the richer content body for the same event.",
                "author": None,
                "source": "CNN",
                "image_url": "https://images.example.com/anthropic.jpg",
                "url": "https://example.com/anthropic",
                "published_at": "2026-03-24T11:00:00+00:00",
                "category": "technology",
                "relevance_score": 0.7,
                "relevant": True,
                "relevance_reason": "Matched: Anthropic",
            },
        ]

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=(None, None, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            return_value=cached_articles,
        ), patch.object(
            feed_service,
            "_hydrate_missing_feed_images",
            new=AsyncMock(),
        ) as hydrate_mock:
            articles = await feed_service.get_personalized_feed(user_id, conn=object(), limit=10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["image_url"], "https://images.example.com/anthropic.jpg")
        hydrate_mock.assert_awaited_once()

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


    # --- Score blending tests (S3) ---

    def test_score_blending_lowers_high_model_with_low_deterministic(self):
        """When LLM gives 0.9 but deterministic gives low, blended is pulled down."""
        profile = feed_service._build_preference_profile(
            "I like quantum physics", {"topics": ["Quantum Physics"]}
        )
        candidates = [
            {"title": "City council votes on zoning", "summary": "Local zoning debate",
             "category": "general", "source_name": "Local News",
             "url": "https://localnews.com/zoning", "content": ""},
        ]
        results = [{"relevant": True, "score": 0.9, "reason": "Tangentially related"}]
        feed_service._apply_individual_analysis_results(candidates, results, profile)
        # Blended should be < 0.9 (pulled down by low deterministic)
        self.assertLess(candidates[0]["_score"], 0.9)
        # But still relevant if blend >= 0.35
        self.assertTrue(candidates[0]["_relevant"])

    def test_score_blending_rejects_when_blend_below_threshold(self):
        """When blended score falls below 0.35, article is not relevant."""
        profile = feed_service._build_preference_profile(
            "I like quantum physics", {"topics": ["Quantum Physics"]}
        )
        candidates = [
            {"title": "Celebrity gossip update", "summary": "Stars at party",
             "category": "entertainment", "source_name": "TMZ",
             "url": "https://tmz.com/story", "content": ""},
        ]
        # LLM says barely relevant with low score
        results = [{"relevant": True, "score": 0.3, "reason": "Tangentially related"}]
        feed_service._apply_individual_analysis_results(candidates, results, profile)
        # Blended should be below threshold since deterministic is ~0
        self.assertFalse(candidates[0]["_relevant"])

    def test_generic_backfill_threshold_removed(self):
        """The rebuilt feed should not pad results using generic score thresholds."""
        import inspect
        source = inspect.getsource(feed_service.get_personalized_feed)
        self.assertNotIn("0.50", source)

    def test_recency_fill_removed(self):
        """The rebuilt feed should not recency-pad sparse personalized feeds."""
        import inspect
        source = inspect.getsource(feed_service.get_personalized_feed)
        self.assertNotIn("max_recency", source)
        self.assertNotIn("min(3,", source)

    def test_specific_profile_no_longer_uses_padding_branch(self):
        """Specific profiles no longer need a special-case skip because padding is gone entirely."""
        import inspect
        source = inspect.getsource(feed_service.get_personalized_feed)
        self.assertNotIn("not profile.is_specific", source)

    def test_llm_fallback_uses_deterministic_only(self):
        """When LLM returns fallback reason, deterministic score is used alone."""
        profile = feed_service._build_preference_profile(
            "I like AI and machine learning", {"topics": ["AI", "Machine Learning"]}
        )
        candidates = [
            {"title": "AI breakthrough in healthcare", "summary": "New AI model helps doctors",
             "category": "ai", "source_name": "TechCrunch",
             "url": "https://techcrunch.com/ai", "content": "AI breakthrough details"},
        ]
        results = [{"relevant": False, "score": 0.0, "reason": "scoring unavailable"}]
        feed_service._apply_individual_analysis_results(candidates, results, profile)
        # Should use deterministic score, not the 0.0 from LLM
        self.assertGreater(candidates[0]["_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
