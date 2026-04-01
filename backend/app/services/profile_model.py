from __future__ import annotations

import json
import re
from typing import Any


DEFAULT_CONTENT_DEPTH = "balanced"
DEFAULT_TONE = "neutral"
DEFAULT_SPECIFICITY = "mixed"


def _empty_source_selection_brief() -> dict[str, Any]:
    return {
        "priority_topics": [],
        "must_cover_entities": [],
        "must_avoid_topics": [],
        "preferred_source_types": [],
        "coverage_targets": [],
        "specificity_level": DEFAULT_SPECIFICITY,
    }


def empty_user_profile_v2() -> dict[str, Any]:
    return {
        "stable_interests": [],
        "current_interests": [],
        "people": [],
        "locations": [],
        "industries": [],
        "excluded_topics": [],
        "utility_priorities": [],
        "content_depth": DEFAULT_CONTENT_DEPTH,
        "tone_preferences": [DEFAULT_TONE],
        "life_context": "",
        "source_selection_brief": _empty_source_selection_brief(),
    }


def _normalize_string_list(values: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(values, list):
        return []

    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = re.sub(r"\s+", " ", str(value).strip())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def normalize_source_selection_brief(payload: Any, *, fallback_specificity: str | None = None) -> dict[str, Any]:
    brief = _empty_source_selection_brief()
    if not isinstance(payload, dict):
        if fallback_specificity:
            brief["specificity_level"] = fallback_specificity
        return brief

    brief["priority_topics"] = _normalize_string_list(payload.get("priority_topics"))
    brief["must_cover_entities"] = _normalize_string_list(payload.get("must_cover_entities"))
    brief["must_avoid_topics"] = _normalize_string_list(payload.get("must_avoid_topics"))
    brief["preferred_source_types"] = _normalize_string_list(payload.get("preferred_source_types"), limit=8)
    brief["coverage_targets"] = _normalize_string_list(payload.get("coverage_targets"), limit=8)

    specificity = str(payload.get("specificity_level") or fallback_specificity or DEFAULT_SPECIFICITY).strip().lower()
    if specificity not in {"specific", "mixed", "broad"}:
        specificity = fallback_specificity or DEFAULT_SPECIFICITY
    brief["specificity_level"] = specificity
    return brief


def normalize_user_profile_v2(payload: Any, *, fallback_specificity: str | None = None) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("profile"), dict):
        payload = payload["profile"]

    profile = empty_user_profile_v2()
    if not isinstance(payload, dict):
        if fallback_specificity:
            profile["source_selection_brief"]["specificity_level"] = fallback_specificity
        return profile

    profile["stable_interests"] = _normalize_string_list(payload.get("stable_interests"))
    profile["current_interests"] = _normalize_string_list(payload.get("current_interests"))
    profile["people"] = _normalize_string_list(payload.get("people"))
    profile["locations"] = _normalize_string_list(payload.get("locations"))
    profile["industries"] = _normalize_string_list(payload.get("industries"))
    profile["excluded_topics"] = _normalize_string_list(payload.get("excluded_topics"))
    profile["utility_priorities"] = _normalize_string_list(payload.get("utility_priorities"), limit=8)

    depth = str(payload.get("content_depth") or DEFAULT_CONTENT_DEPTH).strip().lower()
    if depth not in {"breaking", "balanced", "deep"}:
        depth = DEFAULT_CONTENT_DEPTH
    profile["content_depth"] = depth

    tones = _normalize_string_list(payload.get("tone_preferences"), limit=6)
    profile["tone_preferences"] = tones or [DEFAULT_TONE]
    life_context = payload.get("life_context")
    if isinstance(life_context, str):
        profile["life_context"] = life_context.strip()[:280]

    profile["source_selection_brief"] = normalize_source_selection_brief(
        payload.get("source_selection_brief"),
        fallback_specificity=fallback_specificity,
    )
    return profile


