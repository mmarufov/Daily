"""The LLM cache is what makes evaluation reproducible and free to rerun."""
import os
import asyncio
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.llm_cache import BudgetExceeded, CacheMiss, CachingOpenAI, CachingUnderstandingProvider, Meter, UnknownModelPricing, cache_key


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
        kw = dict(model="gpt-4o-mini", messages=[{"role": "user", "content": "x"}])
        warm.chat.completions.create(**kw)
        cold = CachingOpenAI(real=None, cache_dir=self.dir, offline=True)
        r = cold.chat.completions.create(**kw)
        self.assertEqual(r.choices[0].message.content, '{"ok": true}')

    def test_embeddings_round_trip(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        r1 = c.embeddings.create(model="text-embedding-3-small", input=["a", "b", "c"])
        r2 = c.embeddings.create(model="text-embedding-3-small", input=["a", "b", "c"])
        self.assertEqual(self.real.embed_calls, 1)
        self.assertEqual(len(r2.data), 3)
        self.assertAlmostEqual(r2.data[2].embedding[0], 2.0, places=2)
        self.assertEqual(r1.usage.prompt_tokens, 15)

    def test_concurrent_writes_same_key(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        kw = dict(model="gpt-4o-mini", messages=[{"role": "user", "content": "race"}])
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
            c.chat.completions.create(model="gpt-4.1", messages=[{"role": "user", "content": "$"}], max_tokens=10)
        self.assertEqual(self.real.chat_calls, 0)

    def test_unknown_model_is_rejected_before_any_provider_call(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        with self.assertRaises(UnknownModelPricing):
            c.chat.completions.create(model="gpt-4.1-mini-2099-01-01", messages=[])
        with self.assertRaises(UnknownModelPricing):
            c.embeddings.create(model="unknown", input=["x"])
        self.assertEqual((self.real.chat_calls, self.real.embed_calls), (0, 0))

    def test_pinned_models_have_real_replay_cost(self):
        for model in ("gpt-4.1-mini-2025-04-14", "gpt-4o-mini-2024-07-18"):
            c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
            kw = dict(model=model, messages=[{"role": "user", "content": "x"}])
            c.chat.completions.create(**kw)
            before = c.meter.usd
            c.chat.completions.create(**kw)
            self.assertGreater(before, 0)
            self.assertAlmostEqual(c.meter.usd, before * 2)
            self.assertEqual(c.meter.reserved_usd, 0)

    def test_budget_requires_bounded_generation(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False, meter=Meter(1))
        with self.assertRaises(ValueError):
            c.chat.completions.create(model="gpt-4o-mini", messages=[])
        self.assertEqual(self.real.chat_calls, 0)

    def test_budget_reservations_are_atomic_across_threads(self):
        meter = Meter(0.001)
        barrier = threading.Barrier(8)
        accepted, rejected = [], []

        def reserve():
            barrier.wait()
            try:
                accepted.append(meter.reserve("gpt-4.1", 500))
            except BudgetExceeded:
                rejected.append(True)

        threads = [threading.Thread(target=reserve) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((len(accepted), len(rejected)), (1, 7))
        self.assertAlmostEqual(meter.reserved_usd, 0.001)
        meter.add("gpt-4.1", 100, reservation=accepted[0])
        self.assertEqual(meter.reserved_usd, 0)
        with self.assertRaises(ValueError):
            meter.add("gpt-4.1", 100, reservation=accepted[0])

    def test_ambiguous_provider_failure_keeps_reservation(self):
        def fail(**kw):
            raise TimeoutError("response was lost")

        self.real.chat.completions.create = fail
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False, meter=Meter(1))
        with self.assertRaises(TimeoutError):
            c.chat.completions.create(model="gpt-4o-mini", messages=[], max_tokens=10)
        self.assertGreater(c.meter.reserved_usd, 0)
        self.assertEqual(c.meter.calls, 0)

    def test_streaming_not_cacheable(self):
        c = CachingOpenAI(real=self.real, cache_dir=self.dir, offline=False)
        with self.assertRaises(NotImplementedError):
            c.chat.completions.create(model="m", messages=[], stream=True)


class _FakeUnderstanding:
    def __init__(self):
        self.calls = 0
        self.failure = None
        self.actual = 0.25
        self.prompt_version = 1

    def prepare_request(self, bundle, recipe, stage):
        return "/chat/completions", {"model": "gpt-4.1-mini-2025-04-14",
                                     "messages": [bundle], "prompt": self.prompt_version}, 0.5

    def estimate_usd(self, *args):
        return 0.5

    async def generate(self, bundle, recipe, stage):
        from app.services.understanding_provider import ProviderOutcome
        self.calls += 1
        if self.failure:
            raise self.failure
        return ProviderOutcome({"kind": "unknown"}, self.actual, "req-test")


class TestUnderstandingCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.directory = Path(self.tmp.name)
        self.provider = _FakeUnderstanding()

    def tearDown(self):
        self.tmp.cleanup()

    def cache(self, **options):
        return CachingUnderstandingProvider(self.provider, cache_dir=self.directory, **options)

    def generate(self, cache, article=1):
        return asyncio.run(cache.generate({"article_id": article}, {"recipe": 1}, "facets"))

    def test_offline_miss_never_calls_provider(self):
        with self.assertRaises(CacheMiss):
            self.generate(self.cache())
        self.assertEqual(self.provider.calls, 0)

    def test_paid_call_needs_explicit_capped_budget(self):
        with self.assertRaises(BudgetExceeded):
            self.generate(self.cache(offline=False))
        with self.assertRaises(ValueError):
            self.cache(budget_usd=5.01)
        self.assertEqual(self.provider.calls, 0)

    def test_budget_rejects_nonfinite_boolean_and_nonpositive_caps(self):
        for value in (float("nan"), float("inf"), True, False, 0, -1):
            with self.assertRaises(ValueError):
                self.cache(budget_usd=value)

    def test_budget_report_includes_ambiguous_reservations_across_instances(self):
        from app.services.understanding_provider import ProviderFailure
        self.provider.failure = ProviderFailure("timeout", ambiguous=True)
        with self.assertRaises(ProviderFailure):
            self.generate(self.cache(offline=False, budget_usd=1))
        report = self.cache().budget_report()
        self.assertEqual(report["spent_usd"], 0)
        self.assertEqual(report["reserved_usd"], 0.5)
        self.assertEqual(report["maximum_committed_usd"], 0.5)
        self.assertEqual(report["attempted_requests"], 1)

    def test_concurrent_distinct_requests_share_the_durable_cap(self):
        barrier = threading.Barrier(4)
        accepted, rejected = [], []

        def reserve(index):
            barrier.wait()
            try:
                self.cache(offline=False, budget_usd=0.5)._reserve(str(index), 0.5)
                accepted.append(index)
            except BudgetExceeded:
                rejected.append(index)

        threads = [threading.Thread(target=reserve, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual((len(accepted), len(rejected)), (1, 3))

    def test_replay_exact_request_preserves_usage_without_spend(self):
        outcome = self.generate(self.cache(offline=False, budget_usd=1))
        self.assertEqual(self.generate(self.cache()), outcome)
        self.assertEqual(self.provider.calls, 1)
        ledger = json.loads((self.directory / "pilot-budget.json").read_text())
        self.assertEqual(ledger["spent_usd"], 0.25)
        self.provider.prompt_version = 2
        with self.assertRaises(CacheMiss):
            self.generate(self.cache())

    def test_budget_persists_across_instances_and_cannot_be_increased(self):
        self.generate(self.cache(offline=False, budget_usd=0.5))
        with self.assertRaises(BudgetExceeded):
            self.generate(self.cache(offline=False, budget_usd=0.5), article=2)
        with self.assertRaises(ValueError):
            self.generate(self.cache(offline=False, budget_usd=1), article=2)
        self.assertEqual(self.provider.calls, 1)

    def test_changing_cache_path_cannot_reset_shared_ledger(self):
        options = {"offline": False, "budget_usd": 0.5, "ledger_dir": self.directory / "ledger"}
        first = CachingUnderstandingProvider(self.provider, cache_dir=self.directory / "first", **options)
        second = CachingUnderstandingProvider(self.provider, cache_dir=self.directory / "second", **options)
        self.generate(first)
        with self.assertRaises(BudgetExceeded):
            self.generate(second)
        with self.assertRaises(BudgetExceeded):
            self.generate(second, article=2)
        self.assertEqual(self.provider.calls, 1)

    def test_refusal_is_replayed_and_uncertain_charge_stays_reserved(self):
        from app.services.understanding_provider import ProviderFailure
        self.provider.failure = ProviderFailure("refused", ambiguous=True)
        with self.assertRaises(ProviderFailure):
            self.generate(self.cache(offline=False, budget_usd=0.5))
        with self.assertRaises(ProviderFailure):
            self.generate(self.cache())
        with self.assertRaises(BudgetExceeded):
            self.generate(self.cache(offline=False, budget_usd=0.5), article=2)
        self.assertEqual(self.provider.calls, 1)

    def test_crash_reservation_blocks_duplicate_submission(self):
        self.provider.failure = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.generate(self.cache(offline=False, budget_usd=1))
        with self.assertRaises(BudgetExceeded):
            self.generate(self.cache(offline=False, budget_usd=1))
        self.assertEqual(self.provider.calls, 1)

    def test_overspent_bound_halts_further_paid_calls(self):
        self.provider.actual = 0.6
        with self.assertRaises(BudgetExceeded):
            self.generate(self.cache(offline=False, budget_usd=5))
        with self.assertRaises(BudgetExceeded):
            self.generate(self.cache(offline=False, budget_usd=5), article=2)
        self.assertEqual(self.provider.calls, 1)


if __name__ == "__main__":
    unittest.main()
