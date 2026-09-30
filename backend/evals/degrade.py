"""Prove each feed-quality metric can fail: inject a known fault, replay offline, re-score.

A metric that never moves is not evidence. Each fault below breaks one behaviour
on purpose and declares, before any measured run, which metrics must respond,
in which direction, and by how much. The matrix then replays every fault from
the committed LLM cache and checks the declarations.

Every fault acts DOWNSTREAM of the model call (on the verdicts, the ranked
feed, or the labels), so each request hashes to the same cache key as the clean
run. That is what keeps the whole matrix offline at $0, and it is checked, not
assumed: every fault run must touch exactly the clean run's cache keys and
raise zero offline cache misses.

Registration rules (fixed at registration, not after):
  * threshold: 0.05 for every target, the regression gate's own TOLERANCE
    (`tests/test_eval_gate.py`). A fault "is detected" iff it moves the metric
    further than the gate already tolerates.
  * statistic: the pooled mean over every persona-snapshot pair (10 personas x
    3 snapshots) where the metric is defined in both the clean and the faulted
    run, faulted minus clean. Pairs where either value is undefined are
    excluded and counted.
  * `unchanged` metrics must be identical on every pair; they are the checks
    that a fault acts only where it claims to.
  * `blind` faults predict the opposite: no metric moves by the threshold or
    more. A blind fault that passes is a named gap in the harness.
  * Sign counts and a one-sided exact sign test are reported, not asserted.

Prior exposure, stated because it matters: a scratch prototype run on
2026-09-30, before this registry existed, had already measured the cells listed
in each fault's `seen_before_registration`. Targets for those cells were chosen
with those numbers in view. Cells not listed there are out of sample.
"""
from __future__ import annotations

THRESHOLD = 0.05          # == tests/test_eval_gate.py TOLERANCE, fixed before any run

SNAPSHOTS = ("2026-08-31", "2026-08-31-quiet", "2026-09-02")

# Every per-persona metric the matrix measures. Higher is better except the
# two rates of junk in the feed.
METRICS = ("recall_at_k", "recall_at_retrieval", "need_to_know_recall", "followup_recall",
           "never_rate", "event_delivery", "needle_recall", "lookalike_rate",
           "judge_precision", "judge_recall")

PROD, PROTO = "prod", "proto-s0-legacy-v1"
_SEEN_ALL_PROD = [(PROD, s) for s in SNAPSHOTS]

