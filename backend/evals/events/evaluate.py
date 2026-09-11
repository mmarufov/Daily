"""Fail-closed S4 quality evidence; never production authorization.

No provider is imported or called. Correlated/weighted streams remain measurable
diagnostics but cannot be promoted by an independent-binomial interval. A future
blocked/survey estimator requires a new frozen protocol, not a checkbox waiver.
"""
from __future__ import annotations

from collections import Counter
import math

from .contracts import (AdversarialEvidence, Dataset, OutcomeReview, Prediction, Protocol, digest, instant, split_digest,
                        validate_bindings)
from .metrics import binomial_bound, membership, score


REPORT_VERSION = 1
REPORT_KIND = "s4-event-quality"
GATE_VERSION = "s4-independent-quality-v1"
EXECUTION_FIELDS = {"requests", "cache_hits", "cache_misses", "known_usage_usd",
                    "unresolved_reserved_usd", "budget_usd", "ledger_sha256"}


def _execution(value) -> list[str]:
    if not isinstance(value, dict) or set(value) != EXECUTION_FIELDS:
        return ["missing_complete_execution_accounting"]
    for key in ("requests", "cache_hits", "cache_misses"):
        if type(value[key]) is not int or value[key] < 0:
            return ["invalid_execution_accounting"]
    for key in ("known_usage_usd", "unresolved_reserved_usd", "budget_usd"):
        if type(value[key]) not in {int, float} or not math.isfinite(value[key]) or value[key] < 0:
            return ["invalid_execution_accounting"]
    ledger = value["ledger_sha256"]
    if not isinstance(ledger, str) or len(ledger) != 64 or any(c not in "0123456789abcdef" for c in ledger):
        return ["invalid_execution_ledger"]
    blockers = []
    if value["cache_misses"]:
        blockers.append("offline_replay_cache_misses")
    if value["known_usage_usd"] + value["unresolved_reserved_usd"] > value["budget_usd"]:
        blockers.append("execution_budget_exceeded")
    if value["unresolved_reserved_usd"]:
        blockers.append("unresolved_provider_accounting")
    return blockers


def _metric_gates(metrics: dict, minimum: int) -> list[str]:
    blockers = []
    def checked_rate(value):
        if not isinstance(value, dict):
            raise ValueError("Malformed quality rate")
        numerator, denominator = value.get("numerator"), value.get("denominator")
        if (type(numerator) is not int or type(denominator) is not int
                or not 0 <= numerator <= denominator):
            raise ValueError("Invalid quality rate counters")
        expected = numerator / denominator if denominator else None
        actual = value.get("value")
        if actual != expected or (actual is not None and type(actual) not in {int, float}):
            raise ValueError("Quality rate does not match its counters")
        return value

    def checked_bound(value, sample, side):
        expected = binomial_bound(sample["numerator"], sample["denominator"], side=side)
        if expected is None:
            valid = value is None
        else:
            valid = (type(value) in {int, float} and math.isfinite(value)
                     and math.isclose(value, expected, rel_tol=0, abs_tol=1e-12))
        if not valid:
            raise ValueError("Quality confidence bound does not match its counters")
        return value

    for category in ("event_membership", "development_membership", "material_delta"):
        for key, target in (("precision", .98), ("recall", .90)):
            r = checked_rate(metrics[category][key])
            if r["denominator"] < minimum:
                blockers.append(f"{category}.{key}:underpowered")
            if r["value"] is None or r["value"] < target:
                blockers.append(f"{category}.{key}:below_target")
    for key, target in (("precision", .99), ("recall", .95)):
        r = checked_rate(metrics["critical"][key])
        if r["denominator"] < minimum:
            blockers.append(f"critical.{key}:underpowered")
        bound = checked_bound(metrics["critical"][f"{key}_lower_95"], r, "lower")
        if bound is None or bound < target:
            blockers.append(f"critical.{key}:confidence_below_target")
    negative = checked_rate(metrics["negative_decisions"])
    checked_bound(negative["error_upper_95"], negative, "upper")
    if negative["denominator"] < minimum:
        blockers.append("negative_decisions:underpowered")
    if negative["error_upper_95"] is None or negative["error_upper_95"] > .005:
        blockers.append("negative_decisions:confidence_above_target")
    representative = checked_rate(metrics["representative"])
    if representative["denominator"] < minimum:
        blockers.append("representative:underpowered")
    if representative["value"] is None or representative["value"] < .99:
        blockers.append("representative:below_target")
    for key in ("unchanged_fact_alerts", "unsupported_assertions", "invalid_representatives"):
        if type(metrics[key]) is not int or metrics[key] < 0:
            raise ValueError("Invalid quality failure counter")
        if metrics[key] != 0:
            blockers.append(key)
    return blockers


