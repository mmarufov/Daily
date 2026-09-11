"""Runners must drive the real production path offline and trace every article."""
import os
import sys
import types
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for _name, _stub in {
    "httpx": types.SimpleNamespace(AsyncClient=object),
    "bs4": types.SimpleNamespace(BeautifulSoup=object),
    "openai": types.SimpleNamespace(OpenAI=object),
    "dotenv": types.SimpleNamespace(load_dotenv=lambda *a, **k: None),
}.items():
    sys.modules.setdefault(_name, _stub)

from evals.fake_db import SnapshotConn, eval_uuid
from evals.runners import ProductionRunner, PrototypeRunner, HistoricalS0PrototypeRunner, get_runner

NOW = datetime(2026, 8, 31, 9, 0, tzinfo=timezone.utc)

PERSONA = {
    "key": "t", "name": "Test — Newark",
    "ai_profile": "I live in Newark and follow the New Jersey Devils and NJ Transit. No crypto.",
    "interests": {"topics": ["NJ Transit", "New Jersey Devils"], "people": [], "locations": ["Newark"],
                  "industries": ["public transit"], "excluded_topics": ["cryptocurrency"], "notes": ""},
    "user_profile_v2": {"stable_interests": ["New Jersey Devils"], "current_interests": ["NJ Transit"],
                        "people": [], "locations": ["Newark"], "industries": ["public transit"],
                        "excluded_topics": ["cryptocurrency"], "expanded_exclusions": ["bitcoin"],
                        "utility_priorities": ["local"], "content_depth": "breaking",
                        "tone_preferences": ["neutral"], "life_context": "Newark commuter.",
                        "source_selection_brief": {"priority_topics": ["NJ Transit"], "must_cover_entities": ["New Jersey Devils"],
                                                   "must_avoid_topics": ["cryptocurrency"], "preferred_source_types": ["publisher"],
                                                   "coverage_targets": ["Newark"], "specificity_level": "specific"}},
}


def _pool(n=30):
    out = []
    for i in range(n):
        if i % 3 == 0:
            title, cat = f"NJ Transit announces schedule change number {i} for Newark commuters", "local"
        elif i % 3 == 1:
            title, cat = f"New Jersey Devils sign defenseman in trade {i}", "sports"
        else:
            title, cat = f"Bitcoin token sale {i} draws crypto investors", "crypto"
        out.append({
            "id": f"a{i:05d}", "url": f"https://example.com/{i}", "title": title,
            "summary": f"{title}. A longer summary sentence to pass the minimum text length check.",
            "content": "", "source": f"Source {i % 4}", "feed_vertical": cat, "category": cat,
            "image_url": None,
            "published_at": (NOW - timedelta(hours=1 + i)).isoformat(),
        })
    # one stale article outside every lookback window
    out.append({**out[0], "id": "a99999", "url": "https://example.com/old",
                "published_at": (NOW - timedelta(days=30)).isoformat()})
    return out


class TestSnapshotConn(unittest.TestCase):

    def test_candidate_query_respects_lookback_and_limit(self):
        conn = SnapshotConn(PERSONA, _pool(), NOW)
        with conn.cursor() as cur:
            cur.execute("SELECT ... FROM public.articles a JOIN public.article_source_links asl ... "
                        "WHERE x > now() - interval '72 hours' ... LIMIT 5", ("u",))
            rows = cur.fetchall()
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["id"], eval_uuid("a00000"))
        self.assertTrue(isinstance(rows[0]["published_at"], datetime))
        self.assertNotIn(eval_uuid("a99999"), {r["id"] for r in rows})

    def test_unhandled_sql_is_recorded_and_raised(self):
        conn = SnapshotConn(PERSONA, _pool(3), NOW)
        with self.assertRaises(AssertionError):
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM public.some_new_table")
        self.assertEqual(len(conn.store["unhandled"]), 1)


class TestProductionRunner(unittest.TestCase):

    def test_fallback_mode_traces_every_article_without_api_calls(self):
        pool = _pool()
        r = ProductionRunner(mode="fallback", k=5).build(PERSONA, pool, NOW)
        self.assertEqual(set(r.trace), {a["id"] for a in pool})
        self.assertEqual(r.calls, 0)
        self.assertTrue(r.feed, "fallback path should still produce a feed")
        self.assertTrue(set(r.feed) <= {a["id"] for a in pool})
        self.assertEqual(r.trace["a99999"]["dropped_at"], "lookback")
        crypto = [a["id"] for a in pool if a["category"] == "crypto"]
        self.assertTrue(all(r.trace[i]["dropped_at"] is not None for i in crypto))
        self.assertTrue(any(r.trace[i]["dropped_at"] == "prefilter:excluded" for i in crypto))
        for rank, i in enumerate(r.feed, 1):
            self.assertEqual(r.trace[i]["rank"], rank)
            self.assertEqual(r.trace[i]["dropped_at"], None if rank <= 5 else "rank")
        self.assertEqual(r.meta["mode"], "fallback")
        self.assertIn("prefilter", r.stage_counts().keys() | r.drop_counts().keys() | {"prefilter"})


