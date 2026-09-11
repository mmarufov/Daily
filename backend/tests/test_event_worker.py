"""Offline worker lifecycle; SQL race guarantees require hosted PostgreSQL."""
import asyncio
from contextlib import contextmanager
import importlib
import sys
import threading
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

existing = sys.modules.get("httpx")
if not isinstance(existing, types.ModuleType) or not getattr(existing, "__spec__", None):
    sys.modules.pop("httpx", None)
importlib.import_module("httpx")

from app.services import event_worker
from app.services.event_worker import EventWorker
from app.services.event_provider import ProviderFailure


class StaleInput(ValueError):
    pass


class LeaseLost(Exception):
    pass


def fake_repository():
    def function(name):
        def operation(*args, **kwargs):
            return None
        operation.__name__ = name
        return operation
    names = ("check_schema", "ingest", "group", "prepare", "refinement_inputs", "reserve", "settle",
        "publish", "publish_refinement", "fail", "pause_provider", "defer_without_attempt",
        "consume_changes", "scan", "reap", "claim")
    return SimpleNamespace(**{name: function(name) for name in names}, StaleInput=StaleInput, LeaseLost=LeaseLost)


class Harness:
    def __init__(self, stage="assess"):
        self.calls = []
        self.job = {"id": "job-1", "stage": stage, "attempts": 1, "recipe_id": "recipe-1",
            "definition": {"provider": {"model": "assessment"}, "refinement_provider": {"model": "refinement"}}}
        self.frozen = {"event_id": "event-1"}
        self.prepared = SimpleNamespace(max_cost_usd=0.02, request_hash="a" * 64)
        self.outcome = SimpleNamespace(payload={"answer": "validated"}, usage_usd=0.01, request_id="req-1")
        self.provider = SimpleNamespace(prepare_request=Mock(return_value=self.prepared),
            prepare_refinement=Mock(return_value=self.prepared), generate_prepared=AsyncMock(return_value=self.outcome))
        self.repository = fake_repository()
        self.results = {"prepare": self.frozen, "reserve": "reservation", "refinement_inputs": ({"id": "evd-1"}, {"input": "frozen"}),
                        "claim": []}
        self.worker = EventWorker(None, self.provider, repository=self.repository)
        async def db(function, *args, **kwargs):
            self.calls.append((function.__name__, args, kwargs))
            result = self.results.get(function.__name__)
            if isinstance(result, BaseException):
                raise result
            return result
        self.worker.db = db

    def names(self):
        return [call[0] for call in self.calls]


@pytest.mark.parametrize("value", [True, False, 0, 17, -1, "4", 1.2])
def test_concurrency_must_be_bounded_integer(value):
    with pytest.raises(ValueError):
        EventWorker(None, None, concurrency=value)


@pytest.mark.asyncio
async def test_assessment_reserves_exact_hash_settles_then_publishes():
    h = Harness()
    await h.worker.process(h.job)
    assert h.names() == ["prepare", "reserve", "settle", "publish"]
    h.provider.prepare_request.assert_called_once_with(h.frozen, {"model": "assessment", "recipe_id": "recipe-1"})
    h.provider.generate_prepared.assert_awaited_once_with(h.prepared)
    assert h.calls[1][1] == (h.job, 0.02, "a" * 64)
    assert h.calls[2][1] == ("reservation", 0.01, "req-1")
    assert h.calls[3][1] == (h.job, h.frozen, h.outcome.payload)


@pytest.mark.asyncio
async def test_refinement_uses_separate_configuration_and_publication():
    h = Harness("refine")
    await h.worker.process(h.job)
    assert h.names() == ["prepare", "refinement_inputs", "reserve", "settle", "publish_refinement"]
    h.provider.prepare_refinement.assert_called_once_with(*h.results["refinement_inputs"],
        {"model": "refinement", "recipe_id": "recipe-1"})
    h.provider.prepare_request.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["ingest", "group"])
async def test_pure_stages_never_reserve_or_call_provider(stage):
    h = Harness(stage)
    await h.worker.process(h.job)
    assert h.names() == [stage]
    h.provider.generate_prepared.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["invalid", "assess", "refine"])
async def test_missing_configuration_or_unknown_stage_fails_without_spend(stage):
    h = Harness(stage)
    h.job["definition"] = {}
    await h.worker.process(h.job)
    assert h.names()[-1] == "fail"
    assert h.calls[-1][2]["retryable"] is False
    assert "reserve" not in h.names()
    h.provider.generate_prepared.assert_not_awaited()


@pytest.mark.asyncio
async def test_superseded_preparation_never_reserves():
    h = Harness()
    h.results["prepare"] = None
    await h.worker.process(h.job)
    assert h.names() == ["prepare"]


@pytest.mark.asyncio
async def test_budget_pause_defers_without_consuming_attempt_or_calling():
    h = Harness()
    h.results["reserve"] = None
    await h.worker.process(h.job)
    assert h.names() == ["prepare", "reserve", "defer_without_attempt"]
    assert h.calls[-1][2] == {"delay": 300}
    h.provider.generate_prepared.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure,settlement", [
    (ProviderFailure("timeout", ambiguous=True, retryable=True), None),
    (ProviderFailure("invalid_response", usage_usd=0.015, request_id="req-bad"), ("reservation", 0.015, "req-bad")),
    (ProviderFailure("known_rejection", ambiguous=False), ("reservation", 0, None)),
])
async def test_failure_settlement_does_not_release_ambiguous_charges(failure, settlement):
    h = Harness()
    h.provider.generate_prepared.side_effect = failure
    await h.worker.process(h.job)
    settlements = [call[1] for call in h.calls if call[0] == "settle"]
    assert settlements == ([] if settlement is None else [settlement])
    assert h.calls[-1][1] == (h.job, "provider_failure")
    assert "publish" not in h.names()


