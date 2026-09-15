"""Regression tests for the feedback loop.

The bug these lock down: tapping "Not relevant" wrote a row to `reading_events`
that every consumer of that table filtered out (`_recompute_behavior_signals`,
`interest_evolution` and `source_quality` all read only impression/tap/read).
The feed cache was cleared, the feed rebuilt from the identical profile, the
article scored identically, and it came back. The client removed it from the
local array, which hid the failure until the next refresh.
"""
import os
import sys
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "httpx" not in sys.modules:
    sys.modules["httpx"] = types.SimpleNamespace(AsyncClient=object)
if "openai" not in sys.modules:
    sys.modules["openai"] = types.SimpleNamespace(OpenAI=object)
if "dotenv" not in sys.modules:
    sys.modules["dotenv"] = types.SimpleNamespace(load_dotenv=lambda *a, **k: None)

from app.services import feedback_signals as fs


class FakeCursor:
    """Minimal cursor: scripted SELECT results, recorded writes."""

    def __init__(self, store):
        self.store = store

    def execute(self, query, params=None):
        q = " ".join(query.split())
        self.store["executed"].append((q, params))
        self._rows = []
        if "FROM public.articles a" in q:
            self._rows = [self.store["article"]] if self.store["article"] else []
        elif "FROM public.user_feedback_signals" in q and q.startswith("SELECT"):
            self._rows = self.store["signals"]
        elif "FROM public.reading_events" in q:
            self._rows = self.store["suppressed"]

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeConn:
    def __init__(self, article=None, signals=None, suppressed=None):
        self.store = {
            "article": article,
            "signals": signals or [],
            "suppressed": suppressed or [],
            "executed": [],
        }

    def cursor(self):
        return FakeCursor(self.store)

    def writes(self):
        return [(q, p) for q, p in self.store["executed"] if q.startswith("INSERT")]


ARTICLE = {
    "source_name": "Yahoo Sports NHL",
    "category": "sports",
    "matched_profile_signals": ["New York Giants", "NHL"],
}


class TestAttribution(unittest.TestCase):
    """One tap must not mean 'I hate hockey'. It means 'this one was wrong'."""

    def test_spreads_across_reasons_the_article_was_shown(self):
        conn = FakeConn(article=ARTICLE)
        n = fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "not_relevant")
        self.assertEqual(n, 4)                       # source + category + 2 topics
        kinds = {p[1] for _q, p in conn.writes()}
        self.assertEqual(kinds, {"source", "category", "topic"})

    def test_matched_interest_is_penalised_hardest(self):
        """The interest is why we selected it; category is far weaker evidence."""
        conn = FakeConn(article=ARTICLE)
        fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "not_relevant")
        by_kind = {p[1]: p[3] for _q, p in conn.writes()}
        self.assertLess(by_kind["topic"], by_kind["source"])
        self.assertLess(by_kind["source"], by_kind["category"])
        self.assertTrue(all(v < 0 for v in by_kind.values()))

    def test_positive_feedback_moves_the_other_way(self):
        conn = FakeConn(article=ARTICLE)
        fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "more_like_this")
        self.assertTrue(all(p[3] > 0 for _q, p in conn.writes()))

    def test_negative_outweighs_positive(self):
        """Bothering to reject something is a stronger signal than a heart tap."""
        self.assertGreater(abs(fs.FEEDBACK_DELTAS["not_relevant"]),
                           fs.FEEDBACK_DELTAS["more_like_this"])

    def test_decays_stored_weight_before_accumulating(self):
        """S10 A4: the UPSERT must decay the stored weight to now() before adding
        the new delta, in the same statement -- not only at read time. Previously
        a year-old -1.0 never relaxed before a fresh +0.2 landed on top of it, so
        a genuine positive correction could not counteract a faded negative one.
        This asserts the fixed SQL shape and that HALF_LIFE_DAYS is bound as a
        parameter; the arithmetic itself runs in Postgres, not this fake cursor."""
        conn = FakeConn(article=ARTICLE)
        fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "not_relevant")
        insert_queries = [q for q, _p in conn.writes()]
        self.assertTrue(insert_queries, "expected at least one INSERT")
        for query in insert_queries:
            self.assertIn("power(0.5", query)
            self.assertIn("public.user_feedback_signals.updated_at", query)
        for _q, params in conn.writes():
            self.assertEqual(params[-1], fs.HALF_LIFE_DAYS)

    def test_unknown_action_is_a_noop(self):
        conn = FakeConn(article=ARTICLE)
        self.assertEqual(fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "shrug"), 0)
        self.assertEqual(conn.writes(), [])

    def test_malformed_article_id_is_a_noop(self):
        conn = FakeConn(article=ARTICLE)
        self.assertEqual(fs.apply_feedback(conn, "u1", "not-a-uuid", "not_relevant"), 0)

    def test_missing_article_is_a_noop(self):
        conn = FakeConn(article=None)
        self.assertEqual(fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "not_relevant"), 0)

    def test_survives_json_encoded_signals(self):
        """jsonb round-trips as a string through some drivers."""
        conn = FakeConn(article={**ARTICLE, "matched_profile_signals": '["NHL"]'})
        self.assertEqual(fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "not_relevant"), 3)

    def test_article_with_no_recorded_reason_still_learns(self):
        """Served from an old cache: source and category still carry signal."""
        conn = FakeConn(article={"source_name": "NJ.com", "category": None,
                                 "matched_profile_signals": None})
        self.assertEqual(fs.apply_feedback(conn, "u1", str(uuid.uuid4()), "not_relevant"), 1)


