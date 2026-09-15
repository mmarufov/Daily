"""Metric definitions, checked on hand-built traces."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.metrics import aggregate, score_build
from evals.runners import BuildResult


def _pool(ids):
    return [{"id": i, "title": f"title {i}", "source": f"src{n % 3}"} for n, i in enumerate(ids)]


def _trace(feed, dropped: dict[str, str], stage_for_dropped: dict[str, str] | None = None,
           model: dict[str, bool] | None = None):
    t = {}
    for rank, i in enumerate(feed, 1):
        t[i] = {"stage_reached": "feed", "dropped_at": None, "score": 0.9, "reason": "", "rank": rank}
    for i, at in dropped.items():
        t[i] = {"stage_reached": (stage_for_dropped or {}).get(i, "loaded"), "dropped_at": at,
                "score": 0.1, "reason": f"dropped at {at}", "rank": None}
    for i, rel in (model or {}).items():
        t[i]["model"] = {"relevant": rel, "score": 0.8 if rel else 0.1, "reason": ""}
    return t


class TestScoreBuild(unittest.TestCase):

    def test_recall_caps_at_k_when_more_must_see_than_slots(self):
        feed = [f"m{i}" for i in range(12)]                   # 12 must-see in the top 12
        must = {f"m{i}" for i in range(20)}                   # but 20 exist
        labels = {i: {"label": "must_see", "tags": []} for i in must}
        r = BuildResult(feed=feed, trace=_trace(feed, {f"m{i}": "prefilter:cap" for i in range(12, 20)}))
        m = score_build(r, labels, {"clusters": []}, _pool(list(must)), k=12, kind="prod")
        self.assertEqual(m["recall_at_k"], 1.0)
        self.assertEqual(m["raw_recall_at_k"], 0.6)
        self.assertEqual(m["loss_by_stage"], {"prefilter:cap": 8})
        self.assertEqual(len(m["losses"]), 8)

    def test_never_rate_and_stage_attribution(self):
        feed = ["a", "b", "n1", "c"]
        labels = {"a": {"label": "must_see", "tags": ["need_to_know"]},
                  "b": {"label": "fine", "tags": []},
                  "n1": {"label": "never", "tags": []},
                  "m2": {"label": "must_see", "tags": []},
                  "m3": {"label": "must_see", "tags": ["need_to_know", "followup"]}}
        trace = _trace(feed, {"m2": "blended", "m3": "lookback"}, {"m2": "scored", "m3": "pool"},
                       model={"a": True, "n1": True, "m2": False})
        r = BuildResult(feed=feed, trace=trace)
        m = score_build(r, labels, {"clusters": []}, _pool(["a", "b", "n1", "c", "m2", "m3"]), k=12, kind="prod")
        self.assertEqual(m["never_rate"], 0.25)
        self.assertEqual(m["recall_at_k"], round(1 / 3, 4))
        self.assertEqual(m["recall_at_retrieval"], round(2 / 3, 4))     # a and m2 reached "scored"+
        self.assertEqual(m["need_to_know_recall"], 0.5)
        self.assertEqual(m["followup_recall"], 0.0)
        self.assertEqual(m["loss_by_stage"], {"blended": 1, "lookback": 1})
        self.assertTrue(m["feed_size_flag"])
        # judge: a (must, relevant) TP; n1 (never, relevant) FP; m2 (must, not relevant) FN
        self.assertEqual(m["judge_precision"], 0.5)
        self.assertEqual(m["judge_recall"], 0.5)
        self.assertEqual(m["unlabelled_in_feed"], 1)

    def test_event_delivery_and_needles(self):
        feed = ["x", "n-p1", "ev-a"]
        labels = {"n-p1": {"label": "must_see", "tags": [], "source": "needle"},
                  "n-l1": {"label": "never", "tags": [], "source": "needle"}}
        events = {"clusters": [{"id": "ev-01", "tier": "world_critical", "article_ids": ["ev-a", "ev-b"]},
                               {"id": "ev-02", "tier": "world_critical", "article_ids": ["ev-c"]},
                               {"id": "ev-03", "tier": "major", "article_ids": ["ev-d"]}]}
        r = BuildResult(feed=feed, trace=_trace(feed, {"n-l1": "prefilter:excluded", "ev-c": "rank"}))
        m = score_build(r, labels, events, _pool(["x", "n-p1", "ev-a", "n-l1", "ev-c"]), k=12, kind="prod")
        self.assertEqual(m["event_delivery"], 0.5)
        self.assertEqual(m["major_delivery"], 0.0)
        self.assertEqual(m["needle_recall"], 1.0)
        self.assertEqual(m["lookalike_rate"], 0.0)

    def test_quiet_snapshot_scores_false_major_rate(self):
        feed = ["routine", "forced-junk"]
        trace = _trace(feed, {})
        trace["forced-junk"]["reason"] = "forced global event"
        r = BuildResult(feed=feed, trace=trace)
        m = score_build(r, {}, {"clusters": []}, _pool(feed), k=12, kind="proto", quiet=True)
        self.assertEqual(m["false_major_rate"], 0.5)

    def test_empty_feed_and_no_labels(self):
        r = BuildResult(feed=[], trace={})
        m = score_build(r, {}, {"clusters": []}, [], k=12, kind="proto")
        self.assertIsNone(m["recall_at_k"])
        self.assertIsNone(m["never_rate"])
        self.assertIsNone(m["event_delivery"])
        self.assertEqual(m["feed_size"], 0)

    def test_aggregate_means_and_mins(self):
        per = {"a": {"recall_at_k": 1.0, "never_rate": 0.0, "calls": 3, "cost_usd": 0.01, "cache_misses": 0,
                     "loss_by_stage": {"rank": 1}},
               "b": {"recall_at_k": 0.5, "never_rate": 0.2, "calls": 1, "cost_usd": 0.02, "cache_misses": 1,
                     "loss_by_stage": {"rank": 2, "blended": 1}}}
        s = aggregate(per)
        self.assertEqual(s["recall_at_k_mean"], 0.75)
        self.assertEqual(s["recall_at_k_min"], 0.5)
        self.assertEqual(s["never_rate_min"], 0.0)
        self.assertEqual(s["calls_total"], 4)
        self.assertEqual(s["loss_by_stage"], {"rank": 3, "blended": 1})
        self.assertEqual(s["cache_misses_total"], 1)


if __name__ == "__main__":
    unittest.main()
