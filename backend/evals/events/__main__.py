"""Evaluate existing artifacts without mutating labels or calling a provider."""
import argparse
import json
from pathlib import Path

from .evaluate import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset", "predictions", "protocol", "bindings", "execution", "outcome-reviews", "adversarial"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--split", choices=["development", "holdout"], default="holdout")
    args = parser.parse_args()
    load = lambda name: json.loads(getattr(args, name).read_text())
    report = evaluate(load("dataset"), load("predictions"), load("protocol"),
                      bindings=load("bindings"), split=args.split, execution=load("execution"),
                      outcome_reviews=load("outcome_reviews"), adversarial=load("adversarial"))
    print(json.dumps(report, indent=2, allow_nan=False))
    raise SystemExit(0 if report["quality_gates_passed"] else 1)


if __name__ == "__main__":
    main()
