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

_DISTINCT_TITLES = [
    "Apple launches new MacBook Pro with M5 chip",
    "Senate passes landmark AI regulation bill today",
    "SpaceX successfully lands Starship on fourth attempt",
    "Google DeepMind announces breakthrough in protein folding",
    "Federal Reserve holds interest rates steady for third quarter",
    "Meta releases open source large language model Llama 4",
    "Tesla Cybertruck recall affects fifty thousand vehicles",
    "Microsoft acquires gaming studio for two billion dollars",
    "Amazon Web Services launches new AI training platform",
    "Nvidia stock surges after record quarterly earnings report",
    "Anthropic raises four billion in new funding round",
    "Samsung unveils foldable tablet with holographic display",
    "EU Parliament approves comprehensive data privacy reform",
    "OpenAI releases GPT-5 with improved reasoning capabilities",
    "Boeing Starliner finally completes crewed mission successfully",
    "TSMC breaks ground on Arizona chip fabrication plant",
    "Spotify introduces lossless audio tier for premium users",
    "China lands rover on far side of Mars surface",
    "Uber launches autonomous ride-hailing in San Francisco",
    "Reddit IPO stock price doubles on first trading day",
    "Intel announces next generation Lunar Lake mobile processors",
    "Waymo expands driverless taxi service to Miami metro",
    "Netflix cracks down on password sharing globally now",
    "Sony PlayStation 6 reveal event set for June date",
    "Cloudflare mitigates record breaking DDoS attack last week",
    "Docker announces major container runtime security overhaul",
    "Stripe launches crypto payment integration for merchants",
    "Figma releases AI design assistant for professional users",
    "Rivian electric truck beats range expectations in testing",
    "GitHub Copilot gets multimodal code generation features today",
    "Oracle cloud infrastructure surpasses Azure in benchmarks",
    "Zoom acquires enterprise collaboration startup for expansion",
    "Palantir wins major defense contract worth billions",
    "TikTok divests US operations to comply with ban",
    "Unity game engine introduces real-time ray tracing update",
    "Block formerly Square launches banking services nationwide",
    "Databricks reaches fifty billion dollar private valuation",
    "Shopify introduces AI-powered store builder for merchants",
    "Qualcomm Snapdragon X Elite beats Apple M4 in tests",
    "Mozilla Firefox introduces built-in VPN for all users",
]


def _make_distinct_candidates(count: int) -> list:
    candidates = []
    for i in range(min(count, len(_DISTINCT_TITLES))):
        candidates.append({
            "id": str(uuid.uuid4()),
            "title": _DISTINCT_TITLES[i],
            "summary": f"Detailed coverage of {_DISTINCT_TITLES[i].lower()}",
            "content": "",
            "source": f"Source-{i}",
            "image_url": None,
            "url": f"https://example-{i}.com/{uuid.uuid4().hex[:8]}",
            "published_at": f"2026-03-23T{i % 24:02d}:{i % 60:02d}:00+00:00",
            "category": "general",
        })
    return candidates


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
    async def curate_feed_editorial(self, ai_profile, interests=None, user_profile_v2=None, candidates=None):
        if not candidates:
            return []
        picks = []
        for i, c in enumerate(candidates[:15]):
            picks.append({
                "article_id": c["id"],
                "rank": i + 1,
                "why_for_you": f"Relevant to your interests",
                "category_tag": "core_topic",
            })
        return picks