def build_source_selection_brief(
    interests: dict[str, Any] | None,
    profile_v2: dict[str, Any] | None,
    *,
    specificity_level: str,
) -> dict[str, Any]:
    brief = normalize_source_selection_brief(
        (profile_v2 or {}).get("source_selection_brief"),
        fallback_specificity=specificity_level,
    )

    if isinstance(interests, dict):
        topics = _normalize_string_list(interests.get("topics"))
        people = _normalize_string_list(interests.get("people"))
        excluded = _normalize_string_list(interests.get("excluded_topics"))
        locations = _normalize_string_list(interests.get("locations"))
        industries = _normalize_string_list(interests.get("industries"))
    else:
        topics = people = excluded = locations = industries = []

    if not brief["priority_topics"]:
        brief["priority_topics"] = _normalize_string_list(
            (profile_v2 or {}).get("current_interests") or topics or (profile_v2 or {}).get("stable_interests"),
            limit=10,
        )

    if not brief["must_cover_entities"]:
        brief["must_cover_entities"] = _normalize_string_list(people, limit=8)

    if not brief["must_avoid_topics"]:
        brief["must_avoid_topics"] = excluded

    if not brief["coverage_targets"]:
        coverage_targets = []
        coverage_targets.extend(locations[:2])
        coverage_targets.extend(industries[:3])
        coverage_targets.extend((profile_v2 or {}).get("utility_priorities") or [])
        brief["coverage_targets"] = _normalize_string_list(coverage_targets, limit=8)

    if not brief["preferred_source_types"]:
        preferred_types: list[str] = []
        if people:
            preferred_types.append("entity-tracking")
        if specificity_level == "specific":
            preferred_types.extend(["official", "analyst", "publisher"])
        elif specificity_level == "mixed":
            preferred_types.extend(["publisher", "analyst", "breadth"])
        else:
            preferred_types.extend(["breadth", "publisher"])
        brief["preferred_source_types"] = _normalize_string_list(preferred_types, limit=6)

    brief["specificity_level"] = specificity_level
    return brief


def derive_profile_v2_from_preferences(
    interests: dict[str, Any] | None,
    ai_profile: str | None,
    *,
    explicit_context: dict[str, Any] | None = None,
    specificity_level: str = DEFAULT_SPECIFICITY,
) -> dict[str, Any]:
    profile = empty_user_profile_v2()
    interests = interests or {}
    explicit_context = explicit_context or {}

    stable = _normalize_string_list(interests.get("topics"), limit=10)
    current = _normalize_string_list(explicit_context.get("current_interests") or stable[:4], limit=8)
    utility_priorities = _normalize_string_list(explicit_context.get("utility_priorities"), limit=8)
    locations = _normalize_string_list(interests.get("locations"), limit=6)
    industries = _normalize_string_list(interests.get("industries"), limit=6)
    excluded = _normalize_string_list(interests.get("excluded_topics"), limit=8)

    depth = str(explicit_context.get("content_depth") or "").strip().lower()
    if depth not in {"breaking", "balanced", "deep"}:
        depth = _infer_content_depth(ai_profile or "")

    tones = _normalize_string_list(explicit_context.get("tone_preferences"), limit=6)
    if not tones:
        tones = [_infer_tone(ai_profile or "")]

    profile.update(
        {
            "stable_interests": stable,
            "current_interests": current or stable[:4],
            "people": _normalize_string_list(interests.get("people"), limit=8),
            "locations": locations,
            "industries": industries,
            "excluded_topics": excluded,
            "utility_priorities": utility_priorities,
            "content_depth": depth,
            "tone_preferences": tones,
            "life_context": str(explicit_context.get("life_context") or interests.get("notes") or "").strip()[:280],
        }
    )
    profile["source_selection_brief"] = build_source_selection_brief(
        interests,
        profile,
        specificity_level=specificity_level,
    )
    return profile


def _infer_content_depth(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("deep", "analysis", "technical", "expert", "research")):
        return "deep"
    if any(term in lowered for term in ("breaking", "quick", "headlines", "brief")):
        return "breaking"
    return DEFAULT_CONTENT_DEPTH


def _infer_tone(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("skeptical", "critical", "hype")):
        return "skeptical"
    if any(term in lowered for term in ("optimistic", "enthusiastic")):
        return "enthusiastic"
    return DEFAULT_TONE


def loads_json(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None
    return None


def dumps_json(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload)
