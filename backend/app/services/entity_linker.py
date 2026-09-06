"""Candidate validation for S3: a surface name is never a canonical identity.

Candidates come from a trusted, versioned caller-owned registry. This module
does not invent a registry or resolve namesakes by string similarity. A model
may select a supplied candidate, or explicitly leave the mention unresolved.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence


def normalize_mention(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip().casefold()


def prepare_candidates(values: Sequence[Mapping[str, Any]] | None) -> list[dict]:
    """Validate/copy a bounded deterministic registry snapshot, without guessing IDs."""
    if values is None:
        return []
    if not isinstance(values, (list, tuple)) or len(values) > 100:
        raise ValueError("candidate snapshot must contain at most 100 candidates")
    result, seen = [], set()
    for value in values:
        if not isinstance(value, Mapping):
            raise ValueError("candidate must be a mapping")
        identifier, name, version = value.get("id"), value.get("name"), value.get("version")
        if not all(isinstance(v, str) and v.strip() and len(v) <= 300 for v in (identifier, name, version)):
            raise ValueError("candidate id, name and registry version are required")
        if identifier in seen:
            raise ValueError("duplicate candidate id")
        aliases = value.get("aliases", [])
        if not isinstance(aliases, (list, tuple)) or len(aliases) > 30 or any(not isinstance(a, str) or not a.strip() or len(a) > 300 for a in aliases):
            raise ValueError("invalid candidate aliases")
        entity_type = value.get("entity_type")
        if entity_type not in {None, "person", "organization", "product", "event", "other", "place"}:
            raise ValueError("invalid candidate entity type")
        description = value.get("description", "")
        if not isinstance(description, str) or len(description) > 2000:
            raise ValueError("invalid candidate description")
        result.append({"id": identifier, "name": name, "version": version,
                       "aliases": sorted(set(aliases)), "entity_type": entity_type,
                       "description": description})
        seen.add(identifier)
    return sorted(result, key=lambda item: item["id"])


def validate_resolution(mention: str, identifier: str | None, resolution: str,
                        candidates: Sequence[Mapping[str, Any]], *, entity_type: str | None = None) -> None:
    if resolution not in {"resolved", "unresolved", "ambiguous"}:
        raise ValueError("unknown resolution state")
    if resolution != "resolved":
        if identifier is not None:
            raise ValueError("unresolved/ambiguous mention cannot carry a canonical ID")
        return
    selected = next((candidate for candidate in candidates if candidate["id"] == identifier), None)
    if selected is None:
        raise ValueError("resolved ID was not supplied in the registry snapshot")
    names = [selected["name"], *selected.get("aliases", [])]
    if normalize_mention(mention) not in {normalize_mention(name) for name in names}:
        raise ValueError("resolved mention does not match a supplied name or alias")
    if entity_type and selected.get("entity_type") != entity_type:
        raise ValueError("resolved candidate entity type does not match")
