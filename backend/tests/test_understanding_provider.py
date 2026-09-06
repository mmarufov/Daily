"""Offline OpenAI wire contracts: malformed responses never publish ready data."""
from __future__ import annotations

import asyncio
import copy
import importlib
import json
import sys
import types
import unittest
from unittest.mock import patch

existing = sys.modules.get("httpx")
if not isinstance(existing, types.ModuleType) or not getattr(existing, "__spec__", None):
    sys.modules.pop("httpx", None)
httpx = importlib.import_module("httpx")

from app.services import understanding_provider as provider
from app.services.understanding_contract import DEFAULT_RECIPE, build_evidence


def evidence():
    return build_evidence({"id": "article-1", "url": "https://news.example.com/story",
                           "title": "A story", "summary": "Unclear evidence"})


def card(bundle):
    return {"article_id": bundle["article_id"], "input_hash": bundle["input_hash"],
            "kind": "unknown", "kind_evidence": [], "topics": [], "entities": [], "places": [],
            "commercial": {"value": "unknown", "subtype": None, "evidence": []},
            "about": None, "about_evidence": [], "event_hints": [],
            "abstentions": [{"field": field, "reason": "insufficient_evidence"}
                            for field in ["kind", "topics", "entities", "places", "commercial", "about", "event_hints"]]}


def response(bundle, stage="facets"):
    if stage == "embedding":
        return {"model": DEFAULT_RECIPE["embedding_model"], "usage": {"prompt_tokens": 12},
                "data": [{"index": 0, "embedding": [0.5] * 1536}]}
    return {"id": "chatcmpl-test", "model": DEFAULT_RECIPE["model"],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30},
            "choices": [{"index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": json.dumps(card(bundle)), "refusal": None}}]}


