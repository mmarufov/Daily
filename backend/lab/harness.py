"""Run one candidate parser over the case suite and emit prediction records.

This is the process that runs inside the isolation boundary. It is the only
thing the candidate's code can reach, and what it emits is deliberately
impoverished:

    {"case_id": ..., "outcome": "parsed"|"refused"|"crashed"|"timeout",
     "association": {article_id: {relevant, score}} | null,
     "refusal_kind": str | null, "error": str | null, "ms": float}

There is **no field for a grade**. No `passed`, no score, no meaning attached
to the exit code. A candidate that writes `{"passed": true}` into its return
value produces a record that ignores it, because the record is built here from
a fixed set of keys. The verdict is computed later, by trusted code, in another
language, outside this process.

    python -m lab.harness --candidate lab/contract/versions/keyed_v2.py \
        --cases lab/cases/observed.json lab/cases/synthetic.json \
        --out /tmp/records.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math as _math
import signal
import sys
import time
import traceback
from pathlib import Path
from typing import Any

#: Bounded runtime per case. A candidate that hangs yields `timeout`, which the
#: evaluator treats as a failed case — never as an absent one.
DEFAULT_CASE_TIMEOUT_S = 5

#: Bounded output. Records are capped so a candidate cannot exhaust the
#: transport by emitting an enormous association.
MAX_REASON_CHARS = 500
MAX_RECORDS = 5000


class _CaseTimeout(Exception):
    pass


def _alarm(_signum: int, _frame: Any) -> None:
    raise _CaseTimeout()


def load_candidate(path: Path) -> Any:
    """Import the candidate, having first taken away what it could misuse.

    `exec_module` runs the candidate's module-level code in this process, and
    an audit demonstrated the consequence: that code could read `sys.argv`,
    find `--out`, write a complete bundle of its own choosing there and
    `os._exit(0)`. `parse()` never ran and the forged bundle was graded and
    accepted.

    Two things changed. `argv` is scrubbed here, so the shortcut is gone. And
    the bundle no longer travels through a file on this filesystem at all --
    it is framed onto stdout and assembled by a parent in another language on
    another machine, so there is nothing on this side for a candidate to
    overwrite.

    What is still true, and worth saying plainly rather than implying
    otherwise: module-level code in a candidate file *is* the candidate. It
    can emit whatever records it likes. That is no different from a `parse()`
    that lies, and it is useless for the same reason -- `upload-set.ts` ships
    no expectations, so nothing in this microVM knows which answers pass.
    """
    real_argv = sys.argv
    sys.argv = ["lab-candidate"]
    try:
        return _import_candidate(path)
    finally:
        sys.argv = real_argv


def _import_candidate(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("lab_candidate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load candidate at {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["lab_candidate"] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "parse"):
        raise RuntimeError("candidate module defines no parse()")
    return module


def normalise_association(raw: Any, articles: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Project whatever the candidate returned onto the record's fixed shape.

    Anything unrecognised is dropped rather than propagated. This is the point
    at which a candidate's extra keys — including any self-assessment — stop
    existing.
    """
    if not isinstance(raw, list):
        return None
    out: dict[str, Any] = {}
    for entry in raw[: len(articles) + 8]:
        if not isinstance(entry, dict):
            continue
        article_id = entry.get("article_id")
        if not isinstance(article_id, str):
            continue
        raw = entry.get("score")
        usable = isinstance(raw, (int, float)) and not isinstance(raw, bool)
        score = float(raw) if usable else None
        # A record must be valid JSON, and NaN/Infinity are not. A candidate
        # that produced one is recorded as having produced no usable score,
        # which can never equal an expected finite value — so the case still
        # fails, for the right reason, instead of emitting `NaN` into the
        # artifact and breaking every downstream reader.
        if score is not None and not _math.isfinite(score):
            score = None
        out[article_id] = {
            "relevant": bool(entry.get("relevant")),
            "score": score,
            "reason": str(entry.get("reason", ""))[:MAX_REASON_CHARS],
        }
    return out


