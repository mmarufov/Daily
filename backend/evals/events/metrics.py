"""Event/development metrics with explicit denominators and no model judging."""
from __future__ import annotations

from collections import Counter, defaultdict
import math

from .contracts import Dataset, OutcomeReview, Prediction, Protocol, instant


def rate(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator,
            "value": numerator / denominator if denominator else None}


def _binomial_cdf(k: int, n: int, p: float) -> float:
    if k < 0:
        return 0.0
    if k >= n or p == 0:
        return 1.0
    if p == 1:
        return 0.0
    terms = [math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
             + i * math.log(p) + (n - i) * math.log1p(-p) for i in range(k + 1)]
    largest = max(terms)
    return min(1.0, math.exp(largest) * math.fsum(math.exp(t - largest) for t in terms))


def binomial_bound(successes: int, total: int, *, side: str, alpha: float = .05) -> float | None:
    """Exact one-sided Clopper–Pearson bound for independent Bernoulli trials.

    The evaluator separately refuses statistical promotion for correlated or
    weighted sampling: passing these numbers is not an independence detector.
    """
    if (type(successes) is not int or type(total) is not int or total < 0
            or not 0 <= successes <= total or side not in {"lower", "upper"}
            or not 0 < alpha < 1):
        raise ValueError("Invalid binomial sample/bound")
    if total == 0:
        return None
    if side == "lower" and successes == 0:
        return 0.0
    if side == "upper" and successes == total:
        return 1.0
    if side == "lower" and successes == total:
        return alpha ** (1 / total)
    if side == "upper" and successes == 0:
        return -math.expm1(math.log(alpha) / total)
    target = 1 - alpha if side == "lower" else alpha
    k = successes - 1 if side == "lower" else successes
    low, high = 0.0, 1.0
    for _ in range(56):
        mid = (low + high) / 2
        if _binomial_cdf(k, total, mid) > target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def align(dataset: Dataset, predictions: list[Prediction], protocol: Protocol) -> dict[str, str]:
    """Maximum-cardinality deterministic one-to-one identity alignment.

    Never use predicted/gold significance or novelty to choose a match. Candidate
    edges require compatible type/place/time plus canonical gold core coverage.
    Sorting edges by coverage merely resolves ties; this is not maximum-weight
    matching. The exact algorithm is part of the frozen protocol identifier.
    """
    mentions = {m.id: m for m in dataset.mentions}
    edges = {}
    for p in predictions:
        if p.status != "ready":
            continue
        proposed = {mentions[i].canonical_id for i in p.members}
        compatible = []
        for d in dataset.developments:
            if p.event_type != d.event_type or p.place_key != d.place_key:
                continue
            if instant(p.occurred_end) < instant(d.occurred_start) or instant(p.occurred_start) > instant(d.occurred_end):
                continue
            core = {mentions[i].canonical_id for i in d.core_mentions}
            coverage = len(proposed & core) / len(core)
            if coverage >= protocol.minimum_core_coverage:
                compatible.append((-coverage, d.id))
        edges[p.id] = [did for _, did in sorted(compatible)]
    occupied: dict[str, str] = {}
    matched: dict[str, str] = {}
    for root in sorted(edges):
        queue, seen_predictions, parents = [root], {root}, {}
        free = None
        for pid in queue:
            for did in edges[pid]:
                if did in parents:
                    continue
                parents[did] = pid
                if did not in occupied:
                    free = did
                    break
                other = occupied[did]
                if other not in seen_predictions:
                    queue.append(other)
                    seen_predictions.add(other)
            if free is not None:
                break
        while free is not None:
            pid = parents[free]
            previous = matched.get(pid)
            occupied[free], matched[pid] = pid, free
            free = previous
    return {pid: did for did, pid in occupied.items()}


def membership(dataset: Dataset, predictions: list[Prediction], *, level: str) -> dict:
    if level not in {"event", "development"}:
        raise ValueError("Unknown membership level")
    by_id = {m.id: m for m in dataset.mentions}
    focus = {d.id for d in dataset.developments}
    canonical = {m.canonical_id: (getattr(m, f"{level}_id"), m.development_id in focus)
                 for m in dataset.mentions}
    proposed = defaultdict(set)
    for p in predictions:
        if p.status != "ready":
            continue
        group = p.event_id if level == "event" else p.id
        for mid in p.members:
            proposed[by_id[mid].canonical_id].add(group)
    actual_groups = Counter()
    actual_outside = Counter()
    predicted_groups = Counter()
    predicted_outside = Counter()
    intersections = Counter()
    intersections_outside = Counter()
    ambiguous = 0
    for mid, (actual, in_focus) in canonical.items():
        groups = proposed[mid]
        # Unknown/multiply assigned mention cannot certify a shared membership.
        if len(groups) != 1:
            predicted = ("unassigned", mid)
            ambiguous += len(groups) > 1
        else:
            predicted = ("predicted", next(iter(groups)))
        predicted_groups[predicted] += 1
        actual_groups[actual] += 1
        intersections[(actual, predicted)] += 1
        if not in_focus:
            predicted_outside[predicted] += 1
            actual_outside[actual] += 1
            intersections_outside[(actual, predicted)] += 1
    pairs = lambda n: n * (n - 1) // 2
    # Slice diagnostics count pairs touching this slice, never borrow pairs
    # wholly outside it. Cross-slice false merges remain visible in both slices.
    actual = sum(pairs(n) - pairs(actual_outside[g]) for g, n in actual_groups.items())
    predicted = sum(pairs(n) - pairs(predicted_outside[g]) for g, n in predicted_groups.items())
    correct = sum(pairs(n) - pairs(intersections_outside[g]) for g, n in intersections.items())
    return {"precision": rate(correct, predicted), "recall": rate(correct, actual),
            "false_merges": predicted - correct, "missed_merges": actual - correct,
            "ambiguous_mentions": ambiguous, "canonical_mentions": sum(in_focus for _, in_focus in canonical.values())}


