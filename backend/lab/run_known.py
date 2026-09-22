"""Run every known implementation over the case suite and commit the records.

"Known" means: written in this repository, reviewed, and in version control.
These are the only implementations allowed to run outside the isolation
boundary — see `web/lib/lab/runner.ts`, which refuses to execute anything else
locally. Arbitrary candidate code goes to the sandbox.

    python -m lab.run_known
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
CASES = [str(LAB / "cases" / "observed.json"), str(LAB / "cases" / "synthetic.json")]

KNOWN: dict[str, Path] = {
    "positional-v0": LAB / "contract" / "versions" / "positional_v0.py",
    "count-guard-v1": LAB / "contract" / "versions" / "count_guard_v1.py",
    "keyed-v2": LAB / "contract" / "versions" / "keyed_v2.py",
    "control-lenient-keyed": LAB / "contract" / "controls" / "lenient_keyed.py",
    "control-self-reporting": LAB / "contract" / "controls" / "self_reporting.py",
    "control-zero-filling": LAB / "contract" / "controls" / "zero_filling.py",
}


def main() -> int:
    out_dir = LAB / "records"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, path in KNOWN.items():
        target = out_dir / f"{name}.json"
        result = subprocess.run(
            [sys.executable, "-m", "lab.harness", "--candidate", str(path),
             "--cases", *CASES, "--out", str(target)],
            cwd=str(LAB.parent), capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  {name}: FAILED\n{result.stderr}", file=sys.stderr)
            return 1
        bundle = json.loads(target.read_text())
        counts: dict[str, int] = {}
        for record in bundle["records"]:
            counts[record["outcome"]] = counts.get(record["outcome"], 0) + 1
        print(f"  {name:26} {bundle['n_cases']:>3} cases  {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
