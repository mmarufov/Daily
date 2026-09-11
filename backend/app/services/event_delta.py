"""Conservative source-attributed factual deltas over bounded snapshots.

This does not invent stable development IDs; persistence owns identity/lineage.
Exact normalized claim equality handles repeat publication. Semantic paraphrase
or new-action adjudication remains an explicitly uncalibrated model stage.
"""
from __future__ import annotations

from .event_contract import Claim, digest, timestamp, validate_snapshot


DELTA_RECIPE = "exact-attributed-claims-v1-unpromoted"


def claim_fingerprint(claim: dict) -> str:
    # Evidence IDs change across reprints; factual content does not. Preserve
    # modality, attribution and interval precision rather than collapsing denial.
    claim = Claim.model_validate(claim).model_dump()
    normalized = dict(claim)
    normalized["actor_ids"] = sorted(claim["actor_ids"])
    normalized["place_ids"] = sorted(claim["place_ids"])
    normalized["occurrence"] = {key: value for key, value in claim["occurrence"].items() if key != "evidence_ids"}
    for bound in ("start", "end"):
        if normalized["occurrence"][bound] is not None:
            normalized["occurrence"][bound] = timestamp(normalized["occurrence"][bound]).isoformat()
    for key in ("action", "object", "attribution"):
        if isinstance(normalized[key], str):
            normalized[key] = " ".join(normalized[key].casefold().split())
    return digest({"recipe": DELTA_RECIPE, "claim": normalized})


def compare_snapshots(previous: dict | None, current: dict) -> dict:
    current = validate_snapshot(current)
    prior = validate_snapshot(previous) if previous is not None else None
    if prior is not None:
        if prior["event_id"] != current["event_id"] or prior["recipe_id"] != current["recipe_id"]:
            raise ValueError("cannot compare different event/recipe histories")
        if current["generation"] <= prior["generation"]:
            raise ValueError("delta history must advance generation")
        if current["previous_snapshot_hash"] != digest(prior):
            raise ValueError("broken previous snapshot linkage")
    elif current["previous_snapshot_hash"] is not None:
        raise ValueError("missing linked previous snapshot")
    def facts(snapshot):
        return {claim_fingerprint(item["claim"]): item for item in snapshot["evidence"]
                if item["role"] in ("core", "contradiction", "withdrawn")}
    old = facts(prior) if prior else {}
    new = facts(current)
    added, removed = sorted(set(new) - set(old)), sorted(set(old) - set(new))
    if not current["coverage"]["complete"] or not current["coverage"]["supported"] or \
            (not old and not new) or any(item["role"] == "unknown" for item in current["evidence"]):
        kind = "insufficient"
    elif not added and not removed:
        kind = "unchanged" if prior and prior["dependency_digest"] == current["dependency_digest"] else "support_only"
    elif any(new[key]["claim"]["modality"] in ("denied", "disputed", "corrected", "retracted") for key in added) or removed:
        kind = "correction_candidate"
    elif any(new[key]["claim"]["modality"] in ("unknown", "predicted", "alleged") for key in added):
        kind = "insufficient"
    else:
        kind = "material_candidate"
    return {"recipe": DELTA_RECIPE, "kind": kind, "added_claims": added, "removed_claims": removed,
            "requires_adjudication": kind in ("material_candidate", "correction_candidate", "insufficient"),
            "automatic_realert": False}
