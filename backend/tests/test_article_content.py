"""Regression tests for the article-body pipeline.

Covers the four failure modes that left readers looking at a summary instead of
an article:
  1. `content:encoded` shipped by the publisher was thrown away at ingest.
  2. A failed background extraction marked the article done, permanently.
  3. On-demand extraction gated on that flag instead of on the body length.
  4. Model-written prose was stored in `articles.content` and rendered under the
     publisher's byline.
"""
import importlib
import inspect
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda: None)

news_ingestion = importlib.import_module("app.services.news_ingestion")
article_enrichment = importlib.import_module("app.services.article_enrichment")
feed_service = importlib.import_module("app.services.feed_service")
chat_repository = importlib.import_module("app.services.chat_repository")
source_discovery = importlib.import_module("app.services.source_discovery")
user_source_pipeline = importlib.import_module("app.services.user_source_pipeline")

def _real_bs4_available() -> bool:
    """Sibling test modules swap a minimal `bs4` stub into sys.modules at import
    time, so this must be evaluated when the test runs, not when it is collected.
    HTML-stripping assertions only mean anything against the real parser."""
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup("<p>x</p>", "html.parser").get_text(
            separator=" ", strip=True) == "x"
    except Exception:
        return False


class TestFeedSuppliedContent(unittest.TestCase):
    """Feed text is retained with provenance, never trusted as display by default."""

    def test_extracts_content_encoded(self):
        entry = {"content": [{"value": "Real article prose. " * 60}]}
        extracted = news_ingestion._extract_feed_content(entry)
        self.assertIsNotNone(extracted)
        self.assertGreaterEqual(len(extracted), news_ingestion.FEED_CONTENT_MIN_LENGTH)

    def test_strips_markup_from_content_encoded(self):
        if not _real_bs4_available():
            self.skipTest("sibling test stubbed out bs4")
        entry = {"content": [{"value": "<p>" + ("Real article prose. " * 60) + "</p>"}]}
        extracted = news_ingestion._extract_feed_content(entry)
        self.assertNotIn("<p>", extracted)
        self.assertIn("Real article prose.", extracted)

    def test_picks_longest_when_multiple_content_blocks(self):
        entry = {"content": [
            {"value": "short teaser"},
            {"value": "Full body. " * 100},
        ]}
        self.assertGreater(len(news_ingestion._extract_feed_content(entry)), 600)

    def test_ignores_teaser_length_content(self):
        entry = {"content": [{"value": "Just a one-line teaser."}]}
        self.assertIsNone(news_ingestion._extract_feed_content(entry))

    def test_headline_only_entry_returns_none(self):
        self.assertIsNone(news_ingestion._extract_feed_content({}))
        self.assertIsNone(news_ingestion._extract_feed_content({"content": None}))

    def test_ingest_registers_feed_content_without_direct_display_write(self):
        helper_source = inspect.getsource(news_ingestion._upsert_ingested_article)
        self.assertIn("register_ingested_article", helper_source)
        self.assertIn('feed_content=article.get("content")', helper_source)
        self.assertIn("NULL, false", helper_source)

        for fn in (news_ingestion.fetch_rss_feeds, news_ingestion.fetch_topic_feeds):
            src = inspect.getsource(fn)
            self.assertIn("_upsert_ingested_article", src, f"{fn.__name__} bypasses registration")

    def test_every_article_ingestion_path_registers_a_content_job(self):
        user_pipeline_source = inspect.getsource(
            user_source_pipeline._upsert_articles_and_links
        )
        self.assertIn("article_content_transaction", user_pipeline_source)
        self.assertIn("_upsert_ingested_article", user_pipeline_source)

        discovery_source = inspect.getsource(source_discovery.fetch_user_sources)
        self.assertIn("_upsert_ingested_article", discovery_source)

        chat_source = inspect.getsource(chat_repository.upsert_external_articles)
        self.assertIn("article_content_transaction", chat_source)
        self.assertIn("register_ingested_article", chat_source)