class TestDecay(unittest.TestCase):
    """A dislike from a year ago should not still be shaping today's feed."""

    def _load(self, weight, age_days):
        conn = FakeConn(signals=[{
            "kind": "topic", "value": "crypto", "weight": weight,
            "updated_at": datetime.now(timezone.utc) - timedelta(days=age_days),
        }])
        return fs.load_feedback_signals(conn, "u1")["topic"].get("crypto", 0.0)

    def test_fresh_signal_is_intact(self):
        self.assertAlmostEqual(self._load(-0.8, 0), -0.8, places=2)

    def test_half_life_is_thirty_days(self):
        self.assertAlmostEqual(self._load(-0.8, fs.HALF_LIFE_DAYS), -0.4, places=2)

    def test_decayed_noise_is_dropped(self):
        self.assertEqual(self._load(-0.8, 365), 0.0)

    def test_naive_timestamp_does_not_crash(self):
        conn = FakeConn(signals=[{"kind": "topic", "value": "x", "weight": -0.5,
                                  "updated_at": datetime.now()}])
        fs.load_feedback_signals(conn, "u1")   # must not raise

    def test_unknown_kind_ignored(self):
        conn = FakeConn(signals=[{"kind": "wat", "value": "x", "weight": -0.9,
                                  "updated_at": datetime.now(timezone.utc)}])
        out = fs.load_feedback_signals(conn, "u1")
        self.assertEqual(sum(len(v) for v in out.values()), 0)


class TestAdjustment(unittest.TestCase):

    SIGNALS = {"topic": {"nhl": -0.9}, "source": {"nj.com": -0.5},
               "category": {"sports": 0.3}}

    def test_matched_interest_drives_the_penalty(self):
        """A weight below the floor clamps to it; the interest alone is enough."""
        art = {"source": "Other", "category": "general",
               "matched_profile_signals": ["NHL"]}
        self.assertEqual(fs.feedback_adjustment(art, self.SIGNALS), fs.ADJUSTMENT_FLOOR)

    def test_penalty_is_proportional_below_the_clamp(self):
        art = {"source": "Other", "category": "general",
               "matched_profile_signals": ["nhl"]}
        signals = {"topic": {"nhl": -0.2}, "source": {}, "category": {}}
        self.assertAlmostEqual(fs.feedback_adjustment(art, signals), -0.2, places=2)

    def test_signals_combine(self):
        art = {"source": "NJ.com", "category": "sports",
               "matched_profile_signals": ["NHL"]}
        # -0.9 - 0.5 + 0.3 = -1.1, clamped to the floor
        self.assertEqual(fs.feedback_adjustment(art, self.SIGNALS), fs.ADJUSTMENT_FLOOR)

    def test_clamped_asymmetrically(self):
        """Rejection may sink an article; a like may not force junk to the top."""
        self.assertGreater(abs(fs.ADJUSTMENT_FLOOR), fs.ADJUSTMENT_CEILING)
        art = {"source": "x", "category": "y", "matched_profile_signals": ["a", "b", "c"]}
        big = {"topic": {"a": 0.8, "b": 0.8, "c": 0.8}, "source": {}, "category": {}}
        self.assertEqual(fs.feedback_adjustment(art, big), fs.ADJUSTMENT_CEILING)

    def test_no_signals_is_neutral(self):
        self.assertEqual(fs.feedback_adjustment({"source": "x"}, {}), 0.0)

    def test_matching_is_case_insensitive(self):
        art = {"source": "NJ.COM", "category": "", "matched_profile_signals": []}
        self.assertAlmostEqual(fs.feedback_adjustment(art, self.SIGNALS), -0.5, places=2)


