"""Regression tests for world-critical event detection.

The failure this guards against: an active US-Iran war sat in the pool covered
by six outlets across three sections, and not one of three readers received it.
Two causes, both tested here.

  1. Title-token clustering could not group the coverage. "US strikes Iranian
     launchers", "Battle for Hormuz" and "Iran war: Larak Island" share almost
     no tokens, so the biggest story in the pool looked like 17 unrelated
     singletons with breadth 1.
  2. Breadth alone is the wrong signal anyway. A telescope launch covered by six
     tech blogs outscored a war. Breadth shortlists; gravity decides.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from evals.global_events import (
    LOCATION_REGION, SOURCE_REGION, classify_gravity, home_regions,
    detect_events, pick_for_reader, score_breadth, semantic_clusters,
)


def _unit(vec):
    v = np.asarray(vec, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


class TestSemanticClustering(unittest.TestCase):

    def test_groups_differently_worded_coverage(self):
        """The exact case token clustering missed."""
        war = _unit([1.0, 0.05, 0.0])
        emb = np.stack([
            war,                              # "US strikes Iranian launchers"
            _unit([0.97, 0.10, 0.02]),        # "Battle for Hormuz"
            _unit([0.95, 0.14, 0.01]),        # "Iran war: Larak Island"
            _unit([0.0, 0.05, 1.0]),          # unrelated: telescope launch
        ])
        clusters = semantic_clusters(emb, threshold=0.55)
        war_cluster = max(clusters, key=len)
        self.assertEqual(len(war_cluster), 3)
        self.assertNotIn(3, war_cluster)

    def test_unrelated_items_stay_separate(self):
        emb = np.stack([_unit([1, 0, 0]), _unit([0, 1, 0]), _unit([0, 0, 1])])
        self.assertEqual(len(semantic_clusters(emb, threshold=0.55)), 3)

    def test_every_document_lands_in_exactly_one_cluster(self):
        rng = np.random.default_rng(0)
        emb = np.stack([_unit(v) for v in rng.normal(size=(40, 8))])
        clusters = semantic_clusters(emb, threshold=0.6)
        assigned = [i for c in clusters for i in c]
        self.assertEqual(sorted(assigned), list(range(40)))


class TestBreadthScoring(unittest.TestCase):

    def _docs(self, pairs):
        return [{"source": s, "feed_vertical": v} for s, v in pairs]

    def test_cross_vertical_spread_beats_raw_count(self):
        """Six outlets in one section must not outrank four across three."""
        narrow = self._docs([("Space.com", "space"), ("Engadget", "space"),
                             ("Wired", "space"), ("The Verge", "space"),
                             ("DW", "space"), ("BBC", "space")])
        wide = self._docs([("Guardian World", "world"), ("CNBC", "business"),
                           ("Al Jazeera", "world"), ("Straits Times", "singapore")])
        n = score_breadth(narrow, list(range(len(narrow))))
        w = score_breadth(wide, list(range(len(wide))))
        self.assertGreater(n["sources"], w["sources"])       # narrow has more outlets
        self.assertGreater(w["spread"], n["spread"])         # wide still scores higher

    def test_region_counted_from_source_map(self):
        docs = self._docs([("Asia-Plus TJ", "central-asia"), ("BBC", "world")])
        self.assertEqual(score_breadth(docs, [0, 1])["regions"], 2)


class TestGravityClassification(unittest.TestCase):

    def _events(self):
        return [{"id": 0, "title": "war", "spread": 20, "sources": 6,
                 "verticals": 3, "regions": 4, "source_names": ["BBC"]},
                {"id": 1, "title": "telescope", "spread": 18, "sources": 6,
                 "verticals": 1, "regions": 2, "source_names": ["Wired"]}]

    def test_accepts_valid_tiers(self):
        out = classify_gravity(self._events(), lambda s, u: [
            {"id": 0, "tier": "world_critical", "what": "war"},
            {"id": 1, "tier": "major", "what": "launch"}])
        self.assertEqual(out[0]["tier"], "world_critical")
        self.assertEqual(out[1]["tier"], "major")

    def test_rejects_unknown_tier(self):
        out = classify_gravity(self._events(), lambda s, u: [
            {"id": 0, "tier": "APOCALYPTIC", "what": "x"}])
        self.assertNotIn(0, out)

    def test_rejects_hallucinated_ids(self):
        """A verdict for an event we never sent must not be trusted."""
        out = classify_gravity(self._events(), lambda s, u: [
            {"id": 99, "tier": "world_critical", "what": "x"}])
        self.assertEqual(out, {})

    def test_duplicate_ids_make_that_event_unassessed(self):
        out = classify_gravity(self._events(), lambda s, u: [
            {"id": 0, "tier": "world_critical", "what": "first"},
            {"id": 0, "tier": "routine", "what": "second"}])
        self.assertNotIn(0, out)

    def test_rejects_boolean_ids_and_nonstring_explanations(self):
        self.assertEqual(classify_gravity(self._events(), lambda s, u: [
            {"id": True, "tier": "world_critical", "what": "boolean"},
            {"id": 0, "tier": "world_critical", "what": {"injected": True}}]), {})

    def test_rejects_malformed_extra_and_unbounded_response(self):
        for value in (None, {}, [None], [{"id": 0, "tier": "major", "what": "x", "extra": 1}],
                      [{"id": 0, "tier": "major", "what": "x"}] * 1000):
            with self.subTest(value=type(value).__name__):
                self.assertEqual(classify_gravity(self._events(), lambda s, u: value), {})

    def test_absent_gravity_is_unknown_not_routine(self):
        docs = [{"title": "event", "source": "BBC", "feed_vertical": "world", "summary": ""},
                {"title": "event", "source": "DW", "feed_vertical": "world", "summary": ""}]
        events = detect_events(docs, np.array([[1., 0.], [1., 0.]]), None)
        self.assertEqual(events[0]["tier"], "unknown")
        self.assertEqual(events[0]["assessment_status"], "unassessed")

    def test_no_llm_means_nothing_is_critical(self):
        """Failing open would override every reader's preferences."""
        self.assertEqual(classify_gravity(self._events(), None), {})


