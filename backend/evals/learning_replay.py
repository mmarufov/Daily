"""S10 F: synthetic-session replay for the legacy learning loop.

Before this file existed, `fake_db.SnapshotConn` stubbed `user_feedback_signals`
and `reading_events` to an unconditional `[]` (see its old dispatch() branch),
so no S0 persona could ever have any behavior -- there was no way, even in
principle, for this repository's test suite to tell you whether a change to
the learning system helps or hurts. `docs/stages/s10-learning-audit.md` names this
as the single most important gap the audit found, ahead of any modeling work.

This closes it for the legacy (S5-off) path specifically: build a persona's
feed once, apply a scripted sequence of feedback actions through the REAL,
unmodified `app.services.feedback_signals.apply_feedback`, build again through
the REAL, unmodified `app.services.feed_service.get_personalized_feed`, and
assert the second build reflects them. Both builds run production code
against a frozen snapshot; nothing here is a mock of the learning logic
itself, only of the LLM scoring call (a uniform, deterministic stand-in) and
the database.

    python -m evals.learning_replay              # runs the built-in scenarios

The S5 path (reader_feedback.py) has its own, separate fake-DB shape
(`tests/test_ranking_feedback.py`'s `DB` class) and is not covered here; S5's
own extensive test suite (70+ tests) already exercises that path directly.
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from evals.fake_db import SnapshotConn, eval_uuid, persona_uuid
from evals.runners import _frozen_datetime

# Actions the legacy loop accepts (app.services.feedback_signals.FEEDBACK_DELTAS
# plus the two that carry no weight delta but do suppress -- see reward.py).
SUPPRESSING_ACTIONS = {"not_relevant", "less_like_this", "already_knew", "hide_source"}


class _UniformScorer:
    """A fixed, mediocre relevance for every candidate. The point of this
    harness is to isolate the effect of feedback on the deterministic/
    behavioral scoring layers (feedback_adjustment, suppression) -- a
    varying or all-irrelevant LLM stand-in would either dominate or mask
    that signal. Never makes a network call; costs nothing to run."""
    scoring_model = "s10-replay-uniform"

    async def score_articles_batch(self, articles, user_profile, interests=None, user_profile_v2=None):
        return [{"relevant": True, "score": 0.6, "reason": "replay: uniform baseline"} for _ in articles]


@dataclass(frozen=True)
class ScriptedAction:
    """One feedback event to apply between the two builds. `article_id` is a
    snapshot-pool id (e.g. "a00042"), not the derived eval UUID."""
    article_id: str
    action: str


@dataclass
class ReplayResult:
    before: list[dict]
    after: list[dict]
    conn: SnapshotConn = field(repr=False)

    def ids(self, edition: list[dict]) -> list[str]:
        return [a["id"] for a in edition]


def _build_once(user_id: str, conn: SnapshotConn, frozen_now: datetime, limit: int) -> list[dict]:
    from app.services import feed_service, openai_service

    Frozen = _frozen_datetime(frozen_now)
    svc = _UniformScorer()
    with patch.object(feed_service, "datetime", Frozen), \
         patch.object(openai_service, "_openai_service", svc), \
         patch.object(feed_service, "get_openai_service", lambda: svc):
        return asyncio.run(feed_service.get_personalized_feed(
            user_id, conn, limit=limit, force_refresh=True))


def replay(persona: dict, pool: list[dict], frozen_now: datetime,
           actions: list[ScriptedAction], limit: int = 50) -> ReplayResult:
    """Build, apply scripted feedback through the real learning code, build
    again. Both builds call the unmodified production
    `feed_service.get_personalized_feed` against the same connection --
    this is evidence the *pipeline* responds to feedback, not that a
    stand-in does."""
    from app.services import feedback_signals

    frozen_now = frozen_now if frozen_now.tzinfo else frozen_now.replace(tzinfo=timezone.utc)
    conn = SnapshotConn(persona, pool, frozen_now)
    user_id = str(persona_uuid(persona.get("key") or persona.get("name") or "persona"))

    before = _build_once(user_id, conn, frozen_now, limit)

    for scripted in actions:
        if scripted.action in SUPPRESSING_ACTIONS:
            conn.suppress(scripted.article_id)
        feedback_signals.apply_feedback(
            conn, user_id, str(eval_uuid(scripted.article_id)), scripted.action)

    after = _build_once(user_id, conn, frozen_now, limit)
    return ReplayResult(before=before, after=after, conn=conn)


def _demo() -> None:
    """A tiny, self-contained scenario -- no snapshot file, no API key,
    no database. Prints before/after so the effect is visible by eye too."""
    now = datetime.now(timezone.utc)
    persona = {"key": "demo", "name": "Demo reader",
               "ai_profile": "Interested in artificial intelligence policy and semiconductor supply chains.",
               "interests": {"topics": ["AI policy", "semiconductors"]}, "user_profile_v2": {}}
    pool = [
        {"id": "a1", "title": "New AI policy framework proposed", "summary": "Regulators outline a plan.",
         "source": "Reuters", "category": "technology", "content_quality": 0.8,
         "published_at": now.isoformat(), "url": "https://reuters.example/a1"},
        {"id": "a2", "title": "Chip export controls tightened", "summary": "New semiconductor rules.",
         "source": "Reuters", "category": "technology", "content_quality": 0.8,
         "published_at": now.isoformat(), "url": "https://reuters.example/a2"},
        {"id": "a3", "title": "Local weather update", "summary": "Rain expected this weekend.",
         "source": "Local News", "category": "weather", "content_quality": 0.5,
         "published_at": now.isoformat(), "url": "https://local.example/a3"},
    ]
    result = replay(persona, pool, now, [ScriptedAction(article_id="a1", action="not_relevant")])
    print("before:", result.ids(result.before))
    print("after: ", result.ids(result.after))
    still_present = str(eval_uuid("a1")) in result.ids(result.after)
    print("a1 still present after rejection:", still_present, "(expect False)")


if __name__ == "__main__":
    _demo()