def _adversarial(value, policy: Protocol, bindings: dict) -> list[str]:
    if (value is None or policy.fixed_adversarial_suite_sha256 is None
            or not policy.required_adversarial_cases):
        return ["missing_frozen_adversarial_evidence"]
    artifact = AdversarialEvidence.model_validate(value)
    blockers = []
    if artifact.evaluation_binding_sha256 != digest(bindings):
        blockers.append("different_adversarial_candidate_bindings")
    if artifact.suite_sha256 != policy.fixed_adversarial_suite_sha256:
        blockers.append("different_adversarial_suite")
    if artifact.review.status != "adjudicated":
        blockers.append("adversarial_results_not_independently_reviewed")
    if {c.case_id for c in artifact.cases} != set(policy.required_adversarial_cases):
        blockers.append("incomplete_adversarial_cases")
    if any(c.false_critical_promotions or c.unsupported_assertions for c in artifact.cases):
        blockers.append("adversarial_critical_or_support_failure")
    return blockers


def _subset(dataset: Dataset, predictions: list[Prediction], ids: set[str]) -> tuple[Dataset, list[Prediction]]:
    # A cross-slice prediction is charged in every slice whose evidence it uses;
    # its full members stay available for alignment/false-merge diagnostics.
    developments = [d for d in dataset.developments if d.id in ids]
    mentions = [m for m in dataset.mentions if m.development_id in ids]
    mids = {m.id for m in mentions}
    selected = [p for p in predictions if set(p.members) & mids]
    # Keep selected members outside this subset as non-gold prediction evidence.
    # Scoring below uses the full manifest but only selected gold opportunities.
    referenced = {i for p in selected for i in p.members}
    full_mentions = [m for m in dataset.mentions if m.id in referenced or m.id in mids]
    return dataset.model_copy(update={"developments": developments, "mentions": full_mentions}), selected