REGISTRY: dict[str, dict] = {
    "rotate_verdicts": {
        "runner": PROD,
        "what": "Replays the list-position bug: each batch's verdict bodies shift one slot, so "
                "every article is judged by its neighbour's verdict. Any article id stays in place.",
        "targets": {"recall_at_k": "down", "never_rate": "up", "needle_recall": "down",
                    "judge_precision": "down", "judge_recall": "down"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": _SEEN_ALL_PROD,
    },
    "reverse_feed": {
        "runner": PROD,
        "what": "Reverses the final ranked feed, so the worst-ranked articles fill the top 12.",
        "targets": {"recall_at_k": "down", "needle_recall": "down"},
        "unchanged": ["recall_at_retrieval", "judge_precision", "judge_recall"],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "all_relevant": {
        "runner": PROD,
        "what": "The scorer marks every article relevant (score floored at 0.6).",
        "targets": {"judge_precision": "down", "never_rate": "up", "lookalike_rate": "up"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "swap_labels": {
        "runner": PROD,
        "what": "Grades persona i against persona i+1's labels: the ground truth is wrong, the feed is not.",
        "targets": {"recall_at_k": "down", "need_to_know_recall": "down", "followup_recall": "down",
                    "needle_recall": "down", "judge_precision": "down", "judge_recall": "down"},
        "unchanged": [],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "no_diversity": {
        "runner": PROD,
        "what": "Skips the diversity stage (_enforce_diversity returns its input).",
        "blind": True,
        "targets": {},
        "unchanged": ["recall_at_retrieval", "judge_precision", "judge_recall"],
        "seen_before_registration": [(PROD, "2026-08-31")],
    },
    "reverse_top_k": {
        "runner": PROD,
        "what": "Reverses the order inside the top 12 only. Every metric is a set over the top 12, "
                "so this is predicted invisible by construction.",
        "blind": True,
        "targets": {},
        "unchanged": list(METRICS),
        "seen_before_registration": [],
    },
    "proto_rotate_bodies": {
        "runner": PROTO,
        "what": "Prototype judge: verdict bodies shift one slot while each echoed id stays put, "
                "which defeats the id-keyed join.",
        "targets": {"recall_at_k": "down", "never_rate": "up", "needle_recall": "down",
                    "need_to_know_recall": "down", "judge_precision": "down", "judge_recall": "down"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": [(PROTO, "2026-08-31")],
    },
    "proto_rotate_list": {
        "runner": PROTO,
        "what": "Prototype judge: the whole verdict list rotates, ids travelling with their bodies. "
                "The id-keyed join should make this a no-op.",
        "blind": True,
        "targets": {},
        "unchanged": list(METRICS),
        "seen_before_registration": [(PROTO, "2026-08-31")],
    },
    "proto_no_forced": {
        "runner": PROTO,
        "what": "Prototype assembly ignores forced world-critical event slots.",
        "targets": {"event_delivery": "down"},
        "unchanged": ["recall_at_retrieval"],
        "seen_before_registration": [(PROTO, "2026-08-31")],
    },
}

# Not a matrix fault: an UPSTREAM change on purpose. It removes planted needles
# before scoring, which changes every scorer request, so the cache misses. The
# production scorer swallows the miss and falls back to keyword scoring. The
# gate must now fail it on raised offline misses.
GATE_CONTROL = {
    "name": "drop_plants_prefilter",
    "runner": PROD,
    "snapshot": "2026-08-31",
    "expect": "offline_misses_total > 0, so the gate's offline check fails",
    "seen_before_registration": [(PROD, "2026-08-31")],
}


# ---------------------------------------------------------------------------
# Everything below is implementation. It must not change the declarations
# above; `PREREGISTERED_SHA256` pins them to the registration commit.
# ---------------------------------------------------------------------------

import contextlib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import multiprocessing  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

K = 12
RESULTS = Path(__file__).resolve().parent / "results"
MATRIX_PATH = RESULTS / "degradation-matrix.json"
COMMAND = "cd backend && EVAL_OFFLINE=1 python -m evals.degrade --write"
# Metrics where a larger value is worse. Everything else in METRICS is better higher.
WORSE_WHEN_HIGHER = frozenset({"never_rate", "lookalike_rate"})
_ID_KEYS = ("article_id", "id")


def registry_digest() -> str:
    blob = json.dumps({"threshold": THRESHOLD, "snapshots": SNAPSHOTS, "metrics": METRICS,
                       "registry": REGISTRY, "gate_control": GATE_CONTROL}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


# sha256 of the declarations as committed in the registration commit (9f75fd09).
PREREGISTERED_SHA256 = "721d467b6bd12e1039cdce33ae57179dfbbe7d7892011e218588b5c1b2a21e8b"


# -- faults -------------------------------------------------------------------

def _rotate_bodies(verdicts: list) -> list:
    """Shift each verdict's content one slot; ids (if any) stay where they were."""
    if len(verdicts) < 2 or not all(isinstance(v, dict) for v in verdicts):
        return verdicts
    bodies = [{k: v for k, v in r.items() if k not in _ID_KEYS} for r in verdicts]
    bodies = bodies[1:] + bodies[:1]
    return [{**b, **{k: r[k] for k in _ID_KEYS if k in r}} for r, b in zip(verdicts, bodies)]


def _scorer_fault(transform):
    from evals import runners
    original = runners.ProductionRunner._service

    def _service(self):
        svc = original(self)
        score = svc.score_articles_batch

        async def faulted(batch, *a, **kw):
            return transform(await score(batch, *a, **kw))

        svc.score_articles_batch = faulted
        return svc

    return patch.object(runners.ProductionRunner, "_service", _service)


def _feed_fault(reorder):
    from app.services import feed_service
    original = feed_service.get_personalized_feed

    async def feed(*a, **kw):
        return reorder(list(await original(*a, **kw)))

    return patch.object(feed_service, "get_personalized_feed", feed)


def _judge_fault(transform):
    from evals import openai_backend
    original = openai_backend.make_judge

    def make_judge(*a, **kw):
        call = original(*a, **kw)

        def faulted(system, user):
            verdicts = call(system, user)
            # Only relevance verdicts carry "keep"; event-gravity calls pass through.
            if len(verdicts) > 1 and all(isinstance(v, dict) and "keep" in v for v in verdicts):
                return transform(verdicts)
            return verdicts

        return faulted

    return patch.object(openai_backend, "make_judge", make_judge)


def _swap_labels():
    from evals import run as evrun
    from evals.personas import load_personas
    order = list(load_personas(None).keys())
    original = evrun.load_labels

    def load_labels(snapshot, persona, include_needles=True):
        other = order[(order.index(persona) + 1) % len(order)]
        return original(snapshot, other, include_needles=include_needles)

    return patch.object(evrun, "load_labels", load_labels)


def _no_forced():
    from evals import legacy_s0
    original = legacy_s0.assemble

    def assemble(cands, rubric, size=20, max_per_intent=None, min_score=0.7, forced=None):
        return original(cands, rubric, size=size, max_per_intent=max_per_intent,
                        min_score=min_score, forced=[])

    return patch.object(legacy_s0, "assemble", assemble)


def _drop_plants_prefilter():
    from app.services import feed_service
    labels = Path(__file__).resolve().parent / "labels"
    titles = set()
    for snapshot in SNAPSHOTS:
        doc = json.loads((labels / snapshot / "needles.json").read_text())
        for persona, row in doc.items():
            if persona != "_doc":
                titles |= {n.get("title") for n in row.get("plant", [])}
    original = feed_service._prefilter_candidates

    def prefilter(candidates, profile, max_candidates=feed_service.MAX_LLM_CANDIDATES):
        return [c for c in original(candidates, profile, max_candidates=max_candidates)
                if c.get("title") not in titles]

    return patch.object(feed_service, "_prefilter_candidates", prefilter)


def _fault(name: str):
    if name == "none":
        return contextlib.nullcontext()
    if name == "rotate_verdicts":
        return _scorer_fault(_rotate_bodies)
    if name == "all_relevant":
        return _scorer_fault(lambda res: [{**r, "relevant": True, "score": max(float(r.get("score", 0)), 0.6)}
                                          for r in res])
    if name == "reverse_feed":
        return _feed_fault(lambda rows: rows[::-1])
    if name == "reverse_top_k":
        return _feed_fault(lambda rows: rows[:K][::-1] + rows[K:])
    if name == "no_diversity":
        from app.services import feed_service
        return patch.object(feed_service, "_enforce_diversity", lambda articles, *a, **kw: list(articles))
    if name == "swap_labels":
        return _swap_labels()
    if name == "proto_rotate_bodies":
        return _judge_fault(_rotate_bodies)
    if name == "proto_rotate_list":
        return _judge_fault(lambda v: v[1:] + v[:1])
    if name == "proto_no_forced":
        return _no_forced()
    if name == GATE_CONTROL["name"]:
        return _drop_plants_prefilter()
    raise ValueError(f"unknown fault {name!r}")


# -- one replay, in its own process -------------------------------------------

def measure(fault: str, runner: str, snapshot: str) -> dict:
    """Replay one (fault, runner, snapshot) offline and keep what the matrix needs."""
    os.environ["EVAL_OFFLINE"] = "1"
    os.environ.pop("OPENAI_API_KEY", None)
    from evals.run import evaluate
    t0 = time.perf_counter()
    with _fault(fault):
        doc = evaluate(runner, snapshot, k=K, verbose=False, write=False)
    s = doc["summary"]
    return {
        "fault": fault, "runner": runner, "snapshot": snapshot,
        "calls_total": s["calls_total"],
        "cache_misses_total": s["cache_misses_total"],
        "offline_misses_total": s["offline_misses_total"],
        "n_cache_keys": len(doc["cache_keys"]),
        "cache_keys_sha256": hashlib.sha256("\n".join(sorted(doc["cache_keys"])).encode()).hexdigest(),
        "notional_cost_usd": s["cost_usd_total"],
        "means": {m: s.get(f"{m}_mean") for m in METRICS},
        "per_persona": {p: {m: v.get(m) for m in METRICS} for p, v in sorted(doc["per_persona"].items())},
        "_summary": s,
        "_wall_s": round(time.perf_counter() - t0, 1),
    }


# -- statistics -----------------------------------------------------------------

def _sign_p(worse: int, better: int) -> float | None:
    """One-sided exact sign test: P(at least `worse` of n untied pairs move the bad way)."""
    n = worse + better
    if n == 0:
        return None
    return round(sum(math.comb(n, i) for i in range(worse, n + 1)) / 2 ** n, 4)


def pooled(clean: dict[str, dict], faulted: dict[str, dict], metric: str) -> dict:
    """Pool one metric over every persona-snapshot pair, faulted minus clean."""
    pairs, undefined, identical = [], 0, True
    for snapshot in SNAPSHOTS:
        c, f = clean[snapshot]["per_persona"], faulted[snapshot]["per_persona"]
        if set(c) != set(f):
            raise ValueError(f"persona sets differ on {snapshot}")
        for persona in sorted(c):
            cv, fv = c[persona][metric], f[persona][metric]
            identical = identical and cv == fv
            if cv is None or fv is None:
                undefined += 1
                continue
            pairs.append((cv, fv))
    higher_is_worse = metric in WORSE_WHEN_HIGHER
    worse = sum(1 for cv, fv in pairs if (fv > cv if higher_is_worse else fv < cv))
    better = sum(1 for cv, fv in pairs if (fv < cv if higher_is_worse else fv > cv))
    n = len(pairs)
    return {
        "n_pairs": n, "n_undefined": undefined, "identical": identical,
        "clean": round(sum(cv for cv, _ in pairs) / n, 4) if n else None,
        "faulted": round(sum(fv for _, fv in pairs) / n, 4) if n else None,
        "delta": round(sum(fv - cv for cv, fv in pairs) / n, 4) if n else None,
        "pairs_worse": worse, "pairs_better": better, "pairs_same": n - worse - better,
        "sign_test_p_worse": _sign_p(worse, better),
    }


def check(declaration: dict, stats: dict[str, dict], threshold: float = THRESHOLD) -> list[str]:
    """Every way a fault's measured result disagrees with its declaration."""
    failures = []
    for metric, direction in declaration.get("targets", {}).items():
        s = stats[metric]
        if not s["n_pairs"]:
            failures.append(f"{metric}: no pair where it is defined in both runs")
            continue
        moved = s["delta"] if direction == "up" else -s["delta"]
        if moved < threshold:
            failures.append(f"{metric}: declared {direction} by >= {threshold}, moved {s['delta']:+.4f}")
    for metric in declaration.get("unchanged", []):
        if not stats[metric]["identical"]:
            failures.append(f"{metric}: declared unchanged, delta {stats[metric]['delta']}")
    if declaration.get("blind"):
        for metric in METRICS:
            d = stats[metric]["delta"]
            if d is not None and abs(d) >= threshold:
                failures.append(f"{metric}: declared blind, moved {d:+.4f}")
    return failures


def offline_failures(run: dict, clean: dict) -> list[str]:
    """A fault run must replay exactly the clean run's cached requests, and nothing else."""
    out = []
    if run["offline_misses_total"] or run["cache_misses_total"]:
        out.append(f"{run['snapshot']}: {run['offline_misses_total']} raised, "
                   f"{run['cache_misses_total']} fetched cache misses")
    if run["cache_keys_sha256"] != clean["cache_keys_sha256"]:
        out.append(f"{run['snapshot']}: touched different cache keys than the clean run")
    return out


# -- the matrix -------------------------------------------------------------------

def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def _gate_regressions(summary: dict, snapshot: str) -> list[str]:
    from evals.metrics import GATED_METRICS, regression
    base = json.loads((RESULTS / "baseline-prod-llm.json").read_text())
    b = (base.get("snapshot_baselines") or {}).get(snapshot) or base["summary"]
    found = [regression(key, hib, b.get(key), summary.get(key), THRESHOLD) for key, hib in GATED_METRICS]
    return [f for f in found if f]


def compute_matrix(workers: int = 8) -> dict:
    from evals.metrics import offline_violations
    from evals.llm_cache import PRICING
    os.environ["EVAL_OFFLINE"] = "1"
    os.environ.pop("OPENAI_API_KEY", None)
    runners = sorted({d["runner"] for d in REGISTRY.values()})
    jobs = [("none", r, s) for r in runners for s in SNAPSHOTS]
    jobs += [(name, d["runner"], s) for name, d in REGISTRY.items() for s in SNAPSHOTS]
    jobs.append((GATE_CONTROL["name"], GATE_CONTROL["runner"], GATE_CONTROL["snapshot"]))

    t0 = time.perf_counter()
    # One fresh process per replay. A reused worker keeps the process-wide
    # client, so a second replay would see only the cache keys it touched first
    # and the per-run offline accounting would be wrong.
    with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"),
                             max_tasks_per_child=1) as pool:
        results = list(pool.map(measure, *zip(*jobs)))
    wall = round(time.perf_counter() - t0, 1)
    by = {(r["fault"], r["runner"], r["snapshot"]): r for r in results}

    def public(run: dict) -> dict:
        return {k: v for k, v in run.items() if not k.startswith("_")}

    clean = {r: {s: by[("none", r, s)] for s in SNAPSHOTS} for r in runners}
    faults = {}
    for name, decl in REGISTRY.items():
        runs = {s: by[(name, decl["runner"], s)] for s in SNAPSHOTS}
        stats = {m: pooled(clean[decl["runner"]], runs, m) for m in METRICS}
        failures = [f for s in SNAPSHOTS for f in offline_failures(runs[s], clean[decl["runner"]][s])]
        failures += check(decl, stats)
        faults[name] = {**decl, "passed": not failures, "failures": failures, "pooled": stats,
                        "runs": {s: public(runs[s]) for s in SNAPSHOTS}}

    ctl = by[(GATE_CONTROL["name"], GATE_CONTROL["runner"], GATE_CONTROL["snapshot"])]
    violations = offline_violations(ctl["_summary"])
    gate_control = {**GATE_CONTROL, "run": public(ctl),
                    "cache_misses_total": ctl["cache_misses_total"],
                    "offline_misses_total": ctl["offline_misses_total"],
                    "old_offline_check_passes": ctl["cache_misses_total"] == 0,
                    "new_offline_check_fails": bool(violations),
                    "offline_violations": violations,
                    "gate_regressions": _gate_regressions(ctl["_summary"], ctl["snapshot"])}

    shown = sorted({m for f in faults.values() if f["passed"] for m in f["targets"]})
    wall_by_run = {f"{r['fault']}/{r['runner']}/{r['snapshot']}": r["_wall_s"] for r in results}
    return {
        "kind": "degradation-matrix", "schema_version": 1,
        "registry_sha256": registry_digest(), "threshold": THRESHOLD,
        "snapshots": list(SNAPSHOTS), "metrics": list(METRICS), "k": K,
        "provenance": {
            "command": COMMAND, "git_sha": _git("rev-parse", "HEAD"),
            # Uncommitted code under evals/ or app/ would make git_sha a lie.
            "git_dirty": bool(_git("status", "--porcelain", "--", "evals", "app", ":(exclude)evals/results")),
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine": f"{platform.system()} {platform.release()} {platform.machine()}, "
                       f"Python {platform.python_version()}, {os.cpu_count()} CPUs",
            "workers": workers, "wall_s": wall, "wall_s_by_run": wall_by_run,
        },
        "cost": {
            "spent_usd": 0.0,
            "why": "every request replays from the committed cache; the real client is never built offline",
            "notional_replay_usd": round(sum(r["notional_cost_usd"] for r in results), 5),
            "notional_rates_usd_per_1m_tokens": {m: {"input": PRICING[m][0], "output": PRICING[m][1]}
                                                 for m in ("gpt-4o-mini", "text-embedding-3-small")},
        },
        "clean": {r: {s: public(clean[r][s]) for s in SNAPSHOTS} for r in runners},
        "faults": faults,
        "gate_control": gate_control,
        "coverage": {
            "metrics_shown_to_fail": shown,
            "metrics_never_shown_to_fail": [m for m in METRICS if m not in shown],
            "blind_predictions_confirmed": sorted(n for n, f in faults.items() if f.get("blind") and f["passed"]),
            "targeted_faults_passed": sorted(n for n, f in faults.items() if f["targets"] and f["passed"]),
        },
    }


def comparable(matrix: dict) -> dict:
    """The deterministic part of a matrix: everything except where and when it ran."""
    return {k: v for k, v in matrix.items() if k != "provenance"}


def _print(matrix: dict) -> None:
    for name, f in matrix["faults"].items():
        tag = "PASS" if f["passed"] else "FAIL"
        moved = ", ".join(f"{m} {f['pooled'][m]['clean']}->{f['pooled'][m]['faulted']}"
                          for m in (f["targets"] or ())) or "blind: " + ", ".join(
            f"{m} {f['pooled'][m]['delta']:+.3f}" for m in METRICS if f["pooled"][m]["delta"])
        print(f"{tag} {name:<20} {moved or 'no metric moved'}")
        for failure in f["failures"]:
            print(f"       {failure}")
    g = matrix["gate_control"]
    print(f"gate control {g['name']}: {g['offline_misses_total']} raised misses, "
          f"{g['cache_misses_total']} fetched; old check passes={g['old_offline_check_passes']}, "
          f"new check fails={g['new_offline_check_fails']}")
    print(f"metrics shown to fail: {matrix['coverage']['metrics_shown_to_fail']}")
    print(f"never shown to fail:   {matrix['coverage']['metrics_never_shown_to_fail']}")


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Replay every registered fault offline and check its declaration")
    ap.add_argument("--write", action="store_true", help=f"write {MATRIX_PATH.name}")
    ap.add_argument("--check", action="store_true", help="fail if the committed matrix differs from a fresh replay")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args(argv)
    if registry_digest() != PREREGISTERED_SHA256:
        print("registry differs from the pre-registered declarations", file=sys.stderr)
        return 2
    matrix = compute_matrix(workers=args.workers)
    _print(matrix)
    if args.write:
        MATRIX_PATH.write_text(json.dumps(matrix, indent=1, sort_keys=True) + "\n")
        print(f"matrix -> {MATRIX_PATH}")
    if args.check:
        committed = json.loads(MATRIX_PATH.read_text())
        if comparable(committed) != comparable(json.loads(json.dumps(matrix))):
            print("committed matrix differs from a fresh replay", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
