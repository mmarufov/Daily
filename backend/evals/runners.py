"""One interface for every feed system under evaluation.

    result = runner.build(persona, pool, frozen_now)

`result.trace` carries, for every article in the pool, the furthest stage it
reached and — if it never made the top-k — the stage that dropped it and why.
That attribution is the point of S0: "lost at prefilter:cap" is actionable,
"not in feed" is not.

Two implementations:

* `ProductionRunner` drives the REAL `feed_service.get_personalized_feed` with an
  in-memory connection (`fake_db.SnapshotConn`) and the production OpenAI scorer
  replayed through the LLM cache. `mode="fallback"` forces the deterministic
  keyword path production takes when the model is unavailable.
* `PrototypeRunner` wraps `evals.pipeline.run_pipeline`.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol
from unittest.mock import patch

from evals.fake_db import SnapshotConn, eval_uuid, persona_uuid

PROD_STAGES = ("pool", "loaded", "prefilter", "scored", "blended", "dedup", "diversity", "roles", "feed")
PROTO_STAGES = ("pool", "recall", "triage", "judge", "feed")


@dataclass
class BuildResult:
    feed: list[str]                      # snapshot article ids, ranked
    trace: dict[str, dict]               # id -> {stage_reached, dropped_at, score, reason, rank}
    calls: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    meta: dict = field(default_factory=dict)

    def stage_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.trace.values():
            out[t["stage_reached"]] = out.get(t["stage_reached"], 0) + 1
        return out

    def drop_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in self.trace.values():
            if t["dropped_at"]:
                out[t["dropped_at"]] = out.get(t["dropped_at"], 0) + 1
        return out


class FeedSystem(Protocol):
    name: str

    def build(self, persona: dict, pool: list[dict], frozen_now: datetime) -> BuildResult: ...


class _Trace:
    def __init__(self, ids: list[str], first_drop: str):
        self.t = {i: {"stage_reached": "pool", "dropped_at": first_drop, "score": None,
                      "reason": "", "rank": None} for i in ids}

    def reach(self, i: str, stage: str, score: float | None = None, reason: str | None = None) -> None:
        if i not in self.t:
            return
        row = self.t[i]
        row["stage_reached"] = stage
        row["dropped_at"] = None
        if score is not None:
            row["score"] = score
        if reason is not None:
            row["reason"] = reason

    def drop(self, i: str, at: str, reason: str | None = None, score: float | None = None,
             only_if_alive: bool = True) -> None:
        if i not in self.t:
            return
        row = self.t[i]
        if only_if_alive and row["dropped_at"] is not None:
            return
        row["dropped_at"] = at
        if reason is not None:
            row["reason"] = reason
        if score is not None:
            row["score"] = score

    def finish(self, feed: list[str], k: int) -> None:
        for rank, i in enumerate(feed, 1):
            self.reach(i, "feed")
            self.t[i]["rank"] = rank
            if rank > k:
                self.t[i]["dropped_at"] = "rank"
        for i, row in self.t.items():
            if row["dropped_at"] is None and row["rank"] is None:
                row["dropped_at"] = f"after:{row['stage_reached']}"


def _frozen_datetime(frozen_now: datetime) -> type:
    frozen_now = frozen_now if frozen_now.tzinfo else frozen_now.replace(tzinfo=timezone.utc)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen_now if tz is None else frozen_now.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return frozen_now.replace(tzinfo=None)

    return Frozen


def _meter_delta(fn):
    """Run `fn()` and return (value, calls, cost, hits, misses, seconds)."""
    from evals.openai_backend import METER, client
    c = client()
    c0, u0 = METER.snapshot()
    h0, m0 = c.hits, c.misses
    t0 = time.perf_counter()
    value = fn()
    c1, u1 = METER.snapshot()
    return value, c1 - c0, u1 - u0, c.hits - h0, c.misses - m0, time.perf_counter() - t0


# ---------------------------------------------------------------------------
# Production
# ---------------------------------------------------------------------------

class _FallbackService:
    """What production degrades to when OpenAI is unavailable."""
    scoring_model = "deterministic-fallback"

    async def score_articles_batch(self, articles, user_profile, interests=None, user_profile_v2=None):
        return [{"relevant": False, "score": 0.0, "reason": "scoring unavailable"} for _ in articles]


class ProductionRunner:
    def __init__(self, mode: Literal["llm", "fallback"] = "llm", limit: int = 50, k: int = 12,
                 model: str = "gpt-4o-mini"):
        self.mode, self.limit, self.k, self.model = mode, limit, k, model
        self.name = f"prod-{mode}"

    def _service(self):
        if self.mode == "fallback":
            return _FallbackService()
        from app.services import openai_service as osvc
        from evals.openai_backend import client
        if not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = "offline-cache-only"   # constructor only; never used
        # The constructor builds a real SDK client we immediately replace; skip it
        # so offline runs (and test suites that stub the SDK) never touch it.
        with patch.object(osvc, "OpenAI", lambda **kw: None):
            svc = osvc.OpenAIService()
        svc.client = client()
        svc.model = self.model
        svc.scoring_model = self.model
        return svc

    def build(self, persona: dict, pool: list[dict], frozen_now: datetime) -> BuildResult:
        from app.services import feed_service, openai_service

        Frozen = _frozen_datetime(frozen_now)
        conn = SnapshotConn(persona, pool, frozen_now, datetime_cls=Frozen)
        sid = {str(eval_uuid(a["id"])): a["id"] for a in pool}
        tr = _Trace([a["id"] for a in pool], first_drop="lookback")
        svc = self._service()

        o_rows = feed_service._rows_to_candidates
        o_pref = feed_service._prefilter_candidates
        o_apply = feed_service._apply_individual_analysis_results
        o_dedup = feed_service._collapse_duplicate_coverage
        o_div = feed_service._enforce_diversity
        o_roles = feed_service._balance_feed_roles
        o_score = svc.score_articles_batch

        def w_rows(rows):
            out = o_rows(rows)
            kept = {c["id"] for c in out}
            for r in rows:
                u = str(r["id"])
                if u in kept:
                    tr.reach(sid.get(u, u), "loaded")
                else:
                    tr.t[sid.get(u, u)]["stage_reached"] = "loaded_rows"
                    tr.drop(sid.get(u, u), "text_too_short", only_if_alive=False)
            return out

        def w_pref(candidates, profile, max_candidates=feed_service.MAX_LLM_CANDIDATES):
            out = o_pref(candidates, profile, max_candidates=max_candidates)
            kept = {c["id"] for c in out}
            for c in candidates:
                i = sid.get(c["id"], c["id"])
                if c["id"] in kept:
                    tr.reach(i, "prefilter", score=c.get("_prefilter_score"), reason=c.get("_prefilter_reason"))
                else:
                    tr.t[i]["stage_reached"] = "loaded"
                    tr.drop(i, "prefilter:excluded" if c.get("_prefilter_excluded") else "prefilter:cap",
                            reason=c.get("_prefilter_reason"), score=c.get("_prefilter_score"),
                            only_if_alive=False)
            return out

        async def w_score(batch, *a, **kw):
            res = await o_score(batch, *a, **kw)
            for c, r in zip(batch, res):
                i = sid.get(c["id"], c["id"])
                tr.reach(i, "scored", score=float(r.get("score", 0.0)), reason=str(r.get("reason", "")))
                tr.t[i]["model"] = {"relevant": bool(r.get("relevant")), "score": r.get("score"),
                                    "reason": r.get("reason")}
            return res

        def w_apply(candidates, results, profile, ctx):
            o_apply(candidates, results, profile, ctx)
            for c in candidates:
                i = sid.get(c["id"], c["id"])
                if c.get("_relevant"):
                    tr.reach(i, "blended", score=c.get("_score"), reason=c.get("_reason"))
                else:
                    tr.drop(i, "blended", reason=c.get("_reason"), score=c.get("_score"), only_if_alive=False)

        def _stage_wrapper(orig, stage, drop_at):
            def w(articles, *a, **kw):
                out = orig(articles, *a, **kw)
                kept = {x["id"] for x in out}
                for x in articles:
                    i = sid.get(x["id"], x["id"])
                    if tr.t.get(i, {}).get("dropped_at") is not None:
                        continue
                    if x["id"] in kept:
                        tr.reach(i, stage)
                    else:
                        tr.drop(i, drop_at)
                return out
            return w

        svc.score_articles_batch = w_score
        user_id = str(persona_uuid(persona.get("key") or persona.get("name") or "persona"))

        def run():
            with patch.object(feed_service, "datetime", Frozen), \
                 patch.object(openai_service, "_openai_service", svc), \
                 patch.object(feed_service, "get_openai_service", lambda: svc), \
                 patch.object(feed_service, "_rows_to_candidates", w_rows), \
                 patch.object(feed_service, "_prefilter_candidates", w_pref), \
                 patch.object(feed_service, "_apply_individual_analysis_results", w_apply), \
                 patch.object(feed_service, "_collapse_duplicate_coverage", _stage_wrapper(o_dedup, "dedup", "dedup")), \
                 patch.object(feed_service, "_enforce_diversity", _stage_wrapper(o_div, "diversity", "diversity")), \
                 patch.object(feed_service, "_balance_feed_roles", _stage_wrapper(o_roles, "roles", "roles")):
                return asyncio.run(feed_service.get_personalized_feed(
                    user_id, conn, limit=self.limit, force_refresh=True))

        feed_rows, calls, cost, hits, misses, secs = _meter_delta(run)
        if conn.store["unhandled"]:
            raise AssertionError(f"unhandled SQL in production runner: {conn.store['unhandled']}")

        feed = [sid.get(str(a["id"]), str(a["id"])) for a in feed_rows]
        tr.finish(feed, self.k)
        return BuildResult(
            feed=feed, trace=tr.t, calls=calls, cost_usd=cost, latency_s=secs,
            cache_hits=hits, cache_misses=misses,
            meta={"runner": self.name, "mode": self.mode, "model": getattr(svc, "scoring_model", None),
                  "limit": self.limit, "k": self.k, "served": len(conn.store["served_ids"]),
                  "cache_inserts": len(conn.store["cache_inserts"])},
        )


# ---------------------------------------------------------------------------
# Prototype
# ---------------------------------------------------------------------------

class PrototypeRunner:
    protocol = "canonical-global-events-v2"

    def __init__(self, backend: Literal["bm25", "hybrid"] = "hybrid", judge: bool = True,
                 events: bool = True, feed_size: int = 12, k: int = 12,
                 judge_model: str | None = None, cluster_threshold: float = 0.55):
        self.backend_kind, self.judge, self.events = backend, judge, events
        self.feed_size, self.k, self.judge_model = feed_size, k, judge_model
        self.cluster_threshold = cluster_threshold
        self.name = f"proto-{backend}{'-judge' if judge else ''}{'-events' if events else ''}"
        self._pool_state: dict[str, dict] = {}
        self._global_state: dict | None = None
        self._global_prepared: dict | None = None
        self._global_docs_digest: str | None = None

    @staticmethod
    def _digest(value) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def _prepare(self, docs: list[dict], frozen_now: datetime | None = None, *, global_detection: bool = True) -> dict:
        from evals.global_events import GRAVITY_SYSTEM, SOURCE_REGION
        from evals.openai_backend import EMBED_MODEL, JUDGE_MODEL
        key = self._digest({"docs": docs, "cutoff": frozen_now.isoformat() if frozen_now else None,
                            "backend": self.backend_kind, "judge": self.judge, "model": self.judge_model or JUDGE_MODEL,
                            "embedding_model": EMBED_MODEL, "gravity_prompt": GRAVITY_SYSTEM,
                            "source_regions": SOURCE_REGION, "recipe": "legacy-prototype-events-v2",
                            "events": self.events, "threshold": self.cluster_threshold,
                            "global_detection": global_detection})
        st = self._pool_state.get(key)
        if st is not None:
            return st
        from evals.pipeline import BM25Backend
        lexical = BM25Backend(docs)
        st = {"lexical": lexical, "dense": None, "backend": lexical, "emb": None, "events": None, "judge": None}
        if self.judge or self.backend_kind == "hybrid":
            from evals.openai_backend import EmbeddingBackend, HybridBackend, make_judge
            if self.backend_kind == "hybrid":
                dense = EmbeddingBackend(docs)
                st["dense"], st["emb"] = dense, dense.mat
                st["backend"] = HybridBackend(dense, lexical)
            if self.judge:
                st["judge"] = make_judge(self.judge_model) if self.judge_model else make_judge()
        if global_detection and self.events and st["emb"] is not None and st["judge"] is not None:
            from evals.global_events import detect_events
            st["events"] = detect_events(docs, st["emb"], st["judge"],
                                         threshold=self.cluster_threshold, min_sources=2)
        self._pool_state[key] = st
        return st

    def prepare_global(self, docs: list[dict], frozen_now: datetime) -> dict:
        """Freeze detector inputs before per-reader needles; account once.

        The returned costs belong to system preparation, not every persona's
        marginal build. Repeated article IDs with changed evidence are not hits.
        """
        if len({d["id"] for d in docs}) != len(docs):
            raise ValueError("Duplicate canonical global article IDs")
        st, calls, cost, hits, misses, secs = _meter_delta(lambda: self._prepare(docs, frozen_now))
        self._global_prepared = st
        self._global_docs_digest = self._digest(docs)
        self._global_state = {
            "articles": {d["id"]: self._digest(d) for d in docs},
            "cutoff": frozen_now.isoformat(),
            "events": [{**event, "member_ids": [docs[i]["id"] for i in event["members"]],
                        "rep_id": docs[event["rep"]]["id"]} for event in st["events"] or []],
        }
        return {"calls": calls, "cost_usd": cost, "cache_hits": hits, "cache_misses": misses,
                "latency_s": secs, "canonical_pool_sha256": self._digest(self._global_state)}

    def _events_for_pool(self, pool: list[dict], frozen_now: datetime) -> list[dict]:
        state = self._global_state
        if state is None:
            raise ValueError("Canonical global events have not been prepared")
        positions = {doc["id"]: i for i, doc in enumerate(pool)}
        if len(positions) != len(pool) or state["cutoff"] != frozen_now.isoformat():
            raise ValueError("Duplicate pool IDs or changed global decision cutoff")
        for aid, checksum in state["articles"].items():
            if aid not in positions or self._digest(pool[positions[aid]]) != checksum:
                raise ValueError("Canonical global evidence changed; prepare_global again")
        return [{**event, "members": [positions[i] for i in event["member_ids"]],
                 "rep": positions[event["rep_id"]]} for event in state["events"]]

    def build(self, persona: dict, pool: list[dict], frozen_now: datetime) -> BuildResult:
        from evals.global_events import home_regions
        from evals.pipeline import final_score

        st, prep_calls, prep_cost, prep_hits, prep_misses, prep_secs = _meter_delta(
            lambda: self._global_prepared if self._global_state is not None
            and self._global_state["cutoff"] == frozen_now.isoformat()
            and self._global_docs_digest == self._digest(pool)
            else self._prepare(pool, frozen_now, global_detection=self._global_state is None))
        events = self._events_for_pool(pool, frozen_now) if self._global_state is not None else st["events"]
        docs = copy.deepcopy(pool)          # run_pipeline annotates articles in place
        tr = _Trace([d["id"] for d in docs], first_drop="recall")
        home = home_regions(persona) if persona.get("user_profile_v2") else set()

        def run():
            return self._run_pipeline(persona, docs, st["backend"], llm_call=st["judge"],
                                feed_size=self.feed_size, events=events, home=home, emb=st["emb"])

        r, calls, cost, hits, misses, secs = _meter_delta(run)

        for c in r.get("recalled_cands", []):
            tr.reach(c.article["id"], "recall", score=None)
        for c in r.get("triaged_cands", []):
            tr.reach(c.article["id"], "triage")
        for c in r.get("recalled_cands", []):
            if tr.t[c.article["id"]]["stage_reached"] == "recall":
                tr.drop(c.article["id"], "triage", only_if_alive=False)
        if st["judge"] is not None:
            for c in r.get("judged_cands", []):
                v = c.article.get("_judged")
                i = c.article["id"]
                if c.article.get("_forced"):
                    tr.reach(i, "judge", score=1.0, reason=f"forced: {c.article.get('_forced')}")
                elif v is None:
                    tr.drop(i, "judge_unanswered", only_if_alive=False)
                elif not v.get("keep"):
                    tr.drop(i, "judge", reason=v.get("why"), score=float(v.get("score") or 0.0), only_if_alive=False)
                else:
                    tr.reach(i, "judge", score=final_score(c), reason=v.get("why"))
        for i, row in tr.t.items():
            if row["dropped_at"] is None and row["stage_reached"] in ("triage", "judge"):
                row["dropped_at"] = "assemble"

        feed = [c.article["id"] for c in r["feed"]]
        for c in r["feed"]:
            tr.t[c.article["id"]]["score"] = final_score(c)
            if c.article.get("_forced"):
                tr.t[c.article["id"]]["reason"] = f"forced: {c.article.get('_forced')}"
            elif "major story" in c.intent_hits and len(c.intent_hits) == 1:
                tr.t[c.article["id"]]["reason"] = "major story"
        for i in feed:
            tr.t[i]["dropped_at"] = None
        tr.finish(feed, self.k)

        n_events = len([e for e in (events or []) if e.get("tier") == "world_critical"])
        return BuildResult(
            feed=feed, trace=tr.t, calls=calls + prep_calls, cost_usd=cost + prep_cost, latency_s=secs + prep_secs,
            cache_hits=hits + prep_hits, cache_misses=misses + prep_misses,
            meta={"runner": self.name, "backend": self.backend_kind, "judge": self.judge,
                  "protocol": self.protocol, "reader_pipeline_calls": calls,
                  "events": self.events, "world_critical_events": n_events,
                  "reader_preparation": {"calls": prep_calls, "cost_usd": prep_cost, "latency_s": prep_secs},
                  "global_pool_frozen": self._global_state is not None,
                  "recalled": r["recalled"], "triaged": r["triaged"], "k": self.k},
        )

    @staticmethod
    def _run_pipeline(*args, **kwargs):
        from evals.pipeline import run_pipeline
        return run_pipeline(*args, **kwargs)


class HistoricalS0PrototypeRunner(PrototypeRunner):
    """Explicit reproducibility adapter, never selected by the current default.

    Old cached responses belong to persona-dependent detector inputs. They are
    not interchangeable with corrected canonical-global requests. Full cost and
    preparation calls remain accounted; old call ceilings refer to the separate
    reader_pipeline_calls metric, which was their original measurement boundary.
    """
    protocol = "s0-prototype-persona-global-v1"
    prepare_global = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.name += "-s0-legacy-v1"

    @staticmethod
    def _run_pipeline(*args, **kwargs):
        from evals.legacy_s0 import run_pipeline
        return run_pipeline(*args, **kwargs)


def get_runner(name: str, **kw) -> FeedSystem:
    if name == "prod":
        return ProductionRunner(mode="llm", **kw)
    if name == "prod-fallback":
        return ProductionRunner(mode="fallback", **kw)
    if name == "proto":
        return PrototypeRunner(**kw)
    if name == "proto-s0-legacy-v1":
        return HistoricalS0PrototypeRunner(**kw)
    if name == "proto-bm25":
        return PrototypeRunner(backend="bm25", judge=False, events=False, **kw)
    raise ValueError(f"unknown runner {name!r}")
