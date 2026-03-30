import os
import sys
import types
import unittest

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