class TestOnDemandExtractionGate(unittest.TestCase):
    """Opening an article must retry extraction when there is nothing to read."""

    def _row(self, **kw):
        base = {"url": "https://example.com/a", "content": "",
                "content_extracted": True, "extraction_attempt_count": 0}
        base.update(kw)
        return base

    def test_retries_when_background_extraction_failed(self):
        # The exact bug: flag says extracted, body is empty.
        self.assertTrue(feed_service._needs_on_demand_extraction(self._row()))

    def test_retries_on_thin_body(self):
        self.assertTrue(feed_service._needs_on_demand_extraction(self._row(content="x" * 120)))

    def test_skips_when_body_is_readable(self):
        self.assertFalse(feed_service._needs_on_demand_extraction(self._row(content="x" * 2000)))

    def test_stops_after_attempt_budget(self):
        """A hard paywall must not be refetched on every single open."""
        row = self._row(extraction_attempt_count=feed_service.MAX_ON_DEMAND_EXTRACTION_ATTEMPTS)
        self.assertFalse(feed_service._needs_on_demand_extraction(row))

    def test_skips_without_url(self):
        self.assertFalse(feed_service._needs_on_demand_extraction(self._row(url=None)))

    def test_handles_null_attempt_count(self):
        self.assertTrue(feed_service._needs_on_demand_extraction(
            self._row(extraction_attempt_count=None)))


class TestContentQuality(unittest.TestCase):
    """An article we couldn't extract is still an article worth showing."""

    SUMMARY = "A substantive summary sentence that actually carries the story. " * 3

    def test_unrecoverable_body_with_summary_stays_rankable(self):
        # Must clear the candidate query's `content_quality >= 0.4` filter.
        q = article_enrichment.compute_content_quality("", "http://img", summary=self.SUMMARY)
        self.assertGreaterEqual(q, 0.4)

    def test_no_body_no_summary_scores_zero(self):
        self.assertEqual(article_enrichment.compute_content_quality("", None, summary=""), 0.0)

    def test_full_body_still_scores_top(self):
        q = article_enrichment.compute_content_quality("x" * 900, "http://img", summary=self.SUMMARY)
        self.assertEqual(q, 1.0)

    def test_summary_argument_is_optional(self):
        # Existing callers pass three positional args.
        self.assertEqual(article_enrichment.compute_content_quality("x" * 900, "http://img"), 1.0)


class TestAnalysisPresentationBoundary(unittest.TestCase):
    def test_cross_source_analysis_can_rank_but_never_becomes_publisher_summary(self):
        row = {
            "id": "00000000-0000-0000-0000-000000000001",
            "url": "https://example.com/story",
            "title": "A publisher headline with enough context",
            "summary": None,
            "content": None,
            "analysis_text": "Alternate outlet reporting that is private ranking context. " * 20,
            "source_name": "Example",
            "presentation_mode": "source_web",
            "body_state": "none",
            "content_quality": None,
        }

        candidate = feed_service._rows_to_candidates([row])[0]

        self.assertIsNone(candidate["summary"])
        self.assertIsNone(candidate["description"])
        self.assertIn("Alternate outlet reporting", candidate["_analysis_text"])
        self.assertIn("Alternate outlet reporting", candidate["_analysis_summary"])

        finalized = feed_service._finalize_articles([candidate])[0]
        self.assertNotIn("_analysis_text", finalized)
        self.assertNotIn("_analysis_summary", finalized)

    def test_private_analysis_context_reaches_every_ranking_consumer(self):
        candidate = {
            "id": "00000000-0000-0000-0000-000000000001",
            "title": "A generic headline",
            "summary": None,
            "content": None,
            "_analysis_text": "A policy change affecting Kazakhstan residents.",
            "source": "Example",
            "category": "general",
        }

        life_impact, signals = feed_service._compute_life_impact(
            candidate, {"locations": ["Kazakhstan"]}
        )
        self.assertGreater(life_impact, 0)
        self.assertIn("Kazakhstan", signals)

        feed_service._annotate_candidate_feed_roles(
            [candidate], {"current_interests": ["Kazakhstan"]}
        )
        self.assertIn("Kazakhstan", candidate["_matched_profile_signals"])

    def test_batch_scorer_reads_private_analysis_context_not_public_body(self):
        openai_source = inspect.getsource(
            importlib.import_module("app.services.openai_service")
            .OpenAIService.score_articles_batch
        )
        self.assertIn('article.get("_analysis_text")', openai_source)


