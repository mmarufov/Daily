"""Offline S3 label preparation and conservative quality gates.

No provider calls or generated ground truth. Prepare a review queue from verified
S0 snapshots; adjudicate article facets and story membership before splitting.
Unreviewed model-authored labels cannot satisfy the independent-review gate. Unknown model
outcomes count in recall/coverage denominators. This report is quality evidence,
not authorization to deploy or evidence of production lifecycle/latency safety.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from evals.snapshot import load_snapshot, verify_snapshot

ROOT = Path(__file__).resolve().parent / "understanding"
REVIEW_FIELDS = ("kind", "primary_topic", "entity_ids", "place_ids", "promotional")


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def prepare_review_queue(snapshots: list[str], count: int = 600) -> dict:
    if count < 600:
        raise ValueError("The initial review queue requires at least 600 distinct articles")
    distinct: dict[str, dict] = {}
    for name in sorted(set(snapshots)):
        if not verify_snapshot(name):
            raise ValueError(f"Snapshot {name!r} failed its committed content hash")
        for article in load_snapshot(name)["articles"]:
            # Repeated snapshots and quiet-day derivatives must not count twice.
            identity = article.get("url") or digest([article.get("title"), article.get("source")])
            if identity in distinct:
                continue
            distinct[identity] = {
                "article_id": f"{name}:{article['id']}", "snapshot": name,
                "snapshot_article_id": article["id"], "input_sha256": digest(article),
                "url": article.get("url"), "title": article.get("title"),
                "source": article.get("source"), "published_at": article.get("published_at"),
                "language": article.get("language") or "unknown",
                "evidence_tier": "body" if article.get("content") else "excerpt" if article.get("summary") else "title_only",
                "review_status": "unreviewed", "label_provenance": None,
                "reviewed_by": None, "story_id": None, "split": None, "labels": None,
            }
    if len(distinct) < count:
        raise ValueError(f"Only {len(distinct)} distinct articles; need {count}")
    # Round-robin source/date/evidence slices; reproducible, no model judgments.
    buckets: dict[tuple, list] = defaultdict(list)
    for row in distinct.values():
        buckets[(row["snapshot"], row["source"] or "", row["language"], row["evidence_tier"])].append(row)
    for rows in buckets.values():
        rows.sort(key=lambda row: digest(row["article_id"]))
    queue = []
    while len(queue) < count:
        for bucket in sorted(buckets):
            if buckets[bucket]:
                queue.append(buckets[bucket].pop())
                if len(queue) == count:
                    break
    return {
        "schema_version": 1, "status": "awaiting_independent_labels",
        "note": "Sampling metadata is not ground truth. Verify language, evidence eligibility, facets and same-development story groups before splitting. S0 relevance labels are not S3 labels.",
        "snapshots": sorted(set(snapshots)), "article_count": len(queue),
        "reviewed_count": 0, "articles": queue,
    }


def _reviewed(rows: list[dict]) -> None:
    if not rows:
        raise ValueError("No reviewed articles")
    ids = [row["article_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate article IDs")
    urls = [row["url"].split("#", 1)[0] for row in rows if row.get("url")]
    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate article URLs; repeated snapshots are not independent evidence")
    for row in rows:
        if (row.get("review_status") != "adjudicated"
                or row.get("label_provenance") not in {"human", "agent"}
                or not row.get("reviewed_by") or not row.get("story_id")):
            raise ValueError(f"Article {row['article_id']} lacks independent adjudicated labels/story membership")
        labels = row.get("labels") or {}
        if any(key not in labels for key in REVIEW_FIELDS):
            raise ValueError(f"Incomplete facet labels for {row['article_id']}")
        if type(labels["promotional"]) is not bool:
            raise ValueError("Promotional ground truth must be boolean")
        for field in ("kind", "primary_topic"):
            if labels[field] is not None and (not isinstance(labels[field], str) or not labels[field] or labels[field] == "unknown"):
                raise ValueError(f"Invalid {field} ground truth; use null for unsupported labels")
        for field in ("entity_ids", "place_ids"):
            values = labels[field]
            if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values) or len(set(values)) != len(values):
                raise ValueError(f"Invalid {field} ground truth")
        if not row.get("language") or row["language"] == "unknown" or not row.get("evidence_tier"):
            raise ValueError("Adjudication must establish language and evidence tier")


def assign_story_splits(rows: list[dict], seed: str, holdout_fraction: float = 0.25) -> list[dict]:
    """Only reviewed same-development IDs may define leakage boundaries."""
    _reviewed(rows)
    if not seed or not 0 < holdout_fraction < 1:
        raise ValueError("A frozen seed and nonempty development/holdout fractions are required")
    groups = sorted({row["story_id"] for row in rows}, key=lambda value: digest([seed, value]))
    if len(groups) < 2:
        raise ValueError("At least two independent stories are required")
    n_holdout = max(1, min(len(groups) - 1, math.ceil(len(groups) * holdout_fraction)))
    holdout = set(groups[:n_holdout])
    return [{**row, "split": "holdout" if row["story_id"] in holdout else "development"} for row in rows]


def rate(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def wilson_interval(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    scale = 1 + z * z / total
    center = (p + z * z / (2 * total)) / scale
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / scale
    return [max(0.0, center - half), min(1.0, center + half)]


def _classification(rows: list[dict], predictions: dict[str, dict], field: str) -> dict:
    # The runtime kind contract represents abstention as 'unknown'. It cannot
    # count as a classification or as coverage in the evaluation.
    predictions = {key: {**value, field: None if value.get(field) == "unknown" else value.get(field)}
                   for key, value in predictions.items()}
    supported = [row for row in rows if row["labels"][field] is not None]
    correct = sum(predictions.get(row["article_id"], {}).get(field) == row["labels"][field] for row in supported)
    predicted = sum(predictions.get(row["article_id"], {}).get(field) is not None for row in rows)
    classes = sorted({row["labels"][field] for row in supported})
    per_class = {}
    for label in classes:
        true = sum(row["labels"][field] == label for row in rows)
        proposed = sum(predictions.get(row["article_id"], {}).get(field) == label for row in rows)
        tp = sum(row["labels"][field] == label and predictions.get(row["article_id"], {}).get(field) == label for row in rows)
        per_class[label] = {"support": true, "predicted": proposed, "f1": 2 * tp / (true + proposed)}
    return {"precision": rate(correct, predicted), "recall": rate(correct, len(supported)),
            "coverage": rate(predicted, len(rows)), "classes": per_class,
            "macro_f1": sum(item["f1"] for item in per_class.values()) / len(classes) if classes else None}


def _resolution(rows: list[dict], predictions: dict[str, dict], field: str) -> dict:
    correct = proposed = resolvable = 0
    for row in rows:
        true = set(row["labels"][field])
        pred = set(predictions.get(row["article_id"], {}).get(field) or [])
        correct += len(true & pred)
        proposed += len(pred)
        resolvable += len(true)
    return {"precision": rate(correct, proposed), "recall": rate(correct, resolvable),
            "unresolved_resolvable": resolvable - correct}


def story_metrics(rows: list[dict], predictions: dict[str, dict]) -> dict:
    true_groups: dict[str, set] = defaultdict(set)
    pred_groups: dict[tuple, set] = defaultdict(set)
    for row in rows:
        article_id = row["article_id"]
        true_groups[row["story_id"]].add(article_id)
        predicted = predictions.get(article_id, {}).get("story_id")
        pred_groups[("group", predicted) if predicted else ("singleton", article_id)].add(article_id)
    true_by_id = {article_id: group for group in true_groups.values() for article_id in group}
    pred_by_id = {article_id: group for group in pred_groups.values() for article_id in group}
    pair = lambda n: n * (n - 1) // 2
    actual_pairs = sum(pair(len(group)) for group in true_groups.values())
    predicted_pairs = sum(pair(len(group)) for group in pred_groups.values())
    correct_pairs = sum(pair(len(group & true)) for group in pred_groups.values() for true in true_groups.values())
    count = len(rows)
    return {"precision": rate(correct_pairs, predicted_pairs), "recall": rate(correct_pairs, actual_pairs),
            "false_merges": predicted_pairs - correct_pairs, "missed_merges": actual_pairs - correct_pairs,
            "bcubed_precision": sum(len(true_by_id[i] & pred_by_id[i]) / len(pred_by_id[i]) for i in true_by_id) / count if count else None,
            "bcubed_recall": sum(len(true_by_id[i] & pred_by_id[i]) / len(true_by_id[i]) for i in true_by_id) / count if count else None}


def evaluate(rows: list[dict], predictions: dict[str, dict], manifest: dict, *, split: str = "holdout") -> dict:
    _reviewed(rows)
    if split not in {"development", "holdout"}:
        raise ValueError("Invalid evaluation split")
    all_ids = {row["article_id"] for row in rows}
    if not set(predictions).issubset(all_ids):
        raise ValueError("Predictions contain unknown articles")
    for prediction in predictions.values():
        if not isinstance(prediction, dict):
            raise ValueError("Each prediction must be an object")
        for field in ("kind", "primary_topic", "story_id"):
            value = prediction.get(field)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"Invalid predicted {field}")
        for field in ("entity_ids", "place_ids"):
            values = prediction.get(field, [])
            if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values) or len(set(values)) != len(values):
                raise ValueError(f"Invalid predicted {field}")
        if "auto_suppressed" in prediction and type(prediction["auto_suppressed"]) is not bool:
            raise ValueError("auto_suppressed must be boolean")
    story_splits: dict[str, set] = defaultdict(set)
    for row in rows:
        if row.get("split") not in {"development", "holdout"}:
            raise ValueError("All reviewed rows need a frozen split")
        story_splits[row["story_id"]].add(row["split"])
    if any(len(splits) != 1 for splits in story_splits.values()):
        raise ValueError("Story leakage between development and holdout")
    selected = [row for row in rows if row["split"] == split]
    if not selected:
        raise ValueError("Selected split is empty")
    metrics = {"kind": _classification(selected, predictions, "kind"),
               "primary_topic": _classification(selected, predictions, "primary_topic"),
               "entities": _resolution(selected, predictions, "entity_ids"),
               "places": _resolution(selected, predictions, "place_ids"),
               "stories": story_metrics(selected, predictions)}
    true_promo = sum(row["labels"]["promotional"] for row in selected)
    suppressed = [row for row in selected if predictions.get(row["article_id"], {}).get("auto_suppressed") is True]
    correct_promo = sum(row["labels"]["promotional"] for row in suppressed)
    metrics["promotion"] = {"precision": rate(correct_promo, len(suppressed)), "recall": rate(correct_promo, true_promo),
                            "legitimate_falsely_suppressed": len(suppressed) - correct_promo,
                            "precision_interval_95": wilson_interval(correct_promo, len(suppressed))}
    slices = defaultdict(list)
    for row in selected:
        slices[f"{row['language']}:{row['evidence_tier']}"].append(row)
    slice_metrics = {name: {"count": len(members), "kind": _classification(members, predictions, "kind"),
                             "primary_topic": _classification(members, predictions, "primary_topic")}
                     for name, members in sorted(slices.items())}
    blockers = []
    if split != "holdout":
        blockers.append("development_results_cannot_promote")
    minimum = manifest["minimums"]
    if len(rows) < minimum["reviewed_articles"]:
        blockers.append("insufficient_reviewed_articles")
    if len(selected) < minimum["holdout_articles"]:
        blockers.append("insufficient_split_articles")
    targets = manifest["quality_targets"]

    def check(name: str, measurement: dict, target: float, denominator: int):
        if measurement["denominator"] < denominator or measurement["value"] is None or measurement["value"] < target:
            blockers.append(name)

    for family in ("primary_topic", "entities", "places", "stories", "promotion"):
        for metric in ("precision", "recall"):
            check(f"{family}.{metric}", metrics[family][metric], targets[family][metric], minimum["metric_denominator"])
    if metrics["kind"]["macro_f1"] is None or metrics["kind"]["macro_f1"] < targets["kind_macro_f1"]:
        blockers.append("kind.macro_f1")
    declared = manifest.get("supported_slices", [])
    if not declared:
        blockers.append("no_declared_supported_slices")
    for name in declared:
        measured = slice_metrics.get(name)
        if measured is None or measured["count"] < minimum["slice_articles"]:
            blockers.append(f"slice.{name}.insufficient_articles")
            continue
        for metric in ("precision", "recall"):
            check(f"slice.{name}.primary_topic.{metric}", measured["primary_topic"][metric], targets["primary_topic"][metric], minimum["metric_denominator"])
        if measured["kind"]["macro_f1"] is None or measured["kind"]["macro_f1"] < targets["kind_macro_f1"]:
            blockers.append(f"slice.{name}.kind.macro_f1")
    # Point precision from a handful of positive cases is not a sub-1% proof.
    interval = metrics["promotion"]["precision_interval_95"]
    if interval is None or interval[0] < targets["promotion"]["precision"]:
        blockers.append("promotion.precision_underpowered")
    return {"schema_version": 1, "split": split, "dataset_sha256": digest(rows),
            "predictions_sha256": digest(predictions), "manifest_sha256": digest(manifest),
            "reviewed_count": len(rows), "evaluated_count": len(selected),
            "predicted_count": sum(row["article_id"] in predictions for row in selected),
            "metrics": metrics, "slices": slice_metrics, "blockers": blockers,
            "quality_gates_passed": not blockers, "release_ready": False,
            "required_external_gates": ["independent_assertion_grounding_review", "integrity_and_lifecycle_fault_suite",
                                        "filtered_ann_recall", "production_freshness_and_load", "measured_cost_budget",
                                        "S0_consumer_regression", "S1_S2_activation_prerequisites"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--snapshots", nargs="+", required=True)
    prepare.add_argument("--count", type=int, default=600)
    split = commands.add_parser("split")
    split.add_argument("--labels", type=Path, required=True)
    split.add_argument("--seed", required=True)
    score = commands.add_parser("evaluate")
    score.add_argument("--labels", type=Path, required=True)
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--manifest", type=Path, default=ROOT / "acceptance.json")
    score.add_argument("--split", choices=["development", "holdout"], default="holdout")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_review_queue(args.snapshots, args.count)
    elif args.command == "split":
        result = assign_story_splits(json.loads(args.labels.read_text())["articles"], args.seed)
        result = {"schema_version": 1, "split_seed": args.seed, "articles": result}
    else:
        result = evaluate(json.loads(args.labels.read_text())["articles"], json.loads(args.predictions.read_text()),
                          json.loads(args.manifest.read_text()), split=args.split)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.command == "evaluate" and not result["quality_gates_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