class FeedServiceTests(unittest.IsolatedAsyncioTestCase):

    # --- Deduplication tests (unchanged, functions still exist) ---

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

    # --- Cache tests ---

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

    # --- Editorial flow tests (new) ---

    async def test_editorial_flow_returns_curated_articles(self):
        """LLM editorial call curates the feed and returns articles with why_for_you."""
        user_id = str(uuid.uuid4())
        article_1 = {
            "id": str(uuid.uuid4()),
            "title": "Claude AI gets major update",
            "summary": "Anthropic releases Claude 4.",
            "content": "",
            "source": "TechCrunch",
            "image_url": None,
            "url": "https://example.com/claude",
            "published_at": "2026-03-23T10:00:00+00:00",
            "category": "ai",
        }
        article_2 = {
            "id": str(uuid.uuid4()),
            "title": "Spring gardening tips",
            "summary": "Best flowers for the season.",
            "content": "",
            "source": "Garden Weekly",
            "image_url": None,
            "url": "https://example.com/garden",
            "published_at": "2026-03-23T09:00:00+00:00",
            "category": "lifestyle",
        }
        # Generate enough candidates to pass MIN_EDITORIAL_CANDIDATES threshold
        filler = _make_distinct_candidates(30)
        candidates = [article_1, article_2] + filler

        fake_service = AsyncMock()
        fake_service.curate_feed_editorial.return_value = [
            {
                "article_id": article_1["id"],
                "rank": 1,
                "why_for_you": "Directly relevant to your interest in Claude AI",
                "category_tag": "core_topic",
            },
        ]

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=("Show me Claude AI news.", {"topics": ["Claude AI"]}, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            return_value=None,
        ), patch.object(
            feed_service,
            "_load_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            feed_service,
            "_save_feed_cache",
        ), patch.object(
            feed_service,
            "_hydrate_missing_feed_images",
            new=AsyncMock(),
        ), patch.object(
            feed_service,
            "get_openai_service",
            return_value=fake_service,
        ):
            articles = await feed_service.get_personalized_feed(user_id, conn=None, limit=10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Claude AI gets major update")
        self.assertEqual(articles[0]["relevance_reason"], "Directly relevant to your interest in Claude AI")
        self.assertTrue(articles[0]["relevant"])

    async def test_editorial_failure_falls_back_to_cache(self):
        """When LLM editorial returns empty, serve the last cached feed."""
        user_id = str(uuid.uuid4())
        cached_article = {
            "id": str(uuid.uuid4()),
            "title": "Previously cached article",
            "summary": "From earlier.",
            "content": "",
            "source": "Cache Source",
            "image_url": None,
            "url": "https://example.com/cached",
            "published_at": "2026-03-22T10:00:00+00:00",
            "category": "ai",
            "relevance_score": 0.8,
            "relevant": True,
            "relevance_reason": "Previously curated",
        }
        candidates = _make_distinct_candidates(35)

        fake_service = AsyncMock()
        fake_service.curate_feed_editorial.return_value = []  # LLM failure

        # _load_cached_feed is called twice: once for the initial cache check (returns None),
        # and once for the fallback after editorial failure (returns cached article).
        cache_calls = [None, [cached_article]]

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=("AI news", {"topics": ["AI"]}, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            side_effect=cache_calls,
        ), patch.object(
            feed_service,
            "_load_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            feed_service,
            "_save_feed_cache",
        ), patch.object(
            feed_service,
            "_hydrate_missing_feed_images",
            new=AsyncMock(),
        ), patch.object(
            feed_service,
            "get_openai_service",
            return_value=fake_service,
        ):
            articles = await feed_service.get_personalized_feed(user_id, conn=None, limit=10)

        self.assertEqual(len(articles), 1)
        self.assertEqual(articles[0]["title"], "Previously cached article")

    async def test_small_candidate_pool_serves_by_recency(self):
        """When fewer than MIN_EDITORIAL_CANDIDATES, skip LLM and serve by recency."""
        user_id = str(uuid.uuid4())
        distinct_titles = [
            "Apple launches new MacBook Pro with M5 chip",
            "Senate passes landmark AI regulation bill today",
            "SpaceX successfully lands Starship on fourth attempt",
            "Google DeepMind announces breakthrough in protein folding research",
            "Federal Reserve holds interest rates steady for third quarter",
            "Meta releases open source large language model Llama 4",
            "Tesla Cybertruck recall affects fifty thousand vehicles nationwide",
            "Microsoft acquires gaming studio for two billion dollars",
            "Amazon Web Services launches new AI training platform today",
            "Nvidia stock surges after record quarterly earnings report",
        ]
        candidates = []
        for i in range(10):
            candidates.append({
                "id": str(uuid.uuid4()),
                "title": distinct_titles[i],
                "summary": f"Detailed coverage of this unique story number {i}",
                "content": "",
                "source": f"Source {i}",
                "image_url": None,
                "url": f"https://example.com/story-{uuid.uuid4()}",
                "published_at": f"2026-03-23T{10+i:02d}:00:00+00:00",
                "category": "general",
            })

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=("AI news", {"topics": ["AI"]}, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            return_value=None,
        ), patch.object(
            feed_service,
            "_load_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            feed_service,
            "_save_feed_cache",
        ), patch.object(
            feed_service,
            "_hydrate_missing_feed_images",
            new=AsyncMock(),
        ):
            articles = await feed_service.get_personalized_feed(user_id, conn=None, limit=10)

        self.assertEqual(len(articles), 10)
        # Should be sorted by recency (latest first)
        self.assertEqual(articles[0]["title"], "Nvidia stock surges after record quarterly earnings report")
        self.assertEqual(articles[0]["relevance_reason"], "Served by recency (small candidate pool)")

    async def test_editorial_failure_no_cache_serves_recency(self):
        """When LLM fails AND no cache exists, serve candidates by recency."""
        user_id = str(uuid.uuid4())
        candidates = _make_distinct_candidates(35)

        fake_service = AsyncMock()
        fake_service.curate_feed_editorial.return_value = []

        with patch.object(
            feed_service,
            "_load_user_preferences",
            return_value=("AI news", {"topics": ["AI"]}, None),
        ), patch.object(
            feed_service,
            "_load_cached_feed",
            return_value=None,
        ), patch.object(
            feed_service,
            "_load_candidates",
            new=AsyncMock(return_value=candidates),
        ), patch.object(
            feed_service,
            "_save_feed_cache",
        ), patch.object(
            feed_service,
            "_hydrate_missing_feed_images",
            new=AsyncMock(),
        ), patch.object(
            feed_service,
            "get_openai_service",
            return_value=fake_service,
        ):
            articles = await feed_service.get_personalized_feed(user_id, conn=None, limit=10)

        self.assertEqual(len(articles), 10)
        self.assertEqual(articles[0]["relevance_reason"], "Editorial unavailable; served by recency")

    def test_finalize_curated_articles_maps_internal_keys(self):
        """_finalize_curated_articles maps _score/_relevant/_reason/_feed_role to public names."""
        articles = [{
            "id": "abc",
            "title": "Test",
            "_score": 0.85,
            "_relevant": True,
            "_reason": "Great match for AI",
            "_feed_role": "core_topic",
        }]
        result = feed_service._finalize_curated_articles(articles)
        self.assertEqual(result[0]["relevance_score"], 0.85)
        self.assertTrue(result[0]["relevant"])
        self.assertEqual(result[0]["relevance_reason"], "Great match for AI")
        self.assertEqual(result[0]["feed_role"], "core_topic")
        self.assertIsNone(result[0]["why_this_story"])
        self.assertIsNone(result[0]["why_now"])
        self.assertEqual(result[0]["matched_profile_signals"], [])
        self.assertIsNone(result[0]["cluster_id"])
        self.assertEqual(result[0]["importance_score"], 0.0)


if __name__ == "__main__":
    unittest.main()
