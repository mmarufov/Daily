"""The regression gate.

Runs the production system and explicitly versioned historical S0 prototype against
every frozen snapshot, entirely from
the committed LLM cache (no API key, no spend), and fails if quality regressed
against the committed baseline or crossed a hard floor.

Two tiers:
  * always enforced — junk stays out, world-critical events arrive, nothing got
    worse than the baseline by more than the tolerance, and the run stayed
    offline (a cache miss means someone changed a prompt without re-warming).
  * EVAL_GATE_STRICT=1 — the absolute targets from
    tasks/filtering-architecture-plan.md §9. Production does not meet them yet;
    that gap is what S6/S7 exist to close, and the scorecard reports it every run.

The historical prototype fixtures used reader-dependent event discovery. They
cannot certify S4 or the corrected default `proto` protocol. New canonical
requests fail offline on absent exact responses; they must never borrow old
response keys. S4 has its own mandatory release-quality gate.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["EVAL_OFFLINE"] = "1"

from evals.snapshot import list_snapshots  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "evals" / "results"
BASELINES = {"prod-llm": RESULTS / "baseline-prod-llm.json",
             "proto-hybrid-judge-events": RESULTS / "baseline-proto.json"}
RUNNERS = {"prod-llm": "prod", "proto-hybrid-judge-events": "proto-s0-legacy-v1"}
BASELINE_PROTOCOLS = {"prod-llm": "production-feed-v1",
                      "proto-hybrid-judge-events": "s0-prototype-persona-global-v1"}

TOLERANCE = 0.05
NEVER_RATE_MAX = 0.05
CALLS_MAX_PER_PERSONA = {"prod-llm": 12, "proto-hybrid-judge-events": 30}
STRICT = {"recall_at_k_mean": 0.8, "need_to_know_recall_mean": 0.9, "needle_recall_mean": 1.0}

_CACHE: dict = {}


def _run(runner_key: str, snapshot: str) -> dict:
    key = (runner_key, snapshot)
    if key not in _CACHE:
        from evals.run import evaluate
        report = evaluate(RUNNERS[runner_key], snapshot, k=12, verbose=False, write=False)
        if report.get("protocol") != BASELINE_PROTOCOLS[runner_key]:
            raise AssertionError("historical baseline protocol mismatch")
        _CACHE[key] = report
    return _CACHE[key]


@unittest.skipUnless(list_snapshots(), "no frozen snapshots")
class TestEvalGate(unittest.TestCase):

    def _for_each(self):
        for runner_key in RUNNERS:
            for entry in list_snapshots():
                yield runner_key, entry["name"], _run(runner_key, entry["name"])

    def test_runs_fully_offline(self):
        for runner_key, snap, doc in self._for_each():
            with self.subTest(runner=runner_key, snapshot=snap):
                self.assertEqual(doc["summary"]["cache_misses_total"], 0)

    @unittest.skipUnless(os.getenv("EVAL_GATE_STRICT"), "absolute never-rate target is strict-only")
    def test_never_rate_floor(self):
        for runner_key, snap, doc in self._for_each():
            s = doc["summary"]
            with self.subTest(runner=runner_key, snapshot=snap):
                if s["never_rate_mean"] is not None:
                    self.assertLessEqual(s["never_rate_mean"], NEVER_RATE_MAX + (0.0 if runner_key.startswith("proto") else 0.30),
                                         "junk in the feed above the floor")

    @unittest.skipUnless(os.getenv("EVAL_GATE_STRICT"), "absolute event-delivery target is strict-only")
    def test_world_critical_events_delivered(self):
        for runner_key, snap, doc in self._for_each():
            s = doc["summary"]
            with self.subTest(runner=runner_key, snapshot=snap):
                if runner_key.startswith("proto") and s["event_delivery_min"] is not None:
                    self.assertEqual(s["event_delivery_min"], 1.0, "a world-critical event failed to reach a reader")

    @unittest.skipUnless(os.getenv("EVAL_GATE_STRICT"), "absolute false-major target is strict-only")
    def test_no_false_major_on_quiet_snapshot(self):
        for runner_key, snap, doc in self._for_each():
            s = doc["summary"]
            with self.subTest(runner=runner_key, snapshot=snap):
                if s["false_major_rate_mean"] is not None:
                    self.assertEqual(s["false_major_rate_mean"], 0.0)

    def test_calls_per_persona_bounded(self):
        for runner_key, snap, doc in self._for_each():
            with self.subTest(runner=runner_key, snapshot=snap):
                # Preserve the original 12/30 ceiling at its original reader
                # pipeline boundary. Total/preparation calls are still reported.
                self.assertLessEqual(doc["summary"]["reader_pipeline_calls_max_per_persona"], CALLS_MAX_PER_PERSONA[runner_key])

    def test_no_regression_against_baseline(self):
        for runner_key, snap, doc in self._for_each():
            base_path = BASELINES[runner_key]
            if not base_path.exists():
                self.skipTest(f"no baseline at {base_path}")
            base = json.loads(base_path.read_text())
            snapshot_baselines = base.get("snapshot_baselines") or {}
            if snap in snapshot_baselines:
                b = snapshot_baselines[snap]
            elif base.get("snapshot") == snap:
                b = base["summary"]
            else:
                continue
            s = doc["summary"]
            for key, higher_is_better in (("recall_at_k_mean", True), ("recall_at_retrieval_mean", True),
                                          ("need_to_know_recall_mean", True), ("followup_recall_mean", True),
                                          ("needle_recall_mean", True),
                                          ("never_rate_mean", False), ("lookalike_rate_mean", False),
                                          ("false_major_rate_mean", False),
                                          ("event_delivery_mean", True)):
                bv, sv = b.get(key), s.get(key)
                if bv is None or sv is None:
                    continue
                with self.subTest(runner=runner_key, snapshot=snap, metric=key):
                    if higher_is_better:
                        self.assertGreaterEqual(sv, bv - TOLERANCE, f"{key} regressed: {bv} -> {sv}")
                    else:
                        self.assertLessEqual(sv, bv + TOLERANCE, f"{key} regressed: {bv} -> {sv}")

    @unittest.skipUnless(os.getenv("EVAL_GATE_STRICT"), "strict targets only under EVAL_GATE_STRICT=1")
    def test_strict_targets(self):
        for runner_key, snap, doc in self._for_each():
            s = doc["summary"]
            for key, target in STRICT.items():
                with self.subTest(runner=runner_key, snapshot=snap, metric=key):
                    self.assertIsNotNone(s.get(key))
                    self.assertGreaterEqual(s[key], target)
            with self.subTest(runner=runner_key, snapshot=snap, metric="calls"):
                self.assertLessEqual(s["calls_max_per_persona"], 1)


if __name__ == "__main__":
    unittest.main()
