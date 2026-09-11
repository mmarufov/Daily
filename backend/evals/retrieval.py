"""Offline S6 candidate metrics, independent of final-feed relevance scoring.

The caller supplies the *whole frozen eligible corpus*, independent positive
labels, and optionally all judged IDs. Pooled judgments only establish known-
positive recall; unjudged articles are never silently treated as negatives.
This module performs no provider calls and opens no database connection. Runtime
evaluation must supply an isolated frozen-corpus connection, not production data.

CLI: PYTHONPATH=backend python -m evals.retrieval frozen-report.json
The JSON object contains ``batch`` and keyword arguments to
``evaluate_candidate_batch``. Output is a report, not a release approval.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


def _ids(values: Iterable[str], name: str) -> set[str]:
    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError(f"{name} must contain article IDs, not a string or mapping")
    result = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} contains an invalid ID")
        result.add(value)
    return result


def _limit(k: int) -> None:
    if type(k) is not int or not 0 <= k <= 300:
        raise ValueError("k must be an integer between 0 and 300")


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _recall(positives: set[str], retrieved: set[str], k: int) -> dict:
    hits = positives & retrieved
    return {
        "positive_count": len(positives), "hit_count": len(hits),
        "raw_recall_at_k": _ratio(len(hits), len(positives)),
        "capacity_ceiling": _ratio(min(k, len(positives)), len(positives)),
        "hit_ids": sorted(hits), "missing_ids": sorted(positives - hits),
    }


def evaluate_candidate_batch(
    batch: Mapping[str, Any], *, corpus_ids: Iterable[str],
    positive_ids: Iterable[str], judged_ids: Iterable[str] | None = None,
    positives_by_intent: Mapping[str, Iterable[str]] | None = None,
    labels_complete: bool = False, k: int = 300,
    loss_ids: Mapping[str, Iterable[str]] | None = None,
    slices: Mapping[str, Iterable[str]] | None = None,
) -> dict:
    """Measure candidates against independent eligible in-pool positives.

    ``corpus_ids`` must include eligible positives even when their vectors are
    absent or stale. Eligibility is independent of retriever availability.
    ``labels_complete`` requires all corpus IDs in ``judged_ids``. It is an
    explicit caller attestation, never inferred from successful retrieval.
    ``loss_ids`` contains observed rejected/missed IDs by stage; counts alone
    cannot identify which positives a stage lost. Attribution may overlap and
    does not establish causal loss. ``slices`` supports frozen language, source,
    topic, and temporal groups without guessing metadata inside the evaluator.
    """
    _limit(k)
    if type(labels_complete) is not bool:
        raise ValueError("labels_complete must be boolean")
    corpus = _ids(corpus_ids, "corpus_ids")
    positives = _ids(positive_ids, "positive_ids")
    judged = positives if judged_ids is None else _ids(judged_ids, "judged_ids")
    if not positives <= judged:
        raise ValueError("Every positive ID must have an independent judgment")
    if labels_complete and not corpus <= judged:
        raise ValueError("Complete labels require judgments for the whole frozen corpus")
    rows = batch.get("candidates")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("batch.candidates must be a list of candidate objects")
    ordered_ids = [row.get("article_id") for row in rows]
    unique_ids = _ids(ordered_ids, "candidate article IDs")
    if len(unique_ids) != len(rows):
        raise ValueError("CandidateBatch contains duplicate article IDs")
    if not unique_ids <= corpus:
        raise ValueError("CandidateBatch contains IDs outside the frozen eligible corpus")
    selected = rows[:k]
    retrieved = {row["article_id"] for row in selected}
    in_pool_positives = positives & corpus
    missing = in_pool_positives - retrieved
    by_intent: dict[str, set[str]] = defaultdict(set)
    by_leg: dict[str, set[str]] = defaultdict(set)
    for row in selected:
        article_id = row["article_id"]
        intents = _ids(row.get("matched_intent_ids", []), "matched_intent_ids")
        for intent in intents:
            by_intent[intent].add(article_id)
        matches = row.get("matches", [])
        if not isinstance(matches, list):
            raise ValueError("candidate.matches must be a list")
        for match in matches:
            if not isinstance(match, Mapping) or not isinstance(match.get("leg"), str) or not match["leg"]:
                raise ValueError("Every match must identify its retrieval leg")
            by_leg[match["leg"]].add(article_id)

    intent_metrics = {}
    supported_opportunities = 0
    recovered_opportunities = 0
    attributed_opportunities = 0
    for intent_id, intent_positive_values in sorted((positives_by_intent or {}).items()):
        intent_positives = _ids(intent_positive_values, "intent positives")
        if not intent_positives <= positives:
            raise ValueError("Per-intent positives must be included in positive_ids")
        eligible = intent_positives & corpus
        metric = _recall(eligible, retrieved, k)
        attributed_hits = eligible & by_intent.get(intent_id, set())
        metric.update({
            "attributed_hit_ids": sorted(attributed_hits),
            "attributed_recall_at_k": _ratio(len(attributed_hits), len(eligible)),
            "candidate_count": len(by_intent.get(intent_id, set())),
        })
        intent_metrics[intent_id] = metric
        if eligible:
            supported_opportunities += 1
            recovered_opportunities += bool(eligible & retrieved)
            attributed_opportunities += bool(attributed_hits)

    marginal_legs = {}
    for leg, ids in sorted(by_leg.items()):
        other = set().union(*(values for key, values in by_leg.items() if key != leg))
        unique = ids - other
        marginal_legs[leg] = {
            "candidate_count": len(ids), "positive_count": len(ids & in_pool_positives),
            "unique_candidate_ids": sorted(unique),
            "unique_positive_ids": sorted(unique & in_pool_positives),
            "unique_positive_recall_contribution": _ratio(len(unique & in_pool_positives), len(in_pool_positives)),
        }
    attributed_losses = {}
    attributed_missing: set[str] = set()
    for stage, values in sorted((loss_ids or {}).items()):
        lost = _ids(values, f"loss stage {stage}") & missing
        attributed_losses[stage] = sorted(lost)
        attributed_missing |= lost
    slice_metrics = {
        name: _recall(in_pool_positives & _ids(values, f"slice {name}"), retrieved, k)
        for name, values in sorted((slices or {}).items())
    }
    return {
        "schema_version": 1,
        "metric_scope": "in_pool_recall" if labels_complete else "in_pool_known_positive_recall",
        "labels_complete": labels_complete, "k": k, "corpus_count": len(corpus),
        "judged_corpus_count": len(judged & corpus),
        "unjudged_corpus_count": len(corpus - judged),
        "judgment_coverage": _ratio(len(judged & corpus), len(corpus)),
        "returned_count": len(selected), "reported_candidate_count": len(rows),
        "positive_ids_outside_pool": sorted(positives - corpus),
        **_recall(in_pool_positives, retrieved, k),
        "retrieved_unjudged_ids": sorted(retrieved - judged),
        "retrieved_judged_nonpositive_ids": sorted((retrieved & judged) - positives),
        "per_intent": intent_metrics,
        "positive_intent_opportunity_count": supported_opportunities,
        "positive_intent_coverage": _ratio(recovered_opportunities, supported_opportunities),
        "attributed_positive_intent_coverage": _ratio(attributed_opportunities, supported_opportunities),
        "marginal_legs": marginal_legs,
        "marginal_leg_note": "Observed unique provenance contribution, not a rerun or causal ablation.",
        "loss_ids_by_stage": attributed_losses,
        "unattributed_missing_ids": sorted(missing - attributed_missing),
        "slices": slice_metrics,
        "retrieval_diagnostics": deepcopy(batch.get("diagnostics", {})),
        "batch_status": batch.get("status"),
        "request_id": batch.get("request_id"), "as_of": batch.get("as_of"),
        "interpretation": "Unjudged is unknown. Recall is against all eligible labeled positives, not min(K, positives).",
    }


def conditional_ann_recall(
    ann_ids: Iterable[str], exact_distances: Mapping[str, float], *,
    k: int, exhaustive: bool = False, tie_tolerance: float = 1e-12,
) -> dict:
    """Tie-aware conditional ANN recall against an untruncated exact oracle.

    ``exact_distances`` contains ALL eligible frozen neighbors with the same
    geometry and filters. Never supply a capped serving query as this oracle.
    The caller must explicitly attest exhaustive construction. Missing article
    embeddings belong in product recall above, not this conditional denominator.
    Lower distance is better. Boundary ties receive interchangeable credit, but
    missing strictly nearer neighbors cannot be hidden by extra boundary ties.
    """
    _limit(k)
    if exhaustive is not True:
        raise ValueError("ANN evaluation requires an exhaustive exact eligible oracle")
    if isinstance(tie_tolerance, bool) or not math.isfinite(tie_tolerance) or tie_tolerance < 0:
        raise ValueError("tie_tolerance must be finite and nonnegative")
    _ids(exact_distances.keys(), "exact oracle IDs")
    for distance in exact_distances.values():
        if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance):
            raise ValueError("Exact distances must be finite numbers")
    ordered = list(ann_ids)
    ann = _ids(ordered, "ann_ids")
    if len(ann) != len(ordered):
        raise ValueError("ANN result contains duplicate IDs")
    selected = set(ordered[:k])
    denominator = min(k, len(exact_distances))
    if denominator == 0:
        return {"conditional_ann_recall_at_k": None, "k": k, "oracle_count": len(exact_distances),
                "denominator": 0, "credit": 0, "boundary_distance": None,
                "missing_strict_ids": [], "outside_oracle_ids": sorted(selected - exact_distances.keys())}
    boundary = sorted(exact_distances.values())[denominator - 1]
    strict = {identifier for identifier, distance in exact_distances.items() if distance < boundary - tie_tolerance}
    ties = {identifier for identifier, distance in exact_distances.items() if abs(distance - boundary) <= tie_tolerance}
    credit = len(selected & strict) + min(denominator - len(strict), len(selected & ties))
    return {
        "conditional_ann_recall_at_k": credit / denominator,
        "k": k, "oracle_count": len(exact_distances), "denominator": denominator,
        "credit": credit, "boundary_distance": boundary, "tie_tolerance": tie_tolerance,
        "boundary_tie_count": len(ties), "missing_strict_ids": sorted(strict - selected),
        "outside_oracle_ids": sorted(selected - exact_distances.keys()),
    }


def evaluate_retrieval(
    build: Callable[..., Any], conn: Any, user_id: str, snapshot: Mapping[str, Any], *,
    as_of: datetime, corpus_ids: Iterable[str], positive_ids: Iterable[str],
    k: int = 300, **evaluation_options: Any,
) -> dict:
    """Invoke the real builder once against a caller-owned frozen connection.

    This does not freeze a live database: the caller owns corpus/artifact/config
    immutability. Supply the runtime builder directly or a signature-compatible
    adapter; do not substitute a second retrieval algorithm for evaluation.
    """
    _limit(k)
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be a timezone-aware frozen timestamp")
    frozen_time = as_of.astimezone(timezone.utc)
    batch = build(conn, user_id, deepcopy(snapshot), limit=k, as_of=frozen_time)
    if hasattr(batch, "model_dump"):
        batch = batch.model_dump(mode="json")
    if not isinstance(batch, Mapping):
        raise ValueError("The runtime builder must return a CandidateBatch")
    batch_time = batch.get("as_of")
    if batch_time is not None:
        if isinstance(batch_time, str):
            batch_time = datetime.fromisoformat(batch_time.replace("Z", "+00:00"))
        if batch_time != frozen_time:
            raise ValueError("CandidateBatch did not use the frozen evaluation timestamp")
    report = evaluate_candidate_batch(batch, corpus_ids=corpus_ids, positive_ids=positive_ids, k=k, **evaluation_options)
    report["as_of"] = frozen_time.isoformat()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="Frozen candidate batch, corpus IDs and independent labels as JSON")
    args = parser.parse_args()
    payload = json.loads(args.report.read_text())
    if not isinstance(payload, dict) or "batch" not in payload:
        parser.error("JSON must contain batch and evaluate_candidate_batch keyword arguments")
    batch = payload.pop("batch")
    print(json.dumps(evaluate_candidate_batch(batch, **payload), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
