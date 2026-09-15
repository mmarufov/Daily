"""Conservative bounded S4 matching mechanics, not calibrated semantic grouping.

No centroid transitivity, inferred entity identity, universal cosine threshold,
or new UUID generation here. The repository owns stable identities and lineage.
Uncalibrated inputs produce explicit candidates/abstentions, not invented merges.
"""
from __future__ import annotations

import math
from .event_contract import Claim, Evidence, timestamp


MAX_CANDIDATES = 128


def cosine(left, right) -> float | None:
    if not isinstance(left, (list, tuple)) or not isinstance(right, (list, tuple)) or not left or len(left) != len(right):
        return None
    if not all(type(value) in (int, float) and math.isfinite(value) for value in [*left, *right]):
        return None
    ln, rn = math.hypot(*left), math.hypot(*right)
    if not ln or not rn or not math.isfinite(ln + rn):
        return None
    return max(-1.0, min(1.0, sum((a / ln) * (b / rn) for a, b in zip(left, right))))


def _signature(claim: dict) -> tuple | None:
    claim = Claim.model_validate(claim).model_dump()
    time = claim["occurrence"]
    # S3 v1's unknown modality/date cannot become an affirmed match. Exact
    # interval and explicit identities are intentionally high precision only.
    if not claim["actor_ids"] or not claim["place_ids"] or not claim["object"] or \
            claim["modality"] not in ("reported", "corrected") or time["precision"] == "unknown":
        return None
    if time["start"] is None or time["end"] is None or not time["evidence_ids"]:
        return None
    start, end = timestamp(time["start"]), timestamp(time["end"])
    if start > end:
        return None
    return (tuple(sorted(claim["actor_ids"])), claim["action"].casefold().strip(),
            claim["object"].casefold().strip(), tuple(sorted(claim["place_ids"])),
            start, end, time["precision"])


def relation(left: dict, right: dict, *, calibrated: bool = False) -> dict:
    """Candidate relation. Automatic equality is opt-in after independent calibration.

    Missing data is insufficient; conflicting precise occurrence windows are
    different developments, not proof the umbrella events are unrelated.
    """
    if type(calibrated) is not bool:
        raise ValueError("calibration switch must be an explicit boolean")
    a, b = Evidence.model_validate(left).model_dump(), Evidence.model_validate(right).model_dump()
    sa, sb = _signature(a["claim"]), _signature(b["claim"])
    if not calibrated:
        return {"relation": "insufficient", "reason": "uncalibrated_recipe"}
    if a["claim"]["modality"] != b["claim"]["modality"]:
        return {"relation": "insufficient", "reason": "modality_conflict"}
    if sa is not None and sb is not None and sa == sb and a["role"] == b["role"] == "core":
        return {"relation": "same_development", "reason": "exact_supported_signature"}
    if sa is not None and sb is not None and sa != sb:
        return {"relation": "different", "reason": "distinct_precise_development"}
    return {"relation": "insufficient", "reason": "missing_bounded_identity"}


def rank_candidates(query: dict, candidates: list[dict], *, query_vector=None,
                    vectors: dict | None = None, limit: int = 32) -> list[dict]:
    """Union recall scores only; none of these scores authorize membership.

    Callers retrieve bounded SQL candidates first. Oversized input is rejected,
    never silently truncate before checking contradictions/competing matches.
    Unknown entities leave lexical/vector recall available.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_CANDIDATES:
        raise ValueError("invalid candidate limit")
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidate intake exceeds explicit bound")
    q = Evidence.model_validate(query).model_dump()
    rows = [Evidence.model_validate(row).model_dump() for row in candidates]
    if any(row["dependency"]["s3_recipe_id"] != q["dependency"]["s3_recipe_id"] for row in rows):
        raise ValueError("candidate cohort mixes S3 recipes/spaces")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate candidate ID")
    def tokens(claim):
        return set((claim["action"] + " " + (claim["object"] or "")).casefold().split())
    qt = tokens(q["claim"])
    result = []
    for row in rows:
        if row["id"] == q["id"]:
            continue
        text = tokens(row["claim"])
        lexical = len(qt & text) / len(qt | text) if qt | text else 0.0
        entity = bool(set(q["claim"]["actor_ids"]) & set(row["claim"]["actor_ids"]))
        similarity = cosine(query_vector, (vectors or {}).get(row["id"]))
        if lexical or entity or similarity is not None:
            result.append({"evidence_id": row["id"], "lexical": lexical, "entity_overlap": entity,
                           "cosine": similarity})
    return sorted(result, key=lambda row: (-int(row["entity_overlap"]), -row["lexical"],
                                         -(row["cosine"] if row["cosine"] is not None else -1), row["evidence_id"]))[:limit]


def choose_match(candidates: list[dict], *, calibrated: bool = False, minimum_score=None, margin=None) -> dict:
    """Explicit bounded adjudicator outputs: ambiguous competitors remain separate.

    candidate shape: {event_id, score, relation}; score is a calibrated matcher
    output, never raw cosine. This is a selection mechanic, not that matcher.
    """
    if type(calibrated) is not bool:
        raise ValueError("calibration switch must be an explicit boolean")
    if not calibrated:
        return {"event_id": None, "reason": "uncalibrated_recipe"}
    for name, value in (("minimum_score", minimum_score), ("margin", margin)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1:
            raise ValueError("invalid calibrated " + name)
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("candidate intake exceeds explicit bound")
    seen = set()
    eligible = []
    for row in candidates:
        if set(row) != {"event_id", "score", "relation"} or not isinstance(row["event_id"], str) or not row["event_id"].strip():
            raise ValueError("invalid adjudicated candidate")
        if row["event_id"] in seen:
            raise ValueError("duplicate event candidate")
        seen.add(row["event_id"])
        score = row["score"]
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid matcher score")
        if row["relation"] not in ("same_development", "same_event_new_development", "related_only", "different", "insufficient"):
            raise ValueError("unknown relation")
        if row["relation"] in ("same_development", "same_event_new_development"):
            eligible.append(row)
    eligible.sort(key=lambda row: (-row["score"], row["event_id"]))
    if not eligible or eligible[0]["score"] < minimum_score:
        return {"event_id": None, "reason": "no_qualified_match"}
    if len(eligible) > 1 and eligible[0]["score"] - eligible[1]["score"] < margin:
        return {"event_id": None, "reason": "ambiguous_competitors"}
    return {"event_id": eligible[0]["event_id"], "reason": "calibrated_match"}
