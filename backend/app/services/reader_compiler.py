"""Deterministic S5 compiler and explicit policy semantics, shared by consumers."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5
from urllib.parse import urlsplit

from app.services.reader_contract import active, clean_text, validate_profile

COMPILER_VERSION = "reader-v3.1"


def tokenize(text: str) -> list[str]:
    return re.findall(r"[^\W_]+(?:[+.#-][^\W_]*)*", clean_text(text).casefold(), re.UNICODE)


def compile_reader(profile: dict, *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    profile = validate_profile(profile)
    intents = [item for item in profile["intents"] if active(item, now)]
    policies = [item for item in profile["policies"] if active(item, now)]
    expires = [datetime.fromisoformat(item["expires_at"]) for item in intents + policies if item["expires_at"]]
    return {"version": COMPILER_VERSION, "intents": intents, "policies": policies,
            "languages": profile["languages"], "depth": profile["depth"],
            "as_of": now.isoformat(), "valid_until": min([now + timedelta(minutes=15), *expires]).isoformat()}


def policy_allows(profile: dict, article: dict, *, now: datetime | None = None) -> bool:
    """Recommendation policy, NOT S2 access control. Subject IDs require evidence.

    A lexical phrase is a contiguous sequence of Unicode tokens, not a substring.
    Publisher values match exact canonical source IDs/domains (never fuzzy names).
    """
    compiled = compile_reader(profile, now=now)
    language = article.get("language") or article.get("content_language")
    if compiled["languages"] and language not in compiled["languages"]:
        return False
    # Explicit literal rules apply to displayed title/summary, not incidental body
    # mentions. They do not promise semantic aboutness classification.
    text = tokenize(" ".join(str(article.get(key) or "") for key in ("title", "summary")))
    def domain(value):
        try:
            host = urlsplit(value if "://" in value else "https://" + value).hostname or ""
            return host.casefold().removeprefix("www.")
        except ValueError:
            return ""
    source_values = {str(article.get(key) or "").casefold() for key in ("canonical_source_domain", "source_id", "canonical_source_id")}
    source_domains = {domain(str(article.get(key) or "")) for key in ("canonical_source_domain", "url")}
    for policy in compiled["policies"]:
        value = policy["value"]
        if policy["kind"] == "article" and value == str(article.get("id", "")):
            return False
        if policy["kind"] == "publisher" and (value.casefold() in source_values or (domain(value) and domain(value) in source_domains)):
            return False
        if policy["kind"] == "publisher" and not any(source_values) and not any(source_domains):
            return False
        if policy["kind"] == "lexical":
            phrase = tokenize(value)
            if phrase and any(text[i:i + len(phrase)] == phrase for i in range(len(text) - len(phrase) + 1)):
                return False
        if policy["kind"] == "subject":
            values = article.get(policy["scope"] + "_ids")
            if not isinstance(values, list) or value in values:
                return False
    return True


def projections(profile: dict, *, now: datetime | None = None) -> dict:
    profile = validate_profile(profile)
    compiled = compile_reader(profile, now=now)
    groups = {kind: [i["label"] for i in compiled["intents"] if i["kind"] == kind] for kind in ("topic", "entity", "place", "utility")}
    excluded = [p["value"] for p in compiled["policies"] if p["kind"] == "lexical"]
    interests = {"topics": groups["topic"], "people": groups["entity"], "locations": groups["place"], "industries": [], "excluded_topics": excluded, "notes": profile["context"]}
    brief = {"priority_topics": groups["topic"], "must_cover_entities": groups["entity"], "must_avoid_topics": excluded, "preferred_source_types": [], "coverage_targets": groups["place"], "specificity_level": "mixed"}
    v2 = {"stable_interests": groups["topic"], "current_interests": [], "people": groups["entity"], "locations": groups["place"], "industries": [], "utility_priorities": groups["utility"], "excluded_topics": excluded, "expanded_exclusions": [], "content_depth": profile["depth"], "tone_preferences": ["neutral"], "life_context": profile["context"], "source_selection_brief": brief, "preferred_languages": profile["languages"]}
    for scope in ("source", "topic", "place", "sector"):
        v2["blocked_" + scope + "_ids"] = [p["value"] for p in compiled["policies"] if (p["kind"] == "subject" and p["scope"] == scope) or (scope == "source" and p["kind"] == "publisher")]
    v2["place_ids"] = [i["resolved_id"] for i in compiled["intents"] if i["kind"] == "place" and i["resolved_id"]]
    v2["sector_ids"] = [i["resolved_id"] for i in compiled["intents"] if i["kind"] == "topic" and i["resolved_id"] and "sector" in i["qualifiers"]]
    # Machine-generated prose is only a compatibility projection, never authority.
    ai_profile = "Interests: " + "; ".join(i["label"] for i in compiled["intents"])
    if excluded:
        ai_profile += ". Exclude: " + "; ".join(excluded)
    return {"ai_profile": ai_profile, "interests": interests, "user_profile_v2": v2, "source_selection_brief": brief}


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    return {}


def import_legacy(user_id: str, row: dict | None) -> tuple[dict, str, dict]:
    """Conservative candidate, preserving conflicting variants privately for review."""
    if not row:
        return validate_profile({}), "ready", {}
    legacy, v2 = _object(row.get("interests")), _object(row.get("user_profile_v2"))
    intents, policies, seen = [], [], set()
    issue = False
    def values(source, key):
        nonlocal issue
        raw = source.get(key, [])
        if not isinstance(raw, list) or any(not isinstance(x, str) or not clean_text(x) or len(x) > 280 for x in raw):
            issue = True
            return []
        return [clean_text(x) for x in raw]
    for kind, old_keys, new_keys in (("topic", ["topics", "industries"], ["stable_interests", "current_interests", "industries"]), ("entity", ["people"], ["people"]), ("place", ["locations"], ["locations"]), ("utility", [], ["utility_priorities"])):
        old = [x for key in old_keys for x in values(legacy, key)]
        new = [x for key in new_keys for x in values(v2, key)]
        if old and new and {x.casefold() for x in old} != {x.casefold() for x in new}:
            issue = True
        for label in old + new:
            key = (kind, label.casefold())
            if key in seen:
                continue
            seen.add(key)
            if len(intents) == 24:
                issue = True
                continue
            intents.append({"id": str(uuid5(NAMESPACE_URL, f"daily:{user_id}:{kind}:{label.casefold()}")), "kind": kind, "label": label, "provenance": "legacy_import"})
    for key, kind, qualifiers in (("place_ids", "place", []), ("sector_ids", "topic", ["sector"])):
        for identity in values(v2, key):
            if len(intents) == 24:
                raise ValueError("legacy canonical identities exceed reader limit; manual migration required")
            intents.append({"id": str(uuid5(NAMESPACE_URL, f"daily:{user_id}:{key}:{identity}")), "kind": kind,
                            "label": identity, "resolved_id": identity, "qualifiers": qualifiers,
                            "provenance": "legacy_import"})
            issue = True  # A display label needs confirmation, never invented.
    excluded = values(legacy, "excluded_topics") + values(v2, "excluded_topics")
    for kind, scope, entries in [("lexical", "topic", excluded), *[("publisher" if scope == "source" else "subject", scope, values(v2, "blocked_" + scope + "_ids")) for scope in ("source", "topic", "place", "sector")]]:
        for value in entries:
            key = (kind, scope, value.casefold())
            if key in seen:
                continue
            seen.add(key)
            if len(policies) == 64:
                # Never silently import a partially enforced block set.
                raise ValueError("legacy policies exceed reader limit; manual migration required")
            policies.append({"id": str(uuid5(NAMESPACE_URL, f"daily:{user_id}:policy:{key}")), "kind": kind, "scope": scope, "value": value})
    context = legacy.get("notes") or v2.get("life_context") or ""
    if not isinstance(context, str) or len(context) > 280:
        issue, context = True, ""
    languages = values(v2, "preferred_languages")
    if len(languages) > 8 or any(not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", value) for value in languages):
        issue, languages = True, []
    depth = v2.get("content_depth", "balanced")
    if depth not in {"breaking", "balanced", "deep"}:
        issue, depth = True, "balanced"
    if row.get("ai_profile") and not intents:
        issue = True
    profile = validate_profile({"intents": intents, "policies": policies, "languages": list(dict.fromkeys(languages)), "context": context, "depth": depth})
    # Legacy fields have no trustworthy explicit provenance; existing readers review
    # this import before canonical serving, even when the string sets agree.
    status = "needs_review" if issue or any(row.get(k) for k in ("ai_profile", "interests", "user_profile_v2")) else "ready"
    evidence = {key: row.get(key) for key in ("interests", "user_profile_v2", "ai_profile", "source_selection_brief")}
    if len(json.dumps(evidence, default=str).encode()) > 65536:
        evidence = {"oversized_legacy_record": True}
    return profile, status, evidence


def legacy_patch(profile: dict, payload: dict) -> dict:
    """Only explicitly supplied legacy fields change their corresponding slice."""
    legacy = payload.get("interests", payload)
    if not isinstance(legacy, dict):
        raise ValueError("interests must be an object")
    patch, intents = {}, list(profile["intents"])
    mapping = {"topics": "topic", "people": "entity", "locations": "place", "industries": "topic"}
    for field, kind in mapping.items():
        if field not in legacy:
            continue
        labels = legacy[field]
        if not isinstance(labels, list) or any(not isinstance(x, str) or not clean_text(x) for x in labels):
            raise ValueError(field + " must contain nonempty strings")
        previous = {i["label"].casefold(): i for i in intents if i["kind"] == kind}
        kept = [i for i in intents if i["kind"] != kind]
        # Industries shares a topic slice only for legacy compatibility. If both
        # are supplied, union them rather than erase the preceding topics.
        if field == "industries" and "topics" in legacy:
            labels = list(legacy["topics"]) + labels
        for label in dict.fromkeys(clean_text(x) for x in labels):
            kept.append(previous.get(label.casefold()) or {"id": str(uuid5(NAMESPACE_URL, "daily:legacy:" + kind + ":" + label.casefold())), "kind": kind, "label": label, "query": label})
        intents = kept
        patch["intents"] = intents
    if "excluded_topics" in legacy:
        labels = legacy["excluded_topics"]
        if not isinstance(labels, list) or any(not isinstance(x, str) or not clean_text(x) for x in labels):
            raise ValueError("excluded_topics must contain nonempty strings")
        patch["policies"] = [p for p in profile["policies"] if p["kind"] != "lexical"] + [{"id": str(uuid5(NAMESPACE_URL, "daily:exclude:" + label.casefold())), "kind": "lexical", "value": label} for label in dict.fromkeys(clean_text(x) for x in labels)]
    if "notes" in legacy:
        patch["context"] = legacy["notes"]
    return patch
