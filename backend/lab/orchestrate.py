"""A resumable orchestrator for one Lab run.

State lives in an append-only event log on disk, never in this process. Every
invocation reads the log, folds it into a state, and continues from there — so
being killed is not a special case, it is just an invocation that stopped
early.

Fault injection
---------------
`--kill-after <event>` makes the process SIGKILL *itself* immediately after
persisting that event. This is a labelled, deliberate fault: it produces a real
process death at a real point in the state machine, which is what makes the
recovery that follows a real recovery rather than a story about one. Runs
created this way are marked `fault_injected` and the UI says so.

    python -m lab.orchestrate --candidate keyed-v2 --kill-after attempt-started
    python -m lab.orchestrate --candidate keyed-v2          # resumes
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LAB = Path(__file__).resolve().parent
CASES = [str(LAB / "cases" / "observed.json"), str(LAB / "cases" / "synthetic.json")]
EXPERIMENT = "article-to-verdict-association"

CANDIDATES: dict[str, Path] = {
    "positional-v0": LAB / "contract" / "versions" / "positional_v0.py",
    "count-guard-v1": LAB / "contract" / "versions" / "count_guard_v1.py",
    "keyed-v2": LAB / "contract" / "versions" / "keyed_v2.py",
    "control-lenient-keyed": LAB / "contract" / "controls" / "lenient_keyed.py",
    "control-self-reporting": LAB / "contract" / "controls" / "self_reporting.py",
    "control-zero-filling": LAB / "contract" / "controls" / "zero_filling.py",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def spec_hash() -> str:
    path = LAB / "runs" / ".spec-hash"
    return path.read_text().strip() if path.exists() else "unknown0"


def read_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append(path: Path, event: dict[str, Any], kill_after: str | None) -> None:
    """Persist an event, then honour an injected fault.

    The write is flushed and fsynced *before* the process may die, which is the
    property that makes recovery possible at all: an event that was going to be
    written either is written, or the step is retried from the previous state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps(event) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    if kill_after is not None and event["type"] == kill_after:
        print(f"[fault injection] SIGKILL after persisting {event['type']}", flush=True)
        os.kill(os.getpid(), signal.SIGKILL)


def phase_of(events: list[dict[str, Any]]) -> str:
    phase = "preparing"
    for event in events:
        kind = event["type"]
        if kind == "attempt-started":
            phase = "running"
        elif kind == "records-received":
            phase = "evaluating"
        elif kind in {"cancelled", "failed"}:
            return kind
    return phase


def open_attempt(events: list[dict[str, Any]]) -> str | None:
    """An attempt that started and never reported. Recovery has to resolve it."""
    started = {e["attempt_id"] for e in events if e["type"] == "attempt-started"}
    ended = {e["attempt_id"] for e in events if e["type"] == "attempt-ended"}
    remaining = sorted(started - ended)
    return remaining[-1] if remaining else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", default="keyed-v2", choices=sorted(CANDIDATES))
    ap.add_argument("--kill-after")
    ap.add_argument("--tag", default="interrupted")
    args = ap.parse_args()

    source_path = CANDIDATES[args.candidate]
    source_sha = hashlib.sha256(source_path.read_bytes()).hexdigest()
    rid = f"{EXPERIMENT}__{args.candidate}__{source_sha[:12]}__{spec_hash()[:8]}"

    runs = LAB / "runs"
    log = runs / f"{args.candidate}-{args.tag}.events.jsonl"
    records_path = runs / f"{args.candidate}-{args.tag}.records.json"
    events = read_log(log)

    if not events:
        append(log, {"type": "created", "run_id": rid, "candidate_id": args.candidate,
                     "at": now(), "spec_hash": spec_hash()}, args.kill_after)
        append(log, {"type": "scope-checked", "at": now(), "allowed": True,
                     "detail": "backend/lab/contract/candidate.py — within the allowed patch scope"},
               args.kill_after)
        events = read_log(log)

    if phase_of(events) in {"cancelled", "failed", "evaluating"}:
        print(f"run is already {phase_of(events)}; nothing to do")
        return 0

    # Recovery: an attempt that started and never reported. Whether the work
    # completed remotely is not knowable from here, so it is recorded as
    # unknown rather than assumed to have failed.
    orphan = open_attempt(events)
    if orphan is not None:
        append(log, {
            "type": "attempt-ended", "attempt_id": orphan, "at": now(),
            "status": "unknown-outcome",
            "note": ("orchestrator died with this attempt in flight; records file "
                     f"{'present' if records_path.exists() else 'absent'} on recovery"),
        }, args.kill_after)
        events = read_log(log)
        print(f"recovered: {orphan} resolved as unknown-outcome")

    ordinal = sum(1 for e in events if e["type"] == "attempt-started") + 1
    attempt = f"{rid}#{ordinal:02d}"
    append(log, {"type": "attempt-started", "attempt_id": attempt,
                 "runner": "local-known", "at": now()}, args.kill_after)

    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-m", "lab.harness", "--candidate", str(source_path),
         "--cases", *CASES, "--out", str(records_path)],
        cwd=str(LAB.parent), capture_output=True, text=True,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    if completed.returncode != 0:
        append(log, {"type": "attempt-ended", "attempt_id": attempt, "at": now(),
                     "status": "failed", "note": completed.stderr[:300]}, args.kill_after)
        append(log, {"type": "failed", "at": now(), "error": "harness exited non-zero"}, args.kill_after)
        return 1

    bundle = json.loads(records_path.read_text())
    append(log, {"type": "attempt-ended", "attempt_id": attempt, "at": now(), "status": "succeeded",
                 "note": f"completed {bundle['n_cases']} cases in {elapsed_ms}ms"}, args.kill_after)
    append(log, {"type": "records-received", "attempt_id": attempt, "at": now(),
                 "n_records": len(bundle["records"])}, args.kill_after)
    print(f"{attempt} completed {bundle['n_cases']} cases in {elapsed_ms}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
