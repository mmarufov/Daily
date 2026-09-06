"""Durable preference signals learned from explicit feedback.

Before this existed, tapping "Not relevant" wrote a row to `reading_events` that
nothing ever read. The feed cache was cleared, the feed was rebuilt from the
identical profile, the article scored the same, and it came back. The client hid
it locally, which disguised the problem until the next refresh.

The gap was that there was nowhere for a correction to *go*. A profile is what
the reader told us once during onboarding; it has no room for "yes, but not that
one". This module is that room.

Attribution is the interesting part. A single tap does not say "I hate hockey" —
it says "this specific article was wrong". So we spread a small, bounded penalty
across the reasons we showed it: the interest that matched (recorded in
`user_feed_cache.matched_profile_signals` at scoring time), the publisher, and
the category. Repeated taps compound; one tap barely moves anything.
"""
from __future__ import annotations

import logging
import math
import uuid as _uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Per-event weight change. Negative feedback bites harder than positive rewards,
# because a reader who bothers to reject something is giving a much stronger
# signal than one who taps a heart.
FEEDBACK_DELTAS = {
    "not_relevant": -0.30,
    "less_like_this": -0.15,
    "more_like_this": 0.20,
    "important": 0.15,
}

# How much each kind of attribution counts. The matched interest is the reason
# the article was selected at all, so it carries the most; a publisher is weaker
# evidence; a category is weakest — "technology" is too coarse to punish hard.
KIND_FACTORS = {"topic": 1.0, "source": 0.6, "category": 0.35}

# Per-signal accumulation limits. Bounded so a run of taps on one bad day cannot
# permanently erase an interest the reader genuinely holds.
WEIGHT_FLOOR, WEIGHT_CEILING = -1.0, 0.8

# Total per-article score adjustment, also asymmetric: negative feedback may
# sink an article outright, positive feedback may only promote it.
ADJUSTMENT_FLOOR, ADJUSTMENT_CEILING = -0.50, 0.25

# Signals fade. A reader who disliked crypto coverage a year ago may have
# changed jobs since. 30-day half-life.
HALF_LIFE_DAYS = 30.0


def _decayed(weight: float, updated_at) -> float:
    if not updated_at:
        return weight
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - updated_at).total_seconds() / 86400.0
    if age_days <= 0:
        return weight
    return weight * math.pow(0.5, age_days / HALF_LIFE_DAYS)


def _attributions(conn, user_id: str, article_id) -> list[tuple[str, str]]:
    """Why did we show this article? Returns (kind, value) pairs to adjust."""
    pairs: list[tuple[str, str]] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.source_name, a.category, ufc.matched_profile_signals
            FROM public.articles a
            LEFT JOIN public.user_feed_cache ufc
                   ON ufc.article_id = a.id AND ufc.user_id = %s
            WHERE a.id = %s
            """,
            (user_id, article_id),
        )
        row = cur.fetchone()

    if not row:
        return pairs

    if row.get("source_name"):
        pairs.append(("source", str(row["source_name"]).strip().lower()))
    if row.get("category"):
        pairs.append(("category", str(row["category"]).strip().lower()))

    # The interests that caused this article to be selected. Populated by
    # _annotate_candidate_feed_roles; absent for articles served from a cache
    # written before that ran, in which case source/category carry the signal.
    signals = row.get("matched_profile_signals")
    if isinstance(signals, str):
        import json
        try:
            signals = json.loads(signals)
        except ValueError:
            signals = None
    if isinstance(signals, list):
        for s in signals[:6]:
            text = str(s).strip().lower()
            if text:
                pairs.append(("topic", text))

    return pairs


def apply_feedback(conn, user_id: str, article_id: str, action: str) -> int:
    """Record an explicit correction as durable preference weight.

    Returns the number of signals adjusted. Best-effort: a failure here must not
    fail the user's tap.
    """
    delta = FEEDBACK_DELTAS.get(action)
    if delta is None:
        return 0

    try:
        article_uuid = _uuid.UUID(str(article_id))
    except (ValueError, AttributeError):
        return 0

    try:
        pairs = _attributions(conn, user_id, article_uuid)
        if not pairs:
            return 0

        with conn.cursor() as cur:
            for kind, value in pairs:
                cur.execute(
                    """
                    INSERT INTO public.user_feedback_signals
                        (user_id, kind, value, weight, events, updated_at)
                    VALUES (%s, %s, %s, %s, 1, now())
                    ON CONFLICT (user_id, kind, value) DO UPDATE SET
                        weight = GREATEST(%s, LEAST(%s,
                            public.user_feedback_signals.weight + EXCLUDED.weight)),
                        events = public.user_feedback_signals.events + 1,
                        updated_at = now()
                    """,
                    (user_id, kind, value, delta * KIND_FACTORS.get(kind, 0.5),
                     WEIGHT_FLOOR, WEIGHT_CEILING),
                )
        return len(pairs)
    except Exception:
        logger.exception("Failed to apply feedback for user %s article %s", user_id, article_id)
        return 0


def load_feedback_signals(conn, user_id: str) -> dict[str, dict[str, float]]:
    """Load this reader's learned weights, time-decayed, grouped by kind."""
    out: dict[str, dict[str, float]] = {"topic": {}, "source": {}, "category": {}}
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT kind, value, weight, updated_at
                FROM public.user_feedback_signals
                WHERE user_id = %s
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    except Exception:
        logger.exception("Failed to load feedback signals for %s", user_id)
        return out

    for row in rows:
        kind = row.get("kind")
        if kind not in out:
            continue
        w = _decayed(float(row.get("weight") or 0.0), row.get("updated_at"))
        if abs(w) >= 0.01:                      # drop noise that has decayed away
            out[kind][str(row.get("value") or "")] = w
    return out


def load_suppressed_article_ids(conn, user_id: str) -> set[str]:
    """Articles the reader explicitly rejected. These never come back.

    Distinct from the weight system: weights shift ranking, this is absolute.
    A reader who says "not relevant" and then sees the same headline tomorrow
    correctly concludes the button does nothing.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT article_id
                FROM public.reading_events
                WHERE user_id = %s
                  AND event_type IN ('not_relevant', 'less_like_this', 'already_knew')
                """,
                (user_id,),
            )
            return {str(r["article_id"]) for r in cur.fetchall()}
    except Exception:
        logger.exception("Failed to load suppressed articles for %s", user_id)
        return set()


def feedback_adjustment(article: dict, signals: dict[str, dict[str, float]]) -> float:
    """Score delta for one article given this reader's learned weights."""
    if not signals:
        return 0.0

    total = 0.0
    source = str(article.get("source") or article.get("source_name") or "").strip().lower()
    if source:
        total += signals.get("source", {}).get(source, 0.0)

    category = str(article.get("category") or "").strip().lower()
    if category:
        total += signals.get("category", {}).get(category, 0.0)

    topics = signals.get("topic") or {}
    if topics:
        matched = article.get("matched_profile_signals") or article.get("_matched_profile_signals") or []
        for m in matched:
            total += topics.get(str(m).strip().lower(), 0.0)

    return max(ADJUSTMENT_FLOOR, min(ADJUSTMENT_CEILING, total))