class TestSuppression(unittest.TestCase):
    """Weights shift ranking. Rejection is absolute."""

    def test_rejected_articles_are_listed(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        conn = FakeConn(suppressed=[{"article_id": i} for i in ids])
        self.assertEqual(fs.load_suppressed_article_ids(conn, "u1"),
                         {str(i) for i in ids})

    def test_query_covers_every_rejecting_action(self):
        conn = FakeConn()
        fs.load_suppressed_article_ids(conn, "u1")
        q = conn.store["executed"][0][0]
        for action in ("not_relevant", "less_like_this", "already_knew", "hide_source"):
            self.assertIn(action, q)

    def test_scoring_drops_suppressed_articles(self):
        """The end of the loop: a rejected article cannot re-enter the feed."""
        from app.services import feed_service

        art_id = str(uuid.uuid4())
        ctx = feed_service.ScoringContext(suppressed_article_ids={art_id})
        profile = feed_service._build_preference_profile(
            "hockey news", {"topics": ["NHL"]}, user_profile_v2=None)
        candidates = [{
            "id": art_id, "title": "NHL roster news", "summary": "NHL update",
            "content": "", "source": "ESPN", "category": "sports",
            "content_quality": 1.0,
        }]
        feed_service._apply_individual_analysis_results(
            candidates,
            [{"relevant": True, "score": 0.95, "reason": "on topic"}],
            profile, ctx,
        )
        self.assertFalse(candidates[0]["_relevant"])
        self.assertEqual(candidates[0]["_score"], 0.0)

    def test_unsuppressed_article_still_scores(self):
        from app.services import feed_service

        ctx = feed_service.ScoringContext(suppressed_article_ids={str(uuid.uuid4())})
        profile = feed_service._build_preference_profile(
            "hockey news", {"topics": ["NHL"]}, user_profile_v2=None)
        candidates = [{
            "id": str(uuid.uuid4()), "title": "NHL roster news", "summary": "NHL update",
            "content": "", "source": "ESPN", "category": "sports", "content_quality": 1.0,
        }]
        feed_service._apply_individual_analysis_results(
            candidates,
            [{"relevant": True, "score": 0.95, "reason": "on topic"}],
            profile, ctx,
        )
        self.assertTrue(candidates[0]["_relevant"])


class TestScoringUsesFeedback(unittest.TestCase):
    """Negative weight must actually lower the score the feed ranks on."""

    def _score(self, signals):
        from app.services import feed_service

        ctx = feed_service.ScoringContext(feedback_signals=signals)
        profile = feed_service._build_preference_profile(
            "hockey news", {"topics": ["NHL"]}, user_profile_v2=None)
        candidates = [{
            "id": str(uuid.uuid4()), "title": "NHL roster news", "summary": "NHL update",
            "content": "", "source": "ESPN", "category": "sports",
            "content_quality": 1.0, "matched_profile_signals": ["NHL"],
        }]
        feed_service._apply_individual_analysis_results(
            candidates,
            [{"relevant": True, "score": 0.9, "reason": "on topic"}],
            profile, ctx,
        )
        return candidates[0]["_score"]

    def test_negative_feedback_lowers_the_score(self):
        baseline = self._score({})
        after = self._score({"topic": {"nhl": -0.8}, "source": {}, "category": {}})
        self.assertLess(after, baseline)

    def test_positive_feedback_raises_it(self):
        baseline = self._score({})
        after = self._score({"topic": {"nhl": 0.5}, "source": {}, "category": {}})
        self.assertGreaterEqual(after, baseline)

    def test_enough_negative_feedback_drops_below_the_relevance_gate(self):
        """Repeated rejection eventually removes the topic from the feed."""
        self.assertLess(self._score({"topic": {"nhl": -1.0},
                                     "source": {"espn": -1.0},
                                     "category": {"sports": -1.0}}), 0.35)


if __name__ == "__main__":
    unittest.main()
