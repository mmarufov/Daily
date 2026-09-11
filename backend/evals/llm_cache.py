"""Content-addressed cache for every OpenAI call the evaluation makes.

Reproducibility is the whole point of S0. A run that costs money and returns a
different verdict each time cannot be a regression gate. So every chat completion
and embedding request is keyed by a hash of its full request and stored on disk;
a repeated request never touches the network. The cache directory is committed,
which is what lets CI run the gate with no API key at all (`EVAL_OFFLINE=1`).

`CachingOpenAI` is a drop-in for `openai.OpenAI` for the two surfaces the app and
the evals use: `.chat.completions.create(...)` and `.embeddings.create(...)`.
Production's `OpenAIService` only ever calls those through `self.client`, so
swapping `svc.client` for this object replays the real scorer for free.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

CACHE_LLM = Path(__file__).resolve().parent / ".cache" / "llm"

PRICING = {                       # USD per 1M tokens (input, output)
    "text-embedding-3-small": (0.02, 0.0),
    "gpt-4.1-nano":           (0.10, 0.40),
    "gpt-4.1-mini":           (0.40, 1.60),
    "gpt-4.1":                (2.00, 8.00),
    "gpt-4o-mini":            (0.15, 0.60),
    "gpt-4o":                 (2.50, 10.00),
    "o3":                     (2.00, 8.00),
    "o4-mini":                (1.10, 4.40),
    # Explicit snapshots, not prefix matching. Verified against OpenAI's model
    # pages and https://openai.com/index/gpt-4-1/ on 2026-09-05.
    "gpt-4.1-mini-2025-04-14": (0.40, 1.60),
    "gpt-4.1-nano-2025-04-14": (0.10, 0.40),
    "gpt-4.1-2025-04-14":     (2.00, 8.00),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
}


class CacheMiss(RuntimeError):
    """Raised in offline mode when a request has no cached response."""

    def __init__(self, key: str, preview: str):
        super().__init__(
            f"LLM cache miss in offline mode (key {key[:12]}…). "
            f"Re-warm with an API key and commit evals/.cache/llm. Prompt: {preview!r}"
        )
        self.key = key


class BudgetExceeded(RuntimeError):
    pass


class UnknownModelPricing(ValueError):
    pass


def token_cost(model: str, prompt_tokens: int, completion_tokens: int = 0) -> float:
    if model not in PRICING:
        raise UnknownModelPricing(f"No explicit price registered for {model!r}")
    if any(type(n) is not int or n < 0 for n in (prompt_tokens, completion_tokens)):
        raise ValueError("Token counts must be nonnegative integers")
    pin, pout = PRICING[model]
    return (prompt_tokens * pin + completion_tokens * pout) / 1e6


class Meter:
    """Running cost meter with an optional hard budget."""

    def __init__(self, budget_usd: float | None = None):
        if budget_usd is not None and (not math.isfinite(budget_usd) or budget_usd < 0):
            raise ValueError("Budget must be finite and nonnegative")
        self.calls = 0
        self.usd = 0.0
        self.by_model: dict[str, float] = {}
        self.budget_usd = budget_usd
        self._lock = threading.Lock()
        self._reservations: dict[int, float] = {}
        self._next_reservation = 0

    @property
    def reserved_usd(self) -> float:
        with self._lock:
            return sum(self._reservations.values())

    def reserve(self, model: str, prompt_tokens: int, completion_tokens: int = 0) -> int:
        """Reserve before network I/O. Ambiguous failures retain the reservation.

        This meter coordinates threads within one benchmark process. Production
        and multiprocess workers must use the durable database budget ledger.
        """
        cost = token_cost(model, prompt_tokens, completion_tokens)
        with self._lock:
            projected = self.usd + sum(self._reservations.values()) + cost
            if self.budget_usd is not None and projected > self.budget_usd:
                raise BudgetExceeded(f"request reservation would exceed budget ${self.budget_usd:.6f}")
            self._next_reservation += 1
            self._reservations[self._next_reservation] = cost
            return self._next_reservation

    def add(self, model: str, prompt_tokens: int, completion_tokens: int = 0,
            *, reservation: int | None = None) -> float:
        cost = token_cost(model, prompt_tokens, completion_tokens)
        with self._lock:
            if reservation is not None:
                if reservation not in self._reservations:
                    raise ValueError("Unknown or already settled reservation")
                del self._reservations[reservation]
            self.calls += 1
            self.usd += cost
            self.by_model[model] = self.by_model.get(model, 0.0) + cost
            over = self.budget_usd is not None and self.usd + sum(self._reservations.values()) > self.budget_usd
        if over:
            raise BudgetExceeded(f"spend ${self.usd:.2f} exceeded budget ${self.budget_usd:.2f}")
        return cost

    def report(self) -> str:
        parts = ", ".join(f"{m} ${c:.4f}" for m, c in sorted(self.by_model.items()))
        return f"{self.calls} calls, ${self.usd:.4f} total  ({parts})"

    def snapshot(self) -> tuple[int, float]:
        with self._lock:
            return self.calls, self.usd


def cache_key(kind: str, **request: Any) -> str:
    blob = json.dumps({"kind": kind, **request}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _to_ns(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_ns(v) for v in obj]
    return obj


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}.{threading.get_ident()}")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _preview(messages: Any) -> str:
    try:
        for m in reversed(messages):
            if m.get("role") == "user":
                return str(m.get("content", ""))[:200]
    except Exception:
        pass
    return ""


class _Chat:
    def __init__(self, owner: "CachingOpenAI"):
        self.completions = SimpleNamespace(create=owner._chat_create)


class CachingOpenAI:
    """Drop-in for `openai.OpenAI` exposing `.chat.completions.create` and `.embeddings.create`."""

    def __init__(self, real: Any = None, cache_dir: Path = CACHE_LLM,
                 meter: Meter | None = None, offline: bool | None = None,
                 api_key: str | None = None):
        self._real = real
        self._api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.meter = meter or Meter()
        self.offline = bool(os.getenv("EVAL_OFFLINE")) if offline is None else offline
        self.hits = 0
        self.misses = 0
        self.touched: set[str] = set()
        self.chat = _Chat(self)
        self.embeddings = SimpleNamespace(create=self._embed_create)

    # -- real client -------------------------------------------------------
    def real(self) -> Any:
        if self._real is None:
            if self.offline:
                raise RuntimeError("offline mode: real OpenAI client must not be constructed")
            from openai import OpenAI  # imported lazily so tests can run without the SDK
            key = self._api_key or os.getenv("OPENAI_API_KEY")
            if not key or key == "offline-cache-only":
                raise RuntimeError("OPENAI_API_KEY is not set and the request is not cached")
            self._real = OpenAI(api_key=key)
        return self._real

    def _path(self, key: str, suffix: str) -> Path:
        return self.cache_dir / key[:2] / f"{key}{suffix}"

    def _reserve_request(self, kind: str, request: dict) -> int:
        model = request.get("model", "")
        token_cost(model, 0)  # Fail on unknown pricing before constructing a client.
        prompt_bound = completion_bound = 0
        if self.meter.budget_usd is not None:
            # UTF-8 bytes conservatively bound text tokens; extra framing/schema
            # overhead is intentionally overreserved, then settled from usage.
            if kind == "chat":
                for message in request.get("messages", []):
                    if not isinstance(message.get("content"), str):
                        raise ValueError("Budgeted cache calls support text-only messages")
                output_limit = request.get("max_completion_tokens", request.get("max_tokens"))
                count = request.get("n", 1)
                if type(output_limit) is not int or output_limit <= 0 or type(count) is not int or count <= 0:
                    raise ValueError("Budgeted chat requests require a positive explicit output token limit")
                completion_bound = output_limit * count
                prompt_bound = len(json.dumps(request, ensure_ascii=False).encode()) + 1024
            else:
                inputs = request.get("input")
                if isinstance(inputs, str):
                    prompt_bound = len(inputs.encode())
                elif isinstance(inputs, list) and all(isinstance(x, str) for x in inputs):
                    prompt_bound = sum(len(x.encode()) for x in inputs)
                elif isinstance(inputs, list) and all(type(x) is int for x in inputs):
                    prompt_bound = len(inputs)
                elif isinstance(inputs, list) and all(isinstance(x, list) and all(type(t) is int for t in x) for x in inputs):
                    prompt_bound = sum(len(x) for x in inputs)
                else:
                    raise ValueError("Unsupported embedding input for budget reservation")
        return self.meter.reserve(model, prompt_bound, completion_bound)

    # -- chat ----------------------------------------------------------------
    def _chat_create(self, **kw: Any) -> Any:
        if kw.get("stream"):
            raise NotImplementedError("streaming responses are not cacheable")
        key = cache_key("chat", **kw)
        self.touched.add(key)
        path = self._path(key, ".json")
        if path.exists():
            stored = json.loads(path.read_text())
            self.hits += 1
            u = stored.get("usage") or {}
            self.meter.add(stored.get("model", kw.get("model", "")),
                           int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
            return _to_ns({"choices": stored["choices"], "usage": u, "model": stored.get("model")})

        if self.offline:
            raise CacheMiss(key, _preview(kw.get("messages")))

        reservation = self._reserve_request("chat", kw)
        r = self.real().chat.completions.create(**kw)
        self.misses += 1
        usage = {"prompt_tokens": int(getattr(r.usage, "prompt_tokens", 0) or 0),
                 "completion_tokens": int(getattr(r.usage, "completion_tokens", 0) or 0)}
        choices = [{"message": {"role": c.message.role, "content": c.message.content},
                    "finish_reason": getattr(c, "finish_reason", None)} for c in r.choices]
        model = getattr(r, "model", None) or kw.get("model", "")
        # Billed under the requested model name; the API may echo a dated alias.
        self.meter.add(kw.get("model", model), usage["prompt_tokens"], usage["completion_tokens"],
                       reservation=reservation)
        request_meta = {k: v for k, v in kw.items() if k != "messages"}
        request_meta["messages_sha256"] = hashlib.sha256(
            json.dumps(kw.get("messages"), sort_keys=True, default=str).encode()).hexdigest()
        request_meta["preview"] = _preview(kw.get("messages"))
        _atomic_write_bytes(path, json.dumps({
            "request": request_meta, "model": kw.get("model", model),
            "choices": choices, "usage": usage,
        }, ensure_ascii=False, indent=1).encode())
        return _to_ns({"choices": choices, "usage": usage, "model": model})

    # -- embeddings ------------------------------------------------------------
    def _embed_create(self, **kw: Any) -> Any:
        import numpy as np

        key = cache_key("embed", **kw)
        self.touched.add(key)
        npy = self._path(key, ".npy")
        meta_path = self._path(key, ".json")
        if npy.exists() and meta_path.exists():
            meta = json.loads(meta_path.read_text())
            mat = np.load(npy).astype(np.float32)
            self.hits += 1
            self.meter.add(kw.get("model", ""), int(meta.get("prompt_tokens", 0)))
            return _to_ns({"data": [{"embedding": row.tolist(), "index": i} for i, row in enumerate(mat)],
                           "usage": {"prompt_tokens": meta.get("prompt_tokens", 0)},
                           "model": kw.get("model")})

        if self.offline:
            inp = kw.get("input")
            first = inp[0] if isinstance(inp, list) and inp else inp
            raise CacheMiss(key, str(first)[:200])

        reservation = self._reserve_request("embed", kw)
        r = self.real().embeddings.create(**kw)
        self.misses += 1
        prompt_tokens = int(getattr(r.usage, "prompt_tokens", 0) or 0)
        self.meter.add(kw.get("model", ""), prompt_tokens, reservation=reservation)
        # Stored at float16; hand back the same rounded values now so the run that
        # warmed the cache and every later cold run see identical vectors.
        mat = np.asarray([d.embedding for d in r.data], dtype=np.float32).astype(np.float16).astype(np.float32)
        import io
        buf = io.BytesIO()
        np.save(buf, mat.astype(np.float16))
        _atomic_write_bytes(npy, buf.getvalue())
        _atomic_write_bytes(meta_path, json.dumps({
            "model": kw.get("model"), "n": int(mat.shape[0]), "dim": int(mat.shape[1]),
            "prompt_tokens": prompt_tokens,
        }).encode())
        return _to_ns({"data": [{"embedding": row.tolist(), "index": i} for i, row in enumerate(mat)],
                       "usage": {"prompt_tokens": prompt_tokens}, "model": kw.get("model")})

    def stats(self) -> dict:
        return {"cache_hits": self.hits, "cache_misses": self.misses,
                "calls": self.meter.calls, "cost_usd": round(self.meter.usd, 6),
                "reserved_usd": round(self.meter.reserved_usd, 6)}


class CachingUnderstandingProvider:
    """Exact-wire-request S3 cache with a durable, cross-process pilot budget.

    A paid cache miss requires an explicit budget of at most $5. The budget is
    fixed for the ledger's lifetime; cached replay never spends it. A crash or
    ambiguous bill leaves its reservation charged. A request already attempted
    without a complete cache record is blocked pending operator reconciliation.
    Provider failures are replayed too: no silent retry spends outside this cap.
    """

    def __init__(self, provider: Any, *, cache_dir: Path, budget_usd: float | None = None,
                 offline: bool = True, ledger_dir: Path | None = None):
        if budget_usd is not None and (isinstance(budget_usd, bool) or not math.isfinite(budget_usd)
                                       or not 0 < budget_usd <= 5):
            raise ValueError("An explicit finite pilot budget in (0, 5] USD is required")
        self.provider = provider
        self.cache_dir = Path(cache_dir)
        self.ledger_dir = Path(ledger_dir) if ledger_dir is not None else self.cache_dir
        self.budget_usd = budget_usd
        self.offline = offline
        self.hits = 0
        self.misses = 0
        self.touched: set[str] = set()

    def estimate_usd(self, bundle: dict, recipe: dict, stage: str) -> float:
        return self.provider.estimate_usd(bundle, recipe, stage)

    def budget_report(self) -> dict:
        """Read durable aggregate spend, including ambiguous charges, without I/O to providers."""
        path = self.ledger_dir / "pilot-budget.json"
        ledger = json.loads(path.read_text()) if path.exists() else {
            "budget_usd": self.budget_usd, "spent_usd": 0.0, "requests": {}}
        held = sum(record["reserved_usd"] for record in ledger["requests"].values())
        return {"budget_usd": ledger["budget_usd"], "spent_usd": ledger["spent_usd"],
                "reserved_usd": held, "maximum_committed_usd": ledger["spent_usd"] + held,
                "attempted_requests": len(ledger["requests"]), "halted": ledger.get("halted", False)}

    def _ledger(self, mutate):
        # A separate stable lock inode survives atomic ledger replacements.
        import fcntl
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        with (self.ledger_dir / "pilot-budget.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = self.ledger_dir / "pilot-budget.json"
            ledger = json.loads(path.read_text()) if path.exists() else {
                "schema_version": 1, "budget_usd": self.budget_usd, "spent_usd": 0.0, "requests": {}}
            if ledger["budget_usd"] != self.budget_usd:
                raise ValueError("Pilot budget cannot change while reusing a ledger")
            result = mutate(ledger)
            _atomic_write_bytes(path, json.dumps(ledger, allow_nan=False, sort_keys=True).encode())
            return result

    def _reserve(self, key: str, estimate: float) -> str:
        if self.budget_usd is None:
            raise BudgetExceeded("Paid S3 cache misses require an explicit pilot budget")
        if isinstance(estimate, bool) or not math.isfinite(estimate) or estimate <= 0:
            raise ValueError("Provider reservation must be finite and positive")
        token = uuid.uuid4().hex

        def reserve(ledger):
            if ledger.get("halted"):
                raise BudgetExceeded("S3 pilot ledger halted after a provider bound violation")
            if key in ledger["requests"]:
                raise BudgetExceeded("Request already attempted; reconcile its missing cache or uncertain charge")
            held = sum(item["reserved_usd"] for item in ledger["requests"].values())
            if ledger["spent_usd"] + held + estimate > self.budget_usd:
                raise BudgetExceeded("S3 pilot budget would be exceeded before provider submission")
            ledger["requests"][key] = {"token": token, "reserved_usd": estimate, "state": "reserved"}
        self._ledger(reserve)
        return token

    def _settle(self, key: str, token: str, actual: float | None) -> None:
        if actual is None:
            return  # Unknown billing keeps its worst-case pre-call reservation.
        if isinstance(actual, bool) or not math.isfinite(actual) or actual < 0:
            raise ValueError("Provider reported invalid cost")

        def settle(ledger):
            record = ledger["requests"][key]
            if record["token"] != token or record["state"] != "reserved":
                raise ValueError("Unknown or already settled pilot reservation")
            reserved = record["reserved_usd"]
            record.update(state="settled", reserved_usd=0, usage_usd=actual)
            ledger["spent_usd"] += actual
            exceeded = actual > reserved or ledger["spent_usd"] > ledger["budget_usd"]
            ledger["halted"] = ledger.get("halted", False) or exceeded
            return exceeded
        exceeded = self._ledger(settle)
        if exceeded:
            raise BudgetExceeded("Provider usage exceeded its reserved bound; pilot is stopped")

    async def generate(self, bundle: dict, recipe: dict, stage: str):
        from app.services.understanding_provider import ProviderFailure, ProviderOutcome
        path, body, estimate = self.provider.prepare_request(bundle, recipe, stage)
        token_cost(body["model"], 0)  # Unknown models fail before client I/O.
        key = cache_key("s3-wire-v1", path=path, body=body, bundle=bundle, recipe=recipe, stage=stage)
        self.touched.add(key)
        target = self.cache_dir / key[:2] / f"{key}.json"
        if target.exists():
            stored = json.loads(target.read_text())
            if stored.get("key") != key or stored.get("schema_version") != 1:
                raise ValueError("Invalid S3 cache identity")
            self.hits += 1
            if "failure" in stored:
                failure = stored["failure"]
                raise ProviderFailure(failure.pop("kind"), **failure)
            outcome = stored["outcome"]
            if not math.isfinite(outcome["usage_usd"]) or outcome["usage_usd"] < 0:
                raise ValueError("Invalid cached S3 usage")
            return ProviderOutcome(**outcome)
        if self.offline:
            raise CacheMiss(key, "S3 frozen request (article text omitted)")
        token = self._reserve(key, estimate)
        self.misses += 1
        try:
            outcome = await self.provider.generate(bundle, recipe, stage)
        except ProviderFailure as failure:
            stored = {"schema_version": 1, "key": key, "failure": {
                "kind": failure.kind, "retryable": failure.retryable, "retry_after": failure.retry_after,
                "ambiguous": failure.ambiguous, "provider_wide": failure.provider_wide,
                "usage_usd": failure.usage_usd, "request_id": failure.request_id}}
            _atomic_write_bytes(target, json.dumps(stored, allow_nan=False).encode())
            self._settle(key, token, failure.usage_usd)
            raise
        # Persist replay before settling; a crash can conservatively overreserve
        # but can never pay twice to reconstruct a lost response.
        stored = {"schema_version": 1, "key": key, "outcome": {
            "payload": outcome.payload, "usage_usd": outcome.usage_usd, "request_id": outcome.request_id}}
        _atomic_write_bytes(target, json.dumps(stored, allow_nan=False).encode())
        self._settle(key, token, outcome.usage_usd)
        return outcome


# ---------------------------------------------------------------------------
# Garbage collection: drop cache entries no scorecard references
# ---------------------------------------------------------------------------

def referenced_keys(results_dir: Path) -> set[str]:
    """Keys any scorecard, label set or persona build still depends on."""
    keys: set[str] = set()
    evals = Path(__file__).resolve().parent
    files = list(Path(results_dir).glob("*.json"))
    files += list((evals / "labels").glob("*/cache_keys.json"))
    files += [evals / "personas" / "cache_keys.json"]
    for p in files:
        if not p.exists():
            continue
        try:
            doc = json.loads(p.read_text())
            keys.update(doc.get("cache_keys") or [] if isinstance(doc, dict) else doc)
        except Exception:
            continue
    return keys


def write_key_manifest(path: Path, keys: set[str], note: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"note": note, "cache_keys": sorted(keys)}, indent=0) + "\n")


def gc(results_dir: Path, cache_dir: Path = CACHE_LLM, keep: set[str] | None = None,
       dry_run: bool = False) -> list[Path]:
    keep = set(keep or ()) | referenced_keys(results_dir)
    removed: list[Path] = []
    for p in Path(cache_dir).glob("*/*"):
        key = p.name.split(".")[0]
        if key not in keep:
            removed.append(p)
            if not dry_run:
                p.unlink()
    return removed


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="LLM cache maintenance")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("gc", help="delete entries not referenced by any scorecard")
    g.add_argument("--results", default=str(Path(__file__).resolve().parent / "results"))
    g.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("stats")
    args = ap.parse_args()
    if args.cmd == "gc":
        gone = gc(Path(args.results), dry_run=args.dry_run)
        print(f"{'would remove' if args.dry_run else 'removed'} {len(gone)} files")
    else:
        files = list(CACHE_LLM.glob("*/*"))
        size = sum(f.stat().st_size for f in files)
        print(f"{len(files)} files, {size/1e6:.1f} MB in {CACHE_LLM}")
