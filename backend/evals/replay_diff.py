"""Replay two builds of the production feed on the same frozen inputs and diff them.

    python -m evals.replay_diff --base origin/main --head HEAD
    python -m evals.replay_diff --base origin/main --head WORKTREE --live --budget 1.00

Each side is a `git archive` of `backend/` at a revision (or, for `WORKTREE`,
this checkout), run in its own subprocess so its `app/` and `evals/` are the
ones imported. Both run `ProductionRunner` over every snapshot and persona with
the frozen clock and the committed LLM response cache. By default both sides
are offline: a cache miss is an error, not a network call.

`--live` lets the head side call OpenAI for requests the cache lacks, capped by
`Meter` at `--budget` dollars, and writes the new responses into this
checkout's cache so they can be committed. Only `WORKTREE` can be live, because
an archive is thrown away.

The diff reports, per snapshot and in total:
  * feeds: per persona, which article ids entered or left the top k;
  * verdicts: articles whose model verdict (relevant, or scored at all) moved;
  * batches: every scoring call's request size and what the build did with the
    response, which is where misattribution is counted;
  * loss by stage, and the metric deltas, in whichever direction they went.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parent
# Not evals/results/ itself: web/scripts/export-artifacts.ts parses every .json
# there as a scorecard.
RESULTS = BACKEND / "evals" / "results" / "replay"
METRICS = ("recall_at_k", "never_rate", "needle_recall", "lookalike_rate", "event_delivery",
           "recall_at_retrieval", "judge_precision", "judge_recall")

# What each build logs when it receives a response it cannot associate. The
# positional build logs a count mismatch and applies the list anyway; the
# keyed build logs a refusal and applies nothing.
_MISMATCH = re.compile(r"Batch scoring returned (\d+) results for (\d+) articles; normalizing")
_REFUSED = re.compile(r"Batch scoring refused a response for (\d+) articles \((\w+):")
# Production swallows provider errors and falls back, by design. A replay must
# not: a diff against a build whose calls failed measures the outage, not the
# build. This happened once, when the OpenAI account ran out of credits.
_SCORING_ERROR = re.compile(r"Error in batch scoring")
_TIMEOUT = re.compile(r"Batch scoring timed out")


# ---------------------------------------------------------------------------
# Child: runs inside one tree and prints one JSON document.
# ---------------------------------------------------------------------------

class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.batches: list[dict] = []
        self.provider_errors: list[str] = []

    def emit(self, record):
        # Scoring batches run concurrently, so a log line is attributed to the
        # asyncio task that emitted it, never to whichever call is open.
        try:
            task = id(asyncio.current_task())
        except RuntimeError:
            task = None
        message = record.getMessage()
        if _TIMEOUT.search(message):
            self.provider_errors.append(message)
        elif _SCORING_ERROR.search(message):
            exc_type = record.exc_info[0] if record.exc_info else None
            module = getattr(exc_type, "__module__", "") or ""
            if module.split(".")[0] in {"openai", "httpx"}:
                self.provider_errors.append(f"{exc_type.__name__}: {record.exc_info[1]}"[:300])
            else:
                # The model's own output failed to parse (the positional build
                # json.loads a truncated response inside the same handler).
                # That is the build's behaviour, so it is counted, not fatal.
                self.batches.append({"task": task, "outcome": "unparseable",
                                     "error": getattr(exc_type, "__name__", "unknown")})
        if m := _MISMATCH.search(message):
            self.batches.append({"task": task, "articles": int(m.group(2)), "entries": int(m.group(1)),
                                 "outcome": "applied_by_position"})
        elif m := _REFUSED.search(message):
            self.batches.append({"task": task, "articles": int(m.group(1)), "outcome": "refused",
                                 "refusal_kind": m.group(2)})


def _child(snapshots: list[str]) -> dict:
    from app.services import openai_service
    from evals.label import load_events, load_labels, pool_with_needles
    from evals.metrics import aggregate, score_build
    from evals.openai_backend import METER, client
    from evals.personas import load_personas
    from evals.runners import get_runner
    from evals.snapshot import frozen_now, load_snapshot

    capture = _Capture()
    logging.getLogger("app.services.openai_service").addHandler(capture)

    # Count every scoring call and whether its verdicts named their articles.
    # Wrapped on the class, so the runner's own tracer wraps this in turn.
    original = openai_service.OpenAIService.score_articles_batch
    calls: list[dict] = []

    async def counted(self, articles, *args, **kwargs):
        mark = len(capture.batches)
        results = await original(self, articles, *args, **kwargs)
        ids = [str(a.get("id")) for a in articles]
        named = [r.get("article_id") for r in results]
        calls.append({
            "articles": len(articles),
            "keyed": all(isinstance(n, str) for n in named),
            # A verdict applied to an article other than the one it names.
            "misnamed": sum(1 for i, n in zip(ids, named) if isinstance(n, str) and n != i),
            "unscored": sum(1 for r in results if r.get("reason") in {"scoring unavailable", "scoring incomplete"}),
            "events": [{k: v for k, v in e.items() if k != "task"} for e in capture.batches[mark:]
                       if e["task"] == id(asyncio.current_task())],
        })
        return results

    openai_service.OpenAIService.score_articles_batch = counted

    out: dict = {"snapshots": {}}
    runner = get_runner("prod", k=12)
    for snapshot in snapshots:
        snap = load_snapshot(snapshot)
        docs, now = snap["articles"], frozen_now(snap)
        quiet = bool((snap.get("snapshot") or {}).get("quiet"))
        events = load_events(snapshot)
        per, verdicts, feeds, batches = {}, {}, {}, {}
        for key, persona in load_personas(None).items():
            mark = len(calls)
            pool = pool_with_needles(snapshot, key, docs, now)
            labels = load_labels(snapshot, key, include_needles=True)
            result = runner.build(persona, pool, now)
            per[key] = score_build(result, labels, events, pool, k=12, kind="prod", quiet=quiet)
            feeds[key] = result.feed[:12]
            verdicts[key] = {
                i: {"relevant": bool(t["model"].get("relevant")), "score": t["model"].get("score"),
                    "reason": t["model"].get("reason")}
                for i, t in result.trace.items() if isinstance(t.get("model"), dict)
            }
            batches[key] = calls[mark:]
        summary = aggregate(per)
        out["snapshots"][snapshot] = {
            "summary": {m + "_mean": summary.get(m + "_mean") for m in METRICS}
            | {"loss_by_stage": summary.get("loss_by_stage"), "calls_total": summary.get("calls_total"),
               "cache_misses_total": summary.get("cache_misses_total")},
            "per_persona": {k: {m: v.get(m) for m in METRICS} | {"loss_by_stage": v.get("loss_by_stage")}
                            for k, v in per.items()},
            "feeds": feeds, "verdicts": verdicts, "batches": batches,
        }
    out["provider_errors"] = capture.provider_errors
    out["meter"] = {"calls": METER.calls, "usd": round(METER.usd, 6), "by_model": METER.by_model,
                    "cache_hits": client().hits, "cache_misses": client().misses}
    return out


# ---------------------------------------------------------------------------
# Parent: materialise trees, run children, diff.
# ---------------------------------------------------------------------------

def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True, text=True).stdout.strip()


def _materialise(ref: str, into: Path) -> Path:
    if ref == "WORKTREE":
        return BACKEND
    blob = subprocess.run(["git", "archive", "--format=tar", ref, "backend"], cwd=REPO,
                          check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(into, filter="data")
    return into / "backend"


def _run_side(ref: str, tree: Path, snapshots: list[str], live: bool, budget: float | None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("EVAL_")}
    env["PYTHONPATH"] = str(tree)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if live:
        if budget is None:
            raise SystemExit("--live needs --budget")
        env["EVAL_BUDGET_USD"] = f"{budget:.2f}"
    else:
        env["EVAL_OFFLINE"] = "1"
    # The judge model is part of every cache key; pin it rather than inherit.
    env["EVAL_JUDGE_MODEL"] = "gpt-4o-mini"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", *snapshots],
        cwd=tree, env=env, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr[-4000:])
        raise SystemExit(f"{ref}: replay failed with exit code {proc.returncode}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _batch_totals(side: dict) -> dict:
    totals = {"calls": 0, "calls_applied_by_position_after_count_mismatch": 0,
              "verdicts_applied_from_mismatched_batches": 0, "calls_refused": 0,
              "refusals_by_kind": {}, "verdicts_applied_to_another_article": 0, "calls_keyed": 0,
              "unparseable_attempts": 0}
    for persona_calls in side["batches"].values():
        for call in persona_calls:
            totals["calls"] += 1
            totals["calls_keyed"] += bool(call["keyed"])
            totals["verdicts_applied_to_another_article"] += call["misnamed"]
            events = call["events"]
            if any(e["outcome"] == "applied_by_position" for e in events):
                totals["calls_applied_by_position_after_count_mismatch"] += 1
                totals["verdicts_applied_from_mismatched_batches"] += call["articles"]
            totals["unparseable_attempts"] += sum(1 for e in events if e["outcome"] == "unparseable")
            refused = [e for e in events if e["outcome"] == "refused"]
            for e in refused:
                kinds = totals["refusals_by_kind"]
                kinds[e["refusal_kind"]] = kinds.get(e["refusal_kind"], 0) + 1
            totals["calls_refused"] += bool(refused) and call["unscored"] == call["articles"]
    return totals


def _diff_snapshot(base: dict, head: dict) -> dict:
    feeds, moved_relevant, moved_scored, score_changed, compared = {}, 0, 0, 0, 0
    for key in sorted(base["feeds"]):
        b, h = base["feeds"][key], head["feeds"][key]
        feeds[key] = {"entered": [i for i in h if i not in b], "left": [i for i in b if i not in h]}
        bv, hv = base["verdicts"][key], head["verdicts"][key]
        for i in sorted(set(bv) | set(hv)):
            compared += 1
            x, y = bv.get(i), hv.get(i)
            if (x is None) != (y is None):
                moved_scored += 1
                continue
            if x["relevant"] != y["relevant"]:
                moved_relevant += 1
            if x["score"] != y["score"]:
                score_changed += 1

    def unscored(side):
        return sum(1 for vs in side["verdicts"].values() for v in vs.values()
                   if v["reason"] in {"scoring unavailable", "scoring incomplete"})

    metric_delta = {}
    for m in METRICS:
        x, y = base["summary"][m + "_mean"], head["summary"][m + "_mean"]
        metric_delta[m] = {"base": x, "head": y, "delta": None if x is None or y is None else round(y - x, 4)}
    stages = sorted(set(base["summary"]["loss_by_stage"] or {}) | set(head["summary"]["loss_by_stage"] or {}))
    return {
        "metrics": metric_delta,
        "loss_by_stage": {s: {"base": (base["summary"]["loss_by_stage"] or {}).get(s, 0),
                              "head": (head["summary"]["loss_by_stage"] or {}).get(s, 0)} for s in stages},
        "verdicts": {"articles_compared": compared, "relevant_flipped": moved_relevant,
                     "scored_in_one_build_only": moved_scored, "score_changed": score_changed,
                     "moved": moved_relevant + moved_scored,
                     "unscored_base": unscored(base), "unscored_head": unscored(head)},
        "feeds": {"personas_whose_top12_changed": sum(1 for f in feeds.values() if f["entered"] or f["left"]),
                  "articles_entered": sum(len(f["entered"]) for f in feeds.values()),
                  "per_persona": feeds},
        "batches": {"base": _batch_totals(base), "head": _batch_totals(head)},
    }


def _sum(snapshots: dict) -> dict:
    total: dict = {"verdicts": {}, "batches": {"base": {}, "head": {}}}
    for d in snapshots.values():
        for k, v in d["verdicts"].items():
            total["verdicts"][k] = total["verdicts"].get(k, 0) + v
        for side in ("base", "head"):
            for k, v in d["batches"][side].items():
                if isinstance(v, dict):
                    agg = total["batches"][side].setdefault(k, {})
                    for kk, vv in v.items():
                        agg[kk] = agg.get(kk, 0) + vv
                else:
                    total["batches"][side][k] = total["batches"][side].get(k, 0) + v
    return total


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv[:1] == ["--child"]:
        # Import only the tree this child runs in, never the parent's copy.
        sys.path[:] = [os.environ["PYTHONPATH"]] + [p for p in sys.path[1:] if "evals" not in Path(p).parts[-1:]]
        print(json.dumps(_child(argv[1:])))
        return 0

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", required=True, help="git revision, e.g. origin/main")
    ap.add_argument("--head", required=True, help="git revision, or WORKTREE for this checkout")
    ap.add_argument("--snapshot", nargs="*", help="default: every frozen snapshot")
    ap.add_argument("--live", action="store_true", help="head may call OpenAI for uncached requests")
    ap.add_argument("--budget", type=float, help="USD cap for --live, enforced by Meter")
    ap.add_argument("--out", help="write the diff here (default: evals/results/replay-diff-<base>-<head>.json)")
    args = ap.parse_args(argv)
    if args.live and args.head != "WORKTREE":
        raise SystemExit("--live writes new cache entries, so it needs --head WORKTREE")

    sys.path.insert(0, str(BACKEND))
    from evals.snapshot import list_snapshots
    snapshots = args.snapshot or [e["name"] for e in list_snapshots()]

    base_sha = _git("rev-parse", "--short=8", args.base)
    head_sha = "WORKTREE" if args.head == "WORKTREE" else _git("rev-parse", "--short=8", args.head)
    with tempfile.TemporaryDirectory() as tmp:
        base = _run_side(args.base, _materialise(args.base, Path(tmp) / "base"), snapshots, False, None)
        head = _run_side(args.head, _materialise(args.head, Path(tmp) / "head"), snapshots, args.live, args.budget)

    for name, side in (("base", base), ("head", head)):
        if side["provider_errors"]:
            raise SystemExit(f"{name}: {len(side['provider_errors'])} scoring calls hit a provider error, "
                             f"so the diff would measure the outage, not the build. "
                             f"First: {side['provider_errors'][0]}")

    per = {s: _diff_snapshot(base["snapshots"][s], head["snapshots"][s]) for s in snapshots}
    doc = {
        "replay_diff_version": 1,
        "base": {"ref": args.base, "sha": base_sha, "meter": base["meter"]},
        "head": {"ref": args.head, "sha": head_sha, "meter": head["meter"], "live": args.live,
                 "budget_usd": args.budget},
        "snapshots": snapshots,
        "personas": sorted(next(iter(base["snapshots"].values()))["feeds"]),
        "command": "python -m evals.replay_diff " + " ".join(argv),
        "ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "machine": f"{platform.system()} {platform.release()} {platform.machine()}, Python {platform.python_version()}",
        "total": _sum(per),
        "per_snapshot": per,
    }
    out = Path(args.out) if args.out else RESULTS / f"replay-diff-{base_sha}-{head_sha}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    _print(doc)
    print(f"replay diff -> {out}")
    return 0


def _print(doc: dict) -> None:
    print(f"base {doc['base']['sha']}  head {doc['head']['sha']}  snapshots {', '.join(doc['snapshots'])}")
    for s, d in doc["per_snapshot"].items():
        print(f"== {s}")
        for m, v in d["metrics"].items():
            print(f"  {m:<20} {v['base']!s:>7} -> {v['head']!s:<7} ({v['delta']:+.4f})" if v["delta"] is not None
                  else f"  {m:<20} {v['base']!s:>7} -> {v['head']!s:<7}")
        print(f"  verdicts {d['verdicts']}")
        print(f"  feeds    changed for {d['feeds']['personas_whose_top12_changed']} personas, "
              f"{d['feeds']['articles_entered']} articles entered")
        print(f"  loss     {d['loss_by_stage']}")
        for side in ("base", "head"):
            print(f"  {side:<4}     {d['batches'][side]}")
    print(f"== total {doc['total']}")
    print(f"meter base {doc['base']['meter']}  head {doc['head']['meter']}")


if __name__ == "__main__":
    raise SystemExit(main())
