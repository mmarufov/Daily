"""Metrics that assign blame.

Every number here answers a question a person would ask after looking at a feed:
did the must-see stories make it (recall), did junk get in (never-rate), did the
event everyone should know arrive (event delivery), and for each miss, WHICH
STAGE dropped it (loss_by_stage). The judge is measured as a component too, so
a model or prompt swap is visible before it changes the feed.
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from evals.runners import BuildResult

PROD_ORDER = ["pool", "loaded_rows", "loaded", "prefilter", "scored", "blended", "dedup", "diversity", "roles", "feed"]
PROTO_ORDER = ["pool", "recall", "triage", "judge", "feed"]
RETRIEVAL_STAGE = {"prod": "scored", "proto": "triage"}


def _order(kind: str) -> list[str]:
    return PROD_ORDER if kind == "prod" else PROTO_ORDER


def _reached(trace_row: dict, stage: str, kind: str) -> bool:
    order = _order(kind)
    try:
        return order.index(trace_row["stage_reached"]) >= order.index(stage)
    except ValueError:
        return False


def _judge_verdict(t: dict) -> bool | None:
    m = t.get("model")
    if isinstance(m, dict) and "relevant" in m:
        return bool(m["relevant"])
    if t.get("dropped_at") == "judge":
        return False
    if t["stage_reached"] in ("judge", "feed") and "model" not in t:
        return True
    return None


def _div(n: float, d: float) -> float | None:
    return None if not d else round(n / d, 4)


def score_build(result: BuildResult, labels: dict[str, dict], events: dict, pool: list[dict],
                k: int = 12, kind: str = "prod", quiet: bool = False) -> dict:
    by_id = {a["id"]: a for a in pool}
    feed_k = result.feed[:k]
    in_feed = set(feed_k)

    must = {i for i, r in labels.items() if r["label"] == "must_see"}
    never = {i for i, r in labels.items() if r["label"] == "never"}
    ntk = {i for i in must if "need_to_know" in (labels[i].get("tags") or [])}
    followups = {i for i in must if "followup" in (labels[i].get("tags") or [])}
    plants = {i for i, r in labels.items() if r.get("source") == "needle" and r["label"] == "must_see"}
    lookalikes = {i for i, r in labels.items() if r.get("source") == "needle" and r["label"] == "never"}

    hit = must & in_feed
    losses = []
    loss_by_stage: Counter = Counter()
    for i in sorted(must - in_feed):
        t = result.trace.get(i) or {"dropped_at": "not_in_pool", "reason": "", "stage_reached": "-"}
        at = t.get("dropped_at") or f"after:{t.get('stage_reached')}"
        loss_by_stage[at] += 1
        losses.append({"id": i, "title": (by_id.get(i) or {}).get("title", "")[:80], "dropped_at": at,
                       "reason": (t.get("reason") or "")[:120], "score": t.get("score")})

    retrieval_stage = RETRIEVAL_STAGE[kind]
    reached_retrieval = {i for i in must if i in result.trace and _reached(result.trace[i], retrieval_stage, kind)}

    # Events: delivered if any member of a cluster is in the top-k.
    clusters = events.get("clusters", [])
    crit = [c for c in clusters if c["tier"] == "world_critical"]
    major = [c for c in clusters if c["tier"] == "major"]
    crit_delivered = sum(1 for c in crit if set(c["article_ids"]) & in_feed)
    major_delivered = sum(1 for c in major if set(c["article_ids"]) & in_feed)
    important_ids = {i for c in clusters if c["tier"] in ("world_critical", "major") for i in c["article_ids"]}

    false_major = None
    if quiet and kind == "proto":
        forced = [i for i in feed_k if str((result.trace.get(i) or {}).get("reason", "")).startswith("forced")
                  or (result.trace.get(i) or {}).get("reason") == "major story"]
        false_major = _div(sum(1 for i in forced if i not in important_ids), len(feed_k))

    # Judge as a component, over labelled candidates it actually saw.
    tp = fp = fn = tn = 0
    for i, r in labels.items():
        t = result.trace.get(i)
        if not t:
            continue
        v = _judge_verdict(t)
        if v is None:
            continue
        if r["label"] == "must_see":
            tp += v
            fn += (not v)
        elif r["label"] == "never":
            fp += v
            tn += (not v)

    sources = {(by_id.get(i) or {}).get("source") for i in feed_k}
    unlabelled = [i for i in feed_k if i not in labels]

    return {
        "n_must_see": len(must), "n_need_to_know": len(ntk), "n_labelled": len(labels),
        "recall_at_k": _div(len(hit), min(len(must), k)) if must else None,
        "raw_recall_at_k": _div(len(hit), len(must)) if must else None,
        "recall_at_retrieval": _div(len(reached_retrieval), len(must)) if must else None,
        "need_to_know_recall": _div(len(ntk & in_feed), min(len(ntk), k)) if ntk else None,
        "followup_recall": _div(len(followups & in_feed), min(len(followups), k)) if followups else None,
        "never_rate": _div(len(never & in_feed), len(feed_k)) if feed_k else None,
        "never_in_feed": [{"id": i, "title": (by_id.get(i) or {}).get("title", "")[:80],
                           "rank": result.trace[i].get("rank")} for i in feed_k if i in never],
        "feed_size": len(result.feed), "feed_size_k": len(feed_k), "feed_size_flag": len(feed_k) < 6,
        "unlabelled_in_feed": len(unlabelled),
        "distinct_sources": len(sources),
        "loss_by_stage": dict(loss_by_stage), "losses": losses,
        "event_delivery": _div(crit_delivered, len(crit)) if crit else None,
        "major_delivery": _div(major_delivered, len(major)) if major else None,
        "false_major_rate": false_major,
        "judge_precision": _div(tp, tp + fp) if (tp + fp) else None,
        "judge_recall": _div(tp, tp + fn) if (tp + fn) else None,
        "judge_n": tp + fp + fn + tn,
        "needle_recall": _div(len(plants & in_feed), len(plants)) if plants else None,
        "lookalike_rate": _div(len(lookalikes & in_feed), len(lookalikes)) if lookalikes else None,
        "calls": result.calls, "cost_usd": round(result.cost_usd, 5), "latency_s": round(result.latency_s, 2),
        "cache_hits": result.cache_hits, "cache_misses": result.cache_misses,
        "stage_counts": result.stage_counts(), "drop_counts": result.drop_counts(),
        "feed": [{"id": i, "rank": n + 1, "title": (by_id.get(i) or {}).get("title", "")[:80],
                  "source": (by_id.get(i) or {}).get("source"), "label": (labels.get(i) or {}).get("label"),
                  "score": (result.trace.get(i) or {}).get("score")} for n, i in enumerate(feed_k)],
        "meta": result.meta,
    }


NUMERIC = ("recall_at_k", "raw_recall_at_k", "recall_at_retrieval", "need_to_know_recall", "followup_recall", "never_rate",
           "event_delivery", "major_delivery", "false_major_rate", "judge_precision", "judge_recall",
           "needle_recall", "lookalike_rate", "feed_size_k", "distinct_sources", "latency_s")


def aggregate(per_persona: dict[str, dict]) -> dict:
    out: dict = {}
    for key in NUMERIC:
        vals = [m[key] for m in per_persona.values() if m.get(key) is not None]
        out[f"{key}_mean"] = round(mean(vals), 4) if vals else None
        out[f"{key}_min"] = round(min(vals), 4) if vals else None
    out["calls_total"] = sum(m["calls"] for m in per_persona.values())
    out["calls_max_per_persona"] = max((m["calls"] for m in per_persona.values()), default=0)
    out["cost_usd_total"] = round(sum(m["cost_usd"] for m in per_persona.values()), 5)
    out["cache_misses_total"] = sum(m["cache_misses"] for m in per_persona.values())
    loss: Counter = Counter()
    for m in per_persona.values():
        loss.update(m["loss_by_stage"])
    out["loss_by_stage"] = dict(loss)
    out["personas"] = len(per_persona)
    return out


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short=7", "HEAD"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "nogit"


def write_scorecard(path: Path, runner: str, snapshot: str, per_persona: dict, summary: dict,
                    cache_keys: list[str], k: int, meta: dict | None = None) -> Path:
    doc = {
        "git_sha": git_sha(), "runner": runner, "snapshot": snapshot, "k": k,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": summary, "per_persona": per_persona, "cache_keys": sorted(cache_keys),
        "meta": meta or {},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return path


def load_scorecard(path: Path) -> dict:
    return json.loads(Path(path).read_text())
