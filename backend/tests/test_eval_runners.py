"""Runners must drive the real production path offline and trace every article."""
import os
import sys
import types
import unittest
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
from evals.runners import ProductionRunner, PrototypeRunner

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


if __name__ == "__main__":
    unittest.main()
