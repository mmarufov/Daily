"""Build persona profiles the way production builds them.

For every `evals/personas/<key>.json` that has an onboarding `transcript` and no
`profile`, run `OpenAIService.build_complete_user_preferences` through the LLM
cache and freeze the result into the file. Re-running is free and idempotent.

    python -m evals.build_personas            # fill missing profiles
    python -m evals.build_personas --force    # rebuild transcript-based ones
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.llm_cache import cache_key
from evals.openai_backend import METER, client
from evals.personas import PERSONA_DIR, load_persona_files


def _service():
    from unittest.mock import patch
    from app.services import openai_service as osvc
    if not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "offline-cache-only"
    with patch.object(osvc, "OpenAI", lambda **kw: None):
        svc = osvc.OpenAIService()
    svc.client = client()
    return svc


async def build_one(svc, doc: dict) -> dict:
    result = await svc.build_complete_user_preferences(doc["transcript"], doc.get("explicit_context"))
    return {
        "ai_profile": result.get("ai_profile") or "",
        "interests": result.get("interests") or {},
        "user_profile_v2": result.get("user_profile_v2") or {},
        "source_selection_brief": result.get("source_selection_brief") or {},
    }


def main(force: bool = False) -> None:
    docs = load_persona_files()
    todo = [d for d in docs.values() if d.get("transcript") and (force or not d.get("profile"))]
    if not todo:
        print("all personas already built")
        return
    svc = _service()
    for doc in todo:
        profile = asyncio.run(build_one(svc, doc))
        doc["profile"] = profile
        doc["built_with"] = {
            "model": svc.model,
            "cache_key": cache_key("persona", key=doc["key"], transcript=doc["transcript"], model=svc.model),
            "date": date.today().isoformat(),
        }
        (PERSONA_DIR / f"{doc['key']}.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
        v2 = profile["user_profile_v2"]
        print(f"{doc['key']:<9} current={v2.get('current_interests')}  stable={v2.get('stable_interests')}  "
              f"excluded={v2.get('excluded_topics')}")
    from evals.llm_cache import write_key_manifest
    write_key_manifest(PERSONA_DIR / "cache_keys.json", client().touched, note="persona profile builds")
    print(METER.report())


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    main(force=ap.parse_args().force)
