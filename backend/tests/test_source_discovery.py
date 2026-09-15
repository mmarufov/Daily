import os
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "feedparser" not in sys.modules:
    sys.modules["feedparser"] = types.SimpleNamespace(parse=lambda *_args, **_kwargs: types.SimpleNamespace(entries=[]))
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)

from app.services import source_discovery


class _FakeCursor:
    def __init__(self, rows, owner):
        self._rows = rows
        self._owner = owner

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        self._owner.last_query = query
        self._owner.last_params = params

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.last_query = None
        self.last_params = None

    def cursor(self):
        return _FakeCursor(self._rows, self)


class _FakeSafeFetchError(Exception):
    def __init__(self, code="http_status", status_code=503, **kw):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class _FakeFetchResult:
    def __init__(self, text, url="https://example.com/feed.xml"):
        self.text = text
        self.url = url


class _FakePolicy:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class DiscoveryFeedFetchSsrfTests(unittest.IsolatedAsyncioTestCase):
    """S1 2.1: candidate feed URLs reaching _validate_feed/_fetch_feed_sample
    are not limited to a fixed source registry -- _ai_suggest_feeds builds
    them from an LLM response to a prompt containing user-supplied interest
    text. Both previously fetched with a bare httpx client with no
    DNS-pinning or redirect re-validation.
    """

    class _FakeEntry(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    async def test_fetch_feed_sample_never_touches_the_passed_client(self):
        class _ExplodingClient:
            async def get(self, *a, **kw):
                raise AssertionError("must not use the unvalidated client for network I/O")

        entries = [self._FakeEntry(title="Headline one"), self._FakeEntry(title="Headline two")]
        fake_feed = types.SimpleNamespace(entries=entries)
        safe_fetch = AsyncMock(return_value=_FakeFetchResult("<rss/>"))
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            SafeFetchError=_FakeSafeFetchError,
            safe_fetch=safe_fetch,
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}), \
                patch.object(source_discovery.feedparser, "parse", return_value=fake_feed):
            is_valid, titles = await source_discovery._fetch_feed_sample(
                _ExplodingClient(), "https://llm-suggested.example.com/feed.xml"
            )

        safe_fetch.assert_awaited_once()
        self.assertEqual(safe_fetch.await_args.args[0], "https://llm-suggested.example.com/feed.xml")
        self.assertTrue(is_valid)
        self.assertEqual(titles, ["Headline one", "Headline two"])

    async def test_fetch_feed_sample_fails_closed_on_unsafe_url(self):
        """An LLM-suggested URL pointing at cloud metadata or another
        internal address must come back invalid, not raise, not hang."""
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            SafeFetchError=_FakeSafeFetchError,
            safe_fetch=AsyncMock(side_effect=_FakeSafeFetchError("private_address")),
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}):
            is_valid, titles = await source_discovery._fetch_feed_sample(
                None, "http://169.254.169.254/latest/meta-data/"
            )

        self.assertFalse(is_valid)
        self.assertEqual(titles, [])

    async def test_validate_feed_never_touches_the_passed_client(self):
        class _ExplodingClient:
            async def get(self, *a, **kw):
                raise AssertionError("must not use the unvalidated client for network I/O")

        fake_feed = types.SimpleNamespace(entries=[self._FakeEntry(title="x")])
        safe_fetch = AsyncMock(return_value=_FakeFetchResult("<rss/>"))
        safe_http = types.SimpleNamespace(
            SafeFetchPolicy=_FakePolicy,
            SafeFetchError=_FakeSafeFetchError,
            safe_fetch=safe_fetch,
        )
        with patch.dict(sys.modules, {"app.services.safe_http": safe_http}), \
                patch.object(source_discovery.feedparser, "parse", return_value=fake_feed):
            result = await source_discovery._validate_feed(_ExplodingClient(), "https://example.com/feed.xml")

        self.assertTrue(result)
        safe_fetch.assert_awaited_once()


class SourceDiscoveryTests(unittest.TestCase):
    def test_determine_profile_specificity_specific_for_named_entity(self):
        specificity = source_discovery.determine_profile_specificity(
            {"topics": ["Claude AI"], "people": ["Dario Amodei"]},
            "I want Claude model launches and Anthropic deals.",
        )
        self.assertEqual(specificity, "specific")

    def test_determine_profile_specificity_mixed_for_domain_buckets(self):
        specificity = source_discovery.determine_profile_specificity(
            {"topics": ["AI", "tech", "coding"]},
            "I want AI, tech, and coding coverage.",
        )
        self.assertEqual(specificity, "mixed")

    def test_determine_profile_specificity_broad_for_general_headlines(self):
        specificity = source_discovery.determine_profile_specificity(
            {"topics": ["general news"]},
            "Just give me broad daily headlines.",
        )
        self.assertEqual(specificity, "broad")

    def test_match_seed_sources_does_not_force_general_for_mixed_profiles(self):
        conn = _FakeConn(
            [
                {"url": "https://openai.com/blog/rss/", "name": "OpenAI Blog", "category": "ai", "quality_tier": "premium"},
                {"url": "https://dev.to/feed", "name": "DEV Community", "category": "programming", "quality_tier": "standard"},
            ]
        )

        candidates = source_discovery._match_seed_sources(
            conn,
            {"topics": ["AI", "coding"]},
            "mixed",
            ai_profile="I want AI and coding coverage.",
        )

        self.assertEqual([candidate["category"] for candidate in candidates], ["ai", "programming"])
        self.assertNotIn("general", conn.last_params[0])


if __name__ == "__main__":
    unittest.main()