class UnderstandingProviderTests(unittest.IsolatedAsyncioTestCase):
    def make_provider(self, data, *, status=200, headers=None, tokenizer=None):
        self.requests = []

        def handler(request):
            self.requests.append(request)
            return httpx.Response(status, json=data,
                                  headers={"x-request-id": "req-test", **(headers or {})})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(client.aclose)
        return provider.OpenAIUnderstandingProvider("sk-offline-test", client=client,
                                                   tokenizer=tokenizer or (lambda text, model: 100))

    async def test_facets_schema_identity_usage_and_no_tools(self):
        bundle = evidence()
        adapter = self.make_provider(response(bundle))
        result = await adapter.generate(stage="facets", bundle=bundle, recipe=DEFAULT_RECIPE)
        self.assertEqual(result.payload, card(bundle))
        self.assertAlmostEqual(result.usage_usd, 0.000088)
        self.assertGreater(adapter.estimate_usd(bundle, DEFAULT_RECIPE, "facets"), result.usage_usd)
        sent = json.loads(self.requests[0].content)
        self.assertEqual(sent["model"], DEFAULT_RECIPE["model"])
        self.assertTrue(sent["response_format"]["json_schema"]["strict"])
        self.assertNotIn("tools", sent)
        self.assertIn("untrusted", sent["messages"][0]["content"])
        self.assertEqual(str(self.requests[0].url), provider.API_ROOT + "/chat/completions")

    async def test_embeddings_and_queries_use_same_space(self):
        bundle = evidence()
        adapter = self.make_provider(response(bundle, "embedding"))
        result = await adapter.generate(bundle, DEFAULT_RECIPE, "embedding")
        query = await adapter.query_embedding("  cafe\u0301\n story ", DEFAULT_RECIPE)
        self.assertEqual(result.payload, query.payload)
        document, query_body = [json.loads(request.content) for request in self.requests]
        self.assertEqual(query_body["input"], ["café story"])
        for key in ("model", "dimensions", "encoding_format"):
            self.assertEqual(document[key], query_body[key])
        self.assertAlmostEqual(result.usage_usd, 0.00000024)

    async def test_unsupported_recipes_never_reach_network(self):
        adapter = self.make_provider({})
        variants = []
        for key in DEFAULT_RECIPE:
            omitted = dict(DEFAULT_RECIPE)
            del omitted[key]
            variants.append(omitted)
        for key, value in [("model", "unknown-model"), ("dimensions", True),
                           ("model", []), ("status", {}),
                           ("prompt_version", "unimplemented"), ("query_recipe", "mixed-space")]:
            variants.append({**DEFAULT_RECIPE, key: value})
        variants.append({**DEFAULT_RECIPE, "extra": "ignored?"})
        for recipe in variants:
            with self.subTest(recipe=recipe), self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(evidence(), recipe, "facets")
            self.assertEqual(raised.exception.kind, "unsupported_recipe")
        self.assertEqual(self.requests, [])

    async def test_pinned_baseline_model_has_explicit_nonzero_price(self):
        recipe = {**DEFAULT_RECIPE, "model": "gpt-4o-mini-2024-07-18"}
        adapter = self.make_provider({})
        self.assertGreater(adapter.estimate_usd(evidence(), recipe, "facets"), 0)

    async def test_oversized_and_insufficient_evidence_do_not_call_provider(self):
        for stage in ("facets", "embedding"):
            adapter = self.make_provider({}, tokenizer=lambda *_: 100_000)
            with self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(evidence(), DEFAULT_RECIPE, stage)
            self.assertEqual(raised.exception.kind, "input_too_large")
            self.assertEqual(self.requests, [])
        adapter = self.make_provider({})
        with self.assertRaises(provider.ProviderFailure):
            await adapter.generate({"sufficient": False}, DEFAULT_RECIPE, "facets")
        self.assertEqual(self.requests, [])

    async def test_schema_and_identity_failures_retain_actual_charge(self):
        bundle = evidence()
        base = response(bundle)
        cases = []
        for mutate in (
            lambda data: data.update(model="unrequested-model"),
            lambda data: data.update(id="bad\nsecret"),
            lambda data: data.update(choices=[]),
            lambda data: data["choices"][0].update(index=True),
            lambda data: data["choices"][0].update(finish_reason="length"),
            lambda data: data["choices"][0]["message"].update(refusal="private body"),
            lambda data: data["choices"][0]["message"].update(content="not json private body"),
            lambda data: data["choices"][0]["message"].update(content=json.dumps({**card(bundle), "input_hash": "wrong"})),
        ):
            data = copy.deepcopy(base)
            mutate(data)
            cases.append(data)
        for data in cases:
            adapter = self.make_provider(data)
            with self.subTest(data=data), self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(bundle, DEFAULT_RECIPE, "facets")
            self.assertGreater(raised.exception.usage_usd, 0)
            self.assertEqual(raised.exception.request_id, "req-test")
            self.assertNotIn("private body", str(raised.exception))

    async def test_bad_usage_keeps_reservation_ambiguous(self):
        for usage in (None, {}, {"prompt_tokens": True, "completion_tokens": 1},
                      {"prompt_tokens": -1, "completion_tokens": 1},
                      {"prompt_tokens": 1, "completion_tokens": 999999}):
            data = response(evidence())
            data["usage"] = usage
            adapter = self.make_provider(data)
            with self.subTest(usage=usage), self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(evidence(), DEFAULT_RECIPE, "facets")
            self.assertTrue(raised.exception.ambiguous)
            self.assertIsNone(raised.exception.usage_usd)

    async def test_embedding_alignment_and_finiteness_fail_closed(self):
        for rows in ([], [{"index": 1, "embedding": [0.5] * 1536}],
                     [{"index": False, "embedding": [0.5] * 1536}],
                     [{"index": 0, "embedding": [0.0] * 1536}],
                     [{"index": 0, "embedding": [True] * 1536}],
                     [{"index": 0, "embedding": [0.5] * 12}],
                     [{"index": 0, "embedding": [0.5] * 1536}] * 2):
            data = response(evidence(), "embedding")
            data["data"] = rows
            adapter = self.make_provider(data)
            with self.subTest(rows=len(rows)), self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(evidence(), DEFAULT_RECIPE, "embedding")
            self.assertIsNotNone(raised.exception.usage_usd)

    async def test_http_failure_classification_no_implicit_retries(self):
        for status, code, retry, ambiguous, wide in (
            (401, "invalid_key", False, False, True),
            (429, "rate_limit_exceeded", True, False, True),
            (429, "insufficient_quota", False, False, True),
            (500, "error", True, True, True),
            (400, "invalid", False, False, False),
            (302, "redirect", False, False, False),
        ):
            adapter = self.make_provider({"error": {"code": code, "message": "secret-body"}},
                                         status=status, headers={"retry-after": "90"})
            with self.subTest(status=status, code=code), self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(evidence(), DEFAULT_RECIPE, "facets")
            failure = raised.exception
            self.assertEqual((failure.retryable, failure.ambiguous, failure.provider_wide), (retry, ambiguous, wide))
            self.assertEqual(failure.retry_after, 90)
            self.assertEqual(len(self.requests), 1)
            self.assertNotIn("secret-body", str(failure))

    async def test_transport_failures_and_cancellation(self):
        for error, kind in ((httpx.ConnectError("secret"), "connection_unavailable"),
                            (httpx.ReadTimeout("secret"), "transport_ambiguous"),
                            (asyncio.CancelledError(), None)):
            async def handler(request):
                raise error
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                adapter = provider.OpenAIUnderstandingProvider("test", client=client, tokenizer=lambda *_: 100)
                with self.subTest(kind=kind), self.assertRaises(asyncio.CancelledError if kind is None else provider.ProviderFailure) as raised:
                    await adapter.generate(evidence(), DEFAULT_RECIPE, "facets")
                if kind:
                    self.assertEqual(raised.exception.kind, kind)

    async def test_response_size_and_missing_request_id(self):
        adapter = self.make_provider(response(evidence()))
        with patch.object(provider, "MAX_RESPONSE_BYTES", 1):
            with self.assertRaises(provider.ProviderFailure) as raised:
                await adapter.generate(evidence(), DEFAULT_RECIPE, "facets")
        self.assertEqual(raised.exception.kind, "response_too_large")
        self.assertTrue(raised.exception.ambiguous)
        adapter = self.make_provider(response(evidence()), headers={"x-request-id": "bad\nheader"})
        with self.assertRaises(provider.ProviderFailure) as raised:
            await adapter.generate(evidence(), DEFAULT_RECIPE, "facets")
        self.assertEqual(raised.exception.kind, "missing_request_id")

    def test_retry_after_is_bounded_and_nan_safe(self):
        self.assertEqual(provider._retry_after("0"), 1)
        self.assertEqual(provider._retry_after("999999"), 3600)
        for value in ("nan", "inf", "not a date", None):
            self.assertIsNone(provider._retry_after(value))

    async def test_borrowed_client_is_not_closed(self):
        adapter = self.make_provider({})
        await adapter.aclose()
        self.assertFalse(adapter._client.is_closed)

    def test_invalid_config_and_tokenizers_fail_before_submission(self):
        for key in ("", None, "bad key", "bad\x00key", "sk-☃"):
            with self.subTest(key=key), self.assertRaises(provider.ProviderFailure):
                provider.OpenAIUnderstandingProvider(key)
        for timeout in (True, "45", 0, float("nan"), 121):
            with self.subTest(timeout=timeout), self.assertRaises(provider.ProviderFailure):
                provider.OpenAIUnderstandingProvider("test", timeout_seconds=timeout)
        for count in (True, -1, 1.5):
            adapter = provider.OpenAIUnderstandingProvider("test", tokenizer=lambda *_: count)
            with self.subTest(count=count), self.assertRaises(provider.ProviderFailure) as raised:
                adapter.estimate_usd(evidence(), DEFAULT_RECIPE, "facets")
            self.assertEqual(raised.exception.kind, "invalid_tokenizer")


if __name__ == "__main__":
    unittest.main()
