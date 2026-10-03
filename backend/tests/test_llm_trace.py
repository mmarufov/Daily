"""Per-call LLM traces, the fallback tag, and the /llmz decision rule.

The OpenAI calls here go through the real `openai` SDK over an
`httpx.MockTransport`, so the 429 is parsed into `openai.RateLimitError` by the
SDK itself, from OpenAI's own `insufficient_quota` error body.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time

import sys

import httpx
import pytest

# Other test modules may have registered a stub `openai` first. Import the real
# SDK for this module's use, then put back whatever the others expect.
_registered = sys.modules.pop("openai", None)
import openai  # noqa: E402
if _registered is not None:
    sys.modules["openai"] = _registered

import tests._app_stubs  # noqa: E402,F401  (installs import-time stubs)

from app.services import llm_health, llm_trace  # noqa: E402
from app.services.openai_service import OpenAIService  # noqa: E402

PREREGISTERED_POLICY_SHA256 = "3481c5f142ecdc1bb76a49613ecbd3aa1b4c02b13f5f4cf9ee9cbc2ae10c5706"

QUOTA = {"error": {"message": "You exceeded your current quota.", "type": "insufficient_quota",
                   "param": None, "code": "insufficient_quota"}}
RATE = {"error": {"message": "Rate limit reached.", "type": "requests",
                  "param": None, "code": "rate_limit_exceeded"}}
SECRET_TEXT = "profile text that must never be stored"


def _embedding_ok(request):
    return httpx.Response(200, json={
        "object": "list", "model": "text-embedding-3-small",
        "data": [{"object": "embedding", "index": 0, "embedding": [0.5, 0.25]}],
        "usage": {"prompt_tokens": 1000, "total_tokens": 1000}})


def _chat(content, prompt_tokens=200, completion_tokens=100):
    def handler(request):
        return httpx.Response(200, json={
            "id": "c", "object": "chat.completion", "created": 0, "model": "gpt-4o-mini",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                      "total_tokens": prompt_tokens + completion_tokens}})
    return handler


def _status(status, body):
    return lambda request: httpx.Response(status, json=body)


def _service(handler) -> OpenAIService:
    service = OpenAIService.__new__(OpenAIService)
    service.model = service.scoring_model = "gpt-4o-mini"
    service.client = llm_trace.TracedOpenAI(openai.OpenAI(
        api_key="test", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    return service


@pytest.fixture(autouse=True)
def _empty_buffer():
    llm_trace.drain()
    yield
    llm_trace.drain()


def _records():
    return llm_trace.drain()


# ------------------------------------------------------------- pre-registration --

def test_policy_matches_the_preregistered_hash():
    digest = hashlib.sha256(llm_trace.POLICY_PATH.read_bytes()).hexdigest()
    assert digest == PREREGISTERED_POLICY_SHA256, (
        "llm_health_policy.json changed after pre-registration; thresholds are not tuned after a result")


def test_policy_prices_match_the_eval_price_table():
    from evals.llm_cache import PRICING

    for model, price in llm_trace.POLICY["pricing_usd_per_million_tokens"].items():
        assert (price["input"], price["output"]) == PRICING[model], model


# ---------------------------------------------------------------- classification --

def test_the_sdk_raises_a_classifiable_quota_error():
    client = openai.OpenAI(api_key="k", max_retries=0,
                           http_client=httpx.Client(transport=httpx.MockTransport(_status(429, QUOTA))))
    with pytest.raises(openai.RateLimitError) as raised:
        client.embeddings.create(model="text-embedding-3-small", input="x")
    assert llm_trace.classify(raised.value) == "insufficient_quota"
    assert llm_trace.describe(raised.value) == "RateLimitError:insufficient_quota:429"


def test_an_ordinary_rate_limit_is_not_a_quota_error():
    client = openai.OpenAI(api_key="k", max_retries=0,
                           http_client=httpx.Client(transport=httpx.MockTransport(_status(429, RATE))))
    with pytest.raises(openai.RateLimitError) as raised:
        client.embeddings.create(model="text-embedding-3-small", input="x")
    assert llm_trace.classify(raised.value) == "rate_limited"


@pytest.mark.parametrize("exc, outcome", [
    (asyncio.TimeoutError(), "timeout"),
    (json.JSONDecodeError("bad", "{", 0), "parse_error"),
    (KeyError("results"), "schema_invalid"),
    (RuntimeError("boom"), "other_error"),
])
def test_other_failures_are_classified(exc, outcome):
    assert llm_trace.classify(exc) == outcome


# ------------------------------------------------------------- records and tags --

def test_a_successful_embedding_is_traced_with_tokens_and_cost():
    service = _service(_embedding_ok)
    llm_trace.set_job("ingestion")
    try:
        vector = asyncio.run(service.generate_embedding(SECRET_TEXT))
    finally:
        llm_trace.set_job("request")
    assert vector == [0.5, 0.25]
    [record] = _records()
    assert (record.op, record.job, record.model) == ("generate_embedding", "ingestion", "text-embedding-3-small")
    assert (record.outcome, record.fallback) == ("ok", False)
    assert (record.tokens_in, record.cost_usd) == (1000, 0.00002)
    assert record.latency_ms is not None and len(record.prompt_sha256) == 64
    assert SECRET_TEXT not in json.dumps([str(v) for v in record.row()])


def test_a_quota_failure_is_tagged_as_a_fallback_where_it_is_swallowed():
    service = _service(_status(429, QUOTA))
    assert asyncio.run(service.generate_embedding("x")) is None
    [record] = _records()
    assert (record.outcome, record.fallback, record.error) == (
        "insufficient_quota", True, "RateLimitError:insufficient_quota:429")


def test_control_without_the_tag_the_same_failure_is_not_a_fallback(monkeypatch):
    monkeypatch.setattr(llm_trace.Scope, "fallback", lambda self, exc=None, *, outcome=None: None)
    service = _service(_status(429, QUOTA))
    assert asyncio.run(service.generate_embedding("x")) is None
    [record] = _records()
    assert (record.outcome, record.fallback) == ("insufficient_quota", False)


def test_a_fallback_with_no_call_still_counts():
    with llm_trace.scope("generate_embedding") as trace:
        trace.fallback(ValueError("OPENAI_API_KEY environment variable is not set"))
    [record] = _records()
    assert (record.op, record.outcome, record.fallback, record.model) == (
        "generate_embedding", "other_error", True, None)


def test_an_unusable_reply_is_a_schema_fallback_not_a_transport_error():
    service = _service(_chat('{"topics": [], "people": []}'))
    asyncio.run(service.extract_interests_from_profile("I like nothing in particular"))
    [record] = _records()
    assert (record.outcome, record.fallback, record.tokens_out) == ("schema_invalid", True, 100)
    assert record.cost_usd == round((200 * 0.15 + 100 * 0.6) / 1_000_000, 8)


def test_a_timeout_is_recorded_once_and_a_late_return_does_not_rewrite_it():
    release = {"done": False}

    def slow(**_kwargs):
        time.sleep(0.2)
        release["done"] = True
        return type("R", (), {"usage": None})()

    traced = llm_trace._Traced(lambda: slow, "chat")

    async def call():
        with llm_trace.scope("generate_briefing") as trace:
            try:
                await asyncio.wait_for(asyncio.to_thread(traced, model="gpt-4o-mini", messages=[]), 0.01)
            except asyncio.TimeoutError as exc:
                trace.fallback(exc)

    asyncio.run(call())
    while not release["done"]:
        time.sleep(0.01)
    time.sleep(0.05)
    [record] = _records()
    assert (record.outcome, record.fallback) == ("timeout", True)


def test_batch_scoring_tags_only_the_attempt_it_gave_up_on(monkeypatch):
    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    service = _service(_status(429, RATE))
    articles = [{"id": "a", "title": "t", "summary": "s"}]
    result = asyncio.run(service.score_articles_batch(articles, "Likes x."))
    assert result == [{"relevant": False, "score": 0.0, "reason": "scoring unavailable"}]
    records = _records()
    assert [r.outcome for r in records] == ["rate_limited"] * 3
    assert [r.fallback for r in records] == [False, False, True]


def test_a_wrong_count_of_scores_is_schema_invalid_but_served():
    service = _service(_chat(json.dumps({"results": [{"relevant": True, "score": 0.9, "reason": "r"}]})))
    articles = [{"id": "a", "title": "t", "summary": "s"}, {"id": "b", "title": "u", "summary": "s"}]
    asyncio.run(service.score_articles_batch(articles, "Likes x."))
    [record] = _records()
    assert (record.outcome, record.fallback) == ("schema_invalid", False)


def test_calls_outside_any_scope_are_still_traced():
    service = _service(_embedding_ok)
    service.client.embeddings.create(model="text-embedding-3-small", input="x")
    [record] = _records()
    assert (record.op, record.outcome, record.fallback) == ("embedding", "ok", False)


def test_the_buffer_is_bounded_and_counts_what_it_drops(monkeypatch):
    monkeypatch.setitem(llm_trace.POLICY, "trace_buffer_max", 3)
    before = llm_trace.dropped
    for _ in range(5):
        with llm_trace.scope("x") as trace:
            trace.fallback()
    assert len(_records()) == 3
    assert llm_trace.dropped - before == 2


def test_a_failed_flush_keeps_the_records():
    class Broken:
        def cursor(self):
            raise RuntimeError("database down")

    with llm_trace.scope("x") as trace:
        trace.fallback()
    with pytest.raises(RuntimeError):
        llm_trace.flush(Broken())
    assert llm_trace.pending_count() == 1


# ------------------------------------------------------------------- decision --

def _decide(rows, eligible=0, missing=0):
    return llm_health.decide(rows, {"eligible": eligible, "missing": missing})


def test_fallback_trips_above_the_rate_with_enough_calls():
    report = _decide([{"job": "ingestion", "calls": 20, "fallbacks": 5}])
    assert report["status"] == "tripped" and report["tripped"] == ["fallback:ingestion"]


def test_fallback_at_exactly_the_rate_does_not_trip():
    assert _decide([{"job": "ingestion", "calls": 100, "fallbacks": 20}])["status"] == "ok"


def test_too_few_calls_is_insufficient_data_not_a_trip():
    report = _decide([{"job": "request", "calls": 19, "fallbacks": 19}])
    assert report["status"] == "ok"
    assert report["fallback"]["jobs"]["request"]["state"] == "insufficient_data"


def test_coverage_trips_on_count_and_share_together():
    assert _decide([], eligible=100, missing=21)["tripped"] == ["embedding_coverage"]
    assert _decide([], eligible=100, missing=20)["status"] == "ok"
    assert _decide([], eligible=19, missing=19)["status"] == "ok"


def test_unevaluable_is_never_reported_healthy():
    assert llm_health.unevaluable("OperationalError")["status"] != "ok"
