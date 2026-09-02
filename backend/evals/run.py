"""Run a feed system against a frozen snapshot and score it against the labels.

    python -m evals.run --runner prod          --snapshot 2026-08-31
    python -m evals.run --runner prod-fallback --snapshot 2026-08-31 --persona ray wei
    python -m evals.run --runner proto         --all-snapshots
    EVAL_OFFLINE=1 python -m evals.run --runner prod --snapshot 2026-08-31   # no key, cache only

Writes `evals/results/<sha7>-<runner>-<snapshot>.json`, the scorecard that
`compare.py` diffs and `tests/test_eval_gate.py` enforces.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.label import load_events, load_labels, pool_with_needles
from evals.metrics import aggregate, git_sha, score_build, write_scorecard
from evals.personas import load_personas
from evals.runners import get_runner
from evals.snapshot import frozen_now, list_snapshots, load_snapshot

RESULTS = Path(__file__).resolve().parent / "results"


def evaluate(runner_name: str, snapshot: str, persona_keys: list[str] | None = None, k: int = 12,
             needles: bool = True, verbose: bool = True, out_dir: Path = RESULTS,
             write: bool = True) -> dict:
    from evals.openai_backend import client

    snap = load_snapshot(snapshot)
    docs, now = snap["articles"], frozen_now(snap)
    quiet = bool((snap.get("snapshot") or {}).get("quiet"))
    personas = load_personas(persona_keys)
    events = load_events(snapshot)
    runner = get_runner(runner_name, k=k)
    kind = "prod" if runner_name.startswith("prod") else "proto"

    per: dict[str, dict] = {}
    touched_before = set(client().touched)
    for key, persona in personas.items():
        pool = pool_with_needles(snapshot, key, docs, now) if needles else list(docs)
        labels = load_labels(snapshot, key, include_needles=needles)
        result = runner.build(persona, pool, now)
        m = score_build(result, labels, events, pool, k=k, kind=kind, quiet=quiet)
        per[key] = m
        if verbose:
            _print_persona(key, m, pool)

    summary = aggregate(per)
    if verbose:
        _print_summary(runner.name, snapshot, summary)
    keys = sorted(set(client().touched) - touched_before) if not write else sorted(client().touched)
    doc = {"runner": runner.name, "snapshot": snapshot, "k": k, "summary": summary, "per_persona": per,
           "cache_keys": keys}
    if write:
        path = out_dir / f"{git_sha()}-{runner.name}-{snapshot}.json"
        write_scorecard(path, runner.name, snapshot, per, summary, keys, k,
                        meta={"needles": needles, "quiet": quiet})
        doc["path"] = str(path)
        if verbose:
            print(f"scorecard -> {path}")
    return doc


def _fmt(v) -> str:
    return "  -  " if v is None else (f"{v:5.2f}" if isinstance(v, float) else f"{v:>5}")


def _print_persona(key: str, m: dict, pool: list[dict]) -> None:
    print("=" * 108)
    print(f"{key:<9} must_see={m['n_must_see']:<3} recall@k={_fmt(m['recall_at_k'])} "
          f"retrieval={_fmt(m['recall_at_retrieval'])} ntk={_fmt(m['need_to_know_recall'])} "
          f"followup={_fmt(m['followup_recall'])} "
          f"never={_fmt(m['never_rate'])} events={_fmt(m['event_delivery'])} "
          f"needles={_fmt(m['needle_recall'])}/{_fmt(m['lookalike_rate'])} "
          f"judgeP/R={_fmt(m['judge_precision'])}/{_fmt(m['judge_recall'])} "
          f"calls={m['calls']} ${m['cost_usd']:.4f} {m['latency_s']:.1f}s")
    print(f"  loss by stage: {m['loss_by_stage'] or '-'}    drops: {m['drop_counts']}")
    for row in m["feed"]:
        lab = {"must_see": "MUST", "fine": "fine", "never": "NEVR", None: "    "}.get(row["label"], "????")
        sc = row["score"]
        print(f"  {row['rank']:>2} {lab} {sc if sc is None else f'{sc:4.2f}':>5} {str(row['source'])[:16]:<17} {row['title'][:66]}")
    if m["losses"]:
        print("  missed must_see:")
        for l in m["losses"][:8]:
            print(f"     [{l['dropped_at']:<18}] {l['title'][:60]}  {('— ' + l['reason'][:40]) if l['reason'] else ''}")


def _print_summary(runner: str, snapshot: str, s: dict) -> None:
    print("=" * 108)
    print(f"{runner} @ {snapshot}   personas={s['personas']}   calls={s['calls_total']} "
          f"(max/persona {s['calls_max_per_persona']})   cost=${s['cost_usd_total']:.4f}   "
          f"cache misses={s['cache_misses_total']}")
    for key in ("recall_at_k", "recall_at_retrieval", "need_to_know_recall", "followup_recall", "never_rate", "event_delivery",
                "needle_recall", "lookalike_rate", "judge_precision", "judge_recall"):
        print(f"  {key:<22} mean={_fmt(s[key + '_mean'])}  min={_fmt(s[key + '_min'])}")
    print(f"  loss by stage (all personas): {s['loss_by_stage']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Evaluate a feed system against labelled snapshots")
    ap.add_argument("--runner", default="prod", choices=["prod", "prod-fallback", "proto", "proto-bm25"])
    ap.add_argument("--snapshot")
    ap.add_argument("--all-snapshots", action="store_true")
    ap.add_argument("--persona", nargs="*")
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--no-needles", action="store_true")
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    snapshots = [e["name"] for e in list_snapshots()] if args.all_snapshots else [args.snapshot]
    if not snapshots or snapshots == [None]:
        ap.error("--snapshot or --all-snapshots required")
    for s in snapshots:
        evaluate(args.runner, s, args.persona or None, k=args.k, needles=not args.no_needles,
                 verbose=not args.quiet, out_dir=Path(args.out))


if __name__ == "__main__":
    main()
