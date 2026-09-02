"""Evaluation personas, loaded from `evals/personas/<key>.json`.

Each file holds either a hand-written profile or an onboarding transcript that
`build_personas.py` has run through the production profile builder
(`OpenAIService.build_complete_user_preferences`), so the profile under test is
exactly what a real reader would get. `PERSONAS` keeps the historical shape
(`name`, `ai_profile`, `interests`, `user_profile_v2`) so `pipeline.py`,
`global_events.home_regions` and the scripts keep working unchanged.

Axes covered (chosen to stress different failure modes, not to be representative):

  ray      hyper-local + named entities            local recall, entity precision
  wei      professional/technical + geographic     niche depth, adjacency rejection
  farrukh  multi-region geopolitics + trade        breadth, non-Western coverage
  maya     broad "keep me informed" reader         over-filtering, generic quality
  cold     no stated preferences                   cold start must still work
  priya    interests that collide with exclusions  exclusion gate precision
  dilshod  non-English-named entities and places   transliteration, rare proper nouns
  lena     follows one developing story            day-three follow-ups, freshness
  tom      primary topic + background sports fan   routine background must not surface
  aisha    life-context / need-to-know reader      contextual relevance, utility news
"""
from __future__ import annotations

import json
from pathlib import Path

PERSONA_DIR = Path(__file__).resolve().parent / "personas"


def load_persona_files() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in sorted(PERSONA_DIR.glob("*.json")):
        doc = json.loads(p.read_text())
        if not isinstance(doc, dict) or "key" not in doc:
            continue          # e.g. cache_keys.json
        out[doc["key"]] = doc
    return out


def as_persona(doc: dict) -> dict | None:
    """Flatten a persona file into the dict the pipeline and runners consume."""
    prof = doc.get("profile")
    if not prof:
        return None
    v2 = dict(prof.get("user_profile_v2") or {})
    if prof.get("source_selection_brief") and "source_selection_brief" not in v2:
        v2["source_selection_brief"] = prof["source_selection_brief"]
    return {
        "key": doc["key"],
        "name": doc["name"],
        "axis": doc.get("axis", ""),
        "ai_profile": prof.get("ai_profile") or "",
        "interests": prof.get("interests") or {},
        "user_profile_v2": v2,
        "expect": doc.get("expect") or {},
    }


def load_personas(only: list[str] | None = None) -> dict[str, dict]:
    out = {}
    for key, doc in load_persona_files().items():
        if only and key not in only:
            continue
        p = as_persona(doc)
        if p is not None:
            out[key] = p
    return out


PERSONAS: dict[str, dict] = load_personas()