def evaluate(dataset: dict, predictions: list[dict], protocol: dict, *, bindings: dict,
             split: str = "holdout", execution: dict | None = None,
             outcome_reviews: list[dict] | None = None, adversarial: dict | None = None) -> dict:
    """Evaluate immutable independent labels against exact recipe predictions.

    Invalid identities/metadata raise ValueError. Valid but incomplete/unreviewed
    artifacts return a blocked report. No labels are synthesized or upgraded.
    """
    data = Dataset.model_validate(dataset)
    policy = Protocol.model_validate(protocol)
    preds = [Prediction.model_validate(p) for p in predictions]
    reviewed = [OutcomeReview.model_validate(r) for r in outcome_reviews or []]
    if len({r.prediction_id for r in reviewed}) != len(reviewed):
        raise ValueError("Duplicate outcome reviews")
    raw_predictions = {p["id"]: p for p in predictions}
    for review in reviewed:
        if (review.prediction_id not in raw_predictions
                or review.prediction_sha256 != digest(raw_predictions[review.prediction_id])):
            raise ValueError("Outcome review is not bound to this exact prediction")
    if len(preds) > 20000 or len({p.id for p in preds}) != len(preds):
        raise ValueError("Duplicate/excess prediction identities")
    if split not in {"development", "holdout"}:
        raise ValueError("Invalid evaluation split")
    validate_bindings(bindings)
    expected = {"dataset_sha256": digest(dataset), "protocol_sha256": digest(protocol),
                "split_sha256": split_digest(dataset)}
    if any(bindings[key] != value for key, value in expected.items()):
        raise ValueError("Dataset/protocol/split binding mismatch")
    mentions = {m.id: m for m in data.mentions}
    selected_ids = {d.id for d in data.developments if d.split == split}
    for p in preds:
        for mid in p.members:
            if mid not in mentions:
                raise ValueError("Prediction contains unknown evidence mention")
            if mentions[mid].development_id not in selected_ids:
                raise ValueError("Prediction mixes evidence from another evaluation split")
            if instant(mentions[mid].available_at) > instant(p.evidence_cutoff):
                raise ValueError("Prediction uses source evidence unavailable at decision time")
    selected = data.model_copy(update={
        "developments": [d for d in data.developments if d.id in selected_ids],
        "mentions": [m for m in data.mentions if m.development_id in selected_ids],
    })
    blockers = _execution(execution) + _adversarial(adversarial, policy, bindings)
    review_map = {r.prediction_id: r for r in reviewed if r.review.status == "adjudicated"}
    if any(p.status == "ready" and p.id not in review_map for p in preds):
        blockers.append("missing_independent_prediction_review")
    if split != "holdout":
        blockers.append("development_split_not_promotion_evidence")
    if policy.status != "frozen":
        blockers.append("protocol_not_frozen")
    if not policy.supported_slices:
        blockers.append("supported_slices_empty")
    if not selected.developments:
        blockers.append("no_gold_developments")
    if not preds:
        blockers.append("no_predictions")
    if any(d.review.status != "adjudicated" for d in selected.developments):
        blockers.append("labels_not_independently_adjudicated")
    if any(not d.review.blind_to_predictions for d in selected.developments):
        blockers.append("holdout_review_not_blind")
    supported = set(policy.supported_slices)
    if any(not set(d.slices) <= supported for d in selected.developments):
        blockers.append("undeclared_support_slice")
    if data.sampling != "complete_windows":
        blockers.append("population_estimator_not_implemented_for_sampling_design")
    independent = policy.independent_opportunities_attested
    for key in ("independence_id", "family_id", "window_id", "event_id"):
        if any(n > 1 for n in Counter(getattr(d, key) for d in selected.developments).values()):
            independent = False
    origins = {}
    for mention in selected.mentions:
        origins.setdefault(mention.origin_id, set()).add(mention.development_id)
    if any(len(developments) > 1 for developments in origins.values()):
        independent = False
    if policy.interval_method != "independent-opportunity-clopper-pearson-v1" or not independent:
        blockers.append("correlated_or_unattested_opportunities_require_blocked_interval")
    # Summaries remain diagnostics if provenance/independence gates failed.
    metrics = score(selected, preds, policy, review_map)
    blockers.extend(_metric_gates(metrics, policy.minimum_metric_denominator))
    slices = {}
    for label in sorted(supported):
        ids = {d.id for d in selected.developments if label in d.slices}
        subdata, subpreds = _subset(selected, preds, ids)
        measured = score(subdata, subpreds, policy, review_map)
        slices[label] = measured
        if len(ids) < policy.minimum_slice_developments:
            blockers.append(f"slice:{label}:underpowered")
        blockers.extend(f"slice:{label}:{b}" for b in _metric_gates(measured, policy.minimum_metric_denominator))
    families = {}
    for family in sorted({d.family_id for d in selected.developments}):
        ids = {d.id for d in selected.developments if d.family_id == family}
        subdata, subpreds = _subset(selected, preds, ids)
        # Family diagnostics only; independent event counts never come from pairs.
        families[family] = {
            "event_membership": membership(subdata, subpreds, level="event"),
            "development_membership": membership(subdata, subpreds, level="development"),
        }
    family_macro = {}
    for category in ("event_membership", "development_membership"):
        family_macro[category] = {}
        for key in ("precision", "recall"):
            values = [m[category][key]["value"] for m in families.values()
                      if m[category][key]["value"] is not None]
            family_macro[category][key] = {"value": sum(values) / len(values) if values else None,
                                          "families": len(values)}
    report = {
        "schema_version": REPORT_VERSION, "kind": REPORT_KIND, "gate_version": GATE_VERSION,
        "bindings": dict(bindings), "split": split, "protocol": protocol,
        "predictions_sha256": digest(predictions), "execution": execution,
        "outcome_reviews": outcome_reviews, "adversarial": adversarial,
        "metrics": metrics, "slice_metrics": slices, "family_metrics": families,
        "family_macro": family_macro,
        "blockers": sorted(set(blockers)), "quality_gates_passed": not blockers,
        "release_ready": False,
        "note": "Quality evidence only. Integrity hash is not a signature or deployment approval. Correlated/weighted samples cannot use independent-binomial promotion; runtime and reader gates are separate.",
    }
    report["report_sha256"] = digest(report)
    return report


