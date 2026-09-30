"""evals/replay_diff.py: the counts it reports, and when it refuses to report.

The numbers in evals/results/replay/ come from `_diff_snapshot` and
`_batch_totals`. These tests feed both hand-built sides where the right answer
is known, including the control that two identical sides move nothing, and
check that a replay whose scoring calls hit a provider error writes no diff.
"""
import copy
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals import replay_diff  # noqa: E402


def _side(verdicts, calls, feed=("a1", "a2")):
    summary = {m + "_mean": 0.5 for m in replay_diff.METRICS}
    summary["loss_by_stage"] = {"blended": 1}
    return {
        "summary": summary,
        "feeds": {"ray": list(feed)},
        "verdicts": {"ray": verdicts},
        "batches": {"ray": calls},
    }


VERDICTS = {
    "a1": {"relevant": True, "score": 0.9, "reason": "on topic"},
    "a2": {"relevant": False, "score": 0.1, "reason": "off topic"},
    "a3": {"relevant": False, "score": 0.0, "reason": "scoring unavailable"},
}
POSITIONAL_CALL = {"articles": 40, "keyed": False, "misnamed": 0, "unscored": 0,
                   "events": [{"articles": 40, "entries": 27, "outcome": "applied_by_position"}]}
REFUSED_CALL = {"articles": 40, "keyed": True, "misnamed": 0, "unscored": 40,
                "events": [{"articles": 40, "outcome": "refused", "refusal_kind": "missing_id"}] * 3}


class DiffTests(unittest.TestCase):
    def test_identical_sides_move_nothing(self):
        side = _side(VERDICTS, [POSITIONAL_CALL])
        diff = replay_diff._diff_snapshot(side, copy.deepcopy(side))
        self.assertEqual(diff["verdicts"]["moved"], 0)
        self.assertEqual(diff["feeds"]["personas_whose_top12_changed"], 0)
        self.assertTrue(all(v["delta"] == 0 for v in diff["metrics"].values()))

    def test_control_one_flipped_verdict_is_counted(self):
        head = copy.deepcopy(VERDICTS)
        head["a2"]["relevant"] = True
        diff = replay_diff._diff_snapshot(_side(VERDICTS, []), _side(head, [], feed=("a2", "a1")))
        self.assertEqual(diff["verdicts"]["relevant_flipped"], 1)
        self.assertEqual(diff["verdicts"]["unscored_base"], 1)

    def test_feed_changes_are_named(self):
        diff = replay_diff._diff_snapshot(_side(VERDICTS, []), _side(VERDICTS, [], feed=("a1", "a3")))
        self.assertEqual(diff["feeds"]["per_persona"]["ray"], {"entered": ["a3"], "left": ["a2"]})


class BatchTotalTests(unittest.TestCase):
    def test_positional_and_refused_calls_are_counted_apart(self):
        totals = replay_diff._batch_totals(_side({}, [POSITIONAL_CALL, REFUSED_CALL]))
        self.assertEqual(totals["calls"], 2)
        self.assertEqual(totals["calls_applied_by_position_after_count_mismatch"], 1)
        self.assertEqual(totals["verdicts_applied_from_mismatched_batches"], 40)
        self.assertEqual(totals["calls_refused"], 1)
        self.assertEqual(totals["refusals_by_kind"], {"missing_id": 3})

    def test_control_a_misnamed_verdict_is_not_hidden(self):
        misnamed = dict(REFUSED_CALL, misnamed=1, unscored=0, events=[])
        totals = replay_diff._batch_totals(_side({}, [misnamed]))
        self.assertEqual(totals["verdicts_applied_to_another_article"], 1)


class FailClosedTests(unittest.TestCase):
    def _main(self, head_errors, out):
        clean = {"snapshots": {"s": _side(VERDICTS, [])}, "meter": {}, "provider_errors": []}
        broken = dict(clean, provider_errors=head_errors)
        sides = iter([clean, broken])
        with patch.object(replay_diff, "_git", return_value="abc12345"), \
             patch.object(replay_diff, "_materialise", return_value=Path(".")), \
             patch.object(replay_diff, "_run_side", side_effect=lambda *a: next(sides)):
            return replay_diff.main(["--base", "x", "--head", "y", "--snapshot", "s", "--out", str(out)])

    def test_a_clean_replay_writes_its_diff(self):
        out = Path(self.id().replace(".", "_") + ".json")
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        with patch("builtins.print"):
            self.assertEqual(self._main([], out), 0)
        self.assertTrue(out.exists())

    def test_a_provider_error_writes_nothing(self):
        out = Path(self.id().replace(".", "_") + ".json")
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        with self.assertRaises(SystemExit) as raised:
            self._main(["RateLimitError: Error code: 429 insufficient_quota"], out)
        self.assertIn("measure the outage", str(raised.exception))
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
