"""Real OpenAI backends for the eval pipeline: dense retrieval + LLM judge.

Every call goes through `evals.llm_cache.CachingOpenAI`, so a repeated request is
free and deterministic, and `EVAL_OFFLINE=1` runs the whole thing with no key.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

try:
    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent / ".env"))
except Exception:  # pragma: no cover - dotenv is optional for offline runs
    pass

from evals.llm_cache import CachingOpenAI, Meter, PRICING  # noqa: F401  (re-exported)

EMBED_MODEL = "text-embedding-3-small"
# Pinned in code, not .env: the model is part of every cache key, so an
# environment without .env (CI, a colleague's machine) must resolve the same one.
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4o-mini")

METER = Meter(budget_usd=float(os.getenv("EVAL_BUDGET_USD", "0") or 0) or None)
_client: CachingOpenAI | None = None


def client() -> CachingOpenAI:
    """Process-wide caching client. Constructed lazily so importing this module
    never needs a key, and never constructs a network client in offline mode."""
    global _client
    if _client is None:
        _client = CachingOpenAI(meter=METER)
    return _client


# ---------------------------------------------------------------------------
# Dense retrieval
# ---------------------------------------------------------------------------

def _embed(texts: list[str], batch: int = 256) -> np.ndarray:
    out: list[list[float]] = []
    for i in range(0, len(texts), batch):
        chunk = [t[:2000] or " " for t in texts[i:i + batch]]
        for attempt in range(4):
            try:
                r = client().embeddings.create(model=EMBED_MODEL, input=chunk)
                out.extend(d.embedding for d in r.data)
                break
            except Exception as e:
                if attempt == 3 or type(e).__name__ in {"CacheMiss", "BudgetExceeded"}:
                    raise
                time.sleep(2 ** attempt)
    arr = np.asarray(out, dtype=np.float32)
    arr /= np.linalg.norm(arr, axis=1, keepdims=True) + 1e-9
    return arr


def embed_docs(docs: list[dict]) -> np.ndarray:
    texts = [f"{d.get('title','')}. {(d.get('summary') or d.get('content') or '')[:600]}" for d in docs]
    return _embed(texts)


class EmbeddingBackend:
    """Dense retrieval over the corpus. Mirrors production's pgvector path.

    This is the structural answer to the "ai matches ukraine" problem: an
    embedding of the concept *artificial intelligence* has no notion of the
    letters a-i, so it cannot match on them. It also matches OpenAI, LLMs and
    inference hardware, which strict word-boundary matching misses.
    """

    def __init__(self, docs: list[dict], mat: np.ndarray | None = None):
        self.docs = docs
        self.mat = mat if mat is not None else embed_docs(docs)
        self._qcache: dict[str, np.ndarray] = {}

    def search(self, query: str, top_k: int, min_coverage: float = 0.0):
        """`min_coverage` is accepted for interface parity and ignored — token
        coverage is a lexical notion with no meaning in embedding space."""
        q = self._qcache.get(query)
        if q is None:
            q = _embed([f"news about {query}"])[0]
            self._qcache[query] = q
        sims = self.mat @ q
        k = min(top_k, len(sims))
        if k <= 0:
            return []
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        # Cosine similarity floor: below this the "nearest" doc is just the
        # least-unrelated one, which is how junk enters a dense-retrieval feed.
        return [(int(i), float(sims[i])) for i in idx if sims[i] >= 0.28]


class HybridBackend:
    """Dense + lexical. Dense finds meaning, lexical pins exact names.

    Neither is sufficient alone: embeddings alone drift on rare proper nouns
    ("Emomali Rahmon"), lexical alone misses everything not phrased the user's
    way ("OpenAI" for someone who asked for "AI").
    """

    def __init__(self, dense, lexical):
        self.dense, self.lexical = dense, lexical

    def search(self, query: str, top_k: int, min_coverage: float = 0.0):
        d = dict(self.dense.search(query, top_k))
        merged = dict(d)
        if min_coverage >= 1.0:          # named entity: lexical evidence is decisive
            for i, s in self.lexical.search(query, top_k, min_coverage=min_coverage):
                merged[i] = max(merged.get(i, 0.0), 0.30 + min(s / 20.0, 0.55))
        else:
            for i, s in self.lexical.search(query, top_k, min_coverage=min_coverage):
                if i in merged:
                    merged[i] += 0.06    # agreement bonus only
        return sorted(merged.items(), key=lambda kv: -kv[1])[:top_k]


# ---------------------------------------------------------------------------
# LLM judge
# ---------------------------------------------------------------------------

def chat_json(system: str, user: str, model: str, temperature: float = 0.1,
              max_tokens: int = 2000) -> dict:
    """One JSON-object completion through the cache. Raises on failure."""
    r = client().chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return json.loads(r.choices[0].message.content or "{}")


def make_judge(model: str = JUDGE_MODEL, verbose: bool = False):
    """Returns a `call(system, user) -> list[verdict]` for `pipeline.judge`."""

    def call(system: str, user: str) -> list[dict]:
        for attempt in range(3):
            try:
                payload = chat_json(system, user, model)
                verdicts = (payload.get("verdicts") or payload.get("results")
                            or payload.get("events") or [])
                if not verdicts:
                    # Some responses come back as a bare list under an unexpected
                    # key; take the first list-of-dicts value rather than losing
                    # the whole batch to a naming mismatch.
                    for v in payload.values():
                        if isinstance(v, list) and v and isinstance(v[0], dict):
                            verdicts = v
                            break
                if verbose:
                    print(f"    judge: {len(verdicts)} verdicts, {METER.report()}")
                return verdicts if isinstance(verdicts, list) else []
            except Exception as e:
                if type(e).__name__ in {"CacheMiss", "BudgetExceeded"}:
                    raise
                if attempt == 2:
                    print(f"    judge FAILED: {type(e).__name__} {str(e)[:110]}")
                    return []
                time.sleep(1.5 * (attempt + 1))
        return []

    return call
