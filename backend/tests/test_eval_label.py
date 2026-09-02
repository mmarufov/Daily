"""Reviewed-label provenance must be honest and deterministic."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import label


class TestAgentReview(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.labels = Path(self.tmp.name) / "labels"
        self.patch = patch.object(label, "LABELS", self.labels)
        self.patch.start()
        out = self.labels / "snap"
        out.mkdir(parents=True)
        (out / "ray.jsonl").write_text(
            json.dumps({"article_id": "a1", "label": "must_see", "tags": [], "source": "model"}) + "\n" +
            json.dumps({"article_id": "a2", "label": "fine", "tags": [], "source": "model"}) + "\n"
        )

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_agent_overrides_model_but_human_remains_authoritative(self):
        decisions = Path(self.tmp.name) / "decisions.json"
        decisions.write_text(json.dumps({"decisions": [{
            "persona": "ray", "article_id": "a1", "label": "fine",
            "tags": ["background_routine"], "rationale": "Useful, but missable.",
        }]}))
        label.apply_agent_review("snap", decisions)
        loaded = label.load_labels("snap", "ray", include_needles=False)
        self.assertEqual((loaded["a1"]["label"], loaded["a1"]["source"]), ("fine", "agent"))

        with (self.labels / "snap" / "ray.jsonl").open("a") as f:
            f.write(json.dumps({"article_id": "a1", "label": "never", "tags": [], "source": "human"}) + "\n")
        loaded = label.load_labels("snap", "ray", include_needles=False)
        self.assertEqual((loaded["a1"]["label"], loaded["a1"]["source"]), ("never", "human"))

    def test_rejects_unknown_article(self):
        decisions = Path(self.tmp.name) / "decisions.json"
        decisions.write_text(json.dumps([{"persona": "ray", "article_id": "missing", "label": "fine"}]))
        with self.assertRaises(ValueError):
            label.apply_agent_review("snap", decisions)

    def test_requires_complete_review_queue(self):
        with (self.labels / "snap" / "ray.jsonl").open("a") as f:
            f.write(json.dumps({"article_id": "a3", "label": "fine", "tags": [],
                                "source": "model", "contested": True}) + "\n")
        decisions = Path(self.tmp.name) / "decisions.json"
        decisions.write_text(json.dumps([{"persona": "ray", "article_id": "a1", "label": "fine"}]))
        with self.assertRaisesRegex(ValueError, "incomplete review queue"):
            label.apply_agent_review("snap", decisions)

    def test_agent_event_review_validates_snapshot_and_articles(self):
        (self.labels / "snap" / "events.json").write_text(json.dumps({"threshold": 0.55, "clusters": []}))
        decisions = Path(self.tmp.name) / "events-review.json"
        decisions.write_text(json.dumps({
            "snapshot": "snap", "review": "independent audit", "clusters": [{
                "id": "ev-01", "title": "Event", "tier": "major", "article_ids": ["a1"],
                "sources": ["Wire"], "spread": 1, "source": "agent",
            }],
        }))
        label.apply_agent_event_review("snap", decisions, [{"id": "a1"}])
        saved = json.loads((self.labels / "snap" / "events.json").read_text())
        self.assertEqual(saved["clusters"][0]["source"], "agent")
        self.assertEqual(saved["review"]["source"], "agent")


if __name__ == "__main__":
    unittest.main()