def run_case(module: Any, case: dict[str, Any], timeout_s: int) -> dict[str, Any]:
    articles = case["articles"]
    started = time.perf_counter()
    use_alarm = hasattr(signal, "SIGALRM")
    if use_alarm:
        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(timeout_s)
    try:
        result = module.parse(articles, case["response"])
        outcome, association, refusal_kind, error = "crashed", None, None, None
        if isinstance(result, dict):
            if result.get("ok") is True:
                outcome = "parsed"
                association = normalise_association(result.get("verdicts"), articles)
                if association is None:
                    outcome, error = "crashed", "parse() returned ok with no verdict list"
            elif result.get("ok") is False:
                refusal = result.get("refusal")
                if isinstance(refusal, dict) and isinstance(refusal.get("kind"), str):
                    outcome, refusal_kind = "refused", refusal["kind"]
                else:
                    error = "parse() refused without a refusal kind"
            else:
                error = "parse() returned a dict with no ok field"
        else:
            error = f"parse() returned {type(result).__name__}"
    except _CaseTimeout:
        outcome, association, refusal_kind = "timeout", None, None
        error = f"exceeded {timeout_s}s"
    except Exception:
        outcome, association, refusal_kind = "crashed", None, None
        error = traceback.format_exc(limit=3)[:MAX_REASON_CHARS]
    finally:
        if use_alarm:
            signal.alarm(0)

    return {
        "case_id": case["case_id"],
        "outcome": outcome,
        "association": association,
        "refusal_kind": refusal_kind,
        "error": error,
        "ms": round((time.perf_counter() - started) * 1000, 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run a candidate parser over the case suite.")
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--cases", nargs="+", required=True)
    # `--out` writes a file and is for `run_known.py`, which runs only
    # implementations committed to this repository. `--stdout` frames the
    # bundle onto stdout for a parent outside this machine, and is what the
    # sandbox uses: an untrusted candidate must not be able to hand the
    # grader a file it wrote itself.
    ap.add_argument("--out")
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--frame", default="")
    ap.add_argument("--timeout", type=int, default=DEFAULT_CASE_TIMEOUT_S)
    args = ap.parse_args()
    if not args.out and not args.stdout:
        print("one of --out or --stdout is required", file=sys.stderr)
        return 2

    cases: list[dict[str, Any]] = []
    for path in args.cases:
        payload = json.loads(Path(path).read_text())
        cases.extend(payload["cases"])
    if len(cases) > MAX_RECORDS:
        print(f"refusing to run {len(cases)} cases (cap {MAX_RECORDS})", file=sys.stderr)
        return 2

    module = load_candidate(Path(args.candidate))
    version_id = getattr(module, "VERSION_ID", "unknown")
    protocol = getattr(module, "PROTOCOL", "unknown")

    started = time.perf_counter()
    records = [run_case(module, case, args.timeout) for case in cases]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 3)

    bundle = (
        json.dumps(
            {
                "records_version": 1,
                # Self-declared, and treated as a claim rather than a fact: the
                # evaluator checks the protocol against the case, not against
                # what the candidate says about itself.
                "declared_version_id": version_id,
                "declared_protocol": protocol,
                "python": sys.version.split()[0],
                "n_cases": len(cases),
                "elapsed_ms": elapsed_ms,
                "records": records,
            },
            sort_keys=True,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    )

    if args.stdout:
        # Framed, because a candidate is free to print. The markers are not a
        # secret and do not pretend to be: a candidate that forges a framed
        # bundle has done exactly what a lying `parse()` does, and is defeated
        # by the same thing -- it does not know the answers. What the framing
        # buys is that honest noise on stdout cannot corrupt an honest run.
        sys.stdout.write(
            "<<<LAB-RECORDS:" + args.frame + ">>>\n" + bundle + "<<<END:" + args.frame + ">>>\n"
        )
        sys.stdout.flush()
    else:
        Path(args.out).write_text(bundle)
        print(f"{len(records)} records in {elapsed_ms}ms -> {args.out}")
    # Exit code carries no verdict. It is 0 whenever the harness itself ran.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
