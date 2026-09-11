"""Lossless, conservative S3-v1 hint adapter and pure source accounting.

The caller supplies current S3 rows and reviewed source provenance. This module
does not approve a recipe, infer independence, fetch source text or guess a date
or modality. Model-assisted refinement needs its own versioned assessed output.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Mapping

from .event_contract import (
    Evidence, Source, dependency_digest, digest, timestamp, validate_snapshot,
)
from .understanding_contract import validate_card


def _known_id(value):
    return None if value is None else str(value)


def from_s3(bundle: Mapping, current: Mapping, *, source_id: str, source_generation: int,
            observed_at: str, source: Mapping | None = None,
            cluster_version: int | None = None) -> list[dict]:
    """Adapt current facets to unasserted S4 mentions; preserve original spans.

    Current/approved cohort and source-generation fencing are repository duties.
    Even a date-shaped S3 hint is not treated as evidence of occurrence: v1 does
    not carry normalized-date support or negation semantics. Returned mentions
    start role/modality unknown and cannot qualify automatic priority.
    """
    timestamp(observed_at)
    if current.get("state") not in ("ready", "partial") or not current.get("facets"):
        raise ValueError("current facets required")
    if not bundle.get("sufficient") or bundle.get("manifest", {}).get("analysis_allowed") is not True:
        raise ValueError("analysis evidence is not eligible")
    unhashed = dict(bundle)
    supplied_hash = unhashed.pop("input_hash", None)
    if supplied_hash != digest(unhashed):
        raise ValueError("S3 bundle content does not match its hash")
    for key in ("article_id", "semantic_revision", "analysis_eligibility_generation", "input_hash"):
        if current.get(key) != bundle.get(key):
            raise ValueError("S3 input revision mismatch: " + key)
    facet_result = current["facets"]
    if not facet_result.get("id") and not facet_result.get("result_id"):
        raise ValueError("immutable facet result identity required")
    card = validate_card(facet_result["payload"], bundle)
    membership = current.get("membership")
    if membership and cluster_version is None:
        raise ValueError("membership requires its current cluster generation")
    artifact = bundle["manifest"].get("artifact")
    dep = {
        "article_id": bundle["article_id"], "semantic_revision": bundle["semantic_revision"],
        "eligibility_generation": bundle["analysis_eligibility_generation"],
        "input_hash": bundle["input_hash"], "s3_recipe_id": current["recipe_id"],
        "facets_result_id": str(facet_result.get("id") or facet_result["result_id"]),
        "embedding_result_id": _known_id((current.get("embedding") or {}).get("id") or
                                        (current.get("embedding") or {}).get("result_id")),
        "cluster_id": _known_id(membership.get("cluster_id")) if membership else None,
        "membership_version": membership["version"] if membership else None,
        "cluster_version": cluster_version if membership else None,
        "source_id": source_id, "source_generation": source_generation,
        "artifact_id": _known_id(artifact["id"]) if artifact else None,
        "artifact_hash": artifact["content_hash"] if artifact else None,
    }
    src = Source.model_validate(source if source is not None else {
        "publisher_id": None, "reporting_origin_id": None, "origin_status": "unknown",
        "primary_verified": False, "language": bundle.get("language"),
    }).model_dump()
    entities = {entity["mention"]: entity["resolved_id"] for entity in card["entities"]
                if entity["resolution"] == "resolved" and entity["resolved_id"]}
    result = []
    for index, hint in enumerate(card["event_hints"]):
        hint_hash = digest(hint)
        identifier = "evd_" + digest([dep["facets_result_id"], index, hint_hash])
        item = {
            "id": identifier, "dependency": deepcopy(dep), "hint_index": index, "hint_hash": hint_hash,
            "role": "unknown", "source": deepcopy(src),
            "claim": {
                "actor_ids": sorted({entities[name] for name in hint["actors"] if name in entities}),
                "action": hint["action"], "object": hint["object"], "place_ids": hint["place_ids"],
                "modality": "unknown", "attribution": None,
                "occurrence": {"start": None, "end": None, "precision": "unknown", "evidence_ids": []},
            },
            "spans": [{**span, "field_hash": bundle["manifest"]["field_hashes"][span["field"]]}
                      for span in hint["evidence"]],
            "observed_at": observed_at, "published_at": bundle["metadata"]["published_at"],
        }
        result.append(validate_original_spans(item, bundle))
    return result


def validate_original_spans(evidence: Mapping, bundle: Mapping) -> dict:
    """Recheck exact normalized fields; a forged quote cannot acquire provenance."""
    item = Evidence.model_validate(evidence).model_dump()
    dep = item["dependency"]
    if (dep["article_id"] != bundle["article_id"] or dep["input_hash"] != bundle["input_hash"] or
        dep["semantic_revision"] != bundle["semantic_revision"] or
        dep["eligibility_generation"] != bundle["analysis_eligibility_generation"]):
        raise ValueError("wrong evidence owner/revision")
    if bundle["manifest"].get("analysis_allowed") is not True or not bundle.get("sufficient"):
        raise ValueError("revoked or insufficient original evidence")
    artifact = bundle["manifest"].get("artifact")
    if dep["artifact_id"] != (_known_id(artifact["id"]) if artifact else None) or \
            dep["artifact_hash"] != (artifact["content_hash"] if artifact else None):
        raise ValueError("original artifact mismatch")
    for span in item["spans"]:
        field = bundle["fields"][span["field"]]
        if (span["field_hash"] != digest(field) or span["end"] > len(field)
            or field[span["start"]:span["end"]] != span["quote"]):
            raise ValueError("span does not address original field")
    return item


def build_snapshot(*, event_id: str, generation: int, recipe_id: str,
                   s3_control_generation: int, s4_control_generation: int,
                   member_generation: int, as_of: str, evidence: list[dict],
                   coverage: dict, support_policy: dict | None = None,
                   previous_snapshot_hash: str | None = None) -> dict:
    # Canonical sort makes equivalent intake batches hash identically; the
    # caller-owned event/member generations still fence substantive admission.
    evidence = sorted(deepcopy(evidence), key=lambda item: item["id"])
    return validate_snapshot({
        "event_id": event_id, "generation": generation, "recipe_id": recipe_id,
        "s3_control_generation": s3_control_generation, "s4_control_generation": s4_control_generation,
        "member_generation": member_generation, "as_of": as_of, "evidence": evidence,
        "coverage": coverage,
        "support_policy": support_policy or {"minimum_independent_origins": 2, "allow_verified_primary": False},
        "previous_snapshot_hash": previous_snapshot_hash, "dependency_digest": dependency_digest(evidence),
    })


def coverage_counts(evidence: list[dict]) -> dict:
    """Origins count only positive core reports; repeated wire copies add no origin.

    Source provenance is trusted input from a reviewed versioned registry, not
    a model inference. This function reports counts, never a significance tier.
    """
    rows = [Evidence.model_validate(item).model_dump() for item in evidence]
    ids = [item["id"] for item in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence IDs")
    core = [item for item in rows if item["role"] == "core" and item["claim"]["modality"] in ("reported", "corrected")]
    return {
        "mentions": len(rows),
        "articles": len({item["dependency"]["article_id"] for item in rows}),
        "distribution_publishers": len({item["source"]["publisher_id"] for item in rows if item["source"]["publisher_id"]}),
        "independent_core_origins": len({item["source"]["reporting_origin_id"] for item in core
                                         if item["source"]["origin_status"] == "verified"}),
        "unknown_core_origins": len({item["dependency"]["article_id"] for item in core
                                     if item["source"]["origin_status"] == "unknown"}),
        "verified_primary_core": len({item["dependency"]["source_id"] for item in core
                                       if item["source"]["primary_verified"]}),
    }