class TestReaderSourceSelection(unittest.TestCase):
    """Home press is preferred — but never at the cost of the actual story."""

    def setUp(self):
        # 0 = clearest account (UK), 1 = home-press oil angle (US),
        # 2 = home-press direct account (US)
        self.docs = [
            {"source": "Guardian World", "summary": "x" * 300},
            {"source": "CNBC", "summary": "x" * 300},
            {"source": "Fortune", "summary": "x" * 300},
        ]
        self.emb = np.stack([_unit([1.0, 0.0]), _unit([0.80, 0.60]), _unit([0.99, 0.14])])

    def _event(self, tier):
        return {"members": [0, 1, 2], "rep": 0, "tier": tier}

    def test_world_critical_prefers_clarity_over_familiarity(self):
        """A war must be delivered as a war, not as a commodity price move.

        Here the only home-press copy is the off-angle one, so the reader must
        get the foreign masthead that actually states what happened.
        """
        # Three foreign outlets state the event plainly; the only US copy leads
        # on oil prices. A two-member cluster cannot express this — the centroid
        # sits exactly between the pair and both look equally central.
        docs = [{"source": "Guardian World", "summary": "x"},
                {"source": "DW", "summary": "x"},
                {"source": "BBC", "summary": "x"},
                {"source": "CNBC", "summary": "x"}]
        emb = np.stack([_unit([1.0, 0.0]), _unit([0.98, 0.10]),
                        _unit([0.97, 0.12]), _unit([0.80, 0.60])])
        ev = {"members": [0, 1, 2, 3], "rep": 0, "tier": "world_critical"}
        self.assertEqual(pick_for_reader(ev, docs, {"us"}, emb=emb), 0,
                         "off-angle home copy displaced the actual story")

    def test_regional_story_accepts_off_angle_home_press(self):
        """For a regional story local framing is worth the loss of directness."""
        docs = [{"source": "Guardian World", "summary": "x"},
                {"source": "DW", "summary": "x"},
                {"source": "BBC", "summary": "x"},
                {"source": "CNBC", "summary": "x"}]
        emb = np.stack([_unit([1.0, 0.0]), _unit([0.98, 0.10]),
                        _unit([0.97, 0.12]), _unit([0.80, 0.60])])
        ev = {"members": [0, 1, 2, 3], "rep": 0, "tier": "major"}
        self.assertEqual(pick_for_reader(ev, docs, {"us"}, emb=emb), 3)

    def test_direct_home_copy_wins_over_foreign_even_when_critical(self):
        """Fortune states the event as plainly as the Guardian, so it wins."""
        got = pick_for_reader(self._event("world_critical"), self.docs,
                              {"us"}, emb=self.emb)
        self.assertEqual(got, 2)

    def test_home_press_wins_when_equally_direct(self):
        emb = np.stack([_unit([1.0, 0.0]), _unit([0.999, 0.03]), _unit([0.5, 0.9])])
        got = pick_for_reader(self._event("world_critical"), self.docs, {"us"}, emb=emb)
        self.assertEqual(got, 1)

    def test_no_home_press_falls_back_to_representative(self):
        got = pick_for_reader(self._event("world_critical"), self.docs,
                              {"central-asia"}, emb=self.emb)
        self.assertEqual(got, 0)

    def test_no_regions_returns_representative(self):
        self.assertEqual(
            pick_for_reader(self._event("major"), self.docs, set(), emb=self.emb), 0)


class TestHomeRegions(unittest.TestCase):

    def test_local_paper_implies_national_press(self):
        p = {"user_profile_v2": {"locations": ["New Jersey", "Newark"]}}
        self.assertEqual(home_regions(p), {"us-nj", "us"})

    def test_central_asian_locations_map_together(self):
        p = {"user_profile_v2": {"locations": ["Tajikistan", "Kazakhstan", "Russia"]}}
        self.assertEqual(home_regions(p), {"central-asia", "russia"})

    def test_unknown_location_is_dropped_not_guessed(self):
        p = {"user_profile_v2": {"locations": ["Atlantis"]}}
        self.assertEqual(home_regions(p), set())

    def test_every_mapped_region_has_at_least_one_source(self):
        """A location mapping to a region with no outlets silently does nothing."""
        regions_with_sources = set(SOURCE_REGION.values())
        for loc, region in LOCATION_REGION.items():
            self.assertIn(region, regions_with_sources,
                          f"{loc!r} maps to {region!r}, which no source has")


if __name__ == "__main__":
    unittest.main()