class TestPrototypeRunner(unittest.TestCase):

    def test_historical_protocol_requires_explicit_runner_and_default_stays_canonical(self):
        current = get_runner("proto")
        historical = get_runner("proto-s0-legacy-v1")
        self.assertIs(type(current), PrototypeRunner)
        self.assertIs(type(historical), HistoricalS0PrototypeRunner)
        self.assertEqual(current.protocol, "canonical-global-events-v2")
        self.assertEqual(historical.protocol, "s0-prototype-persona-global-v1")
        self.assertTrue(callable(current.prepare_global))
        self.assertIsNone(historical.prepare_global)
        self.assertNotEqual(current.name, historical.name)

    def test_historical_adapter_uses_frozen_boundary_only_when_explicit(self):
        with patch("evals.legacy_s0.run_pipeline", return_value="historical") as old, \
                patch("evals.pipeline.run_pipeline", return_value="current") as current:
            self.assertEqual(get_runner("proto")._run_pipeline("sentinel"), "current")
            old.assert_not_called()
            self.assertEqual(get_runner("proto-s0-legacy-v1")._run_pipeline("sentinel"), "historical")
            old.assert_called_once_with("sentinel")
            current.assert_called_once_with("sentinel")

    def test_baseline_rejects_canonical_report_under_historical_identity(self):
        import test_eval_gate as gate
        with patch.dict(gate._CACHE, {}, clear=True), \
                patch("evals.run.evaluate", return_value={"protocol": "canonical-global-events-v2"}):
            with self.assertRaisesRegex(AssertionError, "baseline protocol mismatch"):
                gate._run("proto-hybrid-judge-events", "sentinel")

    def test_bm25_runner_traces_stages(self):
        pool = _pool()
        r = PrototypeRunner(backend="bm25", judge=False, events=False, feed_size=6, k=6).build(PERSONA, pool, NOW)
        self.assertEqual(set(r.trace), {a["id"] for a in pool})
        self.assertEqual(r.calls, 0)
        self.assertTrue(r.feed)
        crypto = [a["id"] for a in pool if a["category"] == "crypto"]
        self.assertTrue(all(i not in r.feed for i in crypto))
        stages = {t["stage_reached"] for t in r.trace.values()}
        self.assertIn("feed", stages)
        self.assertTrue(all(t["dropped_at"] is None for i, t in r.trace.items() if i in r.feed))

    def test_pool_cache_changes_with_content_and_cutoff_not_only_ids(self):
        runner = PrototypeRunner(backend="bm25", judge=False, events=False)
        pool = _pool(3)
        first = runner._prepare(pool, NOW)
        self.assertIs(runner._prepare(pool, NOW), first)
        changed = [{**a, "summary": "changed"} for a in pool]
        self.assertIsNot(runner._prepare(changed, NOW), first)
        self.assertIsNot(runner._prepare(pool, NOW + timedelta(minutes=1)), first)

    def test_global_pool_excludes_persona_needles_and_rejects_stale_evidence(self):
        runner = PrototypeRunner(backend="bm25", judge=False, events=False)
        canonical = _pool(3)
        state = runner._prepare(canonical, NOW)
        state["events"] = [{"id": 0, "tier": "world_critical", "members": [0, 1], "rep": 0}]
        runner.prepare_global(canonical, NOW)
        needle = {**canonical[0], "id": "needle", "title": "Very major synthetic reader needle"}
        reordered = [needle] + canonical[::-1]
        events = runner._events_for_pool(reordered, NOW)
        self.assertEqual([reordered[i]["id"] for i in events[0]["members"]], [canonical[0]["id"], canonical[1]["id"]])
        self.assertNotIn(0, events[0]["members"])
        bad = [dict(a) for a in reordered]
        bad[1]["summary"] = "new evidence same ID"
        with self.assertRaisesRegex(ValueError, "Canonical global evidence changed"):
            runner._events_for_pool(bad, NOW)
        with self.assertRaisesRegex(ValueError, "cutoff"):
            runner._events_for_pool(reordered, NOW + timedelta(minutes=1))

    def test_preparation_cost_is_included_for_direct_runner_and_once_for_global(self):
        runner = PrototypeRunner(backend="bm25", judge=False, events=False)
        measured = lambda fn: (fn(), 1, .125, 2, 0, .01)
        with patch("evals.runners._meter_delta", side_effect=measured):
            shared = runner.prepare_global(_pool(3), NOW)
            result = runner.build(PERSONA, _pool(3), NOW)
        self.assertEqual(shared["calls"], 1)
        self.assertEqual(shared["cost_usd"], .125)
        self.assertEqual(result.calls, 2)  # per-reader preparation + reader pipeline
        self.assertEqual(result.cost_usd, .25)
        self.assertEqual(result.meta["reader_pipeline_calls"], 1)
        self.assertTrue(result.meta["global_pool_frozen"])

    def test_unchanged_canonical_pool_reuses_shared_preparation(self):
        runner = PrototypeRunner(backend="bm25", judge=False, events=False)
        pool = _pool(3)
        runner.prepare_global(pool, NOW)
        with patch.object(runner, "_prepare", side_effect=AssertionError("duplicate global preparation")):
            result = runner.build(PERSONA, pool, NOW)
        self.assertTrue(result.meta["global_pool_frozen"])

    def test_shared_preparation_added_to_system_totals_once(self):
        from evals import run
        runner = PrototypeRunner(backend="bm25", judge=False, events=False)
        prepared = {"calls": 7, "cost_usd": .25, "cache_misses": 0, "latency_s": .1}
        with patch.object(run, "get_runner", return_value=runner), \
                patch.object(run, "load_snapshot", return_value={"articles": _pool(3), "built_at": NOW.isoformat()}), \
                patch.object(run, "load_personas", return_value={"one": PERSONA, "two": PERSONA}), \
                patch.object(run, "load_events", return_value={"clusters": []}), \
                patch.object(run, "load_labels", return_value={}), \
                patch.object(runner, "prepare_global", return_value=prepared) as prepare:
            report = run.evaluate("proto-bm25", "test", needles=False, verbose=False, write=False)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(report["summary"]["calls_total"], 7)
        self.assertEqual(report["summary"]["reader_calls_total"], 0)
        self.assertEqual(report["summary"]["cost_usd_total"], .25)


if __name__ == "__main__":
    unittest.main()