def validate_report(report: dict, expected_bindings: dict) -> bool:
    """Validate a trusted evaluator artifact before a separate operations gate.

    The caller must obtain the artifact from its reviewed, immutable evaluation
    run. A self-supplied JSON hash does not authenticate a third-party report.
    """
    validate_bindings(expected_bindings)
    if not isinstance(report, dict) or report.get("kind") != REPORT_KIND or report.get("schema_version") != REPORT_VERSION:
        raise ValueError("Invalid S4 quality report")
    if report.get("gate_version") != GATE_VERSION or report.get("bindings") != expected_bindings:
        raise ValueError("Stale or different evaluation bindings")
    content = {key: value for key, value in report.items() if key != "report_sha256"}
    if report.get("report_sha256") != digest(content):
        raise ValueError("Evaluation report integrity mismatch")
    policy = Protocol.model_validate(report.get("protocol"))
    if digest(report["protocol"]) != expected_bindings["protocol_sha256"]:
        raise ValueError("Protocol binding mismatch")
    if (report.get("split") != "holdout" or policy.status != "frozen"
            or not policy.supported_slices or report.get("quality_gates_passed") is not True
            or report.get("blockers") != [] or report.get("release_ready") is not False):
        raise ValueError("S4 quality gates have not passed")
    if _execution(report.get("execution")):
        raise ValueError("Incomplete S4 execution accounting")
    if _adversarial(report.get("adversarial"), policy, expected_bindings):
        raise ValueError("Incomplete independent adversarial evidence")
    reviews = [OutcomeReview.model_validate(r) for r in report.get("outcome_reviews") or []]
    if not reviews or any(r.review.status != "adjudicated" for r in reviews):
        raise ValueError("Missing independent outcome reviews")
    if _metric_gates(report["metrics"], policy.minimum_metric_denominator):
        raise ValueError("S4 aggregate metrics do not satisfy the fixed gates")
    if set(report.get("slice_metrics", {})) != set(policy.supported_slices):
        raise ValueError("Missing supported-slice quality evidence")
    for measured in report["slice_metrics"].values():
        if measured["gold_developments"] < policy.minimum_slice_developments or _metric_gates(measured, policy.minimum_metric_denominator):
            raise ValueError("Supported slice fails S4 gates")
    return True


def validate_promotion(report: dict, expected_bindings: dict) -> bool:
    """Quality-only promotion gate; caller must also enforce operational gates.

    This deliberately shares validate_report's trusted-artifact boundary. It
    does not enable readers, approve a recipe, authenticate JSON or spend money.
    """
    return validate_report(report, expected_bindings)