class TestNoFabricatedArticleBodies(unittest.TestCase):
    """Model-written prose must never reach `articles.content`.

    It renders under the publisher's name and the author's byline, so a
    synthesized paragraph is fabrication attributed to a named journalist.
    """

    def test_enrichment_does_not_synthesize_bodies(self):
        src = inspect.getsource(article_enrichment.enrich_articles)
        self.assertNotIn("generate_expanded_summary", src)

    def test_expander_is_gone_entirely(self):
        openai_service = importlib.import_module("app.services.openai_service")
        self.assertFalse(
            hasattr(openai_service.OpenAIService, "generate_expanded_summary"),
            "the body-fabrication helper is back; it must not be reintroduced",
        )

    def test_web_search_fallback_is_retained(self):
        """Finding the story on a source that serves full text is legitimate."""
        src = inspect.getsource(article_enrichment.enrich_articles)
        self.assertIn("search_article_content", src)


class TestExtractionRetryPolicy(unittest.TestCase):
    """A single failure must not be terminal."""

    def test_failure_is_not_immediately_terminal(self):
        src = inspect.getsource(feed_service)
        self.assertIn("MAX_ON_DEMAND_EXTRACTION_ATTEMPTS", src)

    def test_null_content_quality_defaults_neutral(self):
        """NULL means 'not enriched yet', not 'bad'."""
        self.assertEqual(feed_service.DEFAULT_CONTENT_QUALITY, 0.5)

    def test_candidate_row_uses_neutral_default(self):
        rows = [{
            "id": "00000000-0000-0000-0000-000000000001",
            "url": "https://example.com/a",
            "title": "A headline long enough to clear the candidate text floor",
            "summary": "A summary long enough to clear the candidate text floor.",
            "content": None, "source_name": "Example", "published_at": None,
            "content_quality": None,
        }]
        candidate = feed_service._rows_to_candidates(rows)[0]
        self.assertEqual(candidate["content_quality"], feed_service.DEFAULT_CONTENT_QUALITY)


if __name__ == "__main__":
    unittest.main()


class TestWordBoundaryMatching(unittest.TestCase):
    """A user typing `AI` must not receive Ukraine, Entertainment and Thailand.

    Raw substring matching (`term in text`) put every string containing the
    letters a-i into an AI feed, and classified "entertainment" as an AI
    interest because `"ai" in "entertainment"` is True.
    """

    def setUp(self):
        self.profile = feed_service._build_preference_profile(
            "I want AI news", {"topics": ["AI"]}, user_profile_v2=None
        )

    def _score(self, title):
        s, _r, _e = feed_service._score_candidate(
            {"title": title, "summary": "", "content": "", "source": "", "category": ""},
            self.profile,
        )
        return s

    def test_short_term_does_not_match_inside_words(self):
        for title in ["Ukraine peace talks", "Entertainment roundup",
                      "Chairman said so", "Maintaining the railway",
                      "Thailand floods", "Repairs to the chair"]:
            self.assertEqual(self._score(title), 0.0, f"{title!r} matched 'AI'")

    def test_short_term_still_matches_as_a_word(self):
        self.assertGreater(self._score("New AI model released"), 0.0)

    def test_category_inference_is_boundary_safe(self):
        for term in ["entertainment", "ukraine", "maintain", "chair", "trainer"]:
            self.assertNotIn(
                "ai", feed_service._categories_for_terms([term]),
                f"{term!r} was inferred as an AI interest",
            )

    def test_category_inference_still_works(self):
        self.assertIn("ai", feed_service._categories_for_terms(["machine learning"]))
        self.assertIn("gaming", feed_service._categories_for_terms(["nintendo"]))

    def test_exclusion_matching_is_boundary_safe(self):
        """Excluding 'AI' must not silently exclude every Ukraine story."""
        profile = feed_service._build_preference_profile(
            "I want tech news but no AI",
            {"topics": ["technology"], "excluded_topics": ["AI"]},
            user_profile_v2=None,
        )
        _s, _r, excluded = feed_service._score_candidate(
            {"title": "Ukraine signs technology pact", "summary": "",
             "content": "", "source": "", "category": "technology"},
            profile,
        )
        self.assertFalse(excluded, "Ukraine story was excluded by the term 'AI'")

    def test_punctuated_terms_still_anchor(self):
        """Boundaries use [a-z0-9] lookarounds, so c++/.net/covid-19 survive."""
        p = feed_service._build_preference_profile(
            "c++ news", {"topics": ["c++"]}, user_profile_v2=None
        )
        s, _r, _e = feed_service._score_candidate(
            {"title": "New c++ standard lands", "summary": "", "content": "",
             "source": "", "category": ""}, p,
        )
        self.assertGreater(s, 0.0)
