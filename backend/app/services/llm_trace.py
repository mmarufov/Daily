"""Per-call traces for every OpenAI SDK call, and the fallback tag.

`TracedOpenAI` wraps the SDK client so each `chat.completions.create` and
`embeddings.create` produces one `CallRecord`: job, operation, model, request
hash, tokens, cost, latency and outcome. Request and response text are never
stored.

The wrapper sees whether a call raised, not what the application did next.
The application decides whether to serve a fallback (a `None` vector, keyword
scores, a heuristic profile), so the fallback flag is set at that site:

    with llm_trace.scope("generate_embedding") as trace:
        try:
            response = await asyncio.to_thread(self.client.embeddings.create, ...)
        except Exception as exc:
            trace.fallback(exc)
            return None

`asyncio.to_thread` copies the caller's context into the worker thread, so the
wrapper running there finds the caller's scope and attaches its record to it.
Records leave a scope only when it exits, after any fallback tag, and are
buffered per process until `flush` writes them with `ON CONFLICT DO NOTHING`.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator

logger = logging.getLogger(__name__)

POLICY_PATH = Path(__file__).with_name("llm_health_policy.json")
POLICY: dict = json.loads(POLICY_PATH.read_text())

OUTCOMES = ("ok", "rate_limited", "insufficient_quota", "timeout",
            "parse_error", "schema_invalid", "other_error")
_PENDING = "pending"

GIT_SHA = (
    os.getenv("GIT_SHA")
    or os.getenv("RAILWAY_GIT_COMMIT_SHA")
    or os.getenv("FLY_MACHINE_VERSION")
    or "unknown"
)[:40]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


#: Replaced by the replay test to freeze and advance time.
clock: Callable[[], datetime] = _utcnow

_job: contextvars.ContextVar[str] = contextvars.ContextVar("llm_job", default="request")
_scope: contextvars.ContextVar["Scope | None"] = contextvars.ContextVar("llm_scope", default=None)


@dataclass
class CallRecord:
    op: str
    job: str
    model: str | None
    prompt_sha256: str | None
    ts: datetime = field(default_factory=lambda: clock())
    call_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None
    outcome: str = _PENDING
    fallback: bool = False
    error: str | None = None
    git_sha: str = GIT_SHA
    started: float = field(default_factory=time.monotonic, repr=False)

    def row(self) -> tuple:
        return (self.call_id, self.ts, self.job, self.op, self.model, self.prompt_sha256,
                self.tokens_in, self.tokens_out, self.cost_usd, self.latency_ms,
                self.outcome, self.fallback, self.error, self.git_sha)


# ------------------------------------------------------------------ outcomes --

def classify(exc: BaseException) -> str:
    """Map an exception to an outcome. OpenAI's classes are matched by name
    along the MRO: test modules replace the `openai` module with stubs, and an
    isinstance check against whichever module is loaded would miss them."""
    names = {cls.__name__ for cls in type(exc).__mro__}
    if "RateLimitError" in names:
        body = getattr(exc, "body", None)
        kind = body.get("type") if isinstance(body, dict) else None
        if "insufficient_quota" in (getattr(exc, "code", None), kind):
            return "insufficient_quota"
        return "rate_limited"
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "APITimeoutError" in names:
        return "timeout"
    if isinstance(exc, json.JSONDecodeError):
        return "parse_error"
    if isinstance(exc, (KeyError, IndexError, TypeError)):
        return "schema_invalid"
    return "other_error"


def describe(exc: BaseException) -> str:
    """Class, provider code and status only. Messages can quote model output."""
    parts = [type(exc).__name__]
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if value is not None:
            parts.append(str(value))
    return ":".join(parts)[:200]


# ------------------------------------------------------------------- buffer --

_lock = threading.Lock()
_buffer: list[CallRecord] = []
dropped = 0


def _enqueue(records: list[CallRecord]) -> None:
    global dropped
    if not records:
        return
    with _lock:
        _buffer.extend(records)
        overflow = len(_buffer) - int(POLICY["trace_buffer_max"])
        if overflow > 0:
            del _buffer[:overflow]
            dropped += overflow


def pending_count() -> int:
    with _lock:
        return len(_buffer)


#: A call still in flight after this long is written as a timeout, so a hung
#: thread cannot hold its record in the buffer forever.
STALE_PENDING_SECONDS = 600


def drain() -> list[CallRecord]:
    """Remove and return every finished record. A record whose call is still in
    flight (its scope exited on a timeout) stays until the call returns."""
    now = time.monotonic()
    with _lock:
        for record in _buffer:
            if record.outcome == _PENDING and now - record.started > STALE_PENDING_SECONDS:
                record.outcome = "timeout"
                record.latency_ms = int((now - record.started) * 1000)
        ready = [r for r in _buffer if r.outcome != _PENDING]
        _buffer[:] = [r for r in _buffer if r.outcome == _PENDING]
    return ready


# -------------------------------------------------------------------- scope --

class Scope:
    def __init__(self, op: str):
        self.op = op
        self.calls: list[CallRecord] = []
        self.closed = False

    def fallback(self, exc: BaseException | None = None, *, outcome: str | None = None) -> CallRecord:
        """Mark the scope's latest call as answered by a fallback.

        With no call recorded (the client could not be built, or the failure
        came before the request), a record is created so the fallback still
        counts. A call still in flight, abandoned by a timeout, takes the
        timeout outcome now; the worker thread fills in tokens if it returns."""
        if outcome is not None and outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        if self.calls:
            record = self.calls[-1]
        else:
            record = CallRecord(op=self.op, job=_job.get(), model=None, prompt_sha256=None)
            self.calls.append(record)
        record.fallback = True
        if outcome is not None:
            record.outcome = outcome
        elif record.outcome in (_PENDING, "ok"):
            record.outcome = classify(exc) if exc is not None else "other_error"
        if record.latency_ms is None:
            record.latency_ms = int((time.monotonic() - record.started) * 1000)
        if exc is not None and record.error is None:
            record.error = describe(exc)
        return record


    def failed(self, exc: BaseException) -> None:
        """Record a failed attempt the caller is about to retry. Not a fallback."""
        if self.calls and self.calls[-1].outcome in (_PENDING, "ok"):
            record = self.calls[-1]
            record.outcome = classify(exc)
            record.error = record.error or describe(exc)
            if record.latency_ms is None:
                record.latency_ms = int((time.monotonic() - record.started) * 1000)

    def mark(self, outcome: str) -> None:
        """Downgrade the latest call's outcome when its reply was unusable as
        returned (a wrong count of results), without calling it a fallback."""
        if outcome not in OUTCOMES:
            raise ValueError(f"unknown outcome {outcome!r}")
        if self.calls:
            self.calls[-1].outcome = outcome


@contextmanager
def scope(op: str) -> Iterator[Scope]:
    current = Scope(op)
    token = _scope.set(current)
    try:
        yield current
    finally:
        _scope.reset(token)
        current.closed = True
        _enqueue(current.calls)


def set_job(name: str) -> None:
    """Label every call made from the current task (and the tasks and threads
    it starts) with a job name. Call once at the top of a loop."""
    _job.set(name)


# ------------------------------------------------------------------ wrapper --

def _request_hash(kwargs: dict) -> str:
    material = {k: kwargs.get(k) for k in ("model", "messages", "input", "response_format", "tools")
                if k in kwargs}
    blob = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cost_usd(model: str | None, tokens_in: int | None, tokens_out: int | None) -> float | None:
    price = POLICY["pricing_usd_per_million_tokens"].get(model or "")
    if price is None or tokens_in is None:
        return None
    return round((tokens_in * price["input"] + (tokens_out or 0) * price["output"]) / 1_000_000, 8)


class _Traced:
    def __init__(self, resolve: Callable[[], Callable], kind: str):
        self._resolve = resolve
        self._kind = kind

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        active = _scope.get()
        if active is not None and active.closed:
            # A thread the executor started after its caller gave up.
            active = None
        op = active.op if active is not None else self._kind
        if kwargs.get("stream"):
            op += ".stream"
        record = CallRecord(op=op, job=_job.get(), model=kwargs.get("model"),
                            prompt_sha256=_request_hash(kwargs))
        if active is not None:
            active.calls.append(record)
        try:
            response = self._resolve()(*args, **kwargs)
        except BaseException as exc:
            if record.outcome == _PENDING:
                record.outcome = classify(exc)
                record.error = describe(exc)
            raise
        else:
            if record.outcome == _PENDING:
                record.outcome = "ok"
            usage = getattr(response, "usage", None)
            if usage is not None:
                record.tokens_in = getattr(usage, "prompt_tokens", None)
                record.tokens_out = getattr(usage, "completion_tokens", None)
            record.cost_usd = cost_usd(record.model, record.tokens_in, record.tokens_out)
            return response
        finally:
            if record.latency_ms is None:
                record.latency_ms = int((time.monotonic() - record.started) * 1000)
            if active is None:
                _enqueue([record])


class TracedOpenAI:
    """Drop-in for `openai.OpenAI`: traced `chat.completions.create` and
    `embeddings.create`; everything else passes through."""

    def __init__(self, client: Any):
        self._client = client
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=_Traced(lambda: client.chat.completions.create, "chat")))
        self.embeddings = SimpleNamespace(
            create=_Traced(lambda: client.embeddings.create, "embedding"))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


# ----------------------------------------------------------------- database --

DDL = (
    """
    CREATE TABLE IF NOT EXISTS public.llm_calls (
        call_id uuid PRIMARY KEY,
        ts timestamptz NOT NULL,
        job text NOT NULL,
        op text NOT NULL,
        model text,
        prompt_sha256 text,
        tokens_in integer,
        tokens_out integer,
        cost_usd numeric(14, 8),
        latency_ms integer,
        outcome text NOT NULL CHECK (outcome IN
            ('ok', 'rate_limited', 'insufficient_quota', 'timeout',
             'parse_error', 'schema_invalid', 'other_error')),
        fallback boolean NOT NULL,
        error text,
        git_sha text NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_llm_calls_ts ON public.llm_calls (ts DESC)",
)

_INSERT = """
    INSERT INTO public.llm_calls
        (call_id, ts, job, op, model, prompt_sha256, tokens_in, tokens_out,
         cost_usd, latency_ms, outcome, fallback, error, git_sha)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (call_id) DO NOTHING
"""


def ensure_table(conn) -> None:
    with conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)


def flush(conn) -> int:
    """Write every finished record. On failure the records go back to the
    buffer; a retried write of the same call is a no-op on `call_id`."""
    records = drain()
    if not records:
        return 0
    try:
        with conn.cursor() as cur:
            cur.executemany(_INSERT, [r.row() for r in records])
    except Exception:
        _enqueue(records)
        raise
    return len(records)


def prune(conn, *, now: datetime | None = None) -> int:
    cutoff = (now or clock()) - timedelta(days=int(POLICY["trace_retention_days"]))
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.llm_calls WHERE ts < %s", (cutoff,))
        return max(cur.rowcount, 0)