@pytest.mark.asyncio
async def test_provider_circuit_and_job_failure_are_separate_bounded_operations():
    h = Harness()
    h.provider.generate_prepared.side_effect = ProviderFailure("private-provider-message", provider_wide=True,
        retryable=True, ambiguous=True, retry_after=float("inf"))
    h.job["attempts"] = 10**8
    await h.worker.process(h.job)
    assert h.names() == ["prepare", "reserve", "pause_provider", "fail"]
    assert h.calls[-2][1] == ("provider_failure",)
    assert h.calls[-1][2] == {"retryable": True, "retry_after": 3600}


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,error,expected", [
    ("prepare", StaleInput("private"), "input_changed"),
    ("prepare", ValueError("private"), "contract_invalid"),
    ("publish", StaleInput("private"), "input_changed"),
    ("prepare", RuntimeError("private database body"), "internal_failure"),
])
async def test_stale_validation_and_unexpected_errors_use_safe_categories(phase, error, expected, caplog):
    h = Harness()
    h.results[phase] = error
    await h.worker.process(h.job)
    assert h.calls[-1][1] == (h.job, expected)
    assert "private" not in caplog.text


@pytest.mark.asyncio
async def test_lost_lease_does_not_publish_or_modify_another_attempt():
    h = Harness()
    h.results["prepare"] = LeaseLost()
    await h.worker.process(h.job)
    assert h.names() == ["prepare"]


@pytest.mark.asyncio
async def test_cancellation_during_network_keeps_reservation_and_lease():
    h = Harness()
    entered = asyncio.Event()
    async def network(_):
        entered.set()
        await asyncio.Event().wait()
    h.provider.generate_prepared.side_effect = network
    task = asyncio.create_task(h.worker.process(h.job))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert h.names() == ["prepare", "reserve"]


@pytest.mark.asyncio
async def test_settlement_database_outage_does_not_publish_or_dispatch_twice():
    h = Harness()
    h.results["settle"] = RuntimeError("private")
    await h.worker.process(h.job)
    assert h.names() == ["prepare", "reserve", "settle", "fail"]
    h.provider.generate_prepared.assert_awaited_once()


@pytest.mark.asyncio
async def test_tick_runs_gap_recovery_before_fair_bounded_claim():
    h = Harness("ingest")
    h.results["claim"] = [h.job]
    assert await h.worker.tick() == 1
    assert h.names() == ["consume_changes", "scan", "reap", "claim", "ingest"]
    assert h.calls[3][2] == {"limit": 4}


@pytest.mark.asyncio
async def test_stop_cancels_provider_and_drains_children():
    h = Harness()
    h.results["claim"] = [h.job]
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    async def network(_):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    h.provider.generate_prepared.side_effect = network
    running = asyncio.create_task(h.worker.run())
    await entered.wait()
    h.worker.stop.set()
    await asyncio.wait_for(running, 1)
    assert cancelled.is_set()
    assert "settle" not in h.names() and "publish" not in h.names()


@pytest.mark.asyncio
async def test_tick_error_cancels_siblings_before_returning():
    h = Harness()
    h.results["claim"] = [{"id": "fail"}, {"id": "wait"}]
    waiting = asyncio.Event()
    drained = asyncio.Event()
    async def process(job):
        if job["id"] == "fail":
            await waiting.wait()
            raise RuntimeError("database unavailable")
        waiting.set()
        try:
            await asyncio.Event().wait()
        finally:
            drained.set()
    h.worker.process = process
    with pytest.raises(RuntimeError):
        await h.worker.tick()
    assert drained.is_set()


class Pool:
    def __init__(self):
        self.active = 0
        self.checkouts = 0

    @contextmanager
    def connection(self):
        self.active += 1
        self.checkouts += 1
        try:
            yield object()
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_real_checkout_adapter_releases_connection_before_network():
    h = Harness()
    pool = Pool()
    def function(name):
        def operation(conn, *args, **kwargs):
            assert pool.active == 1
            return h.results.get(name)
        return operation
    for name in ("prepare", "reserve", "settle", "publish"):
        setattr(h.repository, name, function(name))
    h.worker = EventWorker(pool, h.provider, repository=h.repository)
    async def network(_):
        assert pool.active == 0
        return h.outcome
    h.provider.generate_prepared.side_effect = network
    await h.worker.process(h.job)
    assert pool.active == 0 and pool.checkouts == 4


@pytest.mark.asyncio
async def test_cancelled_database_thread_is_drained_before_checkout_release():
    pool = Pool()
    worker = EventWorker(pool, None, repository=fake_repository())
    entered = threading.Event()
    release = threading.Event()
    def operation(conn):
        entered.set()
        assert release.wait(2)
    task = asyncio.create_task(worker.db(operation))
    assert await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()  # repeated shutdown must not orphan an in-flight DB thread
    await asyncio.sleep(0)
    assert pool.active == 1 and not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pool.active == 0


@pytest.mark.asyncio
async def test_entrypoint_disabled_by_default_never_opens_provider_or_pool(monkeypatch):
    monkeypatch.delenv("S4_WORKER_ENABLED", raising=False)
    monkeypatch.setattr(event_worker, "OpenAIEventProvider", Mock(side_effect=AssertionError("provider opened")))
    monkeypatch.setitem(sys.modules, "dotenv", SimpleNamespace(load_dotenv=lambda: None))
    await event_worker.main()
