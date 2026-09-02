"""The LLM cache is what makes evaluation reproducible and free to rerun."""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.llm_cache import BudgetExceeded, CacheMiss, CachingOpenAI, Meter, cache_key


class _FakeReal:
    """Counts calls and returns canned responses shaped like the OpenAI SDK's."""

    def __init__(self):
        self.chat_calls = 0
        self.embed_calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, **kw):
        self.chat_calls += 1
        return SimpleNamespace(
            model=kw["model"],
            choices=[SimpleNamespace(message=SimpleNamespace(role="assistant", content='{"ok": true}'),
                                     finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )

    def _embed(self, **kw):
        self.embed_calls += 1
        n = len(kw["input"])
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[float(i), 1.0, 0.0], index=i) for i in range(n)],
            usage=SimpleNamespace(prompt_tokens=5 * n),
        )


class TestCachingOpenAI(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.real = _FakeReal()

    def tearDown(self):
        self.tmp.cleanup()

    def test_identical_chat_request_hits_cache(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        kw = dict(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}], temperature=0.2)
        r1 = c.chat.completions.create(**kw)
        r2 = c.chat.completions.create(**kw)
        self.assertEqual(self.real.chat_calls, 1)
        self.assertEqual(r1.choices[0].message.content, r2.choices[0].message.content)
        self.assertEqual(r2.usage.prompt_tokens, 100)
        self.assertEqual((c.hits, c.misses), (1, 1))
        # cost is metered on hits too, from stored usage
        self.assertEqual(c.meter.calls, 2)
        self.assertGreater(c.meter.usd, 0)

    def test_different_request_is_a_different_key(self):
        a = cache_key("chat", model="m", messages=[{"role": "user", "content": "a"}])
        b = cache_key("chat", model="m", messages=[{"role": "user", "content": "b"}])
        self.assertNotEqual(a, b)
        self.assertEqual(a, cache_key("chat", messages=[{"role": "user", "content": "a"}], model="m"))

    def test_offline_miss_raises_and_never_builds_real_client(self):
        c = CachingOpenAI(real=None, cache_dir=self.dir, offline=True)
        with self.assertRaises(CacheMiss):
            c.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
        with self.assertRaises(CacheMiss):
            c.embeddings.create(model="e", input=["x"])

    def test_offline_hit_works_without_a_key(self):
        warm = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        kw = dict(model="m", messages=[{"role": "user", "content": "x"}])
        warm.chat.completions.create(**kw)
        cold = CachingOpenAI(real=None, cache_dir=self.dir, offline=True)
        r = cold.chat.completions.create(**kw)
        self.assertEqual(r.choices[0].message.content, '{"ok": true}')

    def test_embeddings_round_trip(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        r1 = c.embeddings.create(model="e", input=["a", "b", "c"])
        r2 = c.embeddings.create(model="e", input=["a", "b", "c"])
        self.assertEqual(self.real.embed_calls, 1)
        self.assertEqual(len(r2.data), 3)
        self.assertAlmostEqual(r2.data[2].embedding[0], 2.0, places=2)
        self.assertEqual(r1.usage.prompt_tokens, 15)

    def test_concurrent_writes_same_key(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        kw = dict(model="m", messages=[{"role": "user", "content": "race"}])
        errors = []

        def go():
            try:
                c.chat.completions.create(**kw)
            except Exception as e:  # pragma: no cover
                errors.append(e)

        ts = [threading.Thread(target=go) for _ in range(8)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errors, [])
        again = CachingOpenAI(real=None, cache_dir=self.dir, offline=True)
        self.assertEqual(again.chat.completions.create(**kw).choices[0].message.content, '{"ok": true}')

    def test_budget_guard(self):
        m = Meter(budget_usd=0.0000001)
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False, meter=m)
        with self.assertRaises(BudgetExceeded):
            c.chat.completions.create(model="gpt-4.1", messages=[{"role": "user", "content": "$"}])

    def test_streaming_not_cacheable(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        with self.assertRaises(NotImplementedError):
            c.chat.completions.create(model="m", messages=[], stream=True)


if __name__ == "__main__":
    unittest.main()
