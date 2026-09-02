"""Diff two scorecards: what moved, and which must-see stories changed stage.

    python -m evals.compare results/abc1234-prod-llm-2026-08-31.json results/def5678-prod-llm-2026-08-31.json
    python -m evals.compare --latest prod-llm 2026-08-31      # two most recent for that runner/snapshot
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from evals.metrics import NUMERIC, load_scorecard

RESULTS = Path(__file__).resolve().parent / "results"


def _fmt(v) -> str:
    return "   -  " if v is None else f"{v:6.3f}"


def compare(a_path: Path, b_path: Path) -> int:
    a, b = load_scorecard(a_path), load_scorecard(b_path)
    print(f"A: {a_path.name}  ({a['git_sha']}, {a['created_at']})")
    print(f"B: {b_path.name}  ({b['git_sha']}, {b['created_at']})")
    print(f"\n{'metric (mean)':<28} {'A':>7} {'B':>7} {'delta':>8}")
    print("-" * 54)
    worse = 0
    for key in NUMERIC:
        av, bv = a["summary"].get(f"{key}_mean"), b["summary"].get(f"{key}_mean")
        d = None if av is None or bv is None else bv - av
        flag = ""
        if d is not None:
            bad = key in ("never_rate", "lookalike_rate", "false_major_rate", "latency_s")
            if (d < -0.02 and not bad) or (d > 0.02 and bad):
                flag = "  ▼"
                worse += 1
            elif abs(d) > 0.02:
                flag = "  ▲"
        print(f"{key:<28} {_fmt(av):>7} {_fmt(bv):>7} {('' if d is None else f'{d:+.3f}'):>8}{flag}")
    print(f"{'calls_total':<28} {a['summary']['calls_total']:>7} {b['summary']['calls_total']:>7}")
    print(f"{'cost_usd_total':<28} {a['summary']['cost_usd_total']:>7.4f} {b['summary']['cost_usd_total']:>7.4f}")

    print("\nmust-see stories that changed stage:")
    moved = 0
    for key in sorted(set(a["per_persona"]) & set(b["per_persona"])):
        la = {l["id"]: l for l in a["per_persona"][key]["losses"]}
        lb = {l["id"]: l for l in b["per_persona"][key]["losses"]}
        for i in sorted(set(la) | set(lb)):
            sa = la.get(i, {}).get("dropped_at", "IN FEED")
            sb = lb.get(i, {}).get("dropped_at", "IN FEED")
            if sa != sb:
                moved += 1
                title = (la.get(i) or lb.get(i))["title"][:60]
                print(f"  {key:<8} {sa:<18} -> {sb:<18} {title}")
    if not moved:
        print("  none")
    return worse


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--latest", nargs=2, metavar=("RUNNER", "SNAPSHOT"))
    args = ap.parse_args(argv)
    if args.latest:
        runner, snap = args.latest
        files = sorted(RESULTS.glob(f"*-{runner}-{snap}.json"), key=lambda p: p.stat().st_mtime)
        if len(files) < 2:
            sys.exit(f"need two scorecards for {runner} @ {snap}, found {len(files)}")
        a, b = files[-2], files[-1]
    elif len(args.paths) == 2:
        a, b = Path(args.paths[0]), Path(args.paths[1])
    else:
        ap.error("give two scorecard paths or --latest RUNNER SNAPSHOT")
    compare(a, b)


if __name__ == "__main__":
    main()
