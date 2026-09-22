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
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=DEFAULT_CASE_TIMEOUT_S)
    args = ap.parse_args()

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

    Path(args.out).write_text(
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
    # Exit code carries no verdict. It is 0 whenever the harness itself ran.
    print(f"{len(records)} records in {elapsed_ms}ms -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