def score(dataset: Dataset, predictions: list[Prediction], protocol: Protocol,
          outcome_reviews: dict[str, OutcomeReview] | None = None) -> dict:
    outcome_reviews = outcome_reviews or {}
    alignment = align(dataset, predictions, protocol)
    gold = {d.id: d for d in dataset.developments}
    mentions = {m.id: m for m in dataset.mentions}
    eligible = {d.id for d in gold.values() if d.eligible}
    critical = {d.id for d in gold.values() if d.eligible and d.tier == "world_critical" and d.material}
    all_critical = {d.id for d in gold.values() if d.tier == "world_critical" and d.material}
    negative = eligible - critical
    ready = [p for p in predictions if p.status == "ready"]
    critical_predictions = [p for p in ready if p.tier == "world_critical" and p.material]
    matched_critical = [p for p in critical_predictions if alignment.get(p.id) in critical]
    timely_critical = [p for p in matched_critical
                       if instant(p.completed_at) <= instant(gold[alignment[p.id]].deadline_at)]
    # One negative opportunity can have many false alert predictions. Count it
    # once for negative-decision FPR; precision still counts every prediction.
    negative_alerted = {mentions[mid].development_id for p in critical_predictions
                        for mid in p.members if mentions[mid].development_id in negative}
    negative_false = len(negative_alerted)
    material_gold = {d.id for d in gold.values() if d.eligible and d.material}
    material_predictions = [p for p in ready if p.material]
    correct_material = [p for p in material_predictions if alignment.get(p.id) in material_gold]
    timely_material = [p for p in correct_material
                       if instant(p.completed_at) <= instant(gold[alignment[p.id]].deadline_at)]
    representatives = [p for p in ready if p.representative_mention_id is not None]
    representative_correct = sum(alignment.get(p.id) in eligible and p.representative_mention_id in
                                 gold[alignment[p.id]].direct_mentions and p.id in outcome_reviews
                                 and outcome_reviews[p.id].direct_support is True for p in representatives)
    def pr(correct, predicted, recalled, expected):
        return {"precision": rate(correct, predicted), "recall": rate(recalled, expected)}
    critical_metrics = pr(len(matched_critical), len(critical_predictions), len(timely_critical), len(critical))
    critical_metrics["precision_lower_95"] = binomial_bound(len(matched_critical), len(critical_predictions), side="lower")
    critical_metrics["recall_lower_95"] = binomial_bound(len(timely_critical), len(critical), side="lower")
    tiers = {}
    for tier in ("world_critical", "major", "routine"):
        actual_tier = {d.id for d in gold.values() if d.eligible and d.tier == tier}
        predicted_tier = [p for p in ready if p.tier == tier]
        correct_tier = [p for p in predicted_tier if alignment.get(p.id) in actual_tier]
        tiers[tier] = pr(len(correct_tier), len(predicted_tier), len(correct_tier), len(actual_tier))
    return {
        "alignment": alignment,
        "event_membership": membership(dataset, predictions, level="event"),
        "development_membership": membership(dataset, predictions, level="development"),
        "critical": critical_metrics,
        # Ingestion/understanding misses remain visible rather than making an
        # apparently excellent conditional S4 score look like world coverage.
        "end_to_end_critical_recall": rate(len(timely_critical), len(all_critical)),
        "upstream_unavailable_critical": len(all_critical - critical),
        "significance_by_tier": tiers,
        "negative_decisions": {**rate(negative_false, len(negative)),
                               "error_upper_95": binomial_bound(negative_false, len(negative), side="upper")},
        "material_delta": pr(len(correct_material), len(material_predictions), len(timely_material), len(material_gold)),
        # Omitting a representative is a failed output, not an opportunity to
        # shrink the quality denominator to the easiest selected examples.
        "representative": rate(representative_correct, len(ready)),
        "invalid_representatives": len(representatives) - representative_correct,
        "unchanged_fact_alerts": sum(alignment.get(p.id) in gold and not gold[alignment[p.id]].material
                                    for p in material_predictions),
        "unsupported_assertions": sum(outcome_reviews[p.id].unsupported_assertions for p in predictions
                                      if p.id in outcome_reviews),
        "coverage": rate(len({alignment[p.id] for p in ready if p.id in alignment}), len(gold)),
        "outcomes": dict(Counter(p.status for p in predictions)),
        "unmatched_predictions": len(ready) - len(alignment),
        "late_critical": len(matched_critical) - len(timely_critical),
        "gold_developments": len(gold),
    }
