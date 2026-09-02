"""Snapshots must be content-hashed, reloadable, and derivable without drift."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import snapshot as snap


def _corpus(n=5):
    return {
        "built_at": "2026-08-31T09:00:00+00:00", "feeds_ok": 1, "feeds_dead": 0,
        "articles": [{"id": f"a{i:05d}", "url": f"https://x/{i}", "title": f"t{i}", "summary": "",
                      "content": "", "source": "S", "feed_vertical": "general", "category": "general",
                      "image_url": None, "published_at": "2026-08-31T08:00:00+00:00"} for i in range(n)],
    }


class TestSnapshot(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._p = [
            patch.object(snap, "SNAPSHOTS", root / "snapshots"),
            patch.object(snap, "MANIFEST", root / "snapshots" / "manifest.json"),
            patch.object(snap, "EVALS", root),
        ]
        [p.start() for p in self._p]

    def tearDown(self):
        [p.stop() for p in self._p]
        self.tmp.cleanup()

    def test_freeze_load_verify(self):
        corpus = Path(self.tmp.name) / "corpus.json"
        corpus.write_text(json.dumps(_corpus()))
        p = snap.freeze(corpus, note="unit")
        self.assertTrue(p.exists())
        data = snap.load_snapshot("2026-08-31")
        self.assertEqual(len(data["articles"]), 5)
        self.assertEqual(data["snapshot"]["frozen_now"], "2026-08-31T09:00:00+00:00")
        self.assertEqual(snap.frozen_now(data).isoformat(), "2026-08-31T09:00:00+00:00")
        self.assertTrue(snap.verify_snapshot("2026-08-31"))
        entry = snap.list_snapshots()[0]
        self.assertEqual((entry["n_articles"], entry["note"]), (5, "unit"))

    def test_derive_removes_exactly_the_named_articles(self):
        snap.save_snapshot(_corpus(), "base")
        labels = Path(self.tmp.name) / "labels" / "base"
        labels.mkdir(parents=True)
        (labels / "events.json").write_text(json.dumps({"snapshot": "base", "clusters": [
            {"id": "ev-01", "tier": "world_critical", "article_ids": ["a00001", "a00003"]},
            {"id": "ev-02", "tier": "routine", "article_ids": ["a00002", "a00003"]},
        ]}))
        (labels / "ray.jsonl").write_text(
            json.dumps({"article_id": "a00001", "label": "must_see"}) + "\n" +
            json.dumps({"article_id": "a00002", "label": "fine"}) + "\n"
        )
        (labels / "needles.json").write_text(json.dumps({"ray": {"plant": [{"id": "needle"}]}}))
        ids = snap.cluster_article_ids("base", ["ev-01"])
        snap.derive("base", "base-quiet", ids, removed_clusters=["ev-01"], quiet=True)
        q = snap.load_snapshot("base-quiet")
        self.assertEqual([a["id"] for a in q["articles"]], ["a00000", "a00002", "a00004"])
        self.assertEqual(q["snapshot"]["derived_from"], "base")
        self.assertEqual(q["snapshot"]["removed_clusters"], ["ev-01"])
        self.assertTrue(q["snapshot"]["quiet"])
        self.assertEqual(len(snap.list_snapshots()), 2)
        derived_labels = Path(self.tmp.name) / "labels" / "base-quiet"
        self.assertEqual([json.loads(line)["article_id"] for line in (derived_labels / "ray.jsonl").read_text().splitlines()], ["a00002"])
        events = json.loads((derived_labels / "events.json").read_text())
        self.assertEqual(events["snapshot"], "base-quiet")
        self.assertEqual(events["clusters"], [{"id": "ev-02", "tier": "routine", "article_ids": ["a00002"]}])
        self.assertTrue((derived_labels / "needles.json").exists())

    def test_duplicate_ids_rejected(self):
        c = _corpus()
        c["articles"][1]["id"] = "a00000"
        with self.assertRaises(ValueError):
            snap.save_snapshot(c, "dup")


if __name__ == "__main__":
    unittest.main()
